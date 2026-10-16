import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def verify(backend, port):
    process = subprocess.Popen([str(backend)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8")
    replies = queue.Queue()
    def read_replies():
        for line in process.stdout:
            replies.put(line)
    threading.Thread(target=read_replies, daemon=True).start()
    events = []
    report = dict(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=port, backend=str(backend), checks=[])

    def request(action, body=None):
        process.stdin.write(json.dumps(dict(action=action, body=body)) + "\n")
        process.stdin.flush()
        reply = json.loads(replies.get(timeout=10))
        assert reply["ok"], reply
        events.extend(reply["events"])
        return reply.get("result")

    def wait(predicate):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for index, event in enumerate(events):
                if predicate(event):
                    del events[:index + 1]
                    return event
            request("poll")
            time.sleep(0.05)
        raise AssertionError("Device confirmation missing")

    def check(name, passed):
        assert passed, name
        report["checks"].append(name)

    try:
        info = request("init")
        check("real-usb-port", not info["demo"] and port in {item["device"] for item in info["ports"]})
        settings = dict(port=port, root=info["root"], bindings=info["bindings"])
        request("connect", settings)
        wait(lambda event: event["kind"] == "connected")
        status = wait(lambda event: event["kind"] == "status")
        check("capabilities", "light" in status["operations"] and status["monitorLights"] and status["monitorGreenOff"])
        check("confirmed-local", status["state"]["mode"] == "local")
        report["lights"] = []
        for effect in ("solid", "rainbow", "breathe", "sweep", "centerExpand", "off"):
            light = dict(effect=effect, red=255, green=255, blue=255, brightness=16)
            request("light", light)
            ack = wait(lambda event: event["kind"] == "command")
            check(effect + "-ack", ack["ok"])
            status = wait(lambda event: event["kind"] == "status")
            check(effect + "-confirmed-value", status["lastLight"] == light)
            report["lights"].append(status["lastLight"])
        request("monitor")
        check("monitor-ack", wait(lambda event: event["kind"] == "command")["ok"])
        status = wait(lambda event: event["kind"] == "status")
        check("monitor-output-connected", status["monitorRequested"] and status["state"]["monitorOutput"] == "connected")
        request("light", dict(effect="solid", red=0, green=0, blue=255, brightness=16))
        ack = wait(lambda event: event["kind"] == "command")
        check("monitor-lock-enforced", not ack["ok"] and ack["error"] == "monitor-mode-active")
        status = wait(lambda event: event["kind"] == "status")
        report["snapshot"] = status
        request("disconnect")
        closed = wait(lambda event: event["kind"] == "disconnected")
        check("disconnect-release-ack", closed["releaseConfirmed"] and closed["monitorOff"])
        request("connect", settings)
        wait(lambda event: event["kind"] == "connected")
        request("close")
        closed = wait(lambda event: event["kind"] == "disconnected")
        check("close-release-ack", closed["releaseConfirmed"])
        process.wait(timeout=10)
        check("helper-exited", process.returncode == 0)
        report["result"] = "pass"
        return report
    finally:
        if process.poll() is None:
            process.stdin.close()
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description="Verify the frozen Tauri USB adapter with existing firmware")
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--port", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.backend.resolve(), args.port)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(result=report["result"], checks=len(report["checks"]), port=args.port)))


if __name__ == "__main__":
    main()
