import ctypes
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import configparser
import subprocess
from unittest.mock import Mock, patch
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pake import Pake
from pairing_auth import derive_daily_key
from wireless_pairing import PairingSocket, PairingStore, BoundedFrames, b64, unb64, confirmation, transcript, pair_device, inspect_pairing, RepairRequired, verify_device, relocate_device, endpoint


class Device:
    def __init__(self):
        self.pin = hashlib.sha256(b"synthetic certificate").digest()
        self.code = "123456"
        self.key = None
        self.drop_commit = False
        self.fail_storage = False
        self.observed_pin = self.pin
        self.repair_enabled = True

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
                if kind in ("pair1", "repair1"):
                    if kind == "repair1" and not device.repair_enabled:
                        raise ConnectionError("old firmware")
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

    def test_inspection_distinguishes_new_local_other_computer_and_changed_identity_without_writes(self):
        inspect = lambda store: inspect_pairing(self.address, store=store, socket_factory=self.device.connect)
        self.assertEqual(inspect(self.store), 'new')
        self.assertEqual(self.store.devices(), [])
        self.assertIsNone(self.device.key)
        self.pair()
        original = self.store.load(self.address)
        self.assertEqual(inspect(self.store), 'paired-here')
        other = PairingStore(Path(self.directory.name) / 'other.sqlite3')
        self.assertEqual(inspect(other), 'repair-required')
        with self.assertRaises(RepairRequired):
            pair_device(self.address, '123456', store=other, socket_factory=self.device.connect)
        self.assertEqual(other.devices(), [])
        self.device.observed_pin = hashlib.sha256(b'different synthetic device').digest()
        self.assertEqual(inspect(self.store), 'identity-changed')
        self.assertEqual(self.store.load(self.address), original)

    def test_inspection_preserves_pending_confirmation(self):
        self.device.drop_commit = True
        with self.assertRaises(TimeoutError): self.pair()
        pending = self.store.load(self.address)
        self.assertEqual(inspect_pairing(self.address, store=self.store, socket_factory=self.device.connect), 'pending')
        self.assertEqual(self.store.load(self.address), pending)

    def test_paired_and_authenticated_after_new_store_instance(self):
        self.pair()
        self.assertTrue(self.store.load(self.address)[2])
        verify_device(self.address, store=PairingStore(self.store.path), socket_factory=self.device.connect)

    def repair(self, address=None, code="123456", store=None):
        pair_device(address or self.address, code, store=store or self.store,
                    socket_factory=self.device.connect, replace=True)

    def test_repair_at_same_and_new_address_replaces_key_only_after_success(self):
        self.pair()
        old_key, pin, _ = self.store.load(self.address)
        self.repair()
        self.assertNotEqual(old_key, self.store.load(self.address)[0])
        self.assertEqual(pin, self.store.load(self.address)[1])
        self.repair("192.0.2.42")
        self.assertIsNone(self.store.load(self.address))
        verify_device("192.0.2.42", store=PairingStore(self.store.path), socket_factory=self.device.connect)

    def test_new_computer_can_repair_without_original_credentials(self):
        self.pair()
        original = self.store.load(self.address)
        other = PairingStore(Path(self.directory.name) / "other.sqlite3")
        self.repair(store=other)
        self.assertTrue(other.load(self.address)[2])
        with self.assertRaises(ValueError):
            verify_device(self.address, store=self.store, socket_factory=self.device.connect)
        self.assertEqual(self.store.load(self.address), original)

    def test_wrong_repair_code_and_old_firmware_keep_original_pairing(self):
        self.pair()
        original = self.store.load(self.address)
        with self.assertRaises(ValueError): self.repair(code="654321")
        self.device.repair_enabled = False
        with self.assertRaises(ConnectionError): self.repair()
        self.assertEqual(self.store.load(self.address), original)
        self.assertEqual(self.device.key, original[0])
        self.assertEqual(len(self.store.devices()), 1)

    def test_repair_lost_ack_recovers_persisted_candidate_after_restart(self):
        self.pair()
        original = self.store.load(self.address)
        self.device.drop_commit = True
        with self.assertRaises(TimeoutError): self.repair()
        self.assertEqual(self.store.load(self.address), original)
        self.assertTrue(self.store.devices()[0]["pendingRepair"])
        verify_device(self.address, store=PairingStore(self.store.path), socket_factory=self.device.connect)
        self.assertEqual(self.store.load(self.address)[0], self.device.key)
        self.assertFalse(self.store.devices()[0]["pendingRepair"])

    def test_failed_repair_storage_retains_old_key_and_can_retry(self):
        self.pair()
        original = self.store.load(self.address)
        self.device.fail_storage = True
        with self.assertRaises(OSError): self.repair()
        self.assertEqual(self.store.load(self.address), original)
        verify_device(self.address, store=self.store, socket_factory=self.device.connect)
        self.assertEqual(self.store.load(self.address), original)
        self.device.fail_storage = False
        self.repair()
        self.assertFalse(self.store.devices()[0]["pendingRepair"])

    def test_repair_after_factory_reset_requires_explicit_action_and_valid_new_code(self):
        self.pair()
        self.device.key = None
        self.device.pin = self.device.observed_pin = b"p" * 32
        with self.assertRaises(ValueError): self.pair()
        self.repair()
        self.assertEqual(self.store.load(self.address)[1], b"p" * 32)

    def test_repair_confirm_rejects_local_concurrent_change(self):
        self.pair()
        self.store.stage_repair(self.address, b"n" * 32, self.device.pin)
        with self.store.open() as db:
            db.execute("DELETE FROM devices WHERE address=?", (endpoint(self.address),))
        with self.assertRaises(ValueError):
            self.store.confirm(self.address, b"n" * 32, self.device.pin)
        self.assertEqual(self.store.authentication_records(self.address)[0][0], b"n" * 32)

    def test_repair_candidate_storage_failure_never_commits_device(self):
        self.pair()
        original = self.device.key
        with patch.object(self.store, "stage_repair", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): self.repair()
        self.assertEqual(self.device.key, original)
        self.assertEqual(self.store.load(self.address)[0], original)

    def test_repair_new_computer_new_address_lost_ack_recovers_without_code(self):
        self.pair()
        other = PairingStore(Path(self.directory.name) / "other.sqlite3")
        self.device.drop_commit = True
        with self.assertRaises(TimeoutError): self.repair("192.0.2.42", store=other)
        self.assertIsNone(other.load("192.0.2.42"))
        self.assertFalse(other.devices()[0]["confirmed"])
        verify_device("192.0.2.42", store=PairingStore(other.path), socket_factory=self.device.connect)
        self.assertTrue(other.load("192.0.2.42")[2])

    def test_repair_preserves_other_devices_even_if_their_local_record_is_damaged(self):
        self.pair()
        self.store.prepare("192.0.2.10", b"o" * 32, b"p" * 32)
        with self.store.open() as db:
            db.execute("INSERT INTO devices VALUES (?, ?, 1)", (endpoint("192.0.2.11"), b"damaged"))
        self.repair()
        self.assertEqual(len(self.store.devices()), 3)
        self.assertEqual(self.store.load("192.0.2.10")[0], b"o" * 32)

    def test_explicit_repair_recovers_corrupt_local_credential_without_erasing_other_data(self):
        self.pair()
        with self.store.open() as db:
            db.execute("UPDATE devices SET record=? WHERE address=?", (b"damaged", endpoint(self.address)))
        self.repair()
        verify_device(self.address, store=self.store, socket_factory=self.device.connect)
        self.assertTrue(self.store.load(self.address)[2])

    def test_network_change_preserves_identity_and_survives_restart(self):
        self.pair()
        original = self.store.load(self.address)
        new = "192.0.2.42"
        relocate_device(self.address, new, store=self.store, socket_factory=self.device.connect)
        self.assertIsNone(self.store.load(self.address))
        self.assertEqual(PairingStore(self.store.path).load(new), original)
        verify_device(new, store=self.store, socket_factory=self.device.connect)
        relocate_device(new, self.address, store=self.store, socket_factory=self.device.connect)
        self.assertEqual(self.store.load(self.address), original)

    def test_migration_failures_leave_original_pairing_intact(self):
        self.pair()
        original = self.store.load(self.address)
        for failure in ("pin", "key", "offline", "cancel"):
            self.device.observed_pin = b"x" * 32 if failure == "pin" else self.device.pin
            self.device.key = b"x" * 32 if failure == "key" else original[0]
            factory = Mock(side_effect=OSError("offline")) if failure == "offline" else self.device.connect
            stop = threading.Event()
            if failure == "cancel": stop.set()
            with self.assertRaises((ValueError, OSError)):
                relocate_device(self.address, "192.0.2.42", store=self.store, socket_factory=factory, stop=stop)
            self.assertEqual(self.store.load(self.address), original)
            self.assertIsNone(self.store.load("192.0.2.42"))

    def test_pending_confirmation_recovers_at_new_address(self):
        self.device.drop_commit = True
        with self.assertRaises(TimeoutError): self.pair()
        original = self.store.load(self.address)
        relocate_device(self.address, "192.0.2.42", store=self.store, socket_factory=self.device.connect)
        self.assertEqual(self.store.load("192.0.2.42"), (*original[:2], True))

    def test_migration_rejects_concurrent_change_and_other_saved_identity(self):
        self.pair()
        original = self.store.load(self.address)
        self.store.prepare("192.0.2.42", b"x" * 32, b"p" * 32)
        with self.assertRaises(ValueError):
            relocate_device(self.address, "192.0.2.42", store=self.store, socket_factory=self.device.connect)
        self.assertEqual(self.store.load(self.address), original)
        with self.assertRaises(ValueError):
            self.store.relocate(self.address, "192.0.2.43", (b"x" * 32, original[1], True))
        self.assertEqual(self.store.load(self.address), original)
        self.assertIsNone(self.store.load("192.0.2.43"))

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
