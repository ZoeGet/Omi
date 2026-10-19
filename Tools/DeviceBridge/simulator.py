import copy

from protocol import (Limits, MAX_SEQUENCE, OPERATIONS, ProtocolError, decode, encode, envelope,
                      token, validate_snapshot, validate_light, default_monitor_profile, validate_monitor_profile)


class DeviceSimulator:
    def __init__(self, limits, *, lease_ms, freshness_challenge=False, desktop_control=False, monitor_lights=False, monitor_green_off=False, monitor_profiles=False, task_cards=False):
        if type(lease_ms) is not int or lease_ms <= 0:
            raise ProtocolError("explicit-positive-lease-required")
        self.limits = limits
        self.task_cards = task_cards
        self.lease_ms = lease_ms
        self.freshness_challenge = freshness_challenge
        self.challenge_at = None
        self.boot = token()
        self.channel = None
        self.session = None
        self.last_seq = 0
        self.last_request = None
        self.last_result = None
        self.deadline = None
        self.now = 0
        self.mode = "local"
        self.snapshot = None
        self.snapshot_deadline = None
        self.last_snapshot_revision = 0
        self.applied_snapshots = 0
        self.expired = False
        self.desktop_control = desktop_control
        self.local_light = None
        self.applied_lights = 0
        self.voice_active = False
        self.monitor_lights = monitor_lights
        self.monitor_green_off = monitor_green_off
        self.monitor_profile = default_monitor_profile() if monitor_profiles else None
        self.profile_writes = 0
        self.profile_save_fails = False
        self.monitor_selected = False
        self.voice_suppressed = False

    def advance(self, now_ms):
        if type(now_ms) is not int or now_ms < self.now:
            raise ProtocolError("non-monotonic-clock")
        self.now = now_ms
        if self.deadline is not None and now_ms >= self.deadline:
            self.mode = "local"
            self.deadline = None
            self.expired = True

    def open(self, now_ms):
        self.advance(now_ms)
        self.channel = token()
        self.session = None
        self.last_seq = 0
        self.last_request = None
        self.last_result = None
        self.mode = "local"
        self.deadline = None
        self.expired = False
        self.snapshot_deadline = None
        self.last_snapshot_revision = 0
        self.challenge_at = None
        self.voice_suppressed = False
        return envelope(self.boot, self.channel, "", 0, "welcome", dict(
            operations=[kind for kind in OPERATIONS if (kind != "light" or self.desktop_control) and (kind != "monitorProfile" or self.monitor_profile is not None)], maxJsonBytes=self.limits.max_json_bytes,
            maxSessions=self.limits.max_sessions, leaseMs=self.lease_ms,
            **({"monitorLights": True} if self.monitor_lights else {}),
            **({"monitorGreenOff": True} if self.monitor_green_off else {}),
            **({"taskCards": True} if self.task_cards else {}),
            **({"freshnessChallenge": True} if self.freshness_challenge else {})))

    def disconnect(self):
        self.channel = None
        self.session = None
        self.mode = "local"
        self.deadline = None
        self.voice_suppressed = False

    def monitor_output(self):
        if not self.monitor_selected:
            return "local"
        return "connected" if self.mode == "monitor" and self.deadline is not None else "disconnected"

    def yield_monitor_to_voice(self):
        self.monitor_selected = False
        self.voice_suppressed = True

    def state(self):
        return dict(mode=self.mode, displayStatus=(self.snapshot["overallStatus"]
                    if self.mode == "monitor" and self.snapshot and self.snapshot_deadline is not None
                    and self.now < self.snapshot_deadline else "unknown"),
                    sourceLiveness="unverified", leaseActive=self.deadline is not None,
                    **({"monitorOutput": self.monitor_output()} if self.monitor_green_off else {}))

    def reply(self, request, ok, code, *, duplicate=False):
        return envelope(self.boot, self.channel or request["channel"], request["session"], request["seq"], "ack",
                        dict(ok=ok, code=code, command=request["type"], duplicate=duplicate, state=self.state(),
                             **({"monitorProfile": copy.deepcopy(self.monitor_profile)} if self.monitor_profile is not None else {})))

    def receive(self, request, now_ms):
        self.advance(now_ms)
        canonical = encode(request, self.limits)
        request = decode(canonical, self.limits)
        if request["boot"] != self.boot or request["channel"] != self.channel:
            return self.reply(request, False, "wrong-connection")
        if self.session is not None and request["session"] != self.session:
            return self.reply(request, False, "wrong-session")
        if self.expired:
            return self.reply(request, False, "connection-expired-reconnect-required")
        seq = request["seq"]
        if seq == self.last_seq and self.last_request is not None:
            if canonical != self.last_request:
                return self.reply(request, False, "sequence-conflict")
            return self.reply(request, *self.last_result, duplicate=True)
        if seq != self.last_seq + 1:
            return self.reply(request, False, "sequence-gap-or-stale")
        kind, body = request["type"], request["body"]
        if self.session is None:
            if kind != "hello" or seq != 1 or body != {"protocol": 1} or type(body.get("protocol")) is not int:
                return self.reply(request, False, "hello-required")
            self.session = request["session"]
            ok, code = True, "ok"
            self.deadline = now_ms + self.lease_ms
        else:
            try:
                if kind == "snapshot":
                    validate_snapshot(body, self.limits)
                    if body["revision"] <= self.last_snapshot_revision:
                        raise ProtocolError("snapshot-revision-stale")
                    validity = body["validForMs"]
                    if self.freshness_challenge and body["overallStatus"] != "unknown":
                        if (body.get("challengeSeq") != self.last_seq or self.challenge_at is None
                                or self.last_request is None
                                or not self.last_result[0]
                                or decode(self.last_request, self.limits)["type"] != "heartbeat"):
                            raise ProtocolError("freshness-challenge-required")
                        validity = max(0, validity - (now_ms - self.challenge_at))
                    self.snapshot = copy.deepcopy(body)
                    if validity == 0 and self.freshness_challenge:
                        self.snapshot["overallStatus"] = "unknown"
                    self.last_snapshot_revision = body["revision"]
                    self.snapshot_deadline = now_ms + validity
                    self.mode = "monitor"
                    self.deadline = now_ms + self.lease_ms
                    self.applied_snapshots += 1
                    if not self.voice_suppressed:
                        self.monitor_selected = True
                elif kind == "monitorProfile" and self.monitor_profile is not None:
                    if body:
                        validate_monitor_profile(body)
                        if body["revision"] != self.monitor_profile["revision"]:
                            raise ProtocolError("monitor-profile-conflict")
                        if body["profiles"] != self.monitor_profile["profiles"]:
                            if body["revision"] == MAX_SEQUENCE:
                                raise ProtocolError("monitor-profile-revision-exhausted")
                            if self.profile_save_fails:
                                raise ProtocolError("monitor-profile-save-failed")
                            self.monitor_profile = copy.deepcopy(body)
                            self.monitor_profile["revision"] += 1
                            self.profile_writes += 1
                    self.deadline = now_ms + self.lease_ms
                elif kind == "light" and self.desktop_control:
                    if self.mode == "monitor":
                        raise ProtocolError("monitor-mode-active")
                    if self.voice_active:
                        raise ProtocolError("voice-active")
                    validate_light(body)
                    self.local_light = copy.deepcopy(body)
                    self.applied_lights += 1
                    self.deadline = now_ms + self.lease_ms
                    self.monitor_selected = self.voice_suppressed = False
                elif kind in ("heartbeat", "release"):
                    disconnect_release = kind == "release" and self.monitor_green_off and body == {"disconnect": True} and type(body.get("disconnect")) is bool
                    if body and not disconnect_release:
                        raise ProtocolError("empty-body-required")
                    if kind == "release":
                        self.mode = "local"
                        self.deadline = None
                        if not disconnect_release:
                            self.monitor_selected = False
                        self.voice_suppressed = False
                    else:
                        self.deadline = now_ms + self.lease_ms
                        self.challenge_at = now_ms
                else:
                    raise ProtocolError("unsupported-command")
                ok, code = True, "ok"
            except ProtocolError as error:
                ok, code = False, str(error)
        self.last_seq, self.last_request, self.last_result = seq, canonical, (ok, code)
        return self.reply(request, ok, code)


