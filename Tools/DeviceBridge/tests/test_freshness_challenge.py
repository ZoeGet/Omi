from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import Limits, envelope
from simulator import DeviceSimulator, HostSession


class FreshnessChallengeTests(unittest.TestCase):
    def setUp(self):
        self.limits = Limits(4096, 16)
        self.device = DeviceSimulator(self.limits, lease_ms=5000, freshness_challenge=True)
        self.host = HostSession(self.device.open(0), self.limits)
        self.send("hello", {"protocol": 1}, 0)

    def send(self, kind, body, now):
        request = self.host.prepare(kind, body)
        reply = self.device.receive(request, now)
        return self.host.accept(reply)

    @staticmethod
    def snapshot(revision, challenge=None, validity=1000):
        body = dict(revision=revision, validForMs=validity, sourceLiveness="unverified",
                    overallStatus="working", sessions=[dict(id="s1", observed="working",
                                                            display="working", host="running")])
        if challenge is not None:
            body["challengeSeq"] = challenge
        return body

    def test_missing_and_replayed_challenge_fail_closed(self):
        self.assertTrue(self.host.freshness_challenge)
        self.assertFalse(self.send("snapshot", self.snapshot(1), 10)["ok"])
        seq = self.host.next_seq
        self.assertTrue(self.send("heartbeat", {}, 20)["ok"])
        self.assertTrue(self.send("snapshot", self.snapshot(1, seq), 30)["ok"])
        self.assertEqual(self.device.state()["displayStatus"], "working")
        self.assertFalse(self.send("snapshot", self.snapshot(2, seq), 40)["ok"])
        self.assertEqual(self.device.last_snapshot_revision, 1)

    def test_heartbeat_renews_lease_but_old_challenge_cannot_renew_status(self):
        old_seq = self.host.next_seq
        self.send("heartbeat", {}, 10)
        self.send("heartbeat", {}, 1010)
        self.send("heartbeat", {}, 2010)
        reply = self.send("snapshot", self.snapshot(1, old_seq), 2020)
        self.assertFalse(reply["ok"])
        self.assertTrue(reply["state"]["leaseActive"])
        self.assertEqual(reply["state"]["displayStatus"], "unknown")

    def test_device_subtracts_elapsed_and_duplicate_does_not_refresh(self):
        seq = self.host.next_seq
        self.send("heartbeat", {}, 10)
        self.assertTrue(self.send("snapshot", self.snapshot(1, seq), 410)["ok"])
        self.device.advance(1009)
        self.assertEqual(self.device.state()["displayStatus"], "working")
        self.device.advance(1010)
        self.assertEqual(self.device.state()["displayStatus"], "unknown")
        duplicate = self.device.receive(self.host.retry() if self.host.pending else envelope(
            self.device.boot, self.device.channel, self.host.session, 3, "snapshot", self.snapshot(1, seq)), 1020)
        self.assertTrue(duplicate["body"]["duplicate"])
        self.assertEqual(duplicate["body"]["state"]["displayStatus"], "unknown")

    def test_delivery_after_validity_is_unknown(self):
        seq = self.host.next_seq
        self.send("heartbeat", {}, 10)
        reply = self.send("snapshot", self.snapshot(1, seq, validity=100), 200)
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["state"]["displayStatus"], "unknown")
        self.assertEqual(self.device.last_snapshot_revision, 1)

    def test_rejected_heartbeat_is_not_a_challenge(self):
        self.send("heartbeat", {}, 10)
        rejected_seq = self.host.next_seq
        self.assertFalse(self.send("heartbeat", {"unexpected": True}, 20)["ok"])
        reply = self.send("snapshot", self.snapshot(1, rejected_seq), 30)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["code"], "freshness-challenge-required")


if __name__ == "__main__":
    unittest.main()
