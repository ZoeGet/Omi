import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from process_probe import capture
from state_view import read_bound_view


@unittest.skipUnless(os.name == "nt", "Windows process ancestry required")
class BoundCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="omipet-bound-wrapper-")
        self.addCleanup(self.temporary.cleanup)
        self.stage = Path(self.temporary.name)
        self.root = self.stage / "state"
        for name in ("bound_collector.py", "host_binding_sidecar.py", "host_observer.py",
                     "process_probe.py"):
            shutil.copy2(SOURCE / name, self.stage / name)
        shutil.copy2(SOURCE / "collector.py", self.stage / "lifecycle_collector.py")
        self.environment = dict(os.environ, OMIPET_CODEX_MONITOR_DIR=str(self.root))

    def send(self, event):
        payload = dict(session_id="bound-test", turn_id="turn-1", tool_use_id="tool-1",
                       hook_event_name=event, prompt="PRIVATE_PROMPT", cwd="PRIVATE_DIRECTORY")
        result = subprocess.run([sys.executable, str(self.stage / "bound_collector.py")],
                                input=json.dumps(payload).encode("utf-8"),
                                capture_output=True, env=self.environment, timeout=15)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))

    def test_parent_binding_requires_matching_tool_pair(self):
        parent = capture(os.getpid())
        configuration = dict(enabled=True, allowedImages=[parent["imagePath"]], maxSessions=16)
        (self.stage / "host-binding-config.json").write_text(json.dumps(configuration), encoding="utf-8")
        self.send("PreToolUse")
        self.assertEqual(json.loads((self.root / "snapshot.json").read_text(encoding="utf-8"))["overallStatus"],
                         "working")
        self.send("PostToolUse")
        bindings = json.loads((self.root / "host-bindings.json").read_text(encoding="utf-8"))
        self.assertEqual(bindings["sessions"]["bound-test"]["identity"], parent)
        self.assertTrue(bindings["sessions"]["bound-test"]["confirmed"])
        self.assertEqual(read_bound_view(self.root, bindings, max_age_seconds=30)["overallStatus"], "working")
        self.assertNotIn("PRIVATE_PROMPT", json.dumps(bindings))
        self.assertNotIn("PRIVATE_DIRECTORY", json.dumps(bindings))

    def test_original_collector_regression_without_opt_in(self):
        result = subprocess.run([sys.executable, str(SOURCE / "tests" / "test_approvals.py"),
                                 str(self.stage / "bound_collector.py")],
                                capture_output=True, env=self.environment, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8", errors="replace") +
                         result.stderr.decode("utf-8", errors="replace"))
        self.assertFalse((self.root / "host-bindings.json").exists())


if __name__ == "__main__":
    unittest.main()
