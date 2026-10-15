import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from protocol import Limits, ProtocolError
from usb_client import UsbClient


def snapshot(status, revision, validity_ms, challenge_seq):
    active = status != "unknown"
    return dict(revision=revision, validForMs=validity_ms if active else 0,
                sourceLiveness="unverified", overallStatus=status,
                sessions=[dict(id="s1", observed=status if active else "working",
                               display=status, host="running" if active else "unverified")],
                challengeSeq=challenge_seq)


def run(client, dwell_seconds, validity_ms, check_lease):
    welcome = client.connect()
    if not welcome["body"].get("freshnessChallenge"):
        raise AssertionError("device does not advertise freshness challenge")
    states = []
    for revision, status in enumerate(("working", "waitingApproval", "idle", "unknown"), 1):
        challenge_seq = client.host.next_seq
        heartbeat = client.request("heartbeat", {})
        if not heartbeat["ok"]:
            raise AssertionError("challenge heartbeat rejected")
        reply = client.request("snapshot", snapshot(status, revision, validity_ms, challenge_seq))
        if not reply["ok"] or reply["state"]["displayStatus"] != status:
            raise AssertionError("unexpected snapshot acknowledgement: " + status + ": " + reply["code"])
        states.append(status)
        client.observe(dwell_seconds)
    release_recovered = False
    try:
        final = client.release()
    except (ProtocolError, TimeoutError):
        client.connect()
        final = client.release()
        release_recovered = True
    if final is not None and not final["ok"] and final.get("code") == "connection-expired-reconnect-required":
        client.connect()
        final = client.release()
        release_recovered = True
    if not final["ok"] or final["state"]["mode"] != "local" or final["state"]["leaseActive"]:
        raise AssertionError("release did not restore local protocol mode")
    client.observe(dwell_seconds)
    result = dict(states=states, releaseConfirmed=True, releaseRecovered=release_recovered,
                  maxRoundTripMs=round(client.diagnostics["maxRoundTripMs"], 1))
    if check_lease:
        welcome = client.connect()
        lease_ms = welcome["body"]["leaseMs"]
        challenge_seq = client.host.next_seq
        if not client.request("heartbeat", {})["ok"]:
            raise AssertionError("lease-test heartbeat rejected")
        reply = client.request("snapshot", snapshot("working", 1, validity_ms, challenge_seq))
        if not reply["ok"] or reply["state"]["displayStatus"] != "working":
            raise AssertionError("lease-test working snapshot rejected")
        client.observe(lease_ms / 1000 + dwell_seconds)
        client.connect()
        release = client.release()
        if not release["ok"] or release["state"]["mode"] != "local":
            raise AssertionError("lease-test reconnect did not release")
        result.update(leaseMs=lease_ms, leaseFallbackExpected=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="Exercise isolated physical monitor LEDs with synthetic status snapshots")
    parser.add_argument("--port", required=True)
    parser.add_argument("--max-json-bytes", type=int, required=True)
    parser.add_argument("--max-sessions", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--retries", type=int, required=True)
    parser.add_argument("--dwell-seconds", type=float, required=True)
    parser.add_argument("--observation-budget-ms", type=int, required=True)
    parser.add_argument("--check-lease", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.dwell_seconds <= 0 or args.observation_budget_ms <= 0:
        parser.error("Dwell and observation budget must be positive")
    import serial
    stream = serial.Serial()
    stream.port, stream.baudrate = args.port, 115200
    stream.dtr = stream.rts = False
    stream.timeout = min(args.timeout_seconds, 0.1)
    stream.write_timeout = args.timeout_seconds
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  syntheticStatesOnly=True, physicalLedControl=True, visualVerified=False)
    with args.log.open("xb") as trace:
        client = UsbClient(stream, Limits(args.max_json_bytes, args.max_sessions),
                           timeout_seconds=args.timeout_seconds, retries=args.retries,
                           on_bytes=lambda data: (trace.write(data), trace.flush()))
        try:
            stream.open()
            report.update(run(client, args.dwell_seconds, args.observation_budget_ms,
                              args.check_lease))
            log = args.log.read_bytes().decode("utf-8", "replace")
            expected = tuple("[LED] owner=monitor effect=center_expand status=" + state
                             for state in report["states"] if state != "unknown")
            report["ledTransitions"] = {state: state in log for state in expected}
            report["localFallback"] = "[LED] owner=local reason=fallback" in log
            if args.check_lease:
                report["leaseFallbackVerified"] = log.count("[LED] owner=local reason=fallback") >= 2
            report["health"] = dict(microphoneOk="mic=ok" in log,
                                    audioQueueProblem=bool(re.search(r"(?:queued|dropped)=[1-9]", log)),
                                    watchdogOrPanic=bool(re.search(r"task_wdt|Guru Meditation|panic'ed|abort\(\)", log)),
                                    unexpectedDebugWake="serial wake trigger" in log)
            report["result"] = "pass" if (all(report["ledTransitions"].values())
                                         and report["localFallback"]
                                         and (not args.check_lease or report["leaseFallbackVerified"])
                                         and report["health"]["microphoneOk"]
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
