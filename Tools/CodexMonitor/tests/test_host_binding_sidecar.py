from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector
from host_binding_sidecar import update
from state_view import read_bound_view


IDENTITY = dict(pid=123, creationTime100ns="456", imagePath="C:\\Programs\\Codex\\codex.exe")
OTHER = dict(pid=124, creationTime100ns="457", imagePath="C:\\Programs\\Codex\\codex.exe")


class HostBindingSidecarTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="omipet-sidecar-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = dict(enabled=True, allowedImages=[IDENTITY["imagePath"]], maxSessions=16)

    def event(self, name, *, session="private-a", turn="turn-a", tool="tool-a"):
        return dict(session_id=session, turn_id=turn, tool_use_id=tool, hook_event_name=name,
                    prompt="PRIVATE_PROMPT", cwd="PRIVATE_DIRECTORY")

    def feed(self, payload, identity=IDENTITY, *, observed=True):
        expected, observed_monotonic_ns = self.collect(payload)
        evidence = dict(associationState="observed" if observed else "unknown",
                        candidateIdentity=identity if observed else None)
        return update(self.root, payload, self.config, expected_updated_at=expected,
                      observed_monotonic_ns=observed_monotonic_ns,
                      observer=lambda _: evidence,
                      lock=collector.monitor_lock, save=collector.atomic_json)

    def collect(self, payload):
        original = collector.timestamp
        captured = []
        def stamp():
            observed_monotonic_ns = time.monotonic_ns()
            value = original()
            captured.append((value, observed_monotonic_ns))
            return value
        collector.timestamp = stamp
        try:
            collector.collect(self.root, payload)
        finally:
            collector.timestamp = original
        return captured[-1]

    def bindings(self):
        return json.loads((self.root / "host-bindings.json").read_text(encoding="utf-8"))

    def projected(self):
        return read_bound_view(self.root, self.bindings(), now=datetime.now(timezone.utc),
                               max_age_seconds=30,
                               process_checker=lambda _: dict(processState="running"))

    def test_pair_confirms_only_current_event_and_removes_private_payload(self):
        self.assertFalse(self.feed(self.event("PreToolUse")))
        self.assertEqual(self.projected()["overallStatus"], "unknown")
        self.assertTrue(self.feed(self.event("PostToolUse")))
        self.assertEqual(self.projected()["overallStatus"], "working")
        raw=(self.root / "host-bindings.json").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_PROMPT", raw)
        self.assertNotIn("PRIVATE_DIRECTORY", raw)
        self.assertEqual(len(list(self.root.glob("host-bindings*.json"))), 1)

    def test_later_same_host_event_updates_proof_then_session_end_clears(self):
        self.feed(self.event("PreToolUse"))
        self.feed(self.event("PostToolUse"))
        self.assertTrue(self.feed(self.event("Stop", tool="")))
        self.assertEqual(self.projected()["overallStatus"], "idle")
        self.assertFalse(self.feed(self.event("SessionEnd", tool="")))
        self.assertNotIn("private-a", self.bindings()["sessions"])

    def test_stale_or_unobserved_event_never_upgrades_binding(self):
        first = self.event("PreToolUse")
        earlier, observed_monotonic_ns = self.collect(first)
        self.collect(self.event("PostToolUse"))
        self.assertFalse(update(self.root, first, self.config, expected_updated_at=earlier,
            observed_monotonic_ns=observed_monotonic_ns,
            observer=lambda _: dict(associationState="observed", candidateIdentity=IDENTITY),
            lock=collector.monitor_lock, save=collector.atomic_json))
        self.assertFalse((self.root / "host-bindings.json").exists())
        self.assertFalse(self.feed(self.event("Stop", tool=""), observed=False))
        self.assertFalse((self.root / "host-bindings.json").exists())

    def test_repeated_event_metadata_cannot_bind_wrong_invocation(self):
        event = self.event("PreToolUse")
        earlier, earlier_monotonic_ns = self.collect(event)
        later, later_monotonic_ns = self.collect(event)
        self.assertNotEqual(earlier, later)
        self.assertFalse(update(self.root, event, self.config, expected_updated_at=earlier,
            observed_monotonic_ns=earlier_monotonic_ns,
            observer=lambda _: dict(associationState="observed", candidateIdentity=IDENTITY),
            lock=collector.monitor_lock, save=collector.atomic_json))
        self.assertFalse((self.root / "host-bindings.json").exists())
        self.assertFalse(update(self.root, self.event("PostToolUse"), self.config,
            expected_updated_at=later, observed_monotonic_ns=later_monotonic_ns,
            observer=lambda _: dict(associationState="observed", candidateIdentity=IDENTITY),
            lock=collector.monitor_lock, save=collector.atomic_json))

    def test_identity_change_requires_new_pair(self):
        self.feed(self.event("PreToolUse"))
        self.feed(self.event("PostToolUse"))
        self.assertFalse(self.feed(self.event("PreToolUse", tool="tool-b"), OTHER))
        self.assertEqual(self.projected()["overallStatus"], "unknown")
        self.assertTrue(self.feed(self.event("PostToolUse", tool="tool-b"), OTHER))
        self.assertEqual(self.projected()["overallStatus"], "working")

    def test_unapplied_late_event_does_not_refresh_binding(self):
        self.feed(self.event("PreToolUse"))
        self.feed(self.event("Stop", tool=""))
        self.assertFalse(self.feed(self.event("PostToolUse")))
        self.assertEqual(self.projected()["overallStatus"], "unknown")

    def test_history_does_not_stop_new_or_existing_binding_updates(self):
        self.config["maxSessions"] = 1
        for number in range(17):
            session = f"history-{number}"
            self.feed(self.event("PreToolUse", session=session))
            self.assertTrue(self.feed(self.event("PostToolUse", session=session)))
            self.feed(self.event("Stop", session=session))
        self.feed(self.event("PreToolUse"))
        self.assertTrue(self.feed(self.event("PostToolUse")))
        self.assertEqual(len(self.bindings()["sessions"]), 18)
        self.assertTrue(self.feed(self.event("Stop")))
        self.assertEqual(self.bindings()["sessions"]["private-a"]["proof"]["lastEvent"], "Stop")


if __name__ == "__main__":
    unittest.main()
