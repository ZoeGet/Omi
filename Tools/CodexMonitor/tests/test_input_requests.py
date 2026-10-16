import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import collect


class InputRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def send(self, event, tool="request_user_input_async", call="call-test", turn="turn-a", **extra):
        collect(self.root, dict(session_id="input-test", turn_id=turn, hook_event_name=event,
                                tool_name=tool, tool_use_id=call, **extra))
        return json.loads((self.root / "snapshot.json").read_text(encoding="utf-8"))["overallStatus"]

    def reply(self, call="call-test"):
        body = [dict(questionItemId=json.dumps(["request_user_input_async", call, 0]),
                     question="PRIVATE_QUESTION", answer="PRIVATE_ANSWER")]
        return self.send("UserPromptSubmit", turn="turn-b",
                         prompt="<send_user_message_question_reply>" + json.dumps(body)
                                + "</send_user_message_question_reply>")

    def test_async_ack_and_stop_keep_yellow_until_matching_reply(self):
        self.assertEqual(self.send("PreToolUse"), "waitingApproval")
        self.assertEqual(self.send("PostToolUse"), "waitingApproval")
        self.assertEqual(self.send("Stop"), "waitingApproval")
        self.assertEqual(self.reply("unrelated-call"), "waitingApproval")
        self.assertEqual(self.reply(), "working")
        self.assertEqual(self.send("Stop", turn="turn-b"), "idle")

    def test_sync_return_and_late_pre_do_not_leave_pending_input(self):
        self.assertEqual(self.send("PreToolUse", tool="request_user_input"), "waitingApproval")
        self.assertEqual(self.send("PostToolUse", tool="request_user_input"), "working")
        self.assertEqual(self.send("PreToolUse", tool="request_user_input"), "working")

    def test_other_tool_or_unstructured_message_does_not_answer_a_question(self):
        self.send("PreToolUse")
        self.assertEqual(self.send("PostToolUse", tool="exec_command", call="other"), "waitingApproval")
        self.assertEqual(self.send("UserPromptSubmit", prompt="hello", turn="turn-b"), "waitingApproval")

    def test_two_pending_calls_require_their_own_replies(self):
        self.send("PreToolUse")
        self.send("PreToolUse", call="call-two")
        self.assertEqual(self.reply(), "waitingApproval")
        self.assertEqual(self.reply("call-two"), "working")

    def test_interrupt_and_session_end_cancel_pending_input(self):
        for event in ("Interrupt", "SessionEnd"):
            with self.subTest(event=event):
                self.send("SessionStart")
                self.send("PreToolUse", turn=event)
                self.send("Stop", turn=event)
                self.assertEqual(self.send(event, turn=event), "unknown" if event == "SessionEnd" else "idle")
                if event == "SessionEnd":
                    state = json.loads((self.root / "sessions/input-test.json").read_text(encoding="utf-8"))
                    self.assertEqual(state["status"], "offline")

    def test_questions_answers_and_tool_arguments_are_not_saved(self):
        self.send("PreToolUse", tool_input={"questions": ["PRIVATE_QUESTION"]})
        self.reply()
        for path in self.root.rglob("*.json*"):
            self.assertNotIn("PRIVATE_", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