class HostSession:
    def __init__(self, welcome, limits):
        welcome = decode(encode(welcome, limits), limits)
        if welcome["type"] != "welcome" or welcome["seq"] != 0 or welcome["session"]:
            raise ProtocolError("welcome-required")
        body = welcome["body"]
        if (type(body.get("maxJsonBytes")) is not int or type(body.get("maxSessions")) is not int
                or type(body.get("leaseMs")) is not int or body["leaseMs"] <= 0
                or not isinstance(body.get("operations"), list) or "hello" not in body["operations"]):
            raise ProtocolError("invalid-capabilities")
        self.limits = Limits(min(limits.max_json_bytes, body["maxJsonBytes"]),
                             min(limits.max_sessions, body["maxSessions"]))
        self.operations = body["operations"]
        if 'taskCards' in body and type(body['taskCards']) is not bool:
            raise ProtocolError('invalid-capabilities')
        self.task_cards = body.get('taskCards', False)
        if "freshnessChallenge" in body and type(body["freshnessChallenge"]) is not bool:
            raise ProtocolError("invalid-capabilities")
        self.freshness_challenge = body.get("freshnessChallenge", False)
        if "monitorLights" in body and type(body["monitorLights"]) is not bool:
            raise ProtocolError("invalid-capabilities")
        self.monitor_lights = body.get("monitorLights", False)
        if "monitorGreenOff" in body and type(body["monitorGreenOff"]) is not bool:
            raise ProtocolError("invalid-capabilities")
        self.monitor_green_off = body.get("monitorGreenOff", False)
        self.monitor_profile = None
        self.lease_ms = body["leaseMs"]
        self.boot, self.channel, self.session = welcome["boot"], welcome["channel"], token()
        self.next_seq = 1
        self.pending = None
        self.ready = False
        self.invalidated = False

    def prepare(self, kind, body):
        if self.invalidated:
            raise ProtocolError("reconnect-required")
        if self.pending is not None:
            raise ProtocolError("ack-pending")
        if kind not in self.operations or kind not in OPERATIONS or (not self.ready and kind != "hello"):
            raise ProtocolError("command-not-negotiated")
        if self.ready and kind == "hello":
            raise ProtocolError("already-initialized")
        if self.next_seq > MAX_SEQUENCE:
            raise ProtocolError("reconnect-required")
        message = envelope(self.boot, self.channel, self.session, self.next_seq, kind, body)
        self.pending = encode(message, self.limits)
        return decode(self.pending, self.limits)

    def retry(self):
        if self.pending is None:
            raise ProtocolError("no-pending-command")
        return decode(self.pending, self.limits)

    def accept(self, reply):
        reply = decode(encode(reply, self.limits), self.limits)
        if self.pending is None:
            raise ProtocolError("unexpected-ack")
        request = decode(self.pending, self.limits)
        if reply["type"] != "ack" or any(reply[key] != request[key] for key in ("boot", "channel", "session", "seq")):
            raise ProtocolError("ack-identity-mismatch")
        if (reply["body"].get("command") != request["type"] or type(reply["body"].get("ok")) is not bool):
            raise ProtocolError("invalid-ack")
        state = reply["body"].get("state")
        state_fields = {"mode", "displayStatus", "sourceLiveness", "leaseActive"}
        if self.monitor_green_off:
            state_fields.add("monitorOutput")
        if (not isinstance(state, dict) or set(state) != state_fields
                or (self.monitor_green_off and state.get("monitorOutput") not in ("local", "connected", "disconnected"))
                or state["mode"] not in ("local", "monitor") or type(state["leaseActive"]) is not bool
                or state["displayStatus"] not in ("working", "waitingApproval", "idle", "offline", "unknown")
                or state["sourceLiveness"] != "unverified"
                or (state["mode"] == "local" and state["displayStatus"] != "unknown")):
            raise ProtocolError("invalid-ack-state")
        if request["type"] == "hello" and not reply["body"]["ok"]:
            raise ProtocolError("hello-rejected-reconnect-required")
        if "monitorProfile" in self.operations:
            validate_monitor_profile(reply["body"].get("monitorProfile"))
            self.monitor_profile = copy.deepcopy(reply["body"]["monitorProfile"])
        elif "monitorProfile" in reply["body"]:
            raise ProtocolError("unnegotiated-monitor-profile")
        self.pending = None
        self.next_seq += 1
        if request["type"] == "hello":
            self.ready = True
        if reply["body"].get("code") in ("connection-expired-reconnect-required", "sequence-conflict",
                                         "sequence-gap-or-stale", "wrong-session", "hello-required"):
            self.invalidated = True
            self.ready = False
        return reply["body"]
