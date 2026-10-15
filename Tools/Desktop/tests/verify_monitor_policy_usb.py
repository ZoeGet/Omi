import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import INTERVAL_SECONDS, default_monitor_root, open_usb


def main():
    parser = argparse.ArgumentParser(description="Explicit USB check of green fallback and disconnect-off policy")
    parser.add_argument("--port", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  syntheticStates=True, physicalUnplugTested=False, visualVerified=False, checks=[])
    control = stream = health = None
    current = "unknown"

    def reader():
        if current == "source-error":
            raise OSError("deliberate local source failure")
        return dict(sourceState="readable", bindingState="event-correlated", maxAgeSeconds=30,
                    evaluatedAtUtc=datetime.now(timezone.utc).isoformat(),
                    evaluatedAtMonotonicNs=str(time.monotonic_ns()), sessions=[] if current == "unknown" else [dict(
                        sessionId="policy-usb-check", lastObservedStatus=current, displayStatus=current,
                        hostProcessState="running", observationAgeSeconds=0)])

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)

    try:
        root = default_monitor_root()
        control, stream, health = open_usb(args.port, root, root / "host-bindings.json")
        check("device advertises green-off monitor policy", control.monitor_green_off)
        control.reader = reader
        control.monitor()
        control.client.observe(INTERVAL_SECONDS)
        check("empty source remains protocol unknown with connected monitor", control.state["displayStatus"] == "unknown"
              and control.state["monitorOutput"] == "connected")
        for current in ("working", "waitingApproval", "idle", "working", "source-error"):
            control.tick()
            control.client.observe(INTERVAL_SECONDS)
            expected = "unknown" if current == "source-error" else current
            check(f"{current}: ACK and connected output", control.state["displayStatus"] == expected
                  and control.state["monitorOutput"] == "connected")
        check("device logged unknown, working, approval and idle diffusion", all(
            health.report["monitorLedTransitions"].get(status, 0) for status in ("unknown", "working", "waitingApproval", "idle")))
        control.close()
        control.client.observe(INTERVAL_SECONDS)
        check("graceful monitor disconnect ACK and off log", control.state["monitorOutput"] == "disconnected"
              and health.report["monitorDisconnectOffs"] >= 1)
        control.connect(local=False)
        check("discovery and hello retain disconnected output", control.state["monitorOutput"] == "disconnected")
        current = "working"
        control.monitor()
        control.client.observe(INTERVAL_SECONDS)
        before = health.report["monitorDisconnectOffs"]
        wait = control.client.host.lease_ms / 1000 + INTERVAL_SECONDS
        control.client.observe(wait)
        reply = control.client.request("heartbeat", {})
        check("silence past negotiated lease turns off and expires connection", not reply["ok"]
              and reply["code"] == "connection-expired-reconnect-required"
              and reply["state"]["monitorOutput"] == "disconnected"
              and health.report["monitorDisconnectOffs"] > before)
        before_local = health.report["localLedFallbacks"]
        control.client.connect()
        reply = control.client.request("heartbeat", {})
        control.client.observe(INTERVAL_SECONDS)
        check("reconnect does not briefly restore local animation", reply["state"]["monitorOutput"] == "disconnected"
              and health.report["localLedFallbacks"] == before_local)
        control.local()
        control.client.observe(INTERVAL_SECONDS)
        check("explicit local mode restores saved light", control.state["monitorOutput"] == "local"
              and health.report["localLedFallbacks"] > before_local)
        check("microphone and audio health", health.report["microphoneOk"] and health.report["audioSamples"] > 0
              and not health.report["audioQueueProblem"] and not health.report["watchdogOrPanic"]
              and not health.report["unexpectedDebugWake"])
        check("no USB timeout or decoding errors", control.client.diagnostics["replyTimeouts"] == 0
              and control.client.diagnostics["decodeIssues"] == 0)
        report["result"] = "pass"
    except Exception as error:
        report.update(result="fail", error=str(error))
    finally:
        if control:
            try:
                control.local()
                report["localConfirmed"] = control.state["monitorOutput"] == "local"
            except Exception:
                report["localConfirmed"] = False
            report["finalState"] = control.state
            report["diagnostics"] = control.client.diagnostics
        if health:
            report["health"] = health.report
        if stream:
            stream.close()
        report["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
