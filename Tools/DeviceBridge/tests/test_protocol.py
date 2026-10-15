import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from protocol import (Limits, ProtocolError, SerialDecoder, SnapshotMapper, decode, decode_websocket,
                      encode, envelope, serial_frame, token, validate_snapshot, websocket_text)
from simulator import DeviceSimulator, HostSession


TEST_LIMITS = Limits(max_json_bytes=4096, max_sessions=16)


def snapshot(status="waitingApproval"):
    return dict(revision=1, validForMs=500, sourceLiveness="unverified", overallStatus=status, sessions=[
        dict(id="s1", observed=status, display=status, host="running")])


class CodecTests(unittest.TestCase):
    def setUp(self):
        self.message = envelope(token(), token(), token(), 1, "hello", {"protocol": 1, "text": "中文\n测试"})

    def test_usb_fragment_boundaries_and_websocket_preserve_identical_message(self):
        wire = serial_frame(self.message, TEST_LIMITS)
        for split in range(len(wire) + 1):
            decoder = SerialDecoder(TEST_LIMITS)
            left, issues1 = decoder.feed(wire[:split])
            right, issues2 = decoder.feed(wire[split:])
            self.assertEqual(left + right, [self.message])
            self.assertEqual(issues1 + issues2 + decoder.finish(), [])
        self.assertEqual(decode_websocket(websocket_text(self.message, TEST_LIMITS), TEST_LIMITS), self.message)

    def test_mixed_logs_are_ignored_and_coalesced_frames_preserved(self):
        decoder = SerialDecoder(TEST_LIMITS)
        frame = serial_frame(self.message, TEST_LIMITS)
        messages, issues = decoder.feed(b"[VOICE] w\nlog @OMI not a frame\n" + frame + frame.replace(b"\n", b"\r\n"))
        self.assertEqual(messages, [self.message, self.message])
        self.assertEqual(issues, [])

    def test_oversized_frame_and_log_have_bounded_buffers_and_resynchronize(self):
        decoder = SerialDecoder(TEST_LIMITS)
        decoder.feed(b"@OMI " + b"x" * (TEST_LIMITS.max_json_bytes * 10))
        self.assertLessEqual(len(decoder.buffer), len(b"@OMI ") + TEST_LIMITS.max_json_bytes + 1)
        messages, issues = decoder.feed(b"\n" + serial_frame(self.message, TEST_LIMITS))
        self.assertEqual(messages, [self.message])
        decoder.feed(b"log" + b"x" * 10000)
        self.assertEqual(len(decoder.buffer), 0)

    def test_partial_frame_is_not_an_executable_message(self):
        decoder = SerialDecoder(TEST_LIMITS)
        self.assertEqual(decoder.feed(serial_frame(self.message, TEST_LIMITS)[:-1])[0], [])
        self.assertEqual(decoder.finish(), ["truncated-frame"])

    def test_invalid_utf8_json_duplicate_keys_nan_and_versions_are_rejected(self):
        for raw in (b"\xff", b"{", b"[]", b'{"v":1,"v":1}', b'{"v":NaN}',
                    json.dumps(self.message | dict(v=2)).encode(),
                    json.dumps(self.message | dict(seq=True)).encode()):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                decode(raw, TEST_LIMITS)

    def test_byte_budget_counts_utf8_not_characters(self):
        raw = encode(self.message, TEST_LIMITS)
        with self.assertRaises(ProtocolError):
            encode(self.message, Limits(max_json_bytes=len(raw) - 1, max_sessions=16))
        self.assertEqual(encode(self.message, Limits(len(raw), 16)), raw)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.device = DeviceSimulator(TEST_LIMITS, lease_ms=1000)
        self.host = HostSession(self.device.open(0), TEST_LIMITS)
        self.exchange("hello", {"protocol": 1}, 0)

    def exchange(self, kind, body, now):
        command = self.host.prepare(kind, body)
        return self.host.accept(self.device.receive(command, now))

    def test_snapshot_receipt_reports_applied_mode_and_unknown_is_preserved(self):
        ack = self.exchange("snapshot", snapshot("unknown"), 1)
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["state"]["mode"], "monitor")
        self.assertEqual(ack["state"]["displayStatus"], "unknown")
        self.assertEqual(ack["state"]["sourceLiveness"], "unverified")

    def test_lost_ack_retry_does_not_reapply_or_extend_lease(self):
        command = self.host.prepare("snapshot", snapshot())
        first = self.device.receive(command, 1)
        deadline = self.device.deadline
        retry = self.device.receive(self.host.retry(), 100)
        self.assertTrue(retry["body"]["duplicate"])
        self.assertEqual(self.device.applied_snapshots, 1)
        self.assertEqual(self.device.deadline, deadline)
        self.host.accept(retry)
        with self.assertRaises(ProtocolError):
            self.host.accept(first)

    def test_same_sequence_different_body_and_out_of_order_frames_are_rejected(self):
        command = self.host.prepare("snapshot", snapshot())
        self.host.accept(self.device.receive(command, 1))
        modified = copy.deepcopy(command)
        modified["body"] = snapshot("idle")
        self.assertEqual(self.device.receive(modified, 2)["body"]["code"], "sequence-conflict")
        modified["seq"] += 2
        self.assertFalse(self.device.receive(modified, 3)["body"]["ok"])
        self.assertEqual(self.device.applied_snapshots, 1)

    def test_one_pending_command_and_ack_identity_are_enforced(self):
        command = self.host.prepare("heartbeat", {})
        with self.assertRaises(ProtocolError):
            self.host.prepare("release", {})
        reply = self.device.receive(command, 1)
        with self.assertRaises(ProtocolError):
            self.host.accept(reply | dict(channel=token()))
        self.assertIsNotNone(self.host.pending)
        self.host.accept(reply)

    def test_expiry_restores_local_and_late_snapshot_cannot_reacquire(self):
        self.exchange("snapshot", snapshot(), 1)
        late = self.host.prepare("snapshot", snapshot("idle"))
        ack = self.host.accept(self.device.receive(late, 1001))
        self.assertFalse(ack["ok"])
        self.assertEqual(ack["state"]["mode"], "local")
        with self.assertRaises(ProtocolError):
            self.host.prepare("heartbeat", {})
        self.assertEqual(self.device.applied_snapshots, 1)

    def test_new_channel_rejects_old_requests_and_old_hello(self):
        old_hello = envelope(self.host.boot, self.host.channel, self.host.session, 1, "hello", {"protocol": 1})
        old_command = self.host.prepare("snapshot", snapshot())
        new_host = HostSession(self.device.open(2), TEST_LIMITS)
        for old in (old_hello, old_command):
            self.assertFalse(self.device.receive(old, 2)["body"]["ok"])
        hello = new_host.prepare("hello", {"protocol": 1})
        self.assertTrue(new_host.accept(self.device.receive(hello, 3))["ok"])
        self.assertEqual(self.device.mode, "local")

    def test_device_restart_and_other_host_nonce_are_not_accepted(self):
        command = self.host.prepare("snapshot", snapshot())
        other = copy.deepcopy(command)
        other["session"] = token()
        self.assertEqual(self.device.receive(other, 1)["body"]["code"], "wrong-session")
        restarted = DeviceSimulator(TEST_LIMITS, lease_ms=1000)
        restarted.open(0)
        with self.assertRaises(ProtocolError):
            self.host.accept(restarted.receive(command, 1))

    def test_heartbeat_keeps_transport_without_reviving_released_monitor(self):
        self.exchange("snapshot", snapshot(), 1)
        self.exchange("release", {}, 2)
        ack = self.exchange("heartbeat", {}, 3)
        self.assertEqual(ack["state"]["mode"], "local")
        self.assertEqual(ack["state"]["displayStatus"], "unknown")

    def test_disconnect_restores_local_and_rejects_old_traffic(self):
        self.exchange("snapshot", snapshot(), 1)
        command = self.host.prepare("heartbeat", {})
        self.device.disconnect()
        self.assertEqual(self.device.mode, "local")
        self.assertFalse(self.device.receive(command, 2)["body"]["ok"])

    def test_invalid_snapshot_never_partially_changes_applied_state(self):
        self.exchange("snapshot", snapshot(), 1)
        broken = snapshot("idle")
        broken["sessions"][0]["host"] = "unknown"
        ack = self.exchange("snapshot", broken, 2)
        self.assertFalse(ack["ok"])
        self.assertEqual(ack["state"]["displayStatus"], "waitingApproval")
        self.assertEqual(self.device.applied_snapshots, 1)

    def test_limits_negotiation_and_unsupported_operations(self):
        smaller = Limits(max_json_bytes=2048, max_sessions=2)
        host = HostSession(self.device.open(1), smaller)
        self.assertEqual(host.limits, smaller)
        with self.assertRaises(ProtocolError):
            host.prepare("setLight", {"rgb": [255, 0, 0]})

    def test_clock_and_lease_are_explicit(self):
        for value in (None, 0, -1, True):
            with self.assertRaises(ProtocolError):
                DeviceSimulator(TEST_LIMITS, lease_ms=value)
        with self.assertRaises(ProtocolError):
            self.device.advance(-1)

    def test_sequence_exhaustion_requires_new_connection_without_wrapping(self):
        self.host.next_seq = 0x100000000
        with self.assertRaises(ProtocolError):
            self.host.prepare("heartbeat", {})

    def test_hello_protocol_boolean_is_not_protocol_one(self):
        host = HostSession(self.device.open(1), TEST_LIMITS)
        request = host.prepare("hello", {"protocol": True})
        reply = self.device.receive(request, 1)
        self.assertFalse(reply["body"]["ok"])
        self.assertIsNone(self.device.session)

    def test_capacity_error_preserves_applied_snapshot_and_lease(self):
        self.exchange("snapshot", snapshot(), 1)
        deadline = self.device.deadline
        broken = snapshot()
        broken["revision"] = 2
        broken["sessions"] *= 17
        request = envelope(self.host.boot, self.host.channel, self.host.session,
                           self.host.next_seq, "snapshot", broken)
        reply = self.device.receive(request, 2)
        self.assertFalse(reply["body"]["ok"])
        self.assertEqual(self.device.applied_snapshots, 1)
        self.assertEqual(self.device.deadline, deadline)

    def test_heartbeat_cannot_extend_business_observation_validity(self):
        self.exchange("snapshot", snapshot(), 1)
        ack = self.exchange("heartbeat", {}, 600)
        self.assertTrue(ack["state"]["leaseActive"])
        self.assertEqual(ack["state"]["mode"], "monitor")
        self.assertEqual(ack["state"]["displayStatus"], "unknown")

    def test_old_snapshot_revision_cannot_refresh_observation(self):
        self.exchange("snapshot", snapshot(), 1)
        ack = self.exchange("snapshot", snapshot(), 200)
        self.assertFalse(ack["ok"])
        self.assertEqual(ack["code"], "snapshot-revision-stale")
        self.assertEqual(self.device.snapshot_deadline, 501)

    def test_malformed_ack_state_does_not_clear_pending_command(self):
        request = self.host.prepare("heartbeat", {})
        reply = self.device.receive(request, 1)
        reply["body"]["state"] = dict(mode="local", displayStatus="idle")
        with self.assertRaises(ProtocolError):
            self.host.accept(reply)
        self.assertIsNotNone(self.host.pending)


