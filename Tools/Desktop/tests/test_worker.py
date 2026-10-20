from pathlib import Path
import queue
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import DeviceWorker
from controller import ControlSession, SimulatedClient


class WorkerTests(unittest.TestCase):
    def test_recovery_reopens_transport_restores_fresh_monitor_and_drops_queued_light(self):
        for wireless in (False, True):
            with self.subTest(wireless=wireless):
                events = queue.Queue()
                worker = DeviceWorker(events, port="test", root=Path("."), bindings=Path("."), wireless=wireless)
                worker.session = Mock(monitor_requested=True)
                old_stream = worker.stream = Mock()
                fresh = Mock()
                fresh.snapshot.return_value = {}
                worker.submit("light", {})
                with patch.object(worker.stopping, "wait", return_value=False), patch(
                        "worker.open_wifi" if wireless else "worker.open_usb", return_value=(fresh, Mock(), None)) as connect:
                    self.assertTrue(worker.recover(OSError("unplugged")))
                connect.assert_called_once()
                old_stream.close.assert_called_once()
                fresh.monitor.assert_called_once()
                fresh.light.assert_not_called()
                self.assertTrue(worker.commands.empty())
                result = list(events.queue)
                self.assertEqual(result[0]["error"], "connection-interrupted")
                self.assertEqual(result[-2]["kind"], "connected")

    def test_recovery_stops_on_cancel_auth_failure_and_retry_budget(self):
        from protocol import ProtocolError
        worker = DeviceWorker(queue.Queue(), port="test", root=Path("."), bindings=Path("."))
        with patch.object(worker.stopping, "wait", return_value=True), patch.object(worker, "open") as connect:
            self.assertFalse(worker.recover(OSError()))
            connect.assert_not_called()
        with patch.object(worker.stopping, "wait") as wait:
            with self.assertRaisesRegex(ProtocolError, "authentication-failed"):
                worker.recover(ProtocolError("wireless-authentication-failed"))
            wait.assert_not_called()
        with patch.object(worker.stopping, "wait", return_value=False) as wait, patch.object(worker, "open", side_effect=OSError()):
            with self.assertRaisesRegex(RuntimeError, "reconnect-exhausted"):
                worker.recover(OSError())
            self.assertEqual(wait.call_count, 5)

    def test_local_status_discards_trace_history_but_preserves_diagnostics(self):
        class RecordingClient(SimulatedClient):
            def request(self, kind, body):
                reply = super().request(kind, body)
                self.round_trips.append(dict(command=kind))
                return reply

        events = queue.Queue()
        worker = DeviceWorker(events, port="demo", root=Path("."), bindings=Path("."), demo=True)
        client = RecordingClient()
        worker.session = ControlSession(client, lambda: {})
        worker.session.connect()
        client.diagnostics.update(replyTimeouts=2, decodeIssues=3, maxRoundTripMs=7)
        expected = dict(client.diagnostics)
        for _ in range(1000):
            worker.session.tick()
            worker.status()
            event = events.get_nowait()
            self.assertEqual(event["kind"], "status")
            self.assertEqual(event["state"]["mode"], "local")
            self.assertEqual(event["diagnostics"], expected)
            self.assertEqual(client.round_trips, [])
        worker.session.tick()
        self.assertEqual(len(client.round_trips), 1)
        worker.publish("update-error", error="simulated update failure")
        self.assertEqual(events.get_nowait()["kind"], "update-error")
        self.assertEqual(client.round_trips, [])
        self.assertEqual(client.diagnostics, expected)

    def test_demo_worker_releases_and_exits_after_mode_and_light_commands(self):
        events = queue.Queue()
        worker = DeviceWorker(events, port="demo", root=Path("."), bindings=Path("."), demo=True)
        worker.start()
        def wait_for(kind, command=None):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                event = events.get(timeout=max(0.01, deadline - time.monotonic()))
                if event["kind"] == kind and (command is None or event.get("command") == command):
                    return event
            self.fail("worker event missing")
        try:
            wait_for("connected")
            for command in ("monitor", "local"):
                worker.submit(command)
                self.assertTrue(wait_for("command", command)["ok"])
            worker.submit("light", dict(effect="off", red=255, green=255, blue=255, brightness=16))
            self.assertTrue(wait_for("command", "light")["ok"])
        finally:
            worker.stop()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertTrue(wait_for("disconnected")["releaseConfirmed"])


if __name__ == "__main__":
    unittest.main()
