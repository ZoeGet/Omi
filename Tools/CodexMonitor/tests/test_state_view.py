from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location("state_view", Path(__file__).resolve().parents[1] / "state_view.py")
view = importlib.util.module_from_spec(spec)
spec.loader.exec_module(view)
NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def session(status="working", age=1, session_id="a"):
    return dict(sessionId=session_id, status=status, lastEvent="PreToolUse",
                updatedAtUtc=(NOW - timedelta(seconds=age)).isoformat())


def snapshot(*sessions):
    return dict(schema=2, generatedAtUtc=NOW.isoformat(), overallStatus="idle", sessions=list(sessions))


class StateViewTests(unittest.TestCase):
    def test_shared_process_query_keeps_identity_proof_and_evaluation_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = dict(pid=123, creationTime100ns="456", imagePath="C:/synthetic/codex.exe")
            identities = [identity, dict(identity), dict(identity, creationTime100ns="457"),
                          dict(identity, imagePath="C:/other/codex.exe"), identity]
            observed = [dict(session(session_id=str(i)), turnId="", toolUseId="") for i in range(5)]
            (root / "snapshot.json").write_text(json.dumps(snapshot(*observed)), encoding="utf-8")
            records = {s["sessionId"]: dict(identity=host, confirmed=True, observedMonotonicNs="1000000000",
                proof={k: s[k] for k in ("updatedAtUtc", "lastEvent", "turnId", "toolUseId")})
                for s, host in zip(observed, identities)}
            records["4"]["proof"]["turnId"] = "unmatched"
            calls = []
            state = "running"
            def check(host):
                calls.append(host)
                return dict(processState=state)
            def read():
                return view.read_bound_view(root, dict(schema=2, sessions=records), now=NOW,
                                            max_age_seconds=10, monotonic_ns=lambda: 1000000000,
                                            process_checker=check)
            result = read()
            self.assertEqual(calls, [identities[0], identities[2], identities[3]])
            self.assertEqual([s["displayStatus"] for s in result["sessions"]], ["working"] * 4 + ["unknown"])
            self.assertEqual(result["sessions"][4]["reason"], "event-binding-unconfirmed")
            state = "exited"
            result = read()
            self.assertEqual(len(calls), 6)
            self.assertTrue(all(s["displayStatus"] == "unknown" for s in result["sessions"]))

    def test_invalid_process_identity_is_not_used_as_a_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "snapshot.json").write_text(json.dumps(snapshot(session(), session(session_id="b"))), encoding="utf-8")
            invalid = dict(pid=[], creationTime100ns={}, imagePath=[])
            calls = []
            def check(identity):
                calls.append(identity)
                return dict(processState="unknown")
            result = view.read_bound_view(root, dict(schema=1, sessions={"a": invalid, "b": invalid}),
                                          now=NOW, max_age_seconds=10, process_checker=check)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["overallStatus"], "unknown")

    def evaluate(self, *sessions, budget=None, unavailable=False):
        return view.project(snapshot(*sessions), now=NOW,
                            max_age_seconds=budget, source_unavailable=unavailable)

    def test_no_default_timeout_or_liveness_claim(self):
        for status in view.STATUSES:
            with self.subTest(status=status):
                result = self.evaluate(session(status))
                self.assertEqual(result["overallStatus"], "unknown")
                self.assertEqual(result["sessions"][0]["lastObservedStatus"], status)
                self.assertEqual(result["sessions"][0]["reason"], "freshness-policy-unset")
                self.assertEqual(result["liveness"], "unverified")

    def test_silence_never_manufactures_idle_or_offline(self):
        for status in ("working", "waitingApproval", "idle", "offline"):
            with self.subTest(status=status):
                result = self.evaluate(session(status, age=11), budget=10)
                self.assertEqual(result["overallStatus"], "unknown")
                self.assertEqual(result["sessions"][0]["lastObservedStatus"], status)
                self.assertEqual(result["sessions"][0]["reason"], "observation-expired")

    def test_explicit_budget_boundary(self):
        self.assertEqual(self.evaluate(session(age=10), budget=10)["overallStatus"], "working")
        self.assertEqual(self.evaluate(session(age=10.001), budget=10)["overallStatus"], "unknown")

    def test_other_session_activity_does_not_refresh_old_approval(self):
        result = self.evaluate(session("waitingApproval", age=100),
                               session("idle", age=0, session_id="b"), budget=10)
        self.assertEqual(result["overallStatus"], "unknown")
        self.assertEqual(result["sessions"][0]["displayStatus"], "unknown")
        self.assertEqual(result["sessions"][1]["displayStatus"], "idle")

    def test_fresh_waiting_and_working_keep_priority_over_unknown(self):
        for status in ("waitingApproval", "working"):
            result = self.evaluate(session(status), session("idle", age=100, session_id="b"), budget=10)
            self.assertEqual(result["overallStatus"], status)

    def test_independent_source_unavailability_preserves_observation(self):
        result = self.evaluate(session("waitingApproval"), budget=10, unavailable=True)
        self.assertEqual(result["overallStatus"], "unknown")
        self.assertEqual(result["sourceState"], "unavailable")
        self.assertEqual(result["sessions"][0]["lastObservedStatus"], "waitingApproval")

    def test_invalid_and_future_timestamps(self):
        for value in (None, "bad", "2026-01-01T12:00:00", "2026-01-01T12:00:01Z"):
            with self.subTest(value=value):
                observed = session()
                observed["updatedAtUtc"] = value
                result = self.evaluate(observed, budget=10)
                self.assertEqual(result["overallStatus"], "unknown")
                self.assertIn(result["sessions"][0]["reason"], ("invalid-timestamp", "future-timestamp"))

    def test_empty_invalid_and_duplicate_source(self):
        for data in (None, [], {}, dict(schema=1, sessions=[]), snapshot(session(), session())):
            self.assertEqual(view.project(data, now=NOW)["sourceState"], "invalid")
        self.assertEqual(self.evaluate()["sourceState"], "empty")

    def test_malformed_session_cannot_create_false_green(self):
        for malformed in (None, {}, dict(sessionId="x", status=[])):
            result = self.evaluate(malformed, session("idle", session_id="b"), budget=10)
            self.assertEqual(result["overallStatus"], "unknown")

    def test_all_explicitly_fresh_offline_sessions_remain_offline(self):
        self.assertEqual(self.evaluate(session("offline"), budget=10)["overallStatus"], "offline")

    def test_invalid_budgets_rejected(self):
        for budget in (0, -1, float("inf"), float("nan"), True, "10"):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.evaluate(session(), budget=budget)

    def test_missing_corrupt_and_read_only_files(self):
        with tempfile.TemporaryDirectory(prefix="omipet-view-test-") as directory:
            root = Path(directory)
            self.assertEqual(view.read_view(root, now=NOW)["sourceState"], "missing")
            path = root / "snapshot.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(view.read_view(root, now=NOW)["sourceState"], "unreadable")
            path.write_text(json.dumps(snapshot(session())), encoding="utf-8")
            before = {file.name: (file.read_bytes(), file.stat().st_mtime_ns) for file in root.iterdir()}
            view.read_view(root, now=NOW, max_age_seconds=10)
            after = {file.name: (file.read_bytes(), file.stat().st_mtime_ns) for file in root.iterdir()}
            self.assertEqual(before, after)

    def test_bound_process_checks_only_demote_matching_sessions(self):
        with tempfile.TemporaryDirectory(prefix="omipet-bound-test-") as directory:
            root = Path(directory)
            data = snapshot(session("waitingApproval"), session("working", session_id="b"))
            (root / "snapshot.json").write_text(json.dumps(data), encoding="utf-8")
            bindings = dict(schema=1, sessions={"a": "exited", "b": "running"})
            before = (root / "snapshot.json").read_bytes()
            result = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10,
                                          process_checker=lambda identity: dict(processState=identity))
            self.assertEqual(result["sessions"][0]["displayStatus"], "unknown")
            self.assertEqual(result["sessions"][0]["lastObservedStatus"], "waitingApproval")
            self.assertEqual(result["sessions"][1]["displayStatus"], "working")
            self.assertEqual((root / "snapshot.json").read_bytes(), before)

    def test_running_process_cannot_bypass_missing_policy_or_expired_observation(self):
        with tempfile.TemporaryDirectory(prefix="omipet-bound-policy-test-") as directory:
            root = Path(directory)
            (root / "snapshot.json").write_text(json.dumps(snapshot(session("idle", age=100))), encoding="utf-8")
            bindings = dict(schema=1, sessions={"a": "running"})
            for budget in (None, 10):
                result = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=budget,
                                              process_checker=lambda identity: dict(processState="running"))
                self.assertEqual(result["overallStatus"], "unknown")
                self.assertEqual(result["liveness"], "unverified")

    def test_missing_and_invalid_bindings_cannot_report_idle(self):
        with tempfile.TemporaryDirectory(prefix="omipet-bound-missing-test-") as directory:
            root = Path(directory)
            (root / "snapshot.json").write_text(json.dumps(snapshot(session("idle"))), encoding="utf-8")
            for bindings in (None, {}, dict(schema=1, sessions={})):
                result = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10)
                self.assertEqual(result["overallStatus"], "unknown")

    def test_event_correlated_binding_must_match_latest_snapshot(self):
        with tempfile.TemporaryDirectory(prefix="omipet-event-bound-test-") as directory:
            root = Path(directory)
            observed = session("working")
            observed.update(turnId="turn-a", toolUseId="tool-a")
            path = root / "snapshot.json"
            path.write_text(json.dumps(snapshot(observed)), encoding="utf-8")
            proof = dict(updatedAtUtc=observed["updatedAtUtc"], lastEvent="PreToolUse",
                         turnId="turn-a", toolUseId="tool-a")
            bindings = dict(schema=2, sessions={"a": dict(identity="running", proof=proof,
                                                           confirmed=True,
                                                           observedMonotonicNs="100000000000")})
            check = lambda identity: dict(processState=identity)
            self.assertEqual(view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10,
                                                  process_checker=check,
                                                  monotonic_ns=lambda: 101000000000)["overallStatus"], "working")
            rolled_clock = view.read_bound_view(root, bindings, now=NOW + timedelta(days=1),
                                                max_age_seconds=10, process_checker=check,
                                                monotonic_ns=lambda: 101000000000)
            self.assertEqual(rolled_clock["overallStatus"], "working")
            expired = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10,
                                           process_checker=check, monotonic_ns=lambda: 111000000000)
            self.assertEqual(expired["overallStatus"], "unknown")
            observed["updatedAtUtc"] = (NOW - timedelta(milliseconds=100)).isoformat()
            path.write_text(json.dumps(snapshot(observed)), encoding="utf-8")
            stale = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10,
                                         process_checker=check, monotonic_ns=lambda: 101000000000)
            self.assertEqual(stale["overallStatus"], "unknown")
            self.assertEqual(stale["sessions"][0]["reason"], "event-binding-unconfirmed")
            bindings["sessions"]["a"]["proof"]["updatedAtUtc"] = observed["updatedAtUtc"]
            bindings["sessions"]["a"]["confirmed"] = False
            self.assertEqual(view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10,
                                                  process_checker=check,
                                                  monotonic_ns=lambda: 101000000000)["overallStatus"], "unknown")

    @unittest.skipUnless(os.name == "nt", "Windows process-bound projection")
    def test_real_owned_child_exit_demotes_projection_without_rewriting_snapshot(self):
        from process_probe import capture
        with tempfile.TemporaryDirectory(prefix="omipet-bound-live-test-") as directory:
            root = Path(directory)
            path = root / "snapshot.json"
            path.write_text(json.dumps(snapshot(session("waitingApproval"))), encoding="utf-8")
            before = path.read_bytes()
            child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"], stdin=subprocess.PIPE)
            try:
                bindings = dict(schema=1, sessions={"a": capture(child.pid)})
                running = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10)
                self.assertEqual(running["sessions"][0]["hostProcessState"], "running")
                self.assertEqual(running["overallStatus"], "waitingApproval")
                child.stdin.close()
                child.wait(timeout=5)
                stopped = view.read_bound_view(root, bindings, now=NOW, max_age_seconds=10)
                self.assertEqual(stopped["overallStatus"], "unknown")
                self.assertEqual(stopped["sessions"][0]["lastObservedStatus"], "waitingApproval")
                self.assertEqual(path.read_bytes(), before)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
