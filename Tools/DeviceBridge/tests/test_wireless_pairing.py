import ctypes
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import configparser
import subprocess
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pake import Pake
from pairing_auth import derive_daily_key
from wireless_pairing import PairingSocket, PairingStore, BoundedFrames, b64, unb64, confirmation, transcript, pair_device, verify_device, endpoint


class Device:
    def __init__(self):
        self.pin = hashlib.sha256(b"synthetic certificate").digest()
        self.code = "123456"
        self.key = None
        self.drop_commit = False
        self.fail_storage = False
        self.observed_pin = self.pin

    def connect(self, address, pin=None):
        device = self
        class Wire:
            def __init__(self):
                if pin is not None and pin != device.observed_pin:
                    raise ValueError("pin mismatch")
                self.pin = device.observed_pin
                self.ready = dict(paired=device.key is not None)
                self.pake = None

            def send(self, kind, **body):
                if kind == "pair1":
                    self.pake = Pake(device.code, server=True)
                    self.c1 = unb64(body["data"])
                    self.s1 = self.pake.write()
                    self.pake.read(self.c1)
                    self.s2 = self.pake.write()
                    self.reply = dict(one=b64(self.s1), two=b64(self.s2))
                elif kind == "pair2":
                    c2 = unb64(body["data"])
                    self.pake.read(c2)
                    shared = self.pake.derive()
                    self.digest = transcript(device.pin, self.c1, self.s1, self.s2, c2)
                    if unb64(body["proof"]) != confirmation(shared, "H", self.digest, device.pin):
                        raise ValueError("proof mismatch")
                    self.key = derive_daily_key(shared, self.digest, device.pin)
                    self.reply = dict(proof=b64(confirmation(shared, "D", self.digest, device.pin)))
                elif kind == "commit":
                    if unb64(body["proof"]) != confirmation(self.key, "C", self.digest, device.pin):
                        raise ValueError("commit mismatch")
                    if device.fail_storage:
                        raise OSError("NVS failed")
                    device.key = self.key
                    self.reply = dict(proof=b64(confirmation(self.key, "S", self.digest, device.pin)))

            def receive(self, kind, fields):
                if kind == "committed" and device.drop_commit:
                    raise TimeoutError("lost ACK")
                return self.reply

            def authenticate(self, key):
                if key != device.key:
                    raise ValueError("auth failed")

            def __enter__(self):
                return self

            def __exit__(self, *_):
                if self.pake:
                    self.pake.__exit__()
        return Wire()


class WirelessPairingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = PairingStore(Path(self.directory.name) / "pairing.sqlite3")
        self.device = Device()
        self.address = "192.0.2.1"

    def tearDown(self):
        self.directory.cleanup()

    def pair(self, code="123456"):
        pair_device(self.address, code, store=self.store, socket_factory=self.device.connect)

    def test_paired_and_authenticated_after_new_store_instance(self):
        self.pair()
        self.assertTrue(self.store.load(self.address)[2])
        verify_device(self.address, store=PairingStore(self.store.path), socket_factory=self.device.connect)

    def test_wrong_code_and_mitm_pin_do_not_save(self):
        with self.assertRaises(ValueError): self.pair("654321")
        self.assertIsNone(self.store.load(self.address))
        self.device.observed_pin = b"x" * 32
        with self.assertRaises(ValueError): self.pair()
        self.assertIsNone(self.store.load(self.address))

    def test_lost_commit_ack_recovers_without_repairing(self):
        self.device.drop_commit = True
        with self.assertRaises(TimeoutError): self.pair()
        original = self.store.load(self.address)[0]
        self.assertFalse(self.store.load(self.address)[2])
        self.pair()
        self.assertEqual(original, self.store.load(self.address)[0])
        self.assertTrue(self.store.load(self.address)[2])

    def test_failed_device_storage_can_retry_pending_identity(self):
        self.device.fail_storage = True
        with self.assertRaises(OSError): self.pair()
        self.assertFalse(self.store.load(self.address)[2])
        self.device.fail_storage = False
        self.pair()
        self.assertTrue(self.store.load(self.address)[2])

    def test_confirmed_identity_cannot_be_replaced_or_downgraded(self):
        self.pair()
        record = self.store.load(self.address)
        self.device.key = None
        with self.assertRaises(ValueError): self.pair()
        with self.assertRaises(ValueError): self.store.prepare(self.address, b"x" * 32, self.device.pin)
        self.assertEqual(record, self.store.load(self.address))

    def test_pairing_roles_match_firmware_hmac_and_differ(self):
        with Pake("123456") as peer:
            function = peer.lib.omi_pairing_confirmation
            function.argtypes = [ctypes.c_char_p, ctypes.c_char, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
            proofs = set()
            for role in "HDCS":
                output = ctypes.create_string_buffer(32)
                self.assertEqual(function(b"k" * 32, role.encode(), b"d" * 32, b"p" * 32, output), 1)
                expected = confirmation(b"k" * 32, role, b"d" * 32, b"p" * 32)
                self.assertEqual(output.raw, expected)
                proofs.add(expected)
            self.assertEqual(len(proofs), 4)

    def test_native_rejects_out_of_order_malformed_and_reused_steps(self):
        with Pake("123456") as peer:
            with self.assertRaises(ValueError): peer.derive()
            with self.assertRaises(ValueError): peer.write()
        with Pake("123456") as peer:
            peer.write()
            with self.assertRaises(ValueError): peer.read(b"bad round")
            with self.assertRaises(ValueError): peer.write()

    def test_oversized_fragmented_and_binary_frames_rejected_before_payload(self):
        for header in (b"\x81\x7e\x10\x01", b"\x01\x01", b"\x82\x01"):
            data = bytearray(header)
            def receive(size):
                if not data: self.fail("payload read after invalid header")
                part = bytes(data[:size])
                del data[:size]
                return part
            with self.assertRaises(ValueError): BoundedFrames(receive, False).recv_frame()

    def test_endpoint_rejects_plaintext_userinfo_and_foreign_paths(self):
        for value in ("ws://192.0.2.1", "wss://user:pass@192.0.2.1", "wss://192.0.2.1/other", "wss://192.0.2.1/?code=123456"):
            with self.assertRaises(ValueError): endpoint(value)
        self.assertEqual(endpoint(self.address), "wss://192.0.2.1:8443/pair")

    def test_pairing_json_validation_remains_strict_after_shared_frame_read(self):
        wire = PairingSocket.__new__(PairingSocket)
        wire.receive_text = Mock(return_value=b'{"v":1,"type":"status","paired":false}')
        self.assertFalse(wire.receive('status', {'paired'})['paired'])
        wire.receive_text.assert_called_once_with(10)
        for raw in (b'{"v":1,"v":1,"type":"status","paired":false}',
                    b'{"v":true,"type":"status","paired":false}',
                    b'{"v":1,"type":"status","paired":false,"extra":0}'):
            wire.receive_text.return_value = raw
            with self.assertRaises(ValueError): wire.receive('status', {'paired'})

    def test_experiment_configuration_survives_disposable_build_directory(self):
        repository = Path(__file__).resolve().parents[3]
        output = Path(self.directory.name) / "wireless.ini"
        build = repository / "Firmware/.pio/config-generation-test"
        subprocess.run([sys.executable, str(Path(__file__).with_name("create_experiment_config.py")),
                        "--output", str(output), "--build-dir", str(build), "--max-json-bytes", "4096",
                        "--rx-bytes-per-loop", "64", "--max-json-depth", "8", "--wireless-pairing"], check=True, capture_output=True)
        config = configparser.ConfigParser()
        config.read(output, encoding="utf-8")
        settings = config["env:esp32-s3-devkitc-1"]
        self.assertFalse(Path(settings["board_build.esp-idf.sdkconfig_path"]).is_relative_to(build))
        defaults = output.with_suffix(".defaults").read_text(encoding="utf-8")
        for flag in ("HTTPD_WS_SUPPORT", "MBEDTLS_ECJPAKE_C", "MBEDTLS_HKDF_C"):
            self.assertIn(f"CONFIG_{flag}=y", defaults)


if __name__ == "__main__":
    unittest.main()
