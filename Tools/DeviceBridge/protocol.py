from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import time
import uuid


PREFIX = b"@OMI "
STATUSES = ("waitingApproval", "working", "unknown", "idle", "offline")
OPERATIONS = ("hello", "heartbeat", "snapshot", "release", "light")
LIGHT_EFFECTS = ("solid", "rainbow", "breathe", "sweep", "centerExpand", "off")
FIELDS = {"v", "boot", "channel", "session", "seq", "type", "body"}
MAX_SEQUENCE = 0xFFFFFFFF


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    max_json_bytes: int
    max_sessions: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.max_json_bytes, self.max_sessions)):
            raise ProtocolError("invalid-limits")


def token():
    return uuid.uuid4().hex


def valid_token(value):
    return isinstance(value, str) and bool(re.fullmatch("[0-9a-f]{32}", value))


def envelope(boot, channel, session, seq, kind, body):
    return dict(v=1, boot=boot, channel=channel, session=session, seq=seq, type=kind, body=body)


def validate(message):
    if not isinstance(message, dict) or set(message) != FIELDS:
        raise ProtocolError("invalid-envelope")
    if type(message["v"]) is not int or message["v"] != 1:
        raise ProtocolError("unsupported-version")
    if not valid_token(message["boot"]) or not valid_token(message["channel"]):
        raise ProtocolError("invalid-connection-identity")
    if not valid_token(message["session"]) and not (message["type"] == "welcome" and message["session"] == ""):
        raise ProtocolError("invalid-session")
    if type(message["seq"]) is not int or not 0 <= message["seq"] <= MAX_SEQUENCE:
        raise ProtocolError("invalid-sequence")
    if not isinstance(message["type"], str) or not isinstance(message["body"], dict):
        raise ProtocolError("invalid-message-type")
    return message


def encode(message, limits):
    validate(message)
    try:
        raw = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise ProtocolError("invalid-json") from error
    if len(raw) > limits.max_json_bytes:
        raise ProtocolError("message-too-large")
    return raw


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate-json-key")
        result[key] = value
    return result


def invalid_constant(value):
    raise ProtocolError("invalid-json-number")


def decode(raw, limits):
    if not isinstance(raw, bytes) or len(raw) > limits.max_json_bytes:
        raise ProtocolError("message-too-large-or-invalid")
    try:
        message = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ProtocolError("invalid-json") from error
    return validate(message)


def serial_frame(message, limits):
    return PREFIX + encode(message, limits) + b"\n"


def websocket_text(message, limits):
    return encode(message, limits).decode("utf-8")


def decode_websocket(text, limits):
    if not isinstance(text, str):
        raise ProtocolError("text-message-required")
    try:
        return decode(text.encode("utf-8"), limits)
    except UnicodeError as error:
        raise ProtocolError("invalid-utf8") from error


class SerialDecoder:
    def __init__(self, limits):
        self.limits = limits
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, data):
        messages, issues = [], []
        for byte in data:
            if byte == 10:
                if not self.dropping and self.buffer.startswith(PREFIX):
                    raw = bytes(self.buffer[len(PREFIX):]).removesuffix(b"\r")
                    try:
                        messages.append(decode(raw, self.limits))
                    except ProtocolError as error:
                        issues.append(str(error))
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) <= len(PREFIX) and not PREFIX.startswith(self.buffer):
                    self.dropping = True
                    self.buffer.clear()
                elif len(self.buffer) > len(PREFIX) + self.limits.max_json_bytes:
                    if not (len(self.buffer) == len(PREFIX) + self.limits.max_json_bytes + 1 and byte == 13):
                        issues.append("message-too-large")
                        self.dropping = True
                        self.buffer.clear()
        return messages, issues

    def finish(self):
        incomplete = not self.dropping and self.buffer.startswith(PREFIX)
        self.buffer.clear()
        self.dropping = False
        return ["truncated-frame"] if incomplete else []


def aggregate(entries):
    states = [entry["display"] for entry in entries]
    return next((status for status in STATUSES if status in states), "unknown")


def validate_light(body):
    if not isinstance(body, dict) or set(body) != {"effect", "red", "green", "blue", "brightness"}:
        raise ProtocolError("invalid-light-fields")
    if (body["effect"] not in LIGHT_EFFECTS or any(type(body[key]) is not int or not 0 <= body[key] <= 255
                                                   for key in ("red", "green", "blue", "brightness"))):
        raise ProtocolError("invalid-light-setting")
    return body


