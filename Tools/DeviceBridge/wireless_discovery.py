from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import hmac
import ipaddress
import json
import socket
import ssl
import subprocess
import time
from urllib.parse import urlsplit

from wireless_pairing import PairingStore, endpoint, relocate_device


def network_candidates(inventory, previous):
    port = urlsplit(endpoint(previous)).port
    addresses = set()
    local = set()
    for item in inventory:
        address = ipaddress.IPv4Address(item["IPAddress"])
        if address.is_loopback or address.is_link_local or address.is_unspecified:
            continue
        local.add(str(address))
        network = ipaddress.IPv4Network(f"{address}/{int(item['PrefixLength'])}", strict=False)
        if network.num_addresses <= 4096:
            addresses.update(str(host) for host in network.hosts())
        for neighbor in item.get("Neighbors") or []:
            host = ipaddress.IPv4Address(neighbor)
            if host in network and host != network.network_address and host != network.broadcast_address:
                addresses.add(str(host))
    addresses.difference_update(local)
    if len(addresses) > 8192:
        raise ValueError("网络范围过大，请手动输入设备新地址")
    return [endpoint(f"{host}:{port}") for host in sorted(addresses, key=ipaddress.IPv4Address)]


def local_candidates(previous):
    script = "$ErrorActionPreference='Stop'; $omiInterfaces=@(Get-NetAdapter -Physical | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { $_.ifIndex }); @((Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' -and $_.InterfaceIndex -in $omiInterfaces }) | ForEach-Object { [pscustomobject]@{ IPAddress=$_.IPAddress; PrefixLength=$_.PrefixLength; Neighbors=@(Get-NetNeighbor -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | ForEach-Object { $_.IPAddress }) } }) | ConvertTo-Json -Depth 4 -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, check=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    inventory = json.loads(result.stdout.decode("utf-8-sig"))
    if isinstance(inventory, dict):
        inventory = [inventory]
    return network_candidates(inventory or [], previous)


def certificate_matches(address, pin, stop):
    if stop.is_set():
        return False
    target = urlsplit(address)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        with socket.create_connection((target.hostname, target.port), timeout=0.5) as raw:
            raw.settimeout(1.5)
            with context.wrap_socket(raw, server_hostname=target.hostname) as tls:
                return hmac.compare_digest(hashlib.sha256(tls.getpeercert(binary_form=True)).digest(), pin)
    except (OSError, ValueError):
        return False


def find_device(previous, *, stop, store=None, candidates=None, probe=certificate_matches,
                relocate=relocate_device, socket_factory=None):
    store = store or PairingStore()
    record = store.load(previous)
    if not record:
        raise ValueError("找不到原配对凭据")
    candidates = local_candidates(previous) if candidates is None else candidates
    deadline = time.monotonic() + 45
    pool = ThreadPoolExecutor(max_workers=24, thread_name_prefix="omi-find")
    pending = {pool.submit(probe, address, record[1], stop): address for address in candidates}
    try:
        while pending and not stop.is_set() and time.monotonic() < deadline:
            done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                address = pending.pop(future)
                if future.result():
                    options = dict(store=store, stop=stop)
                    if socket_factory is not None:
                        options["socket_factory"] = socket_factory
                    return relocate(previous, address, **options)
        raise ValueError("未找到原设备，请检查同一局域网和网络隔离，或手动输入新地址")
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
