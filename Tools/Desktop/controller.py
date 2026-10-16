import copy
import os
from pathlib import Path
import sys
import time

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS / "DeviceBridge"))
from bridge import Bridge, Health
from state_view import LifecycleReader
from protocol import Limits, ProtocolError, validate_light
from simulator import DeviceSimulator, HostSession
from usb_client import UsbClient

MAX_JSON_BYTES = 4096
MAX_SESSIONS = 16
INTERVAL_SECONDS = 1
TIMEOUT_SECONDS = 2
RETRIES = 1
MAX_AGE_SECONDS = 30
DELIVERY_RESERVE_SECONDS = 8


def default_monitor_root():
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OmiPet/codex-monitor-probe-v2"


def monitor_reader(root, bindings):
    return LifecycleReader(root, bindings, max_age_seconds=MAX_AGE_SECONDS)


class ControlSession:
    def __init__(self, client, reader, reopen=lambda: None):
        self.client = client
        self.reader = reader
        self.reopen = reopen
        self.operations = set()
        self.monitor_requested = False
        self.bridge = None
        self.state = None
        self.last_light = None
        self.monitor_lights = False
        self.monitor_green_off = False

    def connect(self, *, local=True):
        self.reopen()
        welcome = self.client.connect()
        self.operations = set(welcome["body"]["operations"])
        self.monitor_lights = self.client.host.monitor_lights
        self.monitor_green_off = self.client.host.monitor_green_off
        self.state = self._accept(self.client.request("release" if local and self.monitor_green_off else "heartbeat", {}))
        return welcome

    def _accept(self, reply):
        if not reply["ok"]:
            raise ProtocolError(reply["code"])
        self.state = copy.deepcopy(reply["state"])
        return self.state

    def local(self):
        if self.client.host is None or self.client.host.pending is not None or self.client.host.invalidated:
            self.connect(local=False)
        reply = self.client.release()
        if reply is None:
            raise ProtocolError("discovery-required")
        self._accept(reply)
        if self.state["mode"] != "local" or self.state["leaseActive"]:
            raise ProtocolError("local-mode-unconfirmed")
        self.monitor_requested = False
        self.bridge = None

    def monitor(self):
        if not self.monitor_green_off:
            raise ProtocolError("monitor-policy-not-supported")
        if not self.monitor_lights:
            raise ProtocolError("monitor-lights-not-supported")
        if not self.client.host or not self.client.host.freshness_challenge:
            raise ProtocolError("freshness-challenge-required")
        self.connect(local=False)
        if hasattr(self.reader, "reset"):
            self.reader.reset()
        self.bridge = Bridge(self.client, self.reader, interval_seconds=INTERVAL_SECONDS,
                             reopen=self.reopen,
                             allow_fresh_display=True,
                             delivery_reserve_seconds=DELIVERY_RESERVE_SECONDS)
        self.monitor_requested = True
        self.tick()

    def light(self, setting):
        if self.monitor_requested or (self.state and self.state["mode"] == "monitor"):
            raise ProtocolError("monitor-mode-active")
        if "light" not in self.operations:
            raise ProtocolError("light-command-not-supported")
        validate_light(setting)
        self._accept(self.client.request("light", setting))
        self.last_light = copy.deepcopy(setting)

    def tick(self):
        if self.monitor_requested:
            if not self.bridge.step():
                self.state = None
                raise ProtocolError("monitor-update-failed")
            self.state = copy.deepcopy(self.bridge.report["lastDeviceState"])
            if self.state.get("monitorOutput") == "local":
                self.local()
        else:
            if self.client.host is None or self.client.host.invalidated or self.client.host.pending is not None:
                self.connect()
            self._accept(self.client.request("heartbeat", {}))

    def close(self):
        if self.monitor_requested and self.bridge is not None:
            self.bridge.release()
            if not self.bridge.report["releaseConfirmed"]:
                raise ProtocolError("monitor-disconnect-unconfirmed")
            self.state = copy.deepcopy(self.bridge.report["lastDeviceState"])
            self.monitor_requested = False
            self.bridge = None
        else:
            self.local()

    def snapshot(self):
        return dict(state=copy.deepcopy(self.state), monitorRequested=self.monitor_requested,
                    monitorLights=self.monitor_lights,
                    monitorGreenOff=self.monitor_green_off,
                    operations=sorted(self.operations), lastLight=copy.deepcopy(self.last_light),
                    diagnostics=copy.deepcopy(self.client.diagnostics))


class SimulatedClient:
    def __init__(self):
        self.limits = Limits(MAX_JSON_BYTES, MAX_SESSIONS)
        self.device = DeviceSimulator(self.limits, lease_ms=5000,
                                      freshness_challenge=True, desktop_control=True, monitor_lights=True, monitor_green_off=True)
        self.host = None
        self.round_trips = []
        self.diagnostics = dict(replyTimeouts=0, decodeIssues=0, maxRoundTripMs=0)
        self.started = time.monotonic()

    def now(self):
        return int((time.monotonic() - self.started) * 1000)

    def connect(self):
        welcome = self.device.open(self.now())
        self.host = HostSession(welcome, self.limits)
        self.request("hello", {"protocol": 1})
        return welcome

    def request(self, kind, body):
        request = self.host.prepare(kind, body)
        return self.host.accept(self.device.receive(request, self.now()))

    def release(self):
        return self.request("release", {}) if self.host is not None else None


def demo_reader():
    from datetime import datetime, timezone
    status = ("working", "waitingApproval", "idle")[int(time.monotonic() // 8) % 3]
    return dict(sourceState="readable", bindingState="event-correlated", maxAgeSeconds=30,
                evaluatedAtUtc=datetime.now(timezone.utc).isoformat(),
                evaluatedAtMonotonicNs=str(time.monotonic_ns()), sessions=[dict(
                    sessionId="demo", lastObservedStatus=status, displayStatus=status,
                    hostProcessState="running", observationAgeSeconds=0)])


def _open_control(stream, root, bindings, reopen, health=None):
    client = UsbClient(stream, Limits(MAX_JSON_BYTES, MAX_SESSIONS),
                       timeout_seconds=TIMEOUT_SECONDS, retries=RETRIES, on_bytes=health.feed if health else None)
    try:
        session = ControlSession(client, monitor_reader(root, bindings), reopen)
        session.connect()
        return session, stream, health
    except Exception:
        stream.close()
        raise


def open_usb(port, root, bindings):
    import serial
    stream = serial.Serial()
    stream.port, stream.baudrate = port, 115200
    stream.dtr = stream.rts = False
    stream.timeout = INTERVAL_SECONDS
    stream.write_timeout = TIMEOUT_SECONDS
    def reopen():
        if stream.is_open:
            stream.close()
        stream.open()
    return _open_control(stream, root, bindings, reopen, Health(MAX_JSON_BYTES + 8))


def open_wifi(address, root, bindings):
    from wss_stream import WssStream
    stream = WssStream(address, timeout=TIMEOUT_SECONDS)
    return _open_control(stream, root, bindings, stream.open)
