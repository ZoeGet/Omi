import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

BACKEND = Path(__file__).resolve().parents[1] / "backend.py"
spec = importlib.util.spec_from_file_location("tauri_backend", BACKEND)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BackendTests(unittest.TestCase):
    def test_close_releases_device_before_waiting_for_startup_check(self):
        finish_check = threading.Event()
        released = threading.Event()
        self.backend.monitor_watcher = threading.Thread(target=finish_check.wait)
        self.backend.monitor_watcher.start()
        self.backend.worker = Mock()
        self.backend.worker.stop.side_effect = released.set
        closing = threading.Thread(target=self.backend.close)
        closing.start()
        try:
            self.assertTrue(released.wait(1), "Startup check must not delay device release")
        finally:
            finish_check.set()
            closing.join(5)
        self.assertFalse(closing.is_alive())

    def test_startup_check_runs_once_and_demo_never_starts_it(self):
        with patch.object(self.backend, "watch_monitor") as check:
            self.request("init")
            check.assert_not_called()
            self.backend.demo = False
            with patch.object(self.backend, "ports", return_value=[]):
                self.request("init")
                self.backend.monitor_watcher.join()
                self.request("init")
            check.assert_called_once()

    def test_explicit_ready_check_clears_update_reminder(self):
        with patch("monitor_setup.MonitorSetup") as setup:
            setup.return_value.status.return_value = dict(state="awaiting-binding")
            self.request("monitor-setup-status")
            self.assertFalse(any(e["kind"] == "monitor-setup" for e in self.received))
            setup.return_value.status.return_value = dict(state="ready")
            self.request("monitor-setup-status")
            self.assertIn(dict(kind="monitor-setup", update=None), self.received)

    def test_monitor_watcher_reports_updates_without_touching_device(self):
        self.backend.demo = False
        self.backend.connected = True
        result = dict(state="awaiting-event", message="请信任新 Hook")
        with patch("monitor_setup.MonitorSetup") as setup:
            setup.return_value.auto_update.return_value = result
            self.backend.watch_monitor()
            setup.return_value.auto_update.assert_called_once()
            event = self.backend.events.drain()[0]
            self.assertEqual(event, dict(kind="monitor-setup", update=result))
            self.assertTrue(self.backend.connected)
            self.assertIsNone(self.backend.worker)

    def test_monitor_watcher_failure_is_actionable_and_does_not_stop_backend(self):
        with patch("monitor_setup.MonitorSetup") as setup:
            for construction_fails in (False, True):
                setup.side_effect = OSError("private details") if construction_fails else None
                setup.return_value.auto_update.side_effect = OSError("private details")
                self.backend.watch_monitor()
                event = self.backend.events.drain()[0]
                self.assertEqual(event["update"]["state"], "manual-update")
                self.assertNotIn("private", event["update"]["message"])

    def test_pairing_inspection_is_read_only_explicit_and_reports_safe_state(self):
        self.backend.demo = False
        with patch('wireless_pairing.inspect_pairing', return_value='repair-required') as inspect:
            self.assertTrue(self.request('inspect-wireless', dict(address='192.0.2.1'))['ok'])
            event = self.wait_for('pairing')
            self.assertEqual(event['pairingState'], 'repair-required')
            self.assertEqual(event['port'], 'wss://192.0.2.1:8443/pair')
            inspect.assert_called_once()
        self.backend.connected = True
        self.assertFalse(self.request('inspect-wireless', dict(address='192.0.2.1'))['ok'])

    def test_existing_binding_is_reported_without_raw_error_or_automatic_repair(self):
        from wireless_pairing import RepairRequired
        self.backend.demo = False
        with patch('wireless_pairing.pair_device', side_effect=RepairRequired('private 123456')) as pair:
            self.assertTrue(self.request('pair', dict(address='192.0.2.1', code='123456'))['ok'])
            event = self.wait_for('pairing')
            self.assertEqual(event['pairingState'], 'repair-required')
            self.assertFalse(event['ok'])
            self.assertNotIn('123456', json.dumps(event))
            self.assertNotIn('replace', pair.call_args.kwargs)

    def test_setup_is_explicit_and_never_mutates_in_demo_or_connected_mode(self):
        with patch('monitor_setup.MonitorSetup') as setup:
            setup.return_value.status.return_value = dict(state='not-installed')
            self.assertTrue(self.request('monitor-setup-status')['ok'])
            self.assertFalse(self.request('monitor-setup-install', dict(images=['C:/Codex.exe']))['ok'])
            self.assertFalse(self.request('monitor-setup-uninstall')['ok'])
            setup.return_value.install.assert_not_called()
            self.backend.demo = False
            self.backend.connected = True
            self.assertFalse(self.request('monitor-setup-uninstall')['ok'])
            self.backend.connected = False
            self.assertFalse(self.request('monitor-setup-install', dict(extra=True))['ok'])
            setup.return_value.install.return_value = dict(message='installed')
            self.assertTrue(self.request('monitor-setup-install', dict(images=['C:/Codex.exe']))['ok'])
            setup.return_value.install.assert_called_once_with(['C:/Codex.exe'])

    def test_pairing_runs_off_request_thread_and_redacts_errors(self):
        self.backend.demo = False
        entered, release = module.threading.Event(), module.threading.Event()
        def fail(*args, **kwargs):
            entered.set()
            release.wait(5)
            raise ValueError("private proof 123456")
        with patch("wireless_pairing.pair_device", side_effect=fail):
            try:
                self.assertTrue(self.request("pair", dict(address="192.0.2.1", code="123456"))["ok"])
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.request("poll")["ok"])
                self.assertFalse(self.request("pair", dict(address="192.0.2.1", code="123456"))["ok"])
            finally:
                release.set()
            event = self.wait_for("pairing")
            self.assertFalse(event["ok"])
            self.assertNotIn("123456", json.dumps(event))

    def test_find_and_manual_migration_use_background_worker_and_report_verified_address(self):
        self.backend.demo = False
        for action, target in (("find-wireless", "wireless_discovery.find_device"),
                               ("relocate-wireless", "wireless_pairing.relocate_device")):
            body = dict(address="192.0.2.1")
            if action == "relocate-wireless": body["previous"] = "192.0.2.9"
            with patch(target, return_value="wss://192.0.2.42:8443/pair") as operation:
                self.assertTrue(self.request(action, body)["ok"])
                event = self.wait_for("pairing")
                self.assertTrue(event["ok"])
                self.assertEqual(event["port"], "wss://192.0.2.42:8443/pair")
                operation.assert_called_once()
                self.assertIs(operation.call_args.kwargs["stop"], self.backend.pairing_stop)
            self.backend.pairing_worker.join()
        self.assertFalse(self.request("relocate-wireless", dict(address="192.0.2.1"))["ok"])
        self.backend.connected = True
        self.assertFalse(self.request("find-wireless", dict(address="192.0.2.1"))["ok"])

    def test_repair_requires_explicit_command_and_six_digit_code(self):
        self.backend.demo = False
        for code in ("12345", "abcdef", "１２３４５６"):
            self.assertFalse(self.request("re-pair", dict(address="192.0.2.1", code=code))["ok"])
        with patch("wireless_pairing.pair_device") as pair:
            self.assertTrue(self.request("re-pair", dict(address="192.0.2.1", code="123456"))["ok"])
            self.assertTrue(self.wait_for("pairing")["ok"])
            self.assertTrue(pair.call_args.kwargs["replace"])

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

    def test_profile_command_flows_through_backend_worker_and_session(self):
        from protocol import default_monitor_profile
        self.connect()
        setting = default_monitor_profile()
        setting["profiles"]["unknown"].update(effect="off", brightness=0)
        self.assertTrue(self.request("monitor-profile", setting)["ok"])
        command = self.wait_for("command")
        self.assertTrue(command["ok"])
        self.assertEqual(command["command"], "monitor-profile")
        self.assertEqual(self.backend.worker.session.monitor_profile["profiles"], setting["profiles"])
        self.assertEqual(self.backend.worker.session.monitor_profile["revision"], 1)
        setting["profiles"].pop("idle")
        self.assertFalse(self.request("monitor-profile", setting)["ok"])

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
