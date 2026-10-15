import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import Limits, ProtocolError, serial_frame
from simulator import DeviceSimulator
from usb_client import DISCOVERY, UsbClient


class Stream:
    def __init__(self, *, legacy=False, lose_ack=False):
        self.now = 0
        self.legacy = legacy
        self.lose_ack = lose_ack
        self.writes = []
        self.buffer = bytearray()
        self.device = DeviceSimulator(Limits(4096, 16), lease_ms=1000)
        self.short = False

    def write(self, data):
        self.writes.append(data)
        if self.short:
            return len(data) // 2
        if self.legacy:
            self.buffer.extend(b"[SYS] alive mic=ok\n")
        elif data == DISCOVERY:
            self.buffer.extend(serial_frame(self.device.open(int(self.now * 1000)), self.device.limits))
        else:
            request = json.loads(data.strip()[5:])
            reply = self.device.receive(request, int(self.now * 1000))
            if self.lose_ack:
                self.lose_ack = False
            else:
                self.buffer.extend(b"[MIC] log\n" + serial_frame(reply, self.device.limits))
        return len(data)

    def read(self, count):
        self.now += 0.001
        data = self.buffer[:min(7, count)]
        del self.buffer[:len(data)]
        return bytes(data)

    @property
    def in_waiting(self):
        return len(self.buffer)


class ResetStream(Stream):
    reset_on_request = False

    def write(self, data):
        if self.reset_on_request and data != DISCOVERY:
            self.reset_on_request = False
            self.writes.append(data)
            self.buffer.extend(serial_frame(self.device.open(int(self.now * 1000)), self.device.limits))
            return len(data)
        return super().write(data)


class BurstWelcomeStream(Stream):
    def write(self, data):
        if data == DISCOVERY:
            self.writes.append(data)
            stale = self.device.open(int(self.now * 1000))
            current = self.device.open(int(self.now * 1000))
            self.buffer.extend(serial_frame(stale, self.device.limits))
            self.buffer.extend(serial_frame(current, self.device.limits))
            return len(data)
        return super().write(data)


class WrongChannelAckStream(Stream):
    def write(self, data):
        if data != DISCOVERY and self.device.channel is not None:
            self.writes.append(data)
            request = json.loads(data.strip()[5:])
            self.device.open(int(self.now * 1000))
            self.buffer.extend(serial_frame(self.device.reply(request, False, "wrong-connection"), self.device.limits))
            return len(data)
        return super().write(data)


class UsbClientTests(unittest.TestCase):
    def client(self, stream, retries=1):
        return UsbClient(stream, Limits(4096, 16), timeout_seconds=0.2, retries=retries, clock=lambda: stream.now)

    def test_legacy_only_receives_safe_probe(self):
        stream = Stream(legacy=True)
        with self.assertRaises(TimeoutError):
            self.client(stream).connect()
        self.assertTrue(all(data == DISCOVERY and b"w" not in data for data in stream.writes))

    def test_chunked_logs_handshake_and_release(self):
        stream = Stream()
        client = self.client(stream)
        client.connect()
        self.assertTrue(client.request("heartbeat", {})["ok"])
        self.assertEqual(client.release()["state"]["mode"], "local")
        self.assertIsNone(stream.device.deadline)

    def test_lost_ack_reuses_sequence(self):
        stream = Stream(lose_ack=True)
        client = self.client(stream)
        client.connect()
        self.assertEqual(stream.writes[1], stream.writes[2])
        self.assertEqual(stream.device.last_seq, 1)
        self.assertEqual(client.diagnostics["replyTimeouts"], 1)
        self.assertEqual(client.diagnostics["lastTimeout"]["command"], "hello")

    def test_no_request_before_discovery(self):
        stream = Stream()
        with self.assertRaises(ProtocolError):
            self.client(stream).request("heartbeat", {})
        self.assertEqual(stream.writes, [])

    def test_partial_write_requires_reconnect(self):
        stream = Stream()
        client = self.client(stream)
        client.connect()
        stream.short = True
        with self.assertRaises(ProtocolError):
            client.request("heartbeat", {})
        self.assertIsNone(client.host)

    def test_stale_welcome_recovery(self):
        stream = Stream()
        stale = stream.device.open(0)
        stream.buffer.extend(serial_frame(stale, stream.device.limits))
        self.client(stream).connect()
        self.assertTrue(stream.device.session)

    def test_burst_welcomes_use_current_channel(self):
        stream = BurstWelcomeStream()
        client = self.client(stream, retries=0)
        welcome = client.connect()
        self.assertEqual(welcome["channel"], stream.device.channel)
        self.assertEqual(stream.writes.count(DISCOVERY), 1)
        self.assertTrue(stream.device.session)

    def test_wrong_channel_ack_requests_reconnect_without_timeout(self):
        stream = WrongChannelAckStream()
        client = self.client(stream, retries=0)
        with self.assertRaisesRegex(ProtocolError, "device-reopened-reconnect-required"):
            client.connect()
        self.assertEqual(client.diagnostics["replyTimeouts"], 0)
        self.assertIsNone(client.host)

    def test_new_welcome_interrupts_ack_wait_without_timeout(self):
        stream = ResetStream()
        client = self.client(stream)
        client.connect()
        stream.reset_on_request = True
        with self.assertRaisesRegex(ProtocolError, "device-reopened-reconnect-required"):
            client.request("heartbeat", {})
        self.assertIsNone(client.host)
        self.assertEqual(client.diagnostics["replyTimeouts"], 0)
        client.connect()
        self.assertTrue(client.request("heartbeat", {})["ok"])


if __name__ == "__main__":
    unittest.main()
