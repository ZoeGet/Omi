import base64
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import time
from urllib.parse import urlsplit

import websocket
from websocket._abnf import frame_buffer

from pake import Pake
from pairing_auth import derive_daily_key, make_proof, verify_certificate_pin, verify_proof
from pairing_credentials import encode_record, decode_record
from protocol import unique_object, invalid_constant


def endpoint(address):
    parsed = urlsplit(address if "://" in address else "wss://" + address)
    if (parsed.scheme != "wss" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/pair")):
        raise ValueError("请输入设备局域网地址")
    host = parsed.hostname
    port = parsed.port or 8443
    return f"wss://{'[' + host + ']' if ':' in host else host}:{port}/pair"


def confirmation(key, role, digest, pin):
    if role not in "HDCS" or len(role) != 1 or any(len(x) != 32 for x in (key, digest, pin)):
        raise ValueError("Invalid confirmation material")
    return hmac.new(key, b"OmiPet pairing confirmation v1" + role.encode("ascii") + digest + pin,
                    hashlib.sha256).digest()


def transcript(pin, *rounds):
    return hashlib.sha256(b"OmiPet pairing transcript v1" + pin + b"".join(
        len(item).to_bytes(2, "big") + item for item in rounds)).digest()


def b64(data):
    return base64.b64encode(data).decode("ascii")


def unb64(text, maximum=1024):
    if not isinstance(text, str) or len(text) > ((maximum + 2) // 3) * 4:
        raise ValueError("配对响应长度无效")
    data = base64.b64decode(text, validate=True)
    if not 0 < len(data) <= maximum:
        raise ValueError("配对响应长度无效")
    return data


class BoundedFrames(frame_buffer):
    def recv_length(self):
        super().recv_length()
        if self.length > 4096 or not self.header[0] or self.header[4] not in (1, 8, 9, 10) or self.header[5]:
            raise ValueError("无线帧超限或格式无效")


class PairingSocket:
    def __init__(self, address, pin=None):
        self.address = endpoint(address)
        target = urlsplit(self.address)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        raw = socket.create_connection((target.hostname, target.port), timeout=10)
        self.ws = websocket.WebSocket()
        self.ws.frame_buffer = BoundedFrames(self.ws._recv, False)
        try:
            tls = context.wrap_socket(raw, server_hostname=target.hostname)
            raw = tls
            certificate = tls.getpeercert(binary_form=True)
            self.pin = hashlib.sha256(certificate).digest()
            if pin is not None and not verify_certificate_pin(certificate, pin):
                raise ValueError("设备身份不匹配，请核对地址；已有配对不会被覆盖")
            self.ws.connect(self.address, socket=tls, timeout=10, redirect_limit=0,
                            suppress_origin=True)
            self.send("status")
            self.ready = self.receive("status", {"paired"})
            if type(self.ready["paired"]) is not bool:
                raise ValueError("设备配对状态无效")
        except BaseException:
            raw.close()
            self.ws.shutdown()
            raise

    def send(self, kind, **body):
        text = json.dumps(dict(v=1, type=kind, **body), separators=(",", ":"), allow_nan=False)
        if len(text.encode("utf-8")) > 4096:
            raise ValueError("无线请求过大")
        self.ws.send(text)

    def receive_text(self, timeout):
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            self.ws.settimeout(remaining)
            frame = self.ws.recv_frame()
            if frame.opcode == websocket.ABNF.OPCODE_PING:
                self.ws.pong(frame.data)
                continue
            if frame.opcode == websocket.ABNF.OPCODE_PONG:
                continue
            if frame.opcode != websocket.ABNF.OPCODE_TEXT:
                raise ConnectionError("设备结束了配对连接")
            return frame.data
        raise websocket.WebSocketTimeoutException("无线接收超时")

    def receive(self, kind, fields):
        data = json.loads(self.receive_text(10).decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=invalid_constant)
        if (not isinstance(data, dict) or set(data) != {"v", "type"} | fields
                or type(data["v"]) is not int or data["v"] != 1 or data["type"] != kind):
            raise ValueError("设备配对响应无效")
        return data

    def authenticate(self, key):
        self.send("challenge")
        nonce = unb64(self.receive("challenge", {"nonce"})["nonce"], 32)
        if len(nonce) != 32:
            raise ValueError("设备随机数长度无效")
        host = os.urandom(32)
        self.send("authenticate", nonce=b64(host), proof=b64(make_proof(key, "host", nonce, host, self.pin)))
        proof = unb64(self.receive("authenticated", {"proof"})["proof"], 32)
        if not verify_proof(key, "device", nonce, host, self.pin, proof):
            raise ValueError("设备认证失败")

    def close(self):
        self.ws.shutdown()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class PairingStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ["LOCALAPPDATA"]) / "OmiPet/pairing.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.open() as db:
            db.execute("CREATE TABLE IF NOT EXISTS devices (address TEXT PRIMARY KEY, record BLOB NOT NULL, confirmed INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS repairs (address TEXT PRIMARY KEY, record BLOB NOT NULL, previous BLOB)")

    @contextmanager
    def open(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, address):
        with self.open() as db:
            row = db.execute("SELECT record, confirmed FROM devices WHERE address=?", (endpoint(address),)).fetchone()
        return (*decode_record(row[0]), bool(row[1])) if row else None

    def prepare(self, address, key, pin):
        with self.open() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record, confirmed FROM devices WHERE address=?", (endpoint(address),)).fetchone()
            if row and (row[1] or decode_record(row[0])[1] != pin):
                raise ValueError("拒绝覆盖已有设备身份")
            db.execute("INSERT OR REPLACE INTO devices VALUES (?, ?, 0)", (endpoint(address), encode_record(key, pin)))

    def confirm(self, address, key, pin):
        with self.open() as db:
            db.execute("BEGIN IMMEDIATE")
            repair = db.execute("SELECT record, previous FROM repairs WHERE address=?", (endpoint(address),)).fetchone()
            if repair and decode_record(repair[0]) == (key, pin):
                current = db.execute("SELECT record FROM devices WHERE address=?", (endpoint(address),)).fetchone()
                if (current[0] if current else None) != repair[1]:
                    raise ValueError("配对凭据已发生变化")
                for old_address, old_record in db.execute("SELECT address, record FROM devices").fetchall():
                    try:
                        same_device = decode_record(old_record)[1] == pin
                    except ValueError:
                        continue
                    if same_device:
                        db.execute("DELETE FROM devices WHERE address=?", (old_address,))
                db.execute("INSERT OR REPLACE INTO devices VALUES (?, ?, 1)", (endpoint(address), repair[0]))
                db.execute("DELETE FROM repairs WHERE address=? AND record=?", (endpoint(address), repair[0]))
                return
            cursor = db.execute("UPDATE devices SET confirmed=1 WHERE address=? AND record=?",
                                (endpoint(address), encode_record(key, pin)))
            if cursor.rowcount != 1:
                raise ValueError("配对凭据已发生变化")

    def stage_repair(self, address, key, pin):
        with self.open() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT record FROM devices WHERE address=?", (endpoint(address),)).fetchone()
            db.execute("INSERT OR REPLACE INTO repairs VALUES (?, ?, ?)",
                       (endpoint(address), encode_record(key, pin), previous[0] if previous else None))

    def authentication_records(self, address):
        with self.open() as db:
            repair = db.execute("SELECT record FROM repairs WHERE address=?", (endpoint(address),)).fetchone()
        existing = self.load(address)
        return ([(*decode_record(repair[0]), False)] if repair else []) + ([existing] if existing else [])

    def devices(self):
        with self.open() as db:
            return [dict(address=row[0], confirmed=bool(row[1]), pendingRepair=bool(row[2])) for row in
                    db.execute("SELECT d.address, d.confirmed, r.address IS NOT NULL FROM devices d LEFT JOIN repairs r ON d.address=r.address "
                               "UNION ALL SELECT r.address, 0, 1 FROM repairs r WHERE NOT EXISTS (SELECT 1 FROM devices d WHERE d.address=r.address) ORDER BY 1")]

    def relocate(self, previous, address, record):
        previous, address = endpoint(previous), endpoint(address)
        key, pin, _ = record
        with self.open() as db:
            db.execute("BEGIN IMMEDIATE")
            source = db.execute("SELECT record, confirmed FROM devices WHERE address=?", (previous,)).fetchone()
            if not source or (*decode_record(source[0]), bool(source[1])) != record:
                raise ValueError("配对凭据已发生变化")
            target = db.execute("SELECT record FROM devices WHERE address=?", (address,)).fetchone()
            if target and decode_record(target[0]) != (key, pin):
                raise ValueError("新地址已有其他设备记录，拒绝覆盖")
            db.execute("DELETE FROM devices WHERE address=?", (previous,))
            db.execute("INSERT OR REPLACE INTO devices VALUES (?, ?, 1)", (address, source[0]))


def inspect_pairing(address, *, store=None, socket_factory=PairingSocket):
    store = store or PairingStore()
    address = endpoint(address)
    records = store.authentication_records(address)
    with socket_factory(address) as wire:
        if records and all(record[1] != wire.pin for record in records):
            return "identity-changed"
        if not wire.ready["paired"]:
            return "repair-required" if records else "new"
        if not records:
            return "repair-required"
        if any(not record[2] for record in records):
            return "pending"
        wire.authenticate(records[0][0])
        return "paired-here"


class RepairRequired(ValueError):
    pass


def pair_device(address, code, *, store=None, socket_factory=PairingSocket, pake_factory=Pake, replace=False):
    store = store or PairingStore()
    existing = None if replace else store.load(address)
    with socket_factory(address, existing[1] if existing and not replace else None) as wire:
        if wire.ready["paired"] and not replace:
            if not existing:
                raise RepairRequired("设备已有绑定，本机没有对应凭据；请明确选择重新配对。")
            wire.authenticate(existing[0])
            store.confirm(address, existing[0], existing[1])
            return
        if existing and existing[2] and not replace:
            raise ValueError("已配对设备的状态异常，拒绝覆盖身份")
        with pake_factory(code) as pake:
            c1 = pake.write()
            wire.send("repair1" if replace else "pair1", data=b64(c1))
            reply = wire.receive("pair1", {"one", "two"})
            s1, s2 = unb64(reply["one"]), unb64(reply["two"])
            pake.read(s1)
            c2 = pake.write()
            pake.read(s2)
            shared = pake.derive()
        digest = transcript(wire.pin, c1, s1, s2, c2)
        wire.send("pair2", data=b64(c2), proof=b64(confirmation(shared, "H", digest, wire.pin)))
        proof = unb64(wire.receive("pair2", {"proof"})["proof"], 32)
        if not hmac.compare_digest(proof, confirmation(shared, "D", digest, wire.pin)):
            raise ValueError("配对码或设备身份验证失败")
        key = derive_daily_key(shared, digest, wire.pin)
        if replace:
            store.stage_repair(address, key, wire.pin)
        else:
            store.prepare(address, key, wire.pin)
        wire.send("commit", proof=b64(confirmation(key, "C", digest, wire.pin)))
        proof = unb64(wire.receive("committed", {"proof"})["proof"], 32)
        if not hmac.compare_digest(proof, confirmation(key, "S", digest, wire.pin)):
            raise ValueError("配对确认未完成，请重新验证连接")
        store.confirm(address, key, wire.pin)


def verify_device(address, *, store=None, socket_factory=PairingSocket):
    store = store or PairingStore()
    records = store.authentication_records(address)
    if not records:
        raise ValueError("请先输入屏幕上的六位码配对")
    for existing in records:
        try:
            with socket_factory(address, existing[1]) as wire:
                wire.authenticate(existing[0])
        except (OSError, ValueError, websocket.WebSocketException):
            continue
        store.confirm(address, existing[0], existing[1])
        return
    raise ValueError("设备认证失败；重配确认不完整时请重试验证或使用屏幕新码重配")


def relocate_device(previous, address, *, store=None, socket_factory=PairingSocket, stop=None):
    store = store or PairingStore()
    record = store.load(previous)
    if not record:
        raise ValueError("找不到原配对凭据")
    with socket_factory(address, record[1]) as wire:
        wire.authenticate(record[0])
    if stop is not None and stop.is_set():
        raise ConnectionError("cancelled")
    store.relocate(previous, address, record)
    return endpoint(address)
