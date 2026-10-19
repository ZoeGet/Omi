from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys


def timestamp():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def monitor_lock(root):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    digest = hashlib.sha256(str(root.resolve()).lower().encode("utf-8")).hexdigest().upper()
    handle = kernel.CreateMutexW(None, False, "Local\\OmiPetCodexMonitor-" + digest)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    owned = False
    try:
        outcome = kernel.WaitForSingleObject(handle, 1000)
        if outcome not in (0, 0x80):
            raise TimeoutError("Monitor lock unavailable")
        owned = True
        yield
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def atomic_json(path, data):
    staged = path.with_name(path.name + f".{os.getpid()}.tmp")
    staged.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(staged, path)


def new_turn(turn_id):
    return dict(turnId=turn_id, closed=False, baseStatus="working", pendingToolIds=[],
                completedToolIds=[], pendingInputIds=[], asyncInputIds=[], completedInputIds=[],
                unattributedApproval=False, approvalUnconfirmed=False)


def turn_status(state):
    if state.get("pendingInputIds") and (state["closed"] or
            set(state["pendingInputIds"]) - set(state.get("asyncInputIds", []))):
        return "waitingApproval"
    if state["closed"]:
        return "idle"
    if state["pendingToolIds"]:
        return "waitingApproval"
    if state["unattributedApproval"]:
        return "unknown" if state["approvalUnconfirmed"] else "waitingApproval"
    return state["baseStatus"]


def aggregate(statuses, baseline="unknown"):
    if "waitingApproval" in statuses:
        return "waitingApproval"
    if "working" in statuses:
        return "working"
    if statuses:
        return "unknown" if "unknown" in statuses else "idle"
    return baseline


def answered_calls(prompt):
    if not isinstance(prompt, str):
        return set()
    match = re.fullmatch(r"\s*<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>\s*",
                         prompt, re.DOTALL)
    if not match:
        return set()
    try:
        replies = json.loads(match[1])
        if not isinstance(replies, list):
            return set()
        calls = set()
        for reply in replies:
            key = json.loads(reply["questionItemId"])
            if (isinstance(key, list) and len(key) == 3
                    and key[0] == "request_user_input_async" and isinstance(key[1], str)
                    and type(key[2]) is int and key[2] >= 0):
                calls.add(key[1])
        return calls
    except (ValueError, KeyError, TypeError):
        return set()


