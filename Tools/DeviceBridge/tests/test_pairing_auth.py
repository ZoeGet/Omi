import hashlib
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pairing_auth import derive_daily_key, make_proof, verify_certificate_pin, verify_proof


class PairingAuthTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(1, 33))
        self.device_nonce = bytes(range(32))
        self.host_nonce = bytes(range(32, 64))
        self.cert_pin = bytes(range(64, 96))

    def proof(self, role="host", key=None, device_nonce=None, host_nonce=None,
              cert_pin=None):
        return make_proof(
            self.key if key is None else key,
            role,
            self.device_nonce if device_nonce is None else device_nonce,
            self.host_nonce if host_nonce is None else host_nonce,
            self.cert_pin if cert_pin is None else cert_pin,
        )

    def test_proof_binds_role_both_nonces_and_cert_pin(self):
        proof = self.proof()
        self.assertTrue(verify_proof(self.key, "host", self.device_nonce,
                                     self.host_nonce, self.cert_pin, proof))
        self.assertFalse(verify_proof(self.key, "device", self.device_nonce,
                                      self.host_nonce, self.cert_pin, proof))
        self.assertNotEqual(proof, self.proof(device_nonce=b"x" * 32))
        self.assertNotEqual(proof, self.proof(host_nonce=b"y" * 32))
        self.assertNotEqual(proof, self.proof(cert_pin=b"z" * 32))
        self.assertNotEqual(proof, self.proof(key=b"k" * 32))

    def test_malformed_or_zero_credentials_rejected(self):
        with self.assertRaises(ValueError):
            self.proof(key=b"\x00" * 32)
        with self.assertRaises(ValueError):
            self.proof(host_nonce=b"short")
        with self.assertRaises(ValueError):
            self.proof(role="monitor")
        with self.assertRaises(ValueError):
            self.proof(cert_pin=b"\x00" * 32)
        self.assertFalse(verify_proof(self.key, "host", self.device_nonce,
                                      self.host_nonce, self.cert_pin, b"short"))

    def test_tls_peer_pin_requires_exact_certificate(self):
        certificate = b"DER certificate fixture"
        pin = hashlib.sha256(certificate).digest()
        self.assertTrue(verify_certificate_pin(certificate, pin))
        self.assertFalse(verify_certificate_pin(b"impostor", pin))
        self.assertFalse(verify_certificate_pin(b"", pin))
        self.assertFalse(verify_certificate_pin(certificate, b"\x00" * 32))

    def test_daily_key_derivation_binds_transcript_and_pin(self):
        secret = bytes(range(1, 33))
        digest = hashlib.sha256(b"framed PAKE transcript").digest()
        key = derive_daily_key(secret, digest, self.cert_pin)
        self.assertEqual(32, len(key))
        self.assertNotEqual(key, derive_daily_key(secret, digest, b"z" * 32))
        self.assertNotEqual(key, derive_daily_key(secret, b"x" * 32, self.cert_pin))
        with self.assertRaises(ValueError):
            derive_daily_key(b"\x00" * 32, digest, self.cert_pin)


if __name__ == "__main__":
    unittest.main()
