import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

from process_probe import check as check_process


STATUSES = {"working", "waitingApproval", "idle", "offline", "unknown"}


def utc_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone required")
    return parsed.astimezone(timezone.utc)


def valid_budget(value):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def overall_status(sessions):
    statuses = [entry["displayStatus"] for entry in sessions]
    for status in ("waitingApproval", "working", "unknown", "idle", "offline"):
        if status in statuses:
            return status
    return "unknown"


def project(snapshot, *, now=None, max_age_seconds=None, source_unavailable=False):
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone required")
    if max_age_seconds is not None and not valid_budget(max_age_seconds):
        raise ValueError("Freshness budget must be finite and positive")
    result = dict(schema=1, evaluatedAtUtc=now.isoformat(),
                  maxAgeSeconds=max_age_seconds, liveness="unverified",
                  overallStatus="unknown", sourceState="invalid", sessions=[])
    if (not isinstance(snapshot, dict) or snapshot.get("schema") != 2
            or not isinstance(snapshot.get("sessions"), list)):
        return result
    result["sourceState"] = "unavailable" if source_unavailable else "readable"
    seen = set()
    for observed in snapshot["sessions"]:
        entry = dict(sessionId=None, lastObservedStatus="unknown", lastEvent=None,
                     lastObservedAtUtc=None, observationAgeSeconds=None,
                     lastTurnId="", lastToolUseId="",
                     displayStatus="unknown", reason="invalid-session")
        result["sessions"].append(entry)
        if not isinstance(observed, dict):
            continue
        session_id = observed.get("sessionId")
        status = observed.get("status")
        if (not isinstance(session_id, str) or not session_id.strip()
                or not isinstance(status, str) or status not in STATUSES):
            continue
        entry.update(sessionId=session_id, lastObservedStatus=status,
                     lastEvent=observed.get("lastEvent") if isinstance(observed.get("lastEvent"), str) else None,
                     lastTurnId=observed.get("turnId") if isinstance(observed.get("turnId"), str) else "",
                     lastToolUseId=observed.get("toolUseId") if isinstance(observed.get("toolUseId"), str) else "")
        if session_id in seen:
            result.update(sourceState="invalid", overallStatus="unknown")
            result["sessions"] = []
            return result
        seen.add(session_id)
        try:
            observed_at = utc_time(observed["updatedAtUtc"])
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            entry["reason"] = "invalid-timestamp"
            continue
        age = (now - observed_at).total_seconds()
        entry.update(lastObservedAtUtc=observed_at.isoformat(), observationAgeSeconds=age)
        if age < 0:
            entry["reason"] = "future-timestamp"
        elif source_unavailable:
            entry["reason"] = "source-unavailable"
        elif max_age_seconds is None:
            entry["reason"] = "freshness-policy-unset"
        elif age > max_age_seconds:
            entry["reason"] = "observation-expired"
        else:
            entry.update(displayStatus=status, reason="within-explicit-budget")
    if not result["sessions"]:
        result["sourceState"] = "unavailable" if source_unavailable else "empty"
    result["overallStatus"] = overall_status(result["sessions"])
    return result


def read_view(root, **options):
    try:
        snapshot = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        result = project(None, **options)
        result["sourceState"] = "missing" if isinstance(error, FileNotFoundError) else "unreadable"
        return result
    return project(snapshot, **options)


def read_bound_view(root, bindings, *, process_checker=check_process,
                    monotonic_ns=time.monotonic_ns, **options):
    result = read_view(root, **options)
    if (not isinstance(bindings, dict) or bindings.get("schema") not in (1, 2)
            or not isinstance(bindings.get("sessions"), dict)):
        result.update(overallStatus="unknown", bindingState="invalid")
        for entry in result["sessions"]:
            entry.update(displayStatus="unknown", reason="invalid-process-bindings")
        return result
    correlated = bindings["schema"] == 2
    result["bindingState"] = "event-correlated" if correlated else "explicit"
    current_monotonic_ns = monotonic_ns() if correlated else None
    if correlated and (type(current_monotonic_ns) is not int or current_monotonic_ns < 0):
        current_monotonic_ns = None
    if correlated and current_monotonic_ns is not None:
        result["evaluatedAtMonotonicNs"] = str(current_monotonic_ns)
    for entry in result["sessions"]:
        record = bindings["sessions"].get(entry["sessionId"])
        if record is None:
            entry.update(hostProcessState="unknown", displayStatus="unknown", reason="process-binding-missing")
            continue
        if correlated:
            proof = record.get("proof") if isinstance(record, dict) else None
            expected = dict(updatedAtUtc=entry["lastObservedAtUtc"], lastEvent=entry["lastEvent"],
                            turnId=entry["lastTurnId"], toolUseId=entry["lastToolUseId"])
            if (not isinstance(record, dict) or record.get("confirmed") is not True
                    or proof != expected):
                entry.update(hostProcessState="unknown", displayStatus="unknown", reason="event-binding-unconfirmed")
                continue
            observed_monotonic_ns = record.get("observedMonotonicNs")
            if (current_monotonic_ns is None or not isinstance(observed_monotonic_ns, str)
                    or not observed_monotonic_ns.isascii() or not observed_monotonic_ns.isdecimal()
                    or len(observed_monotonic_ns) > 20):
                entry.update(hostProcessState="unknown", displayStatus="unknown", reason="event-clock-invalid")
                continue
            elapsed_ns = current_monotonic_ns - int(observed_monotonic_ns)
            if elapsed_ns < 0:
                entry.update(hostProcessState="unknown", displayStatus="unknown", reason="event-clock-invalid")
                continue
            age = elapsed_ns / 1_000_000_000
            entry["observationAgeSeconds"] = age
            budget = result["maxAgeSeconds"]
            if (result["sourceState"] != "readable" or budget is None
                    or age > budget):
                entry.update(displayStatus="unknown", reason=("observation-expired" if budget is not None
                             and age > budget else "source-unavailable-or-budget-unset"))
            else:
                entry.update(displayStatus=entry["lastObservedStatus"], reason="within-monotonic-budget")
            identity = record.get("identity")
        else:
            identity = record
        evidence = process_checker(identity)
        entry["hostProcessState"] = evidence["processState"]
        if evidence["processState"] != "running":
            entry.update(displayStatus="unknown", reason="bound-process-unconfirmed")
    result["overallStatus"] = overall_status(result["sessions"])
    return result


def positive_seconds(value):
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected seconds") from error
    if not valid_budget(seconds):
        raise argparse.ArgumentTypeError("Seconds must be finite and positive")
    return seconds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only observation view; never proves process liveness")
    parser.add_argument("--root", type=Path,
                        default=Path(os.environ["LOCALAPPDATA"]) / "OmiPet/codex-monitor-probe-v2")
    parser.add_argument("--max-age-seconds", type=positive_seconds,
                        help="Explicit observation budget; omitted means display unknown")
    parser.add_argument("--source-unavailable", action="store_true",
                        help="Caller has independent evidence that the source is unavailable")
    parser.add_argument("--process-bindings", type=Path,
                        help="Explicit session-to-process identities; queried live, never inferred")
    args = parser.parse_args()
    options = dict(max_age_seconds=args.max_age_seconds, source_unavailable=args.source_unavailable)
    if args.process_bindings:
        try:
            bindings = json.loads(args.process_bindings.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, UnicodeError):
            bindings = None
        result = read_bound_view(args.root, bindings, **options)
    else:
        result = read_view(args.root, **options)
    print(json.dumps(result, ensure_ascii=False, indent=2))
