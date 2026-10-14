import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path


def audit(root, target_session_id=None, turn_id=None):
    event_path = root / "events.jsonl"
    raw = event_path.read_bytes() if event_path.exists() else b""
    lines = raw.splitlines()
    events = []
    invalid_lines = []
    incomplete_tail = False
    for index, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
            if not isinstance(event, dict) or not event.get("sessionId"):
                raise ValueError("Missing session identifier")
            events.append(event)
        except (ValueError, UnicodeDecodeError):
            if index == len(lines) and not raw.endswith(b"\n"):
                incomplete_tail = True
            else:
                invalid_lines.append(index)

    sessions = {}
    late_starts = []
    unexpected_fields = set()
    allowed_fields = {
        "schema", "receivedAtUtc", "sessionId", "hookEventName", "turnId",
        "cwd", "permissionMode", "toolName", "status",
        "toolUseId", "turnStatus", "applied", "correlatedPendingCount",
        "hasUnattributedApproval", "approvalUnconfirmed",
    }
    for event in events:
        session_id = event["sessionId"]
        event_name = event.get("hookEventName", "")
        previous = sessions.get(session_id)
        if (event_name == "SessionStart" and previous and previous["lastStatus"] == "working"
                and event.get("status") == "unknown"):
            late_starts.append({"sessionId": session_id,
                                "receivedAtUtc": event.get("receivedAtUtc")})
        if previous is None:
            previous = {"sessionId": session_id, "eventCounts": Counter(),
                        "firstReceivedAtUtc": event.get("receivedAtUtc")}
            sessions[session_id] = previous
        previous["eventCounts"][event_name] += 1
        previous.update(lastEvent=event_name, lastStatus=event.get("status"),
                        lastTurnId=event.get("turnId"),
                        lastReceivedAtUtc=event.get("receivedAtUtc"))
        unexpected_fields.update(set(event) - allowed_fields)

    counts = Counter(event.get("hookEventName", "") for event in events)
    limitations = ["Hook records are observations, not authoritative desktop state.",
                   "No heartbeat or expiry policy has been validated.",
                   "Normal completion and approval recovery require controlled live tests."]
    if not counts["Stop"]:
        limitations.append("No Stop received; normal completion to idle is unverified.")
    if not counts["PermissionRequest"]:
        limitations.append("No PermissionRequest hook event received; explicit permission-tool starts are counted separately.")
    if late_starts:
        limitations.append("SessionStart arrived after working and can overwrite that state.")
    report = {
        "schema": 1, "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceDirectory": str(root), "eventCount": len(events),
        "sessionCount": len(sessions), "eventCounts": dict(sorted(counts.items())),
        "invalidLineNumbers": invalid_lines, "incompleteTailIgnored": incomplete_tail,
        "unexpectedFieldNames": sorted(unexpected_fields),
        "collectorErrorFileCount": len(list(root.glob("collector-error-*.json"))),
        "lateSessionStarts": late_starts,
        "sessions": [sessions[key] for key in sorted(sessions)],
        "approvalIdentityCoverage": {
            "withToolUseId": sum(event.get("hookEventName") == "PermissionRequest"
                                 and bool(event.get("toolUseId")) for event in events),
            "withoutToolUseId": sum(event.get("hookEventName") == "PermissionRequest"
                                    and not event.get("toolUseId") for event in events),
            "permissionToolStarts": sum(event.get("hookEventName") == "PreToolUse"
                                        and event.get("toolName") == "request_permissions"
                                        for event in events),
            "permissionToolStartsWithId": sum(event.get("hookEventName") == "PreToolUse"
                                              and event.get("toolName") == "request_permissions"
                                              and bool(event.get("toolUseId")) for event in events),
            "ignoredEventCount": sum(event.get("applied") is False for event in events),
        },
        "limitations": limitations,
    }
    if target_session_id:
        selected = [event for event in events if event["sessionId"] == target_session_id
                    and (not turn_id or event.get("turnId") == turn_id)]
        report["targetCheck"] = {
            "sessionId": target_session_id, "turnId": turn_id,
            "eventCount": len(selected),
            "eventCounts": dict(Counter(event.get("hookEventName", "") for event in selected)),
            "stopReceived": any(event.get("hookEventName") == "Stop" for event in selected),
            "lastObservedStatus": ((selected[-1].get("turnStatus") or selected[-1].get("status"))
                                   if selected else "unknown"),
            "lastReceivedAtUtc": selected[-1].get("receivedAtUtc") if selected else None,
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path(os.environ["LOCALAPPDATA"]) / "OmiPet/codex-monitor-probe-v2")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--session")
    parser.add_argument("--turn")
    args = parser.parse_args()
    if args.turn and not args.session:
        parser.error("--turn requires --session")
    report = audit(args.root, args.session, args.turn)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    summary = {key: report[key] for key in (
        "generatedAtUtc", "eventCount", "sessionCount", "eventCounts",
        "invalidLineNumbers", "incompleteTailIgnored", "unexpectedFieldNames",
        "collectorErrorFileCount", "approvalIdentityCoverage", "limitations")}
    if "targetCheck" in report:
        summary["targetCheck"] = report["targetCheck"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
