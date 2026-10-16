from pathlib import Path
import queue
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import DeviceWorker
from controller import ControlSession, SimulatedClient


class WorkerTests(unittest.TestCase):
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
