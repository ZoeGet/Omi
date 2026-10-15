import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time

from protocol import Limits, serial_frame
from usb_client import UsbClient


def main():
    parser = argparse.ArgumentParser(description="Verify the experimental USB protocol using synthetic states; no LED commands")
    parser.add_argument("--port", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--retries", type=int, required=True)
    parser.add_argument("--max-json-bytes", type=int, required=True)
    parser.add_argument("--max-sessions", type=int, required=True)
    parser.add_argument("--observe-seconds", type=float, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    import serial
    stream = serial.Serial()
    stream.port, stream.baudrate = args.port, 115200
    stream.dtr = stream.rts = False
    stream.timeout = min(args.timeout_seconds, 0.1)
    stream.write_timeout = args.timeout_seconds
    checks = []
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  syntheticStatesOnly=True, physicalLedControl=False, checks=checks)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    trace = args.log.open("xb")
    client = UsbClient(stream, Limits(args.max_json_bytes, args.max_sessions),
                       timeout_seconds=args.timeout_seconds, retries=args.retries,
                       on_bytes=lambda data: (trace.write(data), trace.flush()))

    def check(name, passed):
        checks.append(dict(name=name, passed=bool(passed)))
        if not passed:
            raise AssertionError(name)
        print("PASS " + name, flush=True)

    def snap(revision, status, valid_ms):
        return dict(revision=revision, validForMs=valid_ms, sourceLiveness="unverified", overallStatus=status,
                    sessions=[dict(id="s1", observed=status, display=status, host="running")])

    try:
        stream.open()
        welcome = client.connect()
        report["capabilities"] = welcome["body"]
        check("handshake", client.host.ready)
        pending = client.host.prepare("heartbeat", {})
        client._write(b"\n" + serial_frame(pending, client.host.limits))
        first = client._receive(client.clock() + args.timeout_seconds, lambda item:
                                item["type"] == "ack" and all(item[key] == pending[key]
                                for key in ("boot", "channel", "session", "seq")))
        check("first_ack_observed_before_intentional_drop", first["body"]["ok"])
        repeated = client.retry_pending()
        check("same_request_retry_is_duplicate", repeated["ok"] and repeated["duplicate"])
        reply = client.request("snapshot", snap(1, "working", 1000))
        check("synthetic_snapshot", reply["ok"] and reply["state"]["displayStatus"] == "working")
        client.observe(1.2)
        reply = client.request("heartbeat", {})
        check("heartbeat_does_not_renew_snapshot", reply["ok"] and reply["state"]["displayStatus"] == "unknown")
        reply = client.release()
        check("release", reply["ok"] and reply["state"]["mode"] == "local" and not reply["state"]["leaseActive"])
        reply = client.request("heartbeat", {})
        check("heartbeat_after_release_stays_local", reply["state"]["mode"] == "local")
        client.request("snapshot", snap(2, "unknown", 0))
        stream.close()
        time.sleep(welcome["body"]["leaseMs"] / 1000 + 0.2)
        stream.open()
        reply = client.request("heartbeat", {})
        check("port_close_lease_expiry", not reply["ok"] and reply["code"] == "connection-expired-reconnect-required"
              and reply["state"]["mode"] == "local" and not reply["state"]["leaseActive"])
        next_welcome = client.connect()
        check("reconnect_new_channel_same_boot", next_welcome["channel"] != welcome["channel"] and next_welcome["boot"] == welcome["boot"])
        client._write(b'\n@OMI {"unfinished":"working')
        client.connect()
        check("partial_frame_probe_recovery", client.host.ready)
        client._write(b"\n@OMI " + b"w" * (args.max_json_bytes + 64) + b"\n")
        client.connect()
        check("oversize_frame_probe_recovery", client.host.ready)
        client.release()
        client.observe(args.observe_seconds)
        trace.flush()
        text = args.log.read_bytes().decode("utf-8", "replace")
        check("microphone_alive", "mic=ok" in text)
        check("audio_frames_healthy", "queued=0 dropped=0" in text and not re.search(r"(?:queued|dropped)=[1-9]", text))
        check("no_watchdog_or_panic", not re.search(r"task_wdt|Guru Meditation|panic'ed|abort\(\)", text))
        check("frame_text_did_not_trigger_debug", "serial wake trigger" not in text)
        report["maxPollUs"] = max((int(value) for value in re.findall(r"max_poll_us=(\d+)", text)), default=None)
        report["minReportedHeap"] = min((int(value) for value in re.findall(r"heap=(\d+)", text)), default=None)
        report["result"] = "pass"
    except Exception as error:
        report["result"] = "fail"
        report["error"] = str(error)
        raise
    finally:
        report["roundTrips"] = client.round_trips
        report["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if stream.is_open:
            stream.close()
        trace.close()


if __name__ == "__main__":
    main()
