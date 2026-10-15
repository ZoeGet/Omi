import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path

from protocol import (Limits, ProtocolError, SerialDecoder, SnapshotMapper, decode_websocket,
                      serial_frame, websocket_text)
from simulator import DeviceSimulator, HostSession


def transfer(message, limits):
    decoder = SerialDecoder(limits)
    wire = b"[DEVICE] ordinary log\n" + serial_frame(message, limits)
    messages, issues = [], []
    for byte in wire:
        received, errors = decoder.feed(bytes([byte]))
        messages.extend(received)
        issues.extend(errors)
    if issues or messages != [decode_websocket(websocket_text(message, limits), limits)]:
        raise ProtocolError("transport-codecs-disagree")
    return messages[0]


def run(limits, lease_ms, view=None):
    now = datetime.now(timezone.utc)
    if view is None:
        view = dict(evaluatedAtUtc=now.isoformat(), maxAgeSeconds=None, sourceState="readable", sessions=[dict(
            sessionId="demo-session", lastObservedStatus="working", displayStatus="unknown",
            hostProcessState="unverified", observationAgeSeconds=0)])
    mapper = SnapshotMapper()
    device = DeviceSimulator(limits, lease_ms=lease_ms)
    host = HostSession(transfer(device.open(0), limits), limits)
    trace = []

    def exchange(kind, body):
        request = transfer(host.prepare(kind, body), host.limits)
        ack = transfer(device.receive(request, 0), host.limits)
        result = host.accept(ack)
        trace.append(dict(command=kind, ok=result["ok"], code=result["code"], **result["state"]))
        return result

    exchange("hello", {"protocol": 1})
    body = mapper.convert(view, host.limits, now=now)
    request = transfer(host.prepare("snapshot", body), host.limits)
    device.receive(request, 0)
    reply = transfer(device.receive(transfer(host.retry(), host.limits), 0), host.limits)
    result = host.accept(reply)
    trace.append(dict(command="snapshot-after-lost-ack", duplicate=result["duplicate"], **result["state"]))
    if device.applied_snapshots != 1:
        raise ProtocolError("duplicate-applied-twice")
    exchange("heartbeat", {})
    exchange("release", {})
    later = copy.deepcopy(body)
    later["revision"] += 1
    exchange("snapshot", later)
    device.advance(lease_ms)
    trace.append(dict(command="lease-expired", **device.state()))
    return dict(simulationOnly=True, transportCodecsAgree=True,
                limits=dict(maxJsonBytes=limits.max_json_bytes, maxSessions=limits.max_sessions, leaseMs=lease_ms),
                appliedSnapshots=device.applied_snapshots, trace=trace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="In-memory USB/WebSocket codec simulation; never opens a device")
    parser.add_argument("--max-json-bytes", type=int, required=True)
    parser.add_argument("--max-sessions", type=int, required=True)
    parser.add_argument("--lease-ms", type=int, required=True)
    parser.add_argument("--view-file", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    view = json.loads(args.view_file.read_text(encoding="utf-8-sig")) if args.view_file else None
    result = run(Limits(args.max_json_bytes, args.max_sessions), args.lease_ms, view)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