class MapperTests(unittest.TestCase):
    def setUp(self):
        self.mapper = SnapshotMapper()
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.view = dict(evaluatedAtUtc=self.now.isoformat(), maxAgeSeconds=10, sourceState="readable", sessions=[dict(
            sessionId="PRIVATE_TEST_SESSION", lastObservedStatus="waitingApproval", displayStatus="waitingApproval",
            hostProcessState="running", observationAgeSeconds=1, cwd="PRIVATE_TEST_PATH", prompt="PRIVATE_TEST_PROMPT")])

    def test_only_aliases_and_state_metadata_leave_the_host(self):
        body = self.mapper.convert(self.view, TEST_LIMITS, now=self.now)
        self.assertNotIn("PRIVATE_TEST", json.dumps(body))
        self.assertEqual(body["sessions"][0]["id"], "s1")
        self.assertEqual(body["overallStatus"], "waitingApproval")
        self.view["sessions"].reverse()
        self.assertEqual(self.mapper.convert(self.view, TEST_LIMITS, now=self.now)["sessions"], body["sessions"])

    def test_unknown_or_unfresh_source_cannot_become_green(self):
        for budget, age, source, host in ((None, 1, "readable", "running"),
                (0, 1, "readable", "running"), (10, 11, "readable", "running"),
                (10, 1, "unavailable", "running"), (10, 1, "readable", "unknown")):
            view = copy.deepcopy(self.view)
            view.update(maxAgeSeconds=budget, sourceState=source)
            view["sessions"][0].update(observationAgeSeconds=age, hostProcessState=host, displayStatus="idle")
            self.assertEqual(self.mapper.convert(view, TEST_LIMITS, now=self.now)["overallStatus"], "unknown")

    def test_capacity_and_duplicate_ids_are_rejected_without_alias_mutation(self):
        view = copy.deepcopy(self.view)
        view["sessions"] *= 2
        with self.assertRaises(ProtocolError):
            self.mapper.convert(view, Limits(4096, 1), now=self.now)
        with self.assertRaises(ProtocolError):
            self.mapper.convert(view, TEST_LIMITS, now=self.now)
        self.assertEqual(self.mapper.aliases, {})

    def test_aggregate_cannot_hide_unknown_session(self):
        body = snapshot("idle")
        body["sessions"].append(dict(id="s2", observed="working", display="unknown", host="unknown"))
        with self.assertRaises(ProtocolError):
            validate_snapshot(body, TEST_LIMITS)

    def test_cached_view_does_not_restart_business_validity(self):
        body = self.mapper.convert(self.view, TEST_LIMITS, now=self.now + timedelta(seconds=20))
        self.assertEqual(body["overallStatus"], "unknown")
        self.assertEqual(body["validForMs"], 0)

    def test_delivery_reserve_consumes_original_event_budget(self):
        body = self.mapper.convert(self.view, TEST_LIMITS, now=self.now + timedelta(seconds=2),
                                   delivery_reserve_seconds=3)
        self.assertEqual(body["overallStatus"], "waitingApproval")
        self.assertEqual(body["validForMs"], 4000)
        later = self.mapper.convert(self.view, TEST_LIMITS, now=self.now + timedelta(seconds=6),
                                    delivery_reserve_seconds=3)
        self.assertEqual(later["validForMs"], 0)
        self.assertEqual(later["overallStatus"], "unknown")
        with self.assertRaises(ProtocolError):
            self.mapper.convert(self.view, TEST_LIMITS, now=self.now, delivery_reserve_seconds=float("nan"))

    def test_monotonic_evaluation_survives_wall_clock_jump(self):
        self.view["evaluatedAtMonotonicNs"] = "100000000000"
        body = self.mapper.convert(self.view, TEST_LIMITS, now=self.now - timedelta(days=1),
                                   monotonic_ns=lambda: 102000000000, delivery_reserve_seconds=3)
        self.assertEqual(body["validForMs"], 4000)
        expired = self.mapper.convert(self.view, TEST_LIMITS, now=self.now + timedelta(days=1),
                                      monotonic_ns=lambda: 108000000000, delivery_reserve_seconds=3)
        self.assertEqual(expired["overallStatus"], "unknown")
        self.view["evaluatedAtMonotonicNs"] = "invalid"
        self.assertEqual(self.mapper.convert(self.view, TEST_LIMITS, now=self.now,
                                             monotonic_ns=lambda: 102000000000)["overallStatus"], "unknown")

    def test_alias_history_is_bounded_by_explicit_capacity(self):
        self.mapper.convert(self.view, Limits(4096, 1), now=self.now)
        other = copy.deepcopy(self.view)
        other["sessions"][0]["sessionId"] = "another-session"
        with self.assertRaises(ProtocolError):
            self.mapper.convert(other, Limits(4096, 1), now=self.now)
        self.assertEqual(len(self.mapper.aliases), 1)


if __name__ == "__main__":
    unittest.main()
