import argparse
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import default_monitor_root, open_usb
from protocol import LIGHT_EFFECTS, ProtocolError


def main():
    parser = argparse.ArgumentParser(description="Explicit USB desktop-light and mode integration check")
    parser.add_argument("--port", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--exercise-lights", action="store_true")
    args = parser.parse_args()
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  visualVerified=False, firmwareFlashed=False, checks=[])
    root = default_monitor_root()
    control = stream = health = None
    try:
        control, stream, health = open_usb(args.port, root, root / "host-bindings.json")
        report["desktopLogRecords"] = []
        original_line = health.line
        def capture_line(text):
            match = re.search(r"\[LED\] owner=desktop revision=(\d+) effect=(\d+) rgb=(\d+),(\d+),(\d+) brightness=(\d+)", text)
            if match:
                report["desktopLogRecords"].append(dict(
                    values=[int(value) for value in match.groups()],
                    leadingCharacters=match.start(), trailingCharacters=len(text) - match.end()))
            original_line(text)
        health.line = capture_line
        report["capabilities"] = dict(operations=sorted(control.operations), monitorLights=control.monitor_lights)
        report["checks"].append("real USB discovery and heartbeat")
        if args.exercise_lights:
            setting = dict(effect="solid", red=0, green=0, blue=255, brightness=16)
            report["effectObservations"] = []
            for effect in LIGHT_EFFECTS:
                setting["effect"] = effect
                control.light(setting)
                control.client.observe(1)
                report["effectObservations"].append(dict(requestedEffect=effect, lastLog=health.report["lastDesktopLight"]))
            report["checks"].append("six local effects accepted at brightness 16")
            control.monitor()
            reply = control.client.request("light", setting)
            if reply["ok"] or reply["code"] != "monitor-mode-active":
                raise ProtocolError("firmware-monitor-lock-failed")
            report["checks"].append("firmware rejects manual light during monitor mode")
            control.local()
            control.light(dict(setting, effect="solid"))
            control.client.observe(1)
            control.light(dict(effect="solid", red=255, green=255, blue=255, brightness=16))
            control.client.observe(1)
            report["checks"].append("release restores manual control and final white solid 16")
        control.local()
        report["releaseConfirmed"] = True
        control.client.observe(2)
        report["health"] = health.report
        report["diagnostics"] = control.client.diagnostics
        healthy = (health.report["microphoneOk"] and not health.report["audioQueueProblem"]
                   and not health.report["watchdogOrPanic"] and not health.report["unexpectedDebugWake"])
        applied = not args.exercise_lights or health.report["desktopLightCommands"] == 8
        report["result"] = "pass" if healthy and applied else "incomplete"
    except Exception as error:
        report.update(result="fail", error=str(error))
        if control:
            try:
                control.local()
                report["releaseConfirmed"] = True
            except Exception:
                report["releaseConfirmed"] = False
    finally:
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
