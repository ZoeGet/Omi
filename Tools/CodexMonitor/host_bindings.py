import argparse
from collections import defaultdict
import json
from pathlib import Path

from process_probe import valid_identity


def derive(records):
    result = dict(schema=1, sessions={}, evidence={}, rejectedSessions={},
                  basis="paired-hook-launcher-observations", sessionLiveness="unverified")
    groups = defaultdict(list)
    for record in records:
        if (not isinstance(record, dict) or record.get("schema") != 1
                or not isinstance(record.get("sessionId"), str) or not record["sessionId"].strip()):
            result["inputState"] = "invalid"
            return result
        groups[record["sessionId"]].append(record)
    for session_id, observations in groups.items():
        identities = {}
        calls = defaultdict(set)
        rejected = None
        for observation in observations:
            identity = observation.get("candidateIdentity")
            if observation.get("associationState") != "observed" or not valid_identity(identity):
                rejected = "unconfirmed-ancestor-observation"
                break
            key = (identity["pid"], identity["creationTime100ns"], identity["imagePath"].casefold())
            identities[key] = {field: identity[field] for field in ("pid", "creationTime100ns", "imagePath")}
            turn_id = observation.get("turnId")
            tool_id = observation.get("toolUseId")
            event = observation.get("hookEventName")
            if isinstance(turn_id, str) and turn_id and isinstance(tool_id, str) and tool_id:
                if event in ("PreToolUse", "PostToolUse"):
                    calls[(turn_id, tool_id)].add(event)
        if rejected:
            result["rejectedSessions"][session_id] = rejected
        elif len(identities) != 1:
            result["rejectedSessions"][session_id] = "conflicting-host-identities"
        else:
            pairs = sum(events == {"PreToolUse", "PostToolUse"} for events in calls.values())
            if not pairs:
                result["rejectedSessions"][session_id] = "matching-hook-pair-not-observed"
                continue
            result["sessions"][session_id] = next(iter(identities.values()))
            result["evidence"][session_id] = dict(observationCount=len(observations), pairedToolCalls=pairs)
    result["inputState"] = "valid"
    return result


def read_observations(directory):
    try:
        paths = sorted(directory.glob("*.json"))
        return [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    except (OSError, ValueError, UnicodeError):
        return [None]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Derive candidate identities from paired Hook observations")
    parser.add_argument("--observations", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(derive(read_observations(args.observations)), ensure_ascii=False, indent=2))
