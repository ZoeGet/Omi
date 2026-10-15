from pathlib import Path
import queue
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import DeviceWorker


class WorkerTests(unittest.TestCase):
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
