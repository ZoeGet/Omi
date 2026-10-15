import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from protocol import Limits
from usb_client import UsbClient


def snapshot(revision, validity_ms):
    return dict(revision=revision, validForMs=validity_ms, sourceLiveness="unverified",
                overallStatus="working", sessions=[dict(id="s1", observed="working",
                                                       display="working", host="running")])


def run(client, budget_ms, *, clock=time.monotonic):
    welcome = client.connect()
    lease_ms = welcome["body"]["leaseMs"]
    if type(lease_ms) is not int or lease_ms <= 0 or budget_ms <= lease_ms:
        raise ValueError("Approved observation budget must exceed negotiated lease")
    first = client.request("snapshot", snapshot(1, budget_ms))
    if not first["ok"] or first["state"]["displayStatus"] != "working":
        raise AssertionError("initial synthetic working snapshot was not applied")
    delayed = client.host.prepare("snapshot", snapshot(2, budget_ms))
    silent_started = clock()
    client.observe(lease_ms / 1000)
    while clock() - silent_started < lease_ms / 1000:
        time.sleep(max(0, lease_ms / 1000 - (clock() - silent_started)))
    late = client._exchange(delayed)
    if (late["ok"] or late["code"] != "connection-expired-reconnect-required"
            or late["state"]["mode"] != "local" or late["state"]["displayStatus"] != "unknown"
            or late["state"]["leaseActive"]):
        raise AssertionError("late snapshot did not fail closed after lease expiry")
    next_welcome = client.connect()
    if next_welcome["channel"] == welcome["channel"]:
        raise AssertionError("reconnect reused a connection identity")
    final = client.release()
    if not final["ok"] or final["state"]["mode"] != "local" or final["state"]["leaseActive"]:
        raise AssertionError("final release was not confirmed")
    return dict(leaseMs=lease_ms, observationBudgetMs=budget_ms,
                silentMs=round((clock() - silent_started) * 1000),
                firstDisplay=first["state"]["displayStatus"], lateCode=late["code"],
                lateState=late["state"], releaseConfirmed=True)


def main():
    parser = argparse.ArgumentParser(description="Verify USB lease fallback without physical LED control")
    parser.add_argument("--port", required=True)
    parser.add_argument("--max-json-bytes", type=int, required=True)
    parser.add_argument("--max-sessions", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--retries", type=int, required=True)
    parser.add_argument("--observation-budget-ms", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.observation_budget_ms <= 0:
        parser.error("Observation budget must be positive")
    import serial
    stream = serial.Serial()
    stream.port, stream.baudrate = args.port, 115200
    stream.dtr = stream.rts = False
    stream.timeout = min(args.timeout_seconds, 0.1)
    stream.write_timeout = args.timeout_seconds
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  syntheticStatesOnly=True, physicalLedControl=False)
    with args.log.open("xb") as trace:
        client = UsbClient(stream, Limits(args.max_json_bytes, args.max_sessions),
                           timeout_seconds=args.timeout_seconds, retries=args.retries,
                           on_bytes=lambda data: (trace.write(data), trace.flush()))
        try:
            stream.open()
            report.update(run(client, args.observation_budget_ms))
            trace.flush()
            log = args.log.read_bytes().decode("utf-8", "replace")
            report["health"] = dict(microphoneOk="mic=ok" in log,
                                    audioQueueProblem=bool(re.search(r"(?:queued|dropped)=[1-9]", log)),
                                    watchdogOrPanic=bool(re.search(r"task_wdt|Guru Meditation|panic'ed|abort\(\)", log)),
                                    unexpectedDebugWake="serial wake trigger" in log)
            report["result"] = "pass" if (report["health"]["microphoneOk"]
                                         and not any(value for key, value in report["health"].items()
                                                     if key != "microphoneOk")) else "incomplete"
        except Exception as error:
            report.update(result="fail", errorType=type(error).__name__)
            raise
        finally:
            if client.host is not None and not report.get("releaseConfirmed"):
                try:
                    if client.host.pending is not None or client.host.invalidated:
                        client.connect()
                    client.release()
                except Exception:
                    pass
            if stream.is_open:
                stream.close()
            report["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
