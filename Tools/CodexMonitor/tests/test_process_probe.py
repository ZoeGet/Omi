import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


spec = importlib.util.spec_from_file_location("process_probe", Path(__file__).resolve().parents[1] / "process_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
IDENTITY = dict(pid=123, creationTime100ns="123456789012345678", imagePath="C:\\Programs\\Codex\\codex.exe")


class ProcessProbeTests(unittest.TestCase):
    def observed(self, **changes):
        return dict(IDENTITY, processState="running") | changes

    def test_same_process_is_not_session_liveness(self):
        result = probe.check(IDENTITY, lambda pid: self.observed())
        self.assertEqual(result["processState"], "running")
        self.assertEqual(result["sessionLiveness"], "unverified")

    def test_pid_reuse_cannot_refresh_source(self):
        result = probe.check(IDENTITY, lambda pid: self.observed(creationTime100ns="999"))
        self.assertEqual(result["processState"], "identityMismatch")

    def test_other_pid_or_image_is_not_bound_source(self):
        for changes in (dict(pid=456), dict(imagePath="C:\\Other\\codex.exe")):
            self.assertEqual(probe.check(IDENTITY, lambda pid: self.observed(**changes))["processState"],
                             "identityMismatch")

    def test_windows_path_case_is_ignored(self):
        result = probe.check(IDENTITY, lambda pid: self.observed(imagePath=IDENTITY["imagePath"].upper()))
        self.assertEqual(result["processState"], "running")

    def test_exited_process_needs_matching_birth_identity(self):
        result = probe.check(IDENTITY, lambda pid: self.observed(processState="exited", imagePath=None))
        self.assertEqual(result["processState"], "exited")
        result = probe.check(IDENTITY, lambda pid: self.observed(processState="exited", creationTime100ns="999"))
        self.assertEqual(result["processState"], "identityMismatch")

    def test_access_error_is_unknown_and_sanitized(self):
        def denied(pid):
            error = OSError("PRIVATE_ERROR_TEST")
            error.winerror = 5
            raise error
        result = probe.check(IDENTITY, denied)
        self.assertEqual(result["processState"], "unknown")
        self.assertEqual(result["errorCode"], 5)
        self.assertNotIn("PRIVATE_ERROR_TEST", str(result))

    def test_invalid_identity_does_not_probe(self):
        def forbidden(pid):
            self.fail("Invalid input must not query the OS")
        for identity in (None, {}, IDENTITY | dict(pid=True), IDENTITY | dict(pid=-1),
                         IDENTITY | dict(creationTime100ns="0"), IDENTITY | dict(imagePath="codex.exe")):
            self.assertEqual(probe.check(identity, forbidden)["processState"], "unknown")

    def test_malformed_observation_cannot_report_running(self):
        for changes in (dict(imagePath=None), dict(processState="bad")):
            self.assertEqual(probe.check(IDENTITY, lambda pid: self.observed(**changes))["processState"], "unknown")

    @unittest.skipUnless(os.name == "nt", "Windows API integration")
    def test_current_process_identity(self):
        identity = probe.capture(os.getpid())
        self.assertTrue(probe.valid_identity(identity))
        self.assertEqual(probe.check(identity)["processState"], "running")

    @unittest.skipUnless(os.name == "nt", "Windows API integration")
    def test_owned_child_exit_is_observed_without_event_or_timeout_policy(self):
        child = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.buffer.read()"], stdin=subprocess.PIPE)
        try:
            identity = probe.capture(child.pid)
            self.assertEqual(probe.check(identity)["processState"], "running")
            child.stdin.close()
            child.wait(timeout=5)
            result = probe.check(identity)
            self.assertIn(result["processState"], ("exited", "unknown"))
            self.assertNotEqual(result["processState"], "running")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
