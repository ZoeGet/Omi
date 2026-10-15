from contextlib import nullcontext
import json
from pathlib import Path
import re

from host_observer import ancestry
from process_probe import valid_identity


def event_matches(state, payload, expected_updated_at):
    return (state.get("sessionId") == payload.get("session_id")
            and isinstance(expected_updated_at, str)
            and state.get("updatedAtUtc") == expected_updated_at
            and state.get("lastEvent") == payload.get("hook_event_name")
            and state.get("turnId") == str(payload.get("turn_id") or "")
            and state.get("toolUseId") == str(payload.get("tool_use_id") or ""))


def event_proof(state):
    return {field: state[field] for field in ("updatedAtUtc", "lastEvent", "turnId", "toolUseId")}


def matching_identity(left, right):
    return (valid_identity(left) and valid_identity(right)
            and left["pid"] == right["pid"]
            and left["creationTime100ns"] == right["creationTime100ns"]
            and left["imagePath"].casefold() == right["imagePath"].casefold())


def event_was_applied(root, state, session_id):
    try:
        with (root / "events.jsonl").open("rb") as stream:
            stream.seek(0, 2)
            end = stream.tell()
            stream.seek(max(0, end - 65536))
            lines = stream.read().splitlines()
        event = json.loads(lines[-1])
    except (OSError, IndexError, ValueError, UnicodeError):
        return False
    return (event.get("applied") is True
            and event.get("sessionId") == session_id
            and event.get("receivedAtUtc") == state.get("updatedAtUtc")
            and event.get("hookEventName") == state.get("lastEvent")
            and event.get("turnId") == state.get("turnId")
            and event.get("toolUseId") == state.get("toolUseId"))


def update(root, payload, configuration, *, expected_updated_at,
           observed_monotonic_ns, observer=ancestry, lock=nullcontext, save=None):
    if not configuration.get("enabled") or not payload.get("session_id"):
        return False
    allowed = configuration.get("allowedImages")
    limit = configuration.get("maxSessions")
    if (not isinstance(allowed, list) or not allowed
            or not all(isinstance(item, str) and item for item in allowed)
            or type(limit) is not int or limit <= 0
            or type(observed_monotonic_ns) is not int or observed_monotonic_ns <= 0):
        raise ValueError("Explicit allowed images and positive session capacity required")
    target = root / "host-bindings.json"
    evidence = observer(allowed)
    candidate = evidence.get("candidateIdentity") if evidence.get("associationState") == "observed" else None
    if not valid_identity(candidate):
        return False
    session_id = str(payload["session_id"])
    if not session_id.strip():
        return False
    name = re.sub(r"[^A-Za-z0-9._-]", "_", session_id) + ".json"
    with lock(root):
        state_path = root / "sessions" / name
        if not state_path.is_file():
            return False
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (not event_matches(state, payload, expected_updated_at)
                or not event_was_applied(root, state, session_id)):
            return False
        current = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
        if (current.get("schema") != 2 or not isinstance(current.get("sessions"), list)
                or len(current["sessions"]) > limit):
            return False
        ids = {entry.get("sessionId") for entry in current["sessions"] if isinstance(entry, dict)}
        if session_id not in ids:
            return False
        try:
            previous = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            previous = None
        entries = previous.get("sessions", {}) if isinstance(previous, dict) and previous.get("schema") == 2 else {}
        if not isinstance(entries, dict):
            entries = {}
        entries = {key: item for key, item in entries.items() if key in ids}
        prior = entries.get(session_id)
        same = isinstance(prior, dict) and matching_identity(prior.get("identity"), candidate)
        turn, tool, event = (str(payload.get(key) or "") for key in
                             ("turn_id", "tool_use_id", "hook_event_name"))
        pending = prior.get("pending") if same else None
        confirmed = bool(prior.get("confirmed")) if same else False
        if event == "PreToolUse" and turn and tool:
            pending = {"turnId": turn, "toolUseId": tool}
        elif event == "PostToolUse" and pending == {"turnId": turn, "toolUseId": tool}:
            confirmed = True
            pending = None
        if event == "SessionEnd":
            entries.pop(session_id, None)
        else:
            entries[session_id] = dict(identity={field: candidate[field] for field in
                                               ("pid", "creationTime100ns", "imagePath")},
                                       proof=event_proof(state), confirmed=confirmed, pending=pending,
                                       observedMonotonicNs=str(observed_monotonic_ns))
        if len(entries) > limit:
            return False
        data = dict(schema=2, sessions=entries)
        if save is None:
            staged = target.with_name(target.name + ".tmp")
            staged.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            staged.replace(target)
        else:
            save(target, data)
        return confirmed and event != "SessionEnd"
