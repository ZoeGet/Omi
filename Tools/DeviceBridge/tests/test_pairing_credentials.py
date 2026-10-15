import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pairing_credentials import (
    CredentialState, decode_record, encode_record, load_file, save_file_once,
)


class PairingCredentialTests(unittest.TestCase):
    def setUp(self):
        self.key = bytes(range(1, 33))
        self.pin = bytes(range(64, 96))

    def test_record_cross_language_vector_and_corruption(self):
        record = encode_record(self.key, self.pin)
        self.assertEqual(101, len(record))
        self.assertEqual(
            "5aab7b11f8278032b31fa5545e1750469b7a7968fda7c30e476850283dcdf47e",
            hashlib.sha256(record).hexdigest(),
        )
        self.assertEqual((self.key, self.pin), decode_record(record))
        damaged = bytearray(record)
        damaged[8] ^= 1
        with self.assertRaises(ValueError):
            decode_record(bytes(damaged))
        with self.assertRaises(ValueError):
            decode_record(record[:-1])

    def test_file_is_write_once_and_corrupt_or_partial_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.bin"
            self.assertEqual((CredentialState.ABSENT, None), load_file(path))
            save_file_once(path, self.key, self.pin)
            self.assertEqual((CredentialState.PRESENT, (self.key, self.pin)),
                             load_file(path))
            with self.assertRaises(FileExistsError):
                save_file_once(path, b"z" * 32, self.pin)
            self.assertEqual((CredentialState.PRESENT, (self.key, self.pin)),
                             load_file(path))
            path.write_bytes(b"partial")
            self.assertEqual((CredentialState.UNKNOWN, None), load_file(path))
            with self.assertRaises(FileExistsError):
                save_file_once(path, self.key, self.pin)

    def test_zero_and_wrong_version_are_invalid(self):
        with self.assertRaises(ValueError):
            encode_record(b"\0" * 32, self.pin)
        with self.assertRaises(ValueError):
            encode_record(self.key, b"\0" * 32)
        record = bytearray(encode_record(self.key, self.pin))
        record[4] = 2
        with self.assertRaises(ValueError):
            decode_record(bytes(record))


if __name__ == "__main__":
    unittest.main()
