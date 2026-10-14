import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location("monitor_audit", Path(__file__).resolve().parents[1] / "audit.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="omipet-audit-test-")
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def write_events(self, events, tail=""):
        text = "".join(json.dumps(event) + "\n" for event in events) + tail
        (self.root / "events.jsonl").write_text(text, encoding="utf-8")

    def test_missing_source_is_not_idle(self):
        report = module.audit(self.root, "missing", "turn")
        self.assertEqual(report["eventCount"], 0)
        self.assertEqual(report["targetCheck"]["lastObservedStatus"], "unknown")

    def test_other_session_and_old_turn_stop_do_not_validate_target(self):
        self.write_events([
            dict(sessionId="target", turnId="current", hookEventName="PreToolUse", status="working"),
            dict(sessionId="target", turnId="old", hookEventName="Stop", status="idle"),
            dict(sessionId="other", turnId="current", hookEventName="Stop", status="idle"),
        ])
        check = module.audit(self.root, "target", "current")["targetCheck"]
        self.assertEqual(check["eventCount"], 1)
        self.assertFalse(check["stopReceived"])
        self.assertEqual(check["lastObservedStatus"], "working")

    def test_turn_status_is_distinct_from_session_aggregate(self):
        self.write_events([dict(sessionId="target", turnId="old", hookEventName="Stop",
                                status="working", turnStatus="idle", applied=True)])
        report = module.audit(self.root, "target", "old")
        self.assertEqual(report["targetCheck"]["lastObservedStatus"], "idle")
        self.assertFalse(report["unexpectedFieldNames"])

    def test_partial_tail_is_distinct_from_corrupt_complete_line(self):
        self.write_events([dict(sessionId="a", hookEventName="Stop", status="idle")], "{")
        report = module.audit(self.root)
        self.assertTrue(report["incompleteTailIgnored"])
        self.assertEqual(report["invalidLineNumbers"], [])
        self.write_events([], "{invalid}\n")
        self.assertEqual(module.audit(self.root)["invalidLineNumbers"], [1])

    def test_approval_tool_coverage_and_late_start_are_reported(self):
        self.write_events([
            dict(sessionId="a", hookEventName="UserPromptSubmit", status="working"),
            dict(sessionId="a", hookEventName="SessionStart", status="unknown"),
            dict(sessionId="a", hookEventName="PermissionRequest", status="waitingApproval"),
            dict(sessionId="b", hookEventName="PreToolUse", toolName="request_permissions",
                 toolUseId="call", status="waitingApproval"),
        ])
        report = module.audit(self.root)
        self.assertEqual(len(report["lateSessionStarts"]), 1)
        coverage = report["approvalIdentityCoverage"]
        self.assertEqual(coverage["withoutToolUseId"], 1)
        self.assertEqual(coverage["permissionToolStartsWithId"], 1)


if __name__ == "__main__":
    unittest.main()
