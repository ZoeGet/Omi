from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import Limits
from test_usb_client import Stream
from usb_client import UsbClient
from verify_fallback import run


class FallbackTests(unittest.TestCase):
    def test_held_nonunknown_snapshot_cannot_reacquire_after_silence(self):
        stream = Stream()
        client = UsbClient(stream, Limits(4096, 16), timeout_seconds=0.2, retries=1,
                           clock=lambda: stream.now)
        result = run(client, 30000, clock=lambda: stream.now)
        self.assertEqual(result["firstDisplay"], "working")
        self.assertEqual(result["lateState"]["displayStatus"], "unknown")
        self.assertEqual(result["lateState"]["mode"], "local")
        self.assertGreaterEqual(result["silentMs"], result["leaseMs"])
        self.assertTrue(result["releaseConfirmed"])


if __name__ == "__main__":
    unittest.main()
