import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

BACKEND = Path(__file__).resolve().parents[1] / "backend.py"
spec = importlib.util.spec_from_file_location("tauri_backend", BACKEND)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.backend = module.Backend(demo=True)
        self.received = []

    def tearDown(self):
        self.backend.close()

    def request(self, action, body=None):
        reply = self.backend.call(dict(action=action, body=body))
        self.received.extend(reply["events"])
        return reply

    def connect(self):
        settings = dict(port="demo", root=".", bindings="not-present.json")
        self.assertTrue(self.request("connect", settings)["ok"])
        self.wait_for("connected")

    def wait_for(self, kind):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.request("poll")
            events, self.received = self.received, []
            for event in events:
                if event["kind"] == kind:
                    return event
            time.sleep(0.01)
        self.fail("expected worker event missing: " + kind)

    def test_reuses_worker_for_lights_monitor_lock_and_confirmed_release(self):
        self.connect()
        setting = dict(effect="solid", red=0, green=0, blue=255, brightness=16)
        self.assertTrue(self.request("light", setting)["ok"])
        self.assertTrue(self.wait_for("command")["ok"])
        self.assertTrue(self.request("monitor")["ok"])
        self.assertTrue(self.wait_for("command")["ok"])
        self.assertTrue(self.request("light", setting)["ok"])
        event = self.wait_for("command")
        self.assertFalse(event["ok"])
        self.assertEqual(event["error"], "monitor-mode-active")
        reply = self.request("close")
        closed = next(event for event in reply["events"] if event["kind"] == "disconnected")
        self.assertTrue(closed["releaseConfirmed"])
        self.assertTrue(closed["monitorOff"])

    def test_rejects_malformed_requests_and_unlisted_ports(self):
        for message in ({}, [], dict(action="poll", body={}, extra=True), dict(action="poll", body={})):
            self.assertFalse(self.backend.call(message)["ok"])
        self.assertFalse(self.request("run-process")["ok"])
        self.assertFalse(self.request("connect", dict(port="arbitrary", root=".", bindings="."))["ok"])
        self.connect()
        self.assertFalse(self.request("light", dict(effect="solid", red=0, green=0, blue=0, brightness=True))["ok"])

    def test_suspended_frontend_keeps_latest_events_in_order(self):
        events = module.EventBuffer()
        events.put(dict(kind="connected"))
        for number in range(1000):
            events.put(dict(kind="status", revision=number))
        events.put(dict(kind="command", ok=True))
        events.put(dict(kind="status", revision=1001))
        self.assertEqual(events.drain(), [dict(kind="connected"), dict(kind="command", ok=True), dict(kind="status", revision=1001)])
        self.assertEqual(events.drain(), [])

    def test_stdio_eof_releases_worker_and_bad_json_does_not_desynchronize(self):
        process = subprocess.Popen([sys.executable, str(BACKEND), "--demo"], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        requests = [b"not-json\n", b"x" * 5000 + b"\n"]
        text = b"".join(requests).decode() + json.dumps(dict(action="init", body=None)) + "\n"
        text += json.dumps(dict(action="connect", body=dict(port="demo", root=".", bindings="."))) + "\n"
        output, errors = process.communicate(text, timeout=10)
        replies = [json.loads(line) for line in output.splitlines()]
        self.assertEqual(process.returncode, 0, errors)
        self.assertEqual([reply["ok"] for reply in replies], [False, False, True, True])
        self.assertTrue(replies[2]["result"]["demo"])


if __name__ == "__main__":
    unittest.main()
