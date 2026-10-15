import copy
import json

from protocol import Limits, envelope
from simulator import DeviceSimulator


BOOT = "1" * 32
CHANNEL = "2" * 32
SESSION = "3" * 32


def snapshot(revision=1, status="working", validity=100):
    return dict(revision=revision, validForMs=validity, sourceLiveness="unverified",
                overallStatus=status, sessions=[dict(id="s1", observed=status, display=status, host="running")])


class Scenario:
    def __init__(self, name):
        self.name = name
        self.steps = []
        self.device = DeviceSimulator(Limits(4096, 16), lease_ms=1000)
        self.device.boot = BOOT
        self.open(CHANNEL, 0)

    def record(self, step):
        step["state"] = self.device.state()
        self.steps.append(step)

    def open(self, channel, now):
        reply = self.device.open(now)
        self.device.channel = channel
        reply["channel"] = channel
        self.record(dict(op="open", channel=channel, now=now, reply=reply))

    def send(self, kind, body, now, *, seq=None, session=SESSION, boot=BOOT, channel=None, raw=None):
        request = envelope(boot, channel or self.device.channel, session,
                           seq if seq is not None else self.device.last_seq + 1, kind, body)
        reply = self.device.receive(request, now)
        self.record(dict(op="receive", now=now, raw=raw or json.dumps(request, separators=(",", ":")), reply=reply))
        return request

    def ready(self):
        self.send("hello", {"protocol": 1}, 0)
        return self

    def advance(self, now):
        self.device.advance(now)
        self.record(dict(op="advance", now=now))

    def disconnect(self):
        self.device.disconnect()
        self.record(dict(op="disconnect", now=self.device.now))