def validate_snapshot(body, limits):
    fields = {"revision", "validForMs", "sourceLiveness", "overallStatus", "sessions"}
    if (set(body) not in (fields, fields | {"challengeSeq"})
            or body["sourceLiveness"] != "unverified"):
        raise ProtocolError("invalid-source-state")
    if "challengeSeq" in body and (type(body["challengeSeq"]) is not int
                                   or not 1 <= body["challengeSeq"] <= MAX_SEQUENCE):
        raise ProtocolError("invalid-challenge")
    if (type(body["revision"]) is not int or not 1 <= body["revision"] <= MAX_SEQUENCE
            or type(body["validForMs"]) is not int or not 0 <= body["validForMs"] <= MAX_SEQUENCE):
        raise ProtocolError("invalid-snapshot-validity")
    sessions = body["sessions"]
    if not isinstance(sessions, list) or len(sessions) > limits.max_sessions:
        raise ProtocolError("session-capacity-exceeded")
    ids = set()
    for entry in sessions:
        if not isinstance(entry, dict) or set(entry) != {"id", "observed", "display", "host"}:
            raise ProtocolError("invalid-session-entry")
        alias = entry["id"]
        if not isinstance(alias, str) or not re.fullmatch("s[1-9][0-9]*", alias) or alias in ids:
            raise ProtocolError("invalid-session-alias")
        ids.add(alias)
        if entry["observed"] not in STATUSES or entry["display"] not in STATUSES:
            raise ProtocolError("invalid-business-state")
        if entry["host"] not in ("running", "exited", "identityMismatch", "unknown", "unverified"):
            raise ProtocolError("invalid-host-state")
        if entry["display"] != "unknown" and entry["host"] != "running":
            raise ProtocolError("host-unconfirmed")
        if entry["display"] != "unknown" and body["validForMs"] == 0:
            raise ProtocolError("observation-expired")
    if body["overallStatus"] != aggregate(sessions):
        raise ProtocolError("inconsistent-overall-state")
    return body


class SnapshotMapper:
    def __init__(self):
        self.aliases = {}
        self.revision = 0

    def convert(self, view, limits, *, now=None, delivery_reserve_seconds=0,
                monotonic_ns=time.monotonic_ns):
        if (type(delivery_reserve_seconds) not in (int, float)
                or not math.isfinite(delivery_reserve_seconds) or delivery_reserve_seconds < 0):
            raise ProtocolError("invalid-delivery-reserve")
        now = now if now is not None else datetime.now(timezone.utc)
        try:
            evaluated = datetime.fromisoformat(view["evaluatedAtUtc"].replace("Z", "+00:00"))
            if evaluated.tzinfo is None or evaluated.utcoffset() is None:
                raise ValueError("Timezone required")
            lag = (now - evaluated).total_seconds()
        except (KeyError, ValueError, TypeError, AttributeError):
            lag = -1
        if "evaluatedAtMonotonicNs" in view:
            stamp = view["evaluatedAtMonotonicNs"]
            current = monotonic_ns()
            if (isinstance(stamp, str) and stamp.isascii() and stamp.isdecimal()
                    and len(stamp) <= 20 and type(current) is int and current >= int(stamp)):
                lag = (current - int(stamp)) / 1_000_000_000
            else:
                lag = -1
        entries = view.get("sessions")
        if not isinstance(entries, list) or len(entries) > limits.max_sessions:
            raise ProtocolError("invalid-view-or-capacity")
        pending_aliases = dict(self.aliases)
        sessions, seen, validity = [], set(), []
        for entry in entries:
            key = entry.get("sessionId") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not key or key in seen:
                raise ProtocolError("invalid-view-session")
            seen.add(key)
            if key not in pending_aliases:
                if len(pending_aliases) >= limits.max_sessions:
                    raise ProtocolError("alias-capacity-reconnect-required")
                pending_aliases[key] = "s" + str(len(pending_aliases) + 1)
            host = entry.get("hostProcessState", "unverified")
            display = entry.get("displayStatus", "unknown")
            budget, age = view.get("maxAgeSeconds"), entry.get("observationAgeSeconds")
            age = age + lag + delivery_reserve_seconds if type(age) in (int, float) and lag >= 0 else None
            fresh = (type(budget) in (int, float) and math.isfinite(budget) and budget > 0
                     and type(age) in (int, float) and math.isfinite(age) and 0 <= age <= budget and lag >= 0)
            if host != "running" or not fresh or view.get("sourceState") != "readable":
                display = "unknown"
            remaining = int(min(budget - age, MAX_SEQUENCE / 1000) * 1000) if fresh else 0
            if remaining <= 0:
                display = "unknown"
            if display != "unknown":
                validity.append(remaining)
            sessions.append(dict(id=pending_aliases[key], observed=entry.get("lastObservedStatus", "unknown"),
                                 display=display, host=host))
        body = dict(revision=self.revision + 1, validForMs=min(validity) if validity else 0,
                    sourceLiveness="unverified", overallStatus=aggregate(sessions), sessions=sessions)
        validate_snapshot(body, limits)
        self.aliases = pending_aliases
        self.revision += 1
        return body
