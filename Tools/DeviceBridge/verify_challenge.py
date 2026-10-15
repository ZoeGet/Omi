import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from protocol import Limits
from usb_client import UsbClient


def snapshot(revision, validity_ms, challenge=None):
    body = dict(revision=revision, validForMs=validity_ms, sourceLiveness="unverified",
                overallStatus="working", sessions=[dict(id="s1", observed="working",
                                                       display="working", host="running")])
    if challenge is not None:
        body["challengeSeq"] = challenge
    return body


def run(client, validity_ms):
    welcome = client.connect()
    if welcome["body"].get("freshnessChallenge") is not True:
        raise AssertionError("Device did not advertise the isolated freshness challenge")
    missing = client.request("snapshot", snapshot(1, validity_ms))
    if missing["ok"] or missing["code"] != "freshness-challenge-required":
        raise AssertionError("Missing challenge was not rejected")
    challenge_seq = client.host.next_seq
    heartbeat = client.request("heartbeat", {})
    if not heartbeat["ok"]:
        raise AssertionError("Heartbeat challenge failed")
    accepted = client.request("snapshot", snapshot(1, validity_ms, challenge_seq))
    if not accepted["ok"] or accepted["state"]["displayStatus"] != "working":
        raise AssertionError("Challenged synthetic snapshot was not applied")
    renewed = client.request("heartbeat", {})
    if not renewed["ok"]:
        raise AssertionError("Lease renewal failed")
    stale = client.request("snapshot", snapshot(2, validity_ms, challenge_seq))
    if stale["ok"] or stale["code"] != "freshness-challenge-required":
        raise AssertionError("Old challenge was accepted after heartbeat renewal")
    final = client.release()
    if not final["ok"] or final["state"]["mode"] != "local" or final["state"]["leaseActive"]:
        raise AssertionError("Release was not confirmed")
    return dict(capability=True, missingCode=missing["code"], acceptedDisplay="working",
                staleCode=stale["code"], finalState=final["state"], releaseConfirmed=True)


def main():
    parser = argparse.ArgumentParser(description="Check isolated USB challenge without physical LED control")
    parser.add_argument("--port", required=True)
    parser.add_argument("--max-json-bytes", type=int, required=True)
    parser.add_argument("--max-sessions", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--retries", type=int, required=True)
    parser.add_argument("--observation-budget-ms", type=int, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.observation_budget_ms <= 0:
        parser.error("Observation budget must be positive")
    import serial
    stream = serial.Serial()
    stream.port, stream.baudrate = args.port, 115200
    stream.dtr = stream.rts = False
    stream.timeout = min(args.timeout_seconds, 0.1)
    stream.write_timeout = args.timeout_seconds
    client = UsbClient(stream, Limits(args.max_json_bytes, args.max_sessions),
                       timeout_seconds=args.timeout_seconds, retries=args.retries)
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  syntheticStatesOnly=True, physicalLedControl=False)
    try:
        stream.open()
        report.update(run(client, args.observation_budget_ms))
        report["result"] = "pass"
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
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
