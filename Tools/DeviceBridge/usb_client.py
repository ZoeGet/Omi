import time
import math

from protocol import ProtocolError, SerialDecoder, serial_frame
from simulator import HostSession


DISCOVERY = b"\n@OMI ?\n"


class UsbClient:
    def __init__(self, stream, limits, *, timeout_seconds, retries, clock=time.monotonic, on_bytes=None):
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or type(retries) is not int or retries < 0:
            raise ValueError("Explicit positive timeout and nonnegative retry count required")
        self.stream, self.limits = stream, limits
        self.timeout, self.retries = timeout_seconds, retries
        self.clock, self.on_bytes = clock, on_bytes
        self.decoder = SerialDecoder(limits)
        self.host = None
        self.messages = []
        self.round_trips = []
        self.diagnostics = dict(replyTimeouts=0, decodedMessages=0, decodeIssues=0,
                                unmatchedMessages=0, maxRoundTripMs=0, lastTimeout=None)

    def _write(self, data):
        if self.stream.write(data) != len(data):
            self.host = None
            raise ProtocolError("partial-write-reconnect-required")

    def _receive(self, deadline, predicate):
        while self.clock() < deadline:
            while self.messages:
                message = self.messages.pop(0)
                if predicate(message):
                    return message
                self.diagnostics["unmatchedMessages"] += 1
            waiting = getattr(self.stream, "in_waiting", 4096)
            data = self.stream.read(min(4096, max(1, waiting)))
            if data:
                if self.on_bytes:
                    self.on_bytes(data)
                messages, issues = self.decoder.feed(data)
                self.diagnostics["decodedMessages"] += len(messages)
                self.diagnostics["decodeIssues"] += len(issues)
                self.messages.extend(messages)
        raise TimeoutError("USB reply timeout")

    def _latest_buffered_welcome(self, welcome):
        remaining = 4096
        while remaining > 0:
            waiting = getattr(self.stream, "in_waiting", 0)
            if waiting <= 0:
                break
            data = self.stream.read(min(remaining, waiting))
            if not data:
                break
            if self.on_bytes:
                self.on_bytes(data)
            messages, issues = self.decoder.feed(data)
            self.diagnostics["decodedMessages"] += len(messages)
            self.diagnostics["decodeIssues"] += len(issues)
            self.messages.extend(messages)
            remaining -= len(data)
        for item in self.messages:
            if item["type"] == "welcome":
                welcome = item
            else:
                self.diagnostics["unmatchedMessages"] += 1
        self.messages.clear()
        return welcome

    def connect(self):
        self.host = None
        for attempt in range(self.retries + 1):
            self.decoder = SerialDecoder(self.limits)
            self.messages.clear()
            self._write(DISCOVERY)
            try:
                welcome = self._receive(self.clock() + self.timeout, lambda item: item.get("type") == "welcome")
                welcome = self._latest_buffered_welcome(welcome)
                self.host = HostSession(welcome, self.limits)
                reply = self.request("hello", {"protocol": 1})
                if not reply["ok"]:
                    raise ProtocolError("hello-rejected")
                return welcome
            except (TimeoutError, ProtocolError):
                self.host = None
                if attempt == self.retries:
                    raise

    def request(self, kind, body):
        if self.host is None:
            raise ProtocolError("discovery-required")
        message = self.host.prepare(kind, body)
        return self._exchange(message)

    def retry_pending(self):
        if self.host is None:
            raise ProtocolError("discovery-required")
        return self._exchange(self.host.retry())

    def _exchange(self, message):
        for attempt in range(self.retries + 1):
            started = self.clock()
            self._write(b"\n" + serial_frame(message, self.host.limits))
            try:
                def matches(item):
                    if item["type"] == "welcome" and any(item[key] != message[key] for key in ("boot", "channel")):
                        HostSession(item, self.limits)
                        self.host = None
                        raise ProtocolError("device-reopened-reconnect-required")
                    if (item["type"] == "ack" and item["session"] == message["session"]
                            and item["seq"] == message["seq"] and item["boot"] == message["boot"]
                            and item["channel"] != message["channel"]
                            and item["body"].get("code") == "wrong-connection"):
                        self.host = None
                        raise ProtocolError("device-reopened-reconnect-required")
                    return item["type"] == "ack" and all(item[key] == message[key]
                        for key in ("boot", "channel", "session", "seq"))
                reply = self._receive(started + self.timeout, matches)
                result = self.host.accept(reply)
                elapsed = (self.clock() - started) * 1000
                self.diagnostics["maxRoundTripMs"] = max(self.diagnostics["maxRoundTripMs"], elapsed)
                self.round_trips.append(dict(command=message["type"], sequence=message["seq"],
                                             retry=attempt, milliseconds=elapsed))
                return result
            except TimeoutError:
                self.diagnostics["replyTimeouts"] += 1
                self.diagnostics["lastTimeout"] = dict(command=message["type"], sequence=message["seq"],
                    retry=attempt, elapsedMs=(self.clock() - started) * 1000)
                if attempt == self.retries:
                    raise

    def release(self):
        if self.host is None:
            return None
        return self.request("release", {})

    def observe(self, seconds):
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            data = self.stream.read(4096)
            if data and self.on_bytes:
                self.on_bytes(data)
