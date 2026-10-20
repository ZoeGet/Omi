import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import websocket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import Limits, ProtocolError
from simulator import DeviceSimulator
from usb_client import UsbClient
from wss_stream import WssStream
from wireless_pairing import PairingSocket


class WssStreamTests(unittest.TestCase):
    def setUp(self):
        self.device = DeviceSimulator(Limits(4096, 16), lease_ms=5000, desktop_control=True)
        self.frames, self.sent = [], []
        self.drop = False
        self.wire = Mock()
        def send(text):
            self.sent.append(text)
            reply = self.device.open(0) if text == '?' else self.device.receive(json.loads(text), 1)
            if self.drop:
                self.drop = False
                self.frames.append(websocket.WebSocketTimeoutException())
            else:
                self.frames.append(SimpleNamespace(opcode=1, data=json.dumps(reply).encode()))
        def receive():
            if not self.frames:
                raise websocket.WebSocketTimeoutException()
            frame = self.frames.pop(0)
            if isinstance(frame, Exception): raise frame
            return frame
        self.wire.ws.send.side_effect = send
        self.wire.ws.recv_frame.side_effect = receive
        self.wire.receive_text.side_effect = lambda timeout: PairingSocket.receive_text(self.wire, timeout)
        self.store = Mock()
        self.store.load.return_value = (b'k' * 32, b'p' * 32, True)
        self.factory = Mock(return_value=self.wire)
        self.stream = WssStream('192.0.2.1', timeout=.01, store=self.store, socket_factory=self.factory)
        self.client = UsbClient(self.stream, Limits(4096, 16), timeout_seconds=.02, retries=1)

    def tearDown(self):
        self.stream.close()

    def test_authenticated_raw_json_reuses_retry_without_reapplying_light(self):
        self.stream.open()
        self.factory.assert_called_once_with('wss://192.0.2.1:8443/pair', b'p' * 32)
        self.wire.authenticate.assert_called_once_with(b'k' * 32)
        self.client.connect()
        self.drop = True
        reply = self.client.request('light', dict(effect='solid', red=255, green=0, blue=0, brightness=16))
        self.assertTrue(reply['ok'])
        self.assertTrue(reply['duplicate'])
        self.assertEqual(self.device.applied_lights, 1)
        self.assertEqual(self.sent[-1], self.sent[-2])
        self.assertTrue(all('@OMI' not in text for text in self.sent))

    def test_bad_authentication_closes_before_any_control_message(self):
        self.wire.authenticate.side_effect = ValueError('private credential')
        with self.assertRaisesRegex(ProtocolError, '^wireless-authentication-failed$'):
            self.stream.open()
        self.assertFalse(self.stream.is_open)
        self.wire.ws.send.assert_not_called()
        self.wire.close.assert_called_once()

    def test_unreachable_network_is_retryable_but_identity_failure_is_not(self):
        for error, code in [(OSError('offline'), 'wireless-unavailable'),
                            (ValueError('identity changed'), 'wireless-authentication-failed')]:
            self.factory.side_effect = error
            with self.assertRaisesRegex(ProtocolError, '^' + code + '$'):
                self.stream.open()
            self.assertFalse(self.stream.is_open)

    def test_reconnect_reauthenticates_and_discards_old_buffer(self):
        self.stream.open()
        self.stream.buffer.extend(b'old response')
        self.stream.open()
        self.assertEqual(self.stream.in_waiting, 0)
        self.assertEqual(self.wire.authenticate.call_count, 2)

    def test_invalid_or_closed_socket_cannot_become_a_protocol_reply(self):
        self.stream.open()
        self.frames.append(SimpleNamespace(opcode=1, data=b'{"v":1,"v":1}'))
        with self.assertRaisesRegex(ProtocolError, 'wireless-receive-failed'):
            self.stream.read(1)
        self.assertFalse(self.stream.is_open)

    def test_ping_pong_and_deadline_are_shared_without_extending_read(self):
        self.stream.open()
        self.frames.extend([SimpleNamespace(opcode=9, data=b'ping'), SimpleNamespace(opcode=10, data=b'pong')])
        self.client.connect()
        self.wire.ws.pong.assert_called_once_with(b'ping')
        from unittest.mock import patch
        self.frames.append(SimpleNamespace(opcode=9, data=b'ping'))
        with patch('wireless_pairing.time.monotonic', side_effect=[0, 0, self.stream.timeout]):
            self.assertEqual(self.stream.read(1), b'')
        self.assertTrue(self.stream.is_open)

    def test_close_frame_fails_closed(self):
        self.stream.open()
        self.frames.append(SimpleNamespace(opcode=8, data=b''))
        with self.assertRaisesRegex(ProtocolError, 'wireless-receive-failed'):
            self.stream.read(1)
        self.assertFalse(self.stream.is_open)


if __name__ == '__main__':
    unittest.main()
