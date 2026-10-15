import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_observer as observer
from host_bindings import derive
from process_probe import capture


def identity(pid, created, name):
    return dict(pid=pid, creationTime100ns=str(created), imagePath="C:\\Programs\\" + name)


class HostObserverTests(unittest.TestCase):
    def setUp(self):
        self.identities = {1: identity(1, 300, "python.exe"), 2: identity(2, 200, "cmd.exe"),
                           3: identity(3, 100, "codex.exe"), 4: identity(4, 50, "codex.exe")}
        self.parents = {1: 2, 2: 3, 3: 4}

    def observe(self, **options):
        return observer.ancestry(["C:\\Programs\\codex.exe"], start_pid=1, parents=self.parents,
                                 identity_reader=lambda pid: self.identities[pid],
                                 identity_checker=options.get("checker", lambda entry: dict(processState="running")))

    def test_nearest_exact_allowed_ancestor_is_observed(self):
        result = self.observe()
        self.assertEqual(result["candidateIdentity"]["pid"], 3)
        self.assertEqual(result["associationState"], "observed")
        self.assertEqual(result["sessionLiveness"], "unverified")

    def test_same_basename_other_image_is_not_matched(self):
        self.identities[3]["imagePath"] = "C:\\Other\\codex.exe"
        self.parents.pop(3)
        result = self.observe()
        self.assertIsNone(result["candidateIdentity"])
        self.assertEqual(result["associationState"], "unknown")

    def test_parent_pid_reuse_is_rejected(self):
        self.identities[2]["creationTime100ns"] = "999"
        self.assertEqual(self.observe()["reason"], "parent-pid-reused")

    def test_exit_or_identity_change_during_query_is_rejected(self):
        for status in ("exited", "unknown", "identityMismatch"):
            result = self.observe(checker=lambda entry: dict(processState=status))
            self.assertEqual(result["associationState"], "unknown")
            self.assertIsNone(result["candidateIdentity"])

    def test_cycle_is_rejected(self):
        self.parents[2] = 1
        self.assertEqual(self.observe()["reason"], "ancestry-cycle")

    def test_record_only_saves_metadata_in_separate_files(self):
        with tempfile.TemporaryDirectory(prefix="omipet-host-test-") as directory:
            payload = dict(session_id="session", turn_id="turn", hook_event_name="PreToolUse",
                           tool_use_id="call", prompt="PRIVATE_TEST", tool_input={"key": "PRIVATE_TEST"})
            configuration = dict(enabled=True, allowedImages=["C:\\Programs\\codex.exe"], outputDirectory=directory)
            with patch.object(observer, "ancestry", return_value=self.observe()):
                observer.record(payload, configuration)
                observer.record(payload, configuration)
            files = list(Path(directory).glob("*.json"))
            self.assertEqual(len(files), 2)
            for path in files:
                self.assertNotIn("PRIVATE_TEST", path.read_text(encoding="utf-8"))
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["sessionId"], "session")

    def test_query_failure_stays_unknown_and_sanitized(self):
        with tempfile.TemporaryDirectory(prefix="omipet-host-error-test-") as directory:
            configuration = dict(enabled=True, allowedImages=["C:\\Programs\\codex.exe"], outputDirectory=directory)
            with patch.object(observer, "ancestry", side_effect=OSError("PRIVATE_TEST")):
                observer.record(dict(session_id="session"), configuration)
            text = next(Path(directory).glob("*.json")).read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_TEST", text)
            self.assertEqual(json.loads(text)["associationState"], "unknown")

    @unittest.skipUnless(os.name == "nt", "Windows process ancestry")
    def test_live_parent_is_in_process_snapshot(self):
        parents = observer.process_parents()
        self.assertEqual(parents[os.getpid()], os.getppid())

    @unittest.skipUnless(os.name == "nt", "Windows process ancestry")
    def test_owned_child_observes_exact_parent(self):
        parent = capture(os.getpid())
        program = ("import json,sys; sys.path.insert(0,sys.argv[1]); "
                   "import host_observer; print(json.dumps(host_observer.ancestry([sys.argv[2]])))")
        result = subprocess.run([sys.executable, "-c", program, str(Path(observer.__file__).parent),
                                 parent["imagePath"]], capture_output=True, text=True, timeout=5, check=True)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["associationState"], "observed")
        self.assertEqual(observed["candidateIdentity"], parent)

    def test_sampler_failure_does_not_change_lifecycle_or_output_contract(self):
        with tempfile.TemporaryDirectory(prefix="omipet-wrapper-test-") as directory:
            stage = Path(directory)
            source = Path(observer.__file__).parent
            for name in ("host_sample_collector.py", "host_observer.py", "process_probe.py"):
                (stage / name).write_bytes((source / name).read_bytes())
            (stage / "lifecycle_collector.py").write_bytes((source / "collector.py").read_bytes())
            (stage / "host-observer.json").write_text("{broken", encoding="utf-8")
            payload = dict(session_id="test", turn_id="turn", hook_event_name="UserPromptSubmit")
            output = subprocess.run([sys.executable, str(stage / "host_sample_collector.py")],
                                    input=json.dumps(payload), text=True, capture_output=True, timeout=5,
                                    env=dict(os.environ, OMIPET_CODEX_MONITOR_DIR=str(stage / "data")))
            self.assertEqual((output.returncode, output.stdout, output.stderr), (0, "", ""))
            snapshot = json.loads((stage / "data/snapshot.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["overallStatus"], "working")


def sample(event, session="a", turn="turn", tool="call", host=None):
    return dict(schema=1, sessionId=session, turnId=turn, toolUseId=tool, hookEventName=event,
                associationState="observed", candidateIdentity=host or identity(3, 100, "codex.exe"))


class BindingTests(unittest.TestCase):
    def test_matching_pair_creates_candidate_without_session_liveness_claim(self):
        result = derive([sample("PreToolUse"), sample("PostToolUse")])
        self.assertEqual(result["sessions"]["a"]["pid"], 3)
        self.assertEqual(result["sessionLiveness"], "unverified")

    def test_same_name_different_turn_or_call_is_not_a_pair(self):
        for options in (dict(turn="other"), dict(tool="other"), dict(session="other")):
            result = derive([sample("PreToolUse"), sample("PostToolUse", **options)])
            self.assertEqual(result["sessions"], {})

    def test_duplicate_start_does_not_replace_completion(self):
        self.assertEqual(derive([sample("PreToolUse"), sample("PreToolUse")])["sessions"], {})

    def test_conflicting_or_unconfirmed_host_is_not_automatically_selected(self):
        records = [sample("PreToolUse"), sample("PostToolUse")]
        for other in (sample("Stop", host=identity(4, 200, "codex.exe")),
                      sample("Stop") | dict(associationState="unknown")):
            self.assertEqual(derive(records + [other])["sessions"], {})

    def test_shared_host_for_two_sessions_requires_each_own_pair(self):
        result = derive([sample(event, session=session) for session in ("a", "b")
                         for event in ("PreToolUse", "PostToolUse")])
        self.assertEqual(set(result["sessions"]), {"a", "b"})
        self.assertEqual(result["sessions"]["a"], result["sessions"]["b"])

    def test_invalid_record_invalidates_input_instead_of_partial_binding(self):
        result = derive([sample("PreToolUse"), sample("PostToolUse"), None])
        self.assertEqual(result["inputState"], "invalid")
        self.assertEqual(result["sessions"], {})


if __name__ == "__main__":
    unittest.main()
