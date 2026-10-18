from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wireless_discovery import find_device, network_candidates, certificate_matches
from wireless_pairing import PairingStore


class DiscoveryTests(unittest.TestCase):
    def test_only_direct_subnets_and_neighbors_are_candidates(self):
        inventory = [dict(IPAddress="192.0.2.2", PrefixLength=29, Neighbors=["203.0.113.1"]),
                     dict(IPAddress="127.0.0.1", PrefixLength=8),
                     dict(IPAddress="169.254.1.2", PrefixLength=16),
                     dict(IPAddress="10.0.1.2", PrefixLength=16, Neighbors=["10.0.2.9"])]
        addresses = network_candidates(inventory, "192.168.1.1:8443")
        self.assertEqual(len(addresses), 6)
        self.assertIn("wss://10.0.2.9:8443/pair", addresses)
        self.assertNotIn("wss://192.0.2.2:8443/pair", addresses)
        self.assertNotIn("wss://203.0.113.1:8443/pair", addresses)

    def test_discovery_requires_original_pin_then_authenticated_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PairingStore(Path(directory) / "pairing.sqlite3")
            store.prepare("192.0.2.1", b"k" * 32, b"p" * 32)
            relocate = Mock(return_value="wss://192.0.2.42:8443/pair")
            probe = Mock(side_effect=lambda address, pin, stop: address.endswith("42"))
            stop = threading.Event()
            found = find_device("192.0.2.1", store=store, stop=stop,
                                candidates=["192.0.2.41", "192.0.2.42"], probe=probe, relocate=relocate)
            self.assertEqual(found, "wss://192.0.2.42:8443/pair")
            relocate.assert_called_once_with("192.0.2.1", "192.0.2.42", store=store, stop=stop)
            for call in probe.call_args_list:
                self.assertEqual(call.args[1], b"p" * 32)
            relocate.reset_mock()
            with self.assertRaises(ValueError):
                find_device("192.0.2.1", store=store, stop=stop,
                            candidates=["192.0.2.41"], probe=lambda *_: False, relocate=relocate)
            relocate.assert_not_called()
            stop.set()
            with self.assertRaises(ValueError):
                find_device("192.0.2.1", store=store, stop=stop, candidates=[], relocate=relocate)
            self.assertIsNotNone(store.load("192.0.2.1"))

    def test_probe_rejects_wrong_certificate_and_closes_socket(self):
        with patch("wireless_discovery.socket.create_connection") as connection, patch("wireless_discovery.ssl.SSLContext") as context:
            tls = context.return_value.wrap_socket.return_value.__enter__.return_value
            tls.getpeercert.return_value = b"foreign certificate"
            self.assertFalse(certificate_matches("wss://192.0.2.1:8443/pair", b"p" * 32, threading.Event()))
            connection.return_value.__exit__.assert_called_once()
            context.return_value.wrap_socket.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