def collect(root, payload):
    session_id = str(payload.get("session_id") or "")
    if not session_id.strip():
        return
    directory = root / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (re.sub(r"[^A-Za-z0-9._-]", "_", session_id) + ".json")
    event_name = str(payload.get("hook_event_name") or "")
    turn_id = str(payload.get("turn_id") or "")
    tool_id = str(payload.get("tool_use_id") or "")
    with monitor_lock(root):
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        turns = {state["turnId"]: state for state in previous.get("turnStates", [])}
        for state in turns.values():
            state.setdefault("pendingInputIds", [])
            state.setdefault("completedInputIds", [])
            state.setdefault("asyncInputIds", [])
        baseline = previous.get("baselineStatus", "unknown")
        foreground_turn = previous.get("foregroundTurnId", previous.get("turnId", ""))
        session_closed = previous.get("status") == "offline"
        if previous.get("schema") == 1 and previous.get("turnId"):
            legacy = new_turn(previous["turnId"])
            legacy["closed"] = previous["status"] in ("idle", "offline")
            if legacy["closed"]:
                baseline = "idle"
            if previous["status"] == "unknown":
                legacy["baseStatus"] = "unknown"
            if previous["status"] == "waitingApproval":
                legacy.update(unattributedApproval=True, approvalUnconfirmed=True)
            turns[legacy["turnId"]] = legacy

        applied = True
        selected_status = None
        if event_name == "UserPromptSubmit":
            answered = answered_calls(payload.get("prompt"))
            for state in turns.values():
                matched = answered.intersection(state["pendingInputIds"])
                state["pendingInputIds"] = [key for key in state["pendingInputIds"] if key not in matched]
                state["completedInputIds"].extend(sorted(matched))
        if event_name == "SessionEnd":
            session_closed = True
            foreground_turn = ""
            for state in turns.values():
                state["closed"] = True
                state["pendingInputIds"] = []
        elif event_name == "SessionStart":
            session_closed = False
            if not any(not state["closed"] for state in turns.values()):
                baseline = "unknown"
        elif event_name in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest",
                            "Stop", "Interrupt", "SubagentStart"):
            new_submission = event_name == "UserPromptSubmit" and turn_id not in turns
            state = turns.setdefault(turn_id, new_turn(turn_id))
            if state["closed"] and event_name != "Interrupt":
                applied = False
            elif not turn_id:
                state["baseStatus"] = "unknown"
                applied = False
            else:
                session_closed = False
                if new_submission or not foreground_turn:
                    foreground_turn = turn_id
                if (event_name in ("PreToolUse", "PostToolUse")
                        and payload.get("tool_name") in ("request_user_input", "request_user_input_async")):
                    if event_name == "PreToolUse" and tool_id and tool_id not in state["completedInputIds"]:
                        if tool_id not in state["pendingInputIds"]:
                            state["pendingInputIds"].append(tool_id)
                        if payload["tool_name"] == "request_user_input_async" and tool_id not in state["asyncInputIds"]:
                            state["asyncInputIds"].append(tool_id)
                    elif event_name == "PostToolUse" and tool_id and payload["tool_name"] == "request_user_input":
                        state["pendingInputIds"] = [key for key in state["pendingInputIds"] if key != tool_id]
                        if tool_id not in state["completedInputIds"]:
                            state["completedInputIds"].append(tool_id)
                    #  异步工具返回仅表示窗口已创建，不能当成用户已回答。 / Async return acknowledges creation, not an answer.
                elif event_name == "PermissionRequest" or (
                        event_name == "PreToolUse" and payload.get("tool_name") == "request_permissions"):
                    if not tool_id:
                        state["unattributedApproval"] = True
                    elif tool_id in state["completedToolIds"]:
                        applied = False
                    elif tool_id not in state["pendingToolIds"]:
                        state["pendingToolIds"].append(tool_id)
                elif event_name in ("PreToolUse", "PostToolUse"):
                    if state["unattributedApproval"]:
                        state["approvalUnconfirmed"] = True
                    if event_name == "PostToolUse" and tool_id:
                        state["pendingToolIds"] = [key for key in state["pendingToolIds"] if key != tool_id]
                        if tool_id not in state["completedToolIds"]:
                            state["completedToolIds"].append(tool_id)
                elif event_name in ("Stop", "Interrupt"):
                    state.update(closed=True, pendingToolIds=[], unattributedApproval=False,
                                 approvalUnconfirmed=False)
                    baseline = "idle"
                    if event_name == "Interrupt":
                        state["pendingInputIds"] = []
            selected_status = turn_status(state)

        active = [state for state in turns.values() if not state["closed"] or state["pendingInputIds"]]
        #  新任务接替同聊天旧轮次；保留历史问题记录，真实阻塞审批仍优先。 / New work supersedes old turns in the same chat; retain question history and prioritize blocking approvals.
        displayed = [state for state in active if state["turnId"] == foreground_turn
                     or not state["turnId"] or not state["closed"] and (
                         state["pendingToolIds"] or state["unattributedApproval"]
                         or set(state["pendingInputIds"]) - set(state["asyncInputIds"]))]
        status = "offline" if session_closed else aggregate([turn_status(state) for state in displayed], baseline)
        received_at = timestamp()
        metadata = dict(schema=2, sessionId=session_id, status=status, turnId=turn_id,
                        cwd=str(payload.get("cwd") or ""),
                        permissionMode=str(payload.get("permission_mode") or ""),
                        toolName=str(payload.get("tool_name") or ""), toolUseId=tool_id,
                        correlatedPendingCount=sum(len(state["pendingToolIds"]) for state in active),
                        pendingInputCount=sum(len(state["pendingInputIds"]) for state in active),
                        hasUnattributedApproval=any(state["unattributedApproval"] for state in active),
                        approvalUnconfirmed=any(state["approvalUnconfirmed"] for state in active))
        event = dict(metadata, receivedAtUtc=received_at, hookEventName=event_name,
                     turnStatus=selected_status, applied=applied)
        with (root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        state = dict(metadata, lastEvent=event_name, updatedAtUtc=received_at, foregroundTurnId=foreground_turn,
                     baselineStatus=baseline, turnStates=[turns[key] for key in sorted(turns)])
        atomic_json(path, state)
        sessions = [json.loads(file.read_text(encoding="utf-8")) for file in directory.glob("*.json")]
        overall = aggregate([session["status"] for session in sessions if session["status"] != "offline"])
        atomic_json(root / "snapshot.json", dict(schema=2, generatedAtUtc=received_at,
                    overallStatus=overall, sessions=sorted(sessions, key=lambda entry: entry["sessionId"])))


def main():
    root = Path(os.environ.get("OMIPET_CODEX_MONITOR_DIR") or
                str(Path(os.environ["LOCALAPPDATA"]) / "OmiPet/codex-monitor-probe-v2"))
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("Hook object required")
        collect(root, payload)
    except Exception as error:
        try:
            root.mkdir(parents=True, exist_ok=True)
            atomic_json(root / f"collector-error-{os.getpid()}.json", dict(
                receivedAtUtc=timestamp(), kind="collectorFailure", exceptionType=type(error).__name__))
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
