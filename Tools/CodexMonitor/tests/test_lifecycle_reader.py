from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

TOOLS = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(TOOLS / "CodexMonitor"), str(TOOLS / "DeviceBridge"), str(TOOLS / "Desktop")]
from state_view import LifecycleReader
from protocol import Limits, SnapshotMapper
from controller import ControlSession, SimulatedClient


class LifecycleReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binding_path = self.root / "bindings.json"
        self.clock = 1_000_000_000
        self.host = "running"
        self.reader = LifecycleReader(self.root, self.binding_path, max_age_seconds=30,
                                      monotonic_ns=lambda: self.clock,
                                      process_checker=lambda identity: dict(processState=self.host))
        self.write_event("working")

    def write_event(self, status, identity="host-a"):
        stamp = datetime.now(timezone.utc).isoformat()
        event = dict(sessionId="test", status=status, updatedAtUtc=stamp,
                     lastEvent="Stop" if status == "idle" else "PreToolUse", turnId="turn", toolUseId="call")
        self.snapshot = dict(schema=2, sessions=[event])
        self.bindings = dict(schema=2, sessions={"test": dict(confirmed=True, identity=identity,
            observedMonotonicNs=str(self.clock), proof={key: event[key] for key in
                ("updatedAtUtc", "lastEvent", "turnId", "toolUseId")})})
        self.save()

    def save(self):
        (self.root / "snapshot.json").write_text(json.dumps(self.snapshot), encoding="utf-8")
        self.binding_path.write_text(json.dumps(self.bindings), encoding="utf-8")

    def advance(self, seconds):
        self.clock += seconds * 1_000_000_000

    def wire(self, view):
        return SnapshotMapper().convert(view, Limits(4096, 16), delivery_reserve_seconds=8,
                                         monotonic_ns=lambda: self.clock)

    def test_long_quiet_task_stays_red_and_explicit_stop_turns_green(self):
        self.reader()
        for second in range(1, 62):
            self.advance(1)
            view = self.reader()
            self.assertEqual(view["sessions"][0]["observationAgeSeconds"], second)
            self.assertEqual(self.wire(view)["overallStatus"], "working")
            self.assertEqual(self.wire(view)["validForMs"], 22000)
            self.assertEqual(view["liveness"], "unverified")
        self.write_event("idle")
        self.assertEqual(self.wire(self.reader())["overallStatus"], "idle")

    def test_yellow_survives_long_wait(self):
        self.write_event("waitingApproval")
        self.reader()
        self.advance(90)
        self.assertEqual(self.wire(self.reader())["overallStatus"], "waitingApproval")

    def test_old_record_is_not_admitted_on_start_or_reset(self):
        self.advance(31)
        self.assertEqual(self.reader()["overallStatus"], "unknown")
        self.write_event("working")
        self.reader()
        self.reader.reset()
        self.advance(31)
        self.assertEqual(self.reader()["overallStatus"], "unknown")

    def test_dead_reused_or_unverifiable_host_invalidates_retention(self):
        for host in ("exited", "identityMismatch", "unknown"):
            self.host = "running"
            self.write_event("working")
            self.reader()
            self.advance(31)
            self.host = host
            self.assertEqual(self.reader()["overallStatus"], "unknown")
            self.host = "running"
            self.assertEqual(self.reader()["overallStatus"], "unknown")

    def test_changed_binding_and_unconfirmed_proof_cannot_retain_old_state(self):
        self.reader()
        self.advance(31)
        self.bindings["sessions"]["test"]["identity"] = "new-host"
        self.save()
        self.assertEqual(self.reader()["overallStatus"], "unknown")
        self.bindings["sessions"]["test"]["confirmed"] = False
        self.save()
        self.assertEqual(self.reader()["overallStatus"], "unknown")

    def test_missing_or_corrupt_source_forgets_retention(self):
        self.reader()
        self.advance(31)
        (self.root / "snapshot.json").write_text("broken", encoding="utf-8")
        self.assertEqual(self.reader()["overallStatus"], "unknown")
        self.save()
        self.assertEqual(self.reader()["overallStatus"], "unknown")

    def test_cached_assessment_expires_and_does_not_extend_itself(self):
        view = self.reader()
        self.advance(22)
        self.assertEqual(self.wire(view)["overallStatus"], "unknown")
        self.assertEqual(self.wire(self.reader())["overallStatus"], "working")

    def test_desktop_device_flow_keeps_lifecycle_and_disconnect_lease(self):
        self.clock = time.monotonic_ns()
        started = self.clock
        self.write_event("working")
        client = SimulatedClient()
        client.now = lambda: (self.clock - started) // 1_000_000
        control = ControlSession(client, self.reader)
        control.connect()
        control.monitor()
        control.bridge.monotonic_ns = lambda: self.clock
        for second in range(61):
            self.advance(1)
            control.tick()
            self.assertEqual(control.state["displayStatus"], "working")
        self.write_event("waitingApproval")
        control.tick()
        self.assertEqual(control.state["displayStatus"], "waitingApproval")
        self.write_event("idle")
        control.tick()
        self.assertEqual(control.state["displayStatus"], "idle")
        self.advance(6)
        client.device.advance(client.now())
        self.assertEqual(client.device.monitor_output(), "disconnected")


if __name__ == "__main__":
    unittest.main()
