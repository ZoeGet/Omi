import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


collector = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "collector.py"
root = Path(tempfile.mkdtemp(prefix="omipet-approval-verified-"))
environment = dict(os.environ, OMIPET_CODEX_MONITOR_DIR=str(root))
cases = []
durations = []


def send(session, event, turn="t1", tool="", tool_name="Bash"):
    payload = dict(session_id=session, hook_event_name=event, turn_id=turn,
                   tool_use_id=tool, tool_name=tool_name, cwd="C:/测试/项目",
                   prompt="PRIVATE_TEST_中文", tool_input={"command": "PRIVATE_TEST_KEY"},
                   last_assistant_message="PRIVATE_TEST_：未修改文件。")
    started = time.monotonic()
    command = ([sys.executable, str(collector.resolve())] if collector.suffix == ".py" else
               ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(collector.resolve())])
    result = subprocess.run(command,
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True,
        env=environment, timeout=15)
    durations.append(time.monotonic() - started)
    assert result.returncode == 0 and not result.stdout and not result.stderr, "Collector output contract failed"


def state(session):
    return json.loads((root / "sessions" / f"{session}.json").read_text(encoding="utf-8"))


def expect(session, status):
    actual = state(session)
    assert actual["status"] == status, (session, actual["status"], status)
    assert actual["cwd"] == "C:/测试/项目"


def passed(name):
    cases.append(name)
    print("PASS " + name, flush=True)


send("exact", "UserPromptSubmit")
send("exact", "PermissionRequest", tool="approval-a")
send("exact", "PreToolUse", tool="approval-a")
expect("exact", "waitingApproval")
send("exact", "PostToolUse", tool="unrelated")
expect("exact", "waitingApproval")
send("exact", "PostToolUse", tool="approval-a")
expect("exact", "working")
send("exact", "Stop")
expect("exact", "idle")
passed("matching completion only; PreToolUse and unrelated completion cannot clear approval")

send("multiple", "PermissionRequest", tool="a")
send("multiple", "PermissionRequest", tool="b")
send("multiple", "PostToolUse", tool="a")
expect("multiple", "waitingApproval")
assert state("multiple")["correlatedPendingCount"] == 1
send("multiple", "PostToolUse", tool="b")
expect("multiple", "working")
send("multiple", "PermissionRequest", tool="a")
expect("multiple", "working")
send("multiple", "Stop")
passed("multiple approvals and delayed duplicate PermissionRequest")

send("missing", "PermissionRequest")
expect("missing", "waitingApproval")
send("missing", "PreToolUse", tool="a")
expect("missing", "unknown")
send("missing", "PostToolUse", tool="a")
expect("missing", "unknown")
assert state("missing")["approvalUnconfirmed"] is True
send("missing", "Stop")
expect("missing", "idle")
passed("missing approval identity stays explicitly unconfirmed until turn termination")

send("turns", "UserPromptSubmit", turn="older")
send("turns", "UserPromptSubmit", turn="newer")
send("turns", "PermissionRequest", turn="newer", tool="new-approval")
send("turns", "Stop", turn="older")
expect("turns", "waitingApproval")
send("turns", "PostToolUse", turn="older", tool="new-approval")
expect("turns", "waitingApproval")
send("turns", "PostToolUse", turn="newer", tool="new-approval")
expect("turns", "working")
send("turns", "Stop", turn="newer")
send("turns", "PreToolUse", turn="newer", tool="late")
expect("turns", "idle")
passed("turn isolation, queued submissions, and late tools cannot resurrect completed turns")

send("start", "UserPromptSubmit")
send("start", "SessionStart", turn="")
expect("start", "working")
send("start", "Interrupt")
expect("start", "idle")
send("start", "PermissionRequest", tool="late")
expect("start", "idle")
send("start", "SessionEnd", turn="")
expect("start", "offline")
passed("late SessionStart, Interrupt, and SessionEnd")

send("no-turn", "UserPromptSubmit", turn="real")
send("no-turn", "Stop", turn="")
expect("no-turn", "working")
send("no-turn", "Stop", turn="real")
expect("no-turn", "unknown")
send("no-turn", "SessionEnd", turn="")
passed("missing turn id cannot incorrectly end a known active turn")

legacy = root / "sessions" / "legacy.json"
legacy.write_text(json.dumps(dict(schema=1, sessionId="legacy", status="waitingApproval", turnId="t1")), encoding="utf-8")
send("legacy", "PreToolUse", tool="a")
expect("legacy", "unknown")
send("legacy", "Stop")
expect("legacy", "idle")
passed("schema 1 approval migrates conservatively without fabricating a match")

send("permission-tool", "PreToolUse", tool="permission-a", tool_name="request_permissions")
expect("permission-tool", "waitingApproval")
send("permission-tool", "PreToolUse", tool="other")
send("permission-tool", "PostToolUse", tool="other")
expect("permission-tool", "waitingApproval")
send("permission-tool", "PostToolUse", tool="permission-a", tool_name="request_permissions")
expect("permission-tool", "working")
send("permission-tool", "Stop")
expect("permission-tool", "idle")
passed("explicit permission tool starts approval and only its matching completion releases it")

with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(lambda number: send(f"parallel-{number}", "PermissionRequest", tool=f"tool-{number}"), range(6)))
assert json.loads((root / "snapshot.json").read_text(encoding="utf-8"))["overallStatus"] == "waitingApproval"
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(lambda number: send(f"parallel-{number}", "Stop"), range(6)))
assert json.loads((root / "snapshot.json").read_text(encoding="utf-8"))["overallStatus"] == "idle"
passed("six concurrent sessions and aggregate approval priority")

events = [json.loads(line) for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
assert not list(root.glob("collector-error-*.json"))
for path in root.rglob("*.json*"):
    assert "PRIVATE_TEST" not in path.read_text(encoding="utf-8")
assert all(event["schema"] == 2 for event in events)
report = dict(result="pass", cases=cases, eventCount=len(events), parallelSessions=6,
              maximumInvocationSeconds=round(max(durations), 3), privacyPassed=True,
              outputDirectory=str(root), collectorPath=str(collector.resolve()))
(root / "verification-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
