import unittest

from check_publish import findings


class PublicationTests(unittest.TestCase):
    def test_runtime_material_and_build_output_are_blocked(self):
        for path in ("tmp/report.json", "Tools/Desktop/dist/OmiPet.exe", "auth.json", "private.key",
                     "events.jsonl", "host-bindings.json", "AGENTS.md", "device_credentials.json"):
            self.assertIn("local-only path", list(findings(path, b"")), path)

    def test_reviewed_source_and_fake_vectors_are_publishable(self):
        for path in ("Firmware/include/pairing_credential_record.h", "Tools/DeviceBridge/pairing_credentials.py",
                     "Tools/DeviceBridge/tests/test_pairing_credentials.py", "Firmware/sdkconfig.defaults"):
            self.assertEqual([], list(findings(path, b"fixture = bytes(range(32))")))

    def test_common_tokens_and_private_material_are_detected_without_printing_values(self):
        for value in (b"sk-" + b"a" * 30, b"ghp_" + b"b" * 40,
                      b"-----BEGIN PRIVATE KEY-----\n" + b"c" * 40, b"https://" + b"user:pass@example.invalid"):
            result = list(findings("config.py", value))
            self.assertTrue(result)
            self.assertNotIn(value.decode(), " ".join(result))


if __name__ == "__main__":
    unittest.main()