def write_vectors(path):
    scenarios = []

    def case(name, ready=True):
        result = Scenario(name)
        if ready:
            result.ready()
        scenarios.append(result)
        return result

    test = case("hello_required", ready=False)
    test.send("heartbeat", {}, 0)
    test.send("hello", {"protocol": True}, 0)
    test.send("hello", {"protocol": 2}, 0)
    test.send("hello", {"protocol": 1, "extra": 1}, 0)
    test.ready()
    test.send("hello", {"protocol": 1}, 1)

    test = case("identity_and_sequence")
    test.send("heartbeat", {}, 1, boot="4" * 32)
    test.send("heartbeat", {}, 1, channel="4" * 32)
    test.send("heartbeat", {}, 1, session="4" * 32)
    test.send("heartbeat", {}, 1, seq=4)
    test.send("heartbeat", {}, 1)
    test.send("heartbeat", {}, 2, seq=1)
    test.send("heartbeat", {}, 2, seq=0xFFFFFFFF)

    test = case("duplicate_semantic_content")
    body = snapshot()
    request = test.send("snapshot", body, 10)
    test.send("snapshot", body, 40, seq=2, raw=json.dumps(request, sort_keys=True, indent=1))
    test.send("snapshot", snapshot(status="idle"), 50, seq=2)
    test.send("snapshot", body, 110, seq=2)
    test.advance(1010)
    test.send("snapshot", body, 1010, seq=2)

    test = case("heartbeat_does_not_renew_snapshot")
    test.send("snapshot", snapshot(), 10)
    test.send("heartbeat", {}, 100)
    test.advance(109)
    test.advance(110)
    test.advance(1099)
    test.advance(1100)
    test.send("heartbeat", {}, 1100)

    test = case("integer_precision_duplicate_conflict")
    test.send("snapshot", snapshot(revision=9007199254740992), 1)
    test.send("snapshot", snapshot(revision=9007199254740993), 2, seq=2)
    test.send("snapshot", snapshot(revision=9007199254740992), 3, seq=2)
    request = test.send("snapshot", snapshot(revision=1, status="unknown", validity=0), 4)
    raw = json.dumps(request, separators=(",", ":")).replace('"validForMs":0', '"validForMs":-0')
    test.send("snapshot", snapshot(revision=1, status="unknown", validity=0), 5, seq=3, raw=raw)

    test = case("release_and_reconnect")
    test.send("snapshot", snapshot(), 10)
    test.send("release", {}, 20)
    test.send("heartbeat", {}, 30)
    test.send("snapshot", snapshot(revision=2), 40)
    test.disconnect()
    test.open("4" * 32, 50)
    test.send("snapshot", snapshot(), 50, channel=CHANNEL)
    test.send("hello", {"protocol": 1}, 50)
    test.send("snapshot", snapshot(), 51)

    test = case("expiry_requires_reconnect")
    test.advance(1000)
    test.send("hello", {"protocol": 1}, 1000, seq=1)
    test.send("heartbeat", {}, 1000)
    test.open("4" * 32, 1001)
    test.send("hello", {"protocol": 1}, 1001)

    test = case("business_errors_consume_sequence")
    test.send("snapshot", snapshot(), 10)
    test.send("heartbeat", {"extra": 1}, 20)
    test.send("release", {"extra": 1}, 20)
    test.send("snapshot", snapshot(), 20)
    test.send("snapshot", snapshot(), 30, seq=5)
    test.advance(110)
    test.advance(1010)

    invalid = []
    for key, value in (("sourceLiveness", "verified"), ("revision", 0), ("revision", True),
                       ("revision", 0x100000000), ("validForMs", -1), ("validForMs", True),
                       ("sessions", {}), ("overallStatus", "idle")):
        body = snapshot(revision=2)
        body[key] = value
        invalid.append((key + "_" + str(len(invalid)), body))
    for key, value in (("id", "s0"), ("id", "s01"), ("id", ""), ("id", "s1x"),
                       ("observed", "bad"), ("display", "bad"), ("host", "bad"), ("host", "exited")):
        body = snapshot(revision=2)
        body["sessions"][0][key] = value
        invalid.append((key + "_" + str(len(invalid)), body))
    body = snapshot(revision=2)
    body["sessions"].append(copy.deepcopy(body["sessions"][0]))
    invalid.append(("duplicate_alias", body))
    body = snapshot(revision=2)
    body["sessions"] = [dict(id=f"s{i + 1}", observed="working", display="working", host="running") for i in range(17)]
    invalid.append(("capacity", body))
    body = snapshot(revision=2)
    body["sessions"][0]["extra"] = "unexpected"
    invalid.append(("extra_session_field", body))
    invalid.append(("expired_nonunknown", snapshot(revision=2, validity=0)))
    for name, body in invalid:
        test = case("invalid_snapshot_" + name)
        test.send("snapshot", snapshot(validity=500), 10)
        test.send("snapshot", body, 20)
        test.send("snapshot", body, 30, seq=3)
        test.send("snapshot", snapshot(revision=2, status="idle"), 40)

    test = case("aggregation_and_empty")
    for index, status in enumerate(("offline", "idle", "unknown", "working", "waitingApproval"), 1):
        body = snapshot(revision=index, status=status)
        body["sessions"].append(dict(id="s2", observed="offline", display="offline", host="running"))
        test.send("snapshot", body, index)
    test.send("snapshot", dict(revision=6, validForMs=0, sourceLiveness="unverified", overallStatus="unknown", sessions=[]), 6)
    test.send("snapshot", snapshot(revision=0xFFFFFFFF, validity=0xFFFFFFFF), 7)
    test.send("snapshot", snapshot(revision=1), 8)

    test = case("sustained_seven_session_sorted_snapshots")
    for revision in range(1, 201):
        body = dict(revision=revision, validForMs=0, sourceLiveness="unverified", overallStatus="unknown",
                    sessions=[dict(id=f"s{i + 1}", observed=("working", "idle", "offline")[i % 3],
                                   display="unknown", host="unverified") for i in range(7)])
        request = envelope(BOOT, CHANNEL, SESSION, revision + 1, "snapshot", body)
        test.send("snapshot", body, revision, raw=json.dumps(request, sort_keys=True, separators=(",", ":")))

    path.write_text("\n".join(json.dumps(dict(name=s.name, steps=s.steps), separators=(",", ":"))
                              for s in scenarios) + "\n", encoding="utf-8")
    return len(scenarios)
