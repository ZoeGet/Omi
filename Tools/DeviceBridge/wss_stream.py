import time
import websocket

from protocol import ProtocolError, PREFIX, Limits, decode
from wireless_pairing import PairingSocket, PairingStore, endpoint


class WssStream:
    """复用原有请求重试，仅在传输边界移除串口前缀 / Reuse request retries and remove serial framing only at the transport boundary."""
    def __init__(self, address, *, timeout, store=None, socket_factory=PairingSocket):
        self.address = endpoint(address)
        self.timeout = timeout
        self.store = store or PairingStore()
        self.factory = socket_factory
        self.wire = None
        self.buffer = bytearray()

    @property
    def is_open(self):
        return self.wire is not None

    @property
    def in_waiting(self):
        return len(self.buffer)

    def open(self):
        self.close()
        record = self.store.load(self.address)
        if not record:
            raise ProtocolError("wireless-pairing-required")
        try:
            self.wire = self.factory(self.address, record[1])
            self.wire.authenticate(record[0])
            self.store.confirm(self.address, record[0], record[1])
            self.wire.ws.settimeout(self.timeout)
        except Exception:
            self.close()
            raise ProtocolError("wireless-authentication-failed") from None

    def close(self):
        if self.wire:
            self.wire.close()
            self.wire = None
        self.buffer.clear()

    def write(self, data):
        if not self.wire:
            raise ProtocolError("wireless-disconnected")
        if not data.startswith(b"\n" + PREFIX) or not data.endswith(b"\n"):
            raise ProtocolError("invalid-transport-frame")
        raw = data[len(PREFIX) + 1:-1]
        if raw != b"?":
            decode(raw, Limits(4096, 16))
        try:
            self.wire.ws.settimeout(self.timeout)
            self.wire.ws.send(raw.decode("utf-8"))
        except Exception:
            self.close()
            raise ProtocolError("wireless-send-failed") from None
        return len(data)

    def read(self, size):
        if not self.wire:
            raise ProtocolError("wireless-disconnected")
        deadline = time.monotonic() + self.timeout
        while not self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return b""
            try:
                self.wire.ws.settimeout(remaining)
                frame = self.wire.ws.recv_frame()
                if frame.opcode == websocket.ABNF.OPCODE_PING:
                    self.wire.ws.pong(frame.data)
                    continue
                if frame.opcode == websocket.ABNF.OPCODE_PONG:
                    continue
                if frame.opcode != websocket.ABNF.OPCODE_TEXT:
                    raise ProtocolError("wireless-disconnected")
                decode(frame.data, Limits(4096, 16))
                self.buffer.extend(PREFIX + frame.data + b"\n")
            except websocket.WebSocketTimeoutException:
                return b""
            except Exception:
                self.close()
                raise ProtocolError("wireless-receive-failed") from None
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data
