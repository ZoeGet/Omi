from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import Bridge, Health, read_bound_view, read_view
from protocol import Limits
from simulator import DeviceSimulator
from test_usb_client import Stream, ResetStream
from usb_client import DISCOVERY, UsbClient


def view(status="working", identity="PRIVATE_SESSION_ID"):
    return dict(evaluatedAtUtc=datetime.now(timezone.utc).isoformat(), sourceState="readable",
                maxAgeSeconds=1000, sessions=[dict(sessionId=identity, lastObservedStatus=status,
                displayStatus=status, hostProcessState="running", observationAgeSeconds=0,
                lastObservedAtUtc="2026-10-15T01:00:00+00:00", prompt="PRIVATE_PROMPT")])


class BridgeTests(unittest.TestCase):
    def setup_bridge(self, reader=lambda: view(), *, stream=None, retries=1, reopen=lambda: None):
        stream = stream if stream is not None else Stream()
        clock = lambda: stream.now
        client = UsbClient(stream, Limits(4096, 16), timeout_seconds=0.2, retries=retries, clock=clock)
        bridge = Bridge(client, reader, interval_seconds=0.1, clock=clock, reopen=reopen)
        return stream, bridge

    def test_real_snapshot_reader_changes_and_wire_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(status):
                (root / "snapshot.json").write_text(json.dumps(dict(schema=2, sessions=[dict(
                    sessionId="PRIVATE_SESSION_ID", status=status, updatedAtUtc="2026-10-15T01:00:00Z",
                    cwd="PRIVATE_DIRECTORY", toolName="PRIVATE_TOOL")])) , encoding="utf-8")
            stream, bridge = self.setup_bridge(lambda: read_view(root))
            write("working")
            self.assertTrue(bridge.step())
            write("waitingApproval")
            self.assertTrue(bridge.step())
            body = stream.device.snapshot
            self.assertEqual(body["sessions"][0]["observed"], "waitingApproval")
            self.assertEqual(body["sessions"][0]["display"], "unknown")
            self.assertEqual(body["validForMs"], 0)
            self.assertEqual(bridge.report["observationChanges"], 1)
            for secret in ("PRIVATE_SESSION_ID", "PRIVATE_DIRECTORY", "PRIVATE_TOOL"):
                self.assertNotIn(secret.encode(), b"".join(stream.writes))
                self.assertNotIn(secret, json.dumps(bridge.report))
            self.assertEqual(bridge.client.round_trips, [])

    def test_forces_unknown_even_with_claimed_freshness_and_running_host(self):
        stream, bridge = self.setup_bridge()
        self.assertTrue(bridge.step())
        self.assertEqual(stream.device.snapshot["overallStatus"], "unknown")
        self.assertEqual(stream.device.snapshot["validForMs"], 0)
        self.assertEqual(bridge.report["nonUnknownSnapshotCycles"], 0)
        self.assertEqual(bridge.report["unknownReasons"], {"fresh-display-unavailable": 1})
        self.assertEqual(bridge.report["acknowledgedDeviceDisplays"], {"unknown": 1})
        self.assertNotIn(b"PRIVATE_PROMPT", b"".join(stream.writes))

    def test_bound_freshness_declines_from_original_event_and_reserves_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instant = datetime.now(timezone.utc)
            current = [instant]
            monotonic = [100000000000]
            identity = dict(pid=123, creationTime100ns="456", imagePath="C:/codex.exe")
            bindings = dict(schema=2, sessions={"PRIVATE_SESSION_ID": dict(identity=identity,
                proof=dict(updatedAtUtc=instant.isoformat(), lastEvent="PreToolUse",
                           turnId="turn-a", toolUseId="tool-a"), confirmed=True,
                observedMonotonicNs=str(monotonic[0]))})
            (root / "snapshot.json").write_text(json.dumps(dict(schema=2, sessions=[dict(
                sessionId="PRIVATE_SESSION_ID", status="working", updatedAtUtc=instant.isoformat(),
                lastEvent="PreToolUse", turnId="turn-a", toolUseId="tool-a",
                prompt="PRIVATE_PROMPT")])), encoding="utf-8")
            reader = lambda: read_bound_view(root, bindings, now=current[0], max_age_seconds=12,
                process_checker=lambda _: dict(processState="running"),
                monotonic_ns=lambda: monotonic[0])
            stream = Stream()
            stream.device = DeviceSimulator(Limits(4096, 16), lease_ms=1000,
                                            freshness_challenge=True)
            clock = lambda: stream.now
            client = UsbClient(stream, Limits(4096, 16), timeout_seconds=0.2, retries=1, clock=clock)
            bridge = Bridge(client, reader, interval_seconds=0.1, clock=clock,
                            wall_clock=lambda: current[0], allow_fresh_display=True,
                            delivery_reserve_seconds=8, monotonic_ns=lambda: monotonic[0])
            self.assertTrue(bridge.step())
            self.assertEqual(stream.device.snapshot["overallStatus"], "working")
            self.assertEqual(stream.device.snapshot["validForMs"], 4000)
            self.assertEqual(bridge.report["lastDisplayedCounts"], {"working": 1})
            self.assertEqual(bridge.report["acknowledgedDeviceDisplays"], {"working": 1})
            current[0] += timedelta(seconds=3)
            monotonic[0] += 3_000_000_000
            self.assertTrue(bridge.step())
            self.assertEqual(stream.device.snapshot["validForMs"], 1000)
            current[0] += timedelta(seconds=1)
            monotonic[0] += 1_000_000_000
            self.assertTrue(bridge.step())
            self.assertEqual(stream.device.snapshot["overallStatus"], "unknown")
            self.assertEqual(stream.device.snapshot["validForMs"], 0)
            self.assertEqual(bridge.report["nonUnknownSnapshotCycles"], 2)
            self.assertEqual(bridge.report["acknowledgedDeviceDisplays"], {"working": 2, "unknown": 1})
            self.assertIsNotNone(bridge.report["firstUnknownAckAfterNonUnknownAtUtc"])
            self.assertEqual(bridge.report["unknownReasons"], {"delivery-budget-exhausted": 1})
            self.assertNotIn(b"PRIVATE_SESSION_ID", b"".join(stream.writes))
            self.assertNotIn(b"PRIVATE_PROMPT", b"".join(stream.writes))

    def test_unknown_reason_diagnostics_are_bounded_and_do_not_copy_private_fields(self):
        source = view(status="unknown")
        source["sessions"][0]["reason"] = "event-binding-unconfirmed"
        stream, bridge = self.setup_bridge(lambda: source)
        self.assertTrue(bridge.step())
        self.assertEqual(bridge.report["unknownReasons"], {"event-binding-unconfirmed": 1})
        self.assertEqual(bridge.report["lastUnknownSnapshot"]["reasons"], {"event-binding-unconfirmed": 1})
        source["sessions"][0]["reason"] = "PRIVATE_PROMPT"
        self.assertTrue(bridge.step())
        self.assertEqual(bridge.report["unknownReasons"], {"event-binding-unconfirmed": 1, "unclassified": 1})
        self.assertNotIn("PRIVATE_PROMPT", json.dumps(bridge.report))
        self.assertNotIn("PRIVATE_SESSION_ID", json.dumps(bridge.report))
        self.assertNotIn("snapshots", bridge.report)

    def test_device_unknown_is_distinguished_from_source_unknown(self):
        source = dict(view(), bindingState="event-correlated", evaluatedAtMonotonicNs=str(time.monotonic_ns()))
        stream, bridge = self.setup_bridge(lambda: source)
        stream.device = DeviceSimulator(Limits(4096, 16), lease_ms=1000, freshness_challenge=True)
        bridge.allow_fresh_display, bridge.delivery_reserve_seconds = True, 8
        request = bridge.client.request
        def device_unknown(kind, body):
            reply = request(kind, body)
            if kind == "snapshot":
                self.assertEqual(body["overallStatus"], "working")
                reply["state"]["displayStatus"] = "unknown"
            return reply
        with patch.object(bridge.client, "request", side_effect=device_unknown):
            self.assertTrue(bridge.step())
        self.assertEqual(bridge.report["unknownReasons"], {"device-display-unknown": 1})

    def test_legacy_binding_cannot_enable_fresh_device_display(self):
        stream = Stream()
        client = UsbClient(stream, Limits(4096, 16), timeout_seconds=0.2, retries=1,
                           clock=lambda: stream.now)
        reader = lambda: dict(view(), bindingState="explicit")
        bridge = Bridge(client, reader, interval_seconds=0.1, clock=lambda: stream.now,
                        allow_fresh_display=True, delivery_reserve_seconds=8)
        self.assertTrue(bridge.step())
        self.assertEqual(stream.device.snapshot["overallStatus"], "unknown")
        self.assertEqual(stream.device.snapshot["validForMs"], 0)

    def test_old_device_capability_forces_unknown_even_with_current_binding(self):
        stream = Stream()
        client = UsbClient(stream, Limits(4096, 16), timeout_seconds=0.2, retries=1,
                           clock=lambda: stream.now)
        current = time.monotonic_ns()
        reader = lambda: dict(view(), bindingState="event-correlated",
                              evaluatedAtMonotonicNs=str(current))
        bridge = Bridge(client, reader, interval_seconds=0.1, clock=lambda: stream.now,
                        allow_fresh_display=True, delivery_reserve_seconds=8)
        self.assertTrue(bridge.step())
        self.assertFalse(client.host.freshness_challenge)
        self.assertEqual(stream.device.state()["displayStatus"], "unknown")
        self.assertEqual(stream.device.snapshot["validForMs"], 0)

    def test_unbound_or_failed_process_check_cannot_enable_fresh_display(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instant = datetime.now(timezone.utc)
            (root / "snapshot.json").write_text(json.dumps(dict(schema=2, sessions=[dict(
                sessionId="PRIVATE_SESSION_ID", status="idle", updatedAtUtc=instant.isoformat())])),
                encoding="utf-8")
            for bindings, process_state in ((dict(schema=1, sessions={}), "running"),
                                            (dict(schema=1, sessions={"PRIVATE_SESSION_ID": dict(
                                                pid=123, creationTime100ns="456", imagePath="C:/codex.exe")}), "unknown")):
                with self.subTest(process_state=process_state):
                    reader = lambda: read_bound_view(root, bindings, now=instant, max_age_seconds=12,
                        process_checker=lambda _: dict(processState=process_state))
                    stream, bridge = self.setup_bridge(reader)
                    bridge.allow_fresh_display = True
                    bridge.delivery_reserve_seconds = 8
                    self.assertTrue(bridge.step())
                    self.assertEqual(stream.device.snapshot["overallStatus"], "unknown")
                    self.assertEqual(stream.device.snapshot["validForMs"], 0)

    def test_missing_then_damaged_source_clears_old_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stream, bridge = self.setup_bridge(lambda: read_view(root))
            self.assertTrue(bridge.step())
            self.assertEqual(bridge.report["sourceStates"], {"missing": 1})
            (root / "snapshot.json").write_text("{broken", encoding="utf-8")
            self.assertTrue(bridge.step())
            self.assertEqual(stream.device.snapshot["sessions"], [])
            self.assertEqual(bridge.report["sourceStates"]["unreadable"], 1)

    def test_invalid_or_over_capacity_source_becomes_empty_unknown(self):
        for invalid in (None, {"sessions": [None]}, dict(view(), sessions=view()["sessions"] * 17)):
            with self.subTest(invalid=invalid):
                stream, bridge = self.setup_bridge(lambda: invalid)
                self.assertTrue(bridge.step())
                self.assertEqual(stream.device.snapshot["sessions"], [])
                self.assertEqual(bridge.report["sourceProblems"], {"source-or-capacity-invalid": 1})

    def test_lost_ack_retries_without_reapplying_snapshot(self):
        stream, bridge = self.setup_bridge()
        bridge._connect()
        stream.lose_ack = True
        self.assertTrue(bridge.step())
        self.assertEqual(stream.device.applied_snapshots, 1)
        self.assertEqual(stream.writes[-1], stream.writes[-2])

    def test_serial_failure_reopens_same_stream_and_new_connection(self):
        opens = []
        stream, bridge = self.setup_bridge(reopen=lambda: opens.append(True))
        self.assertTrue(bridge.step())
        channel = stream.device.channel
        stream.short = True
        self.assertFalse(bridge.step())
        stream.short = False
        self.assertTrue(bridge.step())
        self.assertNotEqual(channel, stream.device.channel)
        self.assertEqual(len(opens), 2)
        self.assertEqual(bridge.report["communicationErrors"], 1)
        self.assertEqual(stream.device.last_snapshot_revision, 1)

    def test_lease_expiry_reconnects_with_new_mapper(self):
        stream, bridge = self.setup_bridge()
        self.assertTrue(bridge.step())
        channel = stream.device.channel
        stream.now += 1.1
        self.assertFalse(bridge.step())
        self.assertTrue(bridge.step())
        self.assertNotEqual(channel, stream.device.channel)

    def test_device_reset_recovery_is_recorded_without_timeout(self):
        stream, bridge = self.setup_bridge(stream=ResetStream())
        self.assertTrue(bridge.step())
        stream.reset_on_request = True
        self.assertFalse(bridge.step())
        self.assertEqual(bridge.report["connectionResets"], 1)
        self.assertEqual(bridge.report["communicationErrors"], 0)
        self.assertEqual(bridge.client.diagnostics["replyTimeouts"], 0)
        self.assertTrue(bridge.step())
        self.assertEqual(stream.device.snapshot["revision"], 1)

    def test_alias_churn_forces_new_channel(self):
        selected = [0]
        stream, bridge = self.setup_bridge(lambda: view(identity=f"private-{selected[0]}"))
        for index in range(16):
            selected[0] = index
            self.assertTrue(bridge.step())
        channel = stream.device.channel
        selected[0] = 16
        self.assertFalse(bridge.step())
        self.assertTrue(bridge.step())
        self.assertNotEqual(channel, stream.device.channel)
        self.assertEqual(stream.device.snapshot["sessions"][0]["id"], "s1")

    def test_duration_stops_and_releases(self):
        stream, bridge = self.setup_bridge()
        def wait(seconds):
            stream.now += seconds
        report = bridge.run(duration_seconds=0.6, wait=wait)
        self.assertGreater(report["acknowledgedSnapshots"], 1)
        self.assertTrue(report["releaseConfirmed"])
        self.assertEqual(report["stoppedBy"], "duration")
        self.assertEqual(stream.device.mode, "local")
        self.assertIsNone(stream.device.deadline)

    def test_stop_before_start_sends_nothing(self):
        stream, bridge = self.setup_bridge()
        bridge.run(should_stop=lambda: True)
        self.assertEqual(stream.writes, [])
        self.assertEqual(bridge.report["stoppedBy"], "stop-request")

    def test_stop_during_run_releases(self):
        stream, bridge = self.setup_bridge()
        bridge.run(should_stop=lambda: bridge.report["acknowledgedSnapshots"] > 0,
                   wait=lambda seconds: None)
        self.assertTrue(bridge.report["releaseConfirmed"])
        self.assertEqual(bridge.report["acknowledgedSnapshots"], 1)
        self.assertIsNone(stream.device.deadline)

    def test_cli_existing_stop_file_does_not_open_invalid_port(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stop, report, trace = root / "stop", root / "report.json", root / "protocol.jsonl"
            stop.touch()
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bridge.py"),
                "--port", "INVALID_PORT_MUST_NOT_OPEN", "--max-json-bytes", "4096", "--max-sessions", "16",
                "--interval-seconds", "1", "--timeout-seconds", "2", "--retries", "1",
                "--stop-file", str(stop), "--report", str(report),
                "--protocol-trace", str(trace)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["stoppedBy"], "stop-request")
            self.assertEqual(data["connections"], 0)
            self.assertEqual(data["result"], "incomplete")
            self.assertEqual(data["protocolTrace"], str(trace))
            self.assertEqual(trace.read_text(encoding="utf-8"), "")
            self.assertTrue(stop.exists())

    def test_cli_requires_budget_and_bindings_together(self):
        script = str(Path(__file__).resolve().parents[1] / "bridge.py")
        basic = [sys.executable, script, "--port", "INVALID_PORT_MUST_NOT_OPEN",
                 "--max-json-bytes", "4096", "--max-sessions", "16",
                 "--interval-seconds", "1", "--timeout-seconds", "2", "--retries", "1",
                 "--report", "unused-report.json"]
        for extra in (["--max-age-seconds", "30"],
                      ["--process-bindings", "missing-bindings.json"]):
            with self.subTest(extra=extra):
                result = subprocess.run(basic + extra, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("must be supplied together", result.stderr)

    def test_keyboard_interrupt_releases(self):
        stream, bridge = self.setup_bridge()
        def wait(seconds):
            raise KeyboardInterrupt()
        bridge.run(wait=wait)
        self.assertTrue(bridge.report["releaseConfirmed"])
        self.assertEqual(bridge.report["stoppedBy"], "keyboard-interrupt")

    def test_release_recovers_unconfirmed_command(self):
        stream, bridge = self.setup_bridge(retries=0)
        bridge._connect()
        stream.lose_ack = True
        with self.assertRaises(TimeoutError):
            bridge.client.request("heartbeat", {})
        bridge.release()
        self.assertTrue(bridge.report["releaseConfirmed"])

    def test_failure_then_exit_attempts_release_on_fresh_connection(self):
        stream, bridge = self.setup_bridge(retries=0)
        self.assertTrue(bridge.step())
        stream.lose_ack = True
        self.assertFalse(bridge.step())
        bridge.release()
        self.assertTrue(bridge.report["releaseConfirmed"])

    def test_reset_on_preconnected_first_step_still_releases(self):
        stream, bridge = self.setup_bridge(stream=ResetStream())
        bridge.client.connect()
        stream.reset_on_request = True
        self.assertFalse(bridge.step())
        self.assertEqual(bridge.report["connections"], 0)
        self.assertEqual(bridge.report["connectionResets"], 1)
        bridge.release()
        self.assertTrue(bridge.report["releaseConfirmed"])
        self.assertIsNone(stream.device.deadline)

    def test_old_firmware_receives_safe_probes_only(self):
        stream, bridge = self.setup_bridge(stream=Stream(legacy=True), retries=0)
        self.assertFalse(bridge.step())
        bridge.release()
        self.assertTrue(all(data == DISCOVERY for data in stream.writes))

    def test_interval_at_lease_is_rejected_and_released(self):
        stream, bridge = self.setup_bridge()
        bridge.interval = 1
        with self.assertRaises(ValueError):
            bridge.run(duration_seconds=1)
        self.assertTrue(bridge.report["releaseConfirmed"])

    def test_filtered_link_gaps_are_recorded_separately_from_disconnects(self):
        samples = []
        health = Health(4096, protocol_counter_sink=samples.append)
        health.line("[PROTO] link_losses=1 filtered_link_gaps=4")
        health.line("[PROTO] link_losses=1 filtered_link_gaps=5")
        self.assertEqual(samples[-1]["delta"], dict(link_losses=0, filtered_link_gaps=1))
        self.assertEqual(health.report["lastProtocolCounters"]["filtered_link_gaps"], 5)

    def test_health_is_bounded_and_does_not_keep_raw_log(self):
        health = Health(4096)
        health.feed(b"x" * 5000 + b"\n[SYS] mic=ok\n[AUDIO] queued=0 dropped=0\n")
        health.feed(b"[PROTO] max_poll_us=4000\n")
        health.feed(b"[AUDIO] queued=1 dropped=0\ntask_wdt\nserial wake trigger\n")
        self.assertEqual(health.buffer, bytearray())
        self.assertTrue(health.report["microphoneOk"])
        self.assertEqual(health.report["audioSamples"], 2)
        self.assertTrue(health.report["audioQueueProblem"])
        self.assertTrue(health.report["watchdogOrPanic"])
        self.assertTrue(health.report["unexpectedDebugWake"])
        self.assertEqual(health.report["maxPollUs"], 4000)
        health.feed(b"[PROTO] probes=3 requests=20 sent=21 rejected=1 stalled=0 stale=0 write_failures=0\n")
        self.assertEqual(health.report["lastProtocolCounters"]["requests"], 20)
        health.feed(b"[LED] owner=monitor effect=center_expand status=wait")
        health.feed(b"ingApproval brightness=16\n[LED] owner=local reason=fallback\n")
        health.feed(b"[LED] owner=local reason=voice\r\n")
        health.feed(b"[ASR] detected id=1 phrase=0 score=0.8 text=redacted\n")
        health.feed(b"[LED] owner=voice effect=sweep color=white\r\n[ASR] detected id=6 phrase=0 score=0.8 text=redacted\n[LED] color=blue\r\n")
        self.assertEqual(health.report["monitorLedTransitions"], {"waitingApproval": 1})
        self.assertEqual(health.report["localLedFallbacks"], 1)
        self.assertEqual(health.report["voiceLedTakeovers"], 1)
        self.assertEqual(health.report["wakeSweepStarts"], 1)
        self.assertEqual(health.report["recognizedCommandCounts"], {"1": 1, "6": 1})
        self.assertEqual(health.report["ledColorCommands"], {"blue": 1})
        health.feed(b"[LED] owner=desktop revision=8 effect=0 rgb=255,255,255 brightness=16\n")
        self.assertEqual(health.report["desktopLightCommands"], 1)
        self.assertEqual(health.report["lastDesktopLight"]["revision"], 8)

    def test_protocol_trace_timestamps_counter_changes_without_raw_serial_content(self):
        samples = []
        health = Health(4096, protocol_counter_sink=samples.append,
                        wall_clock=lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
        health.feed(b"[PROTO] link_losses=4 reopens=0 bus_resets=3 link_down_polls=8373 ")
        health.feed(b"last_link_down_ms=1 secret=do-not-save\r\n")
        health.feed(b"[PROTO] link_losses=5 reopens=1 bus_resets=3 link_down_polls=8375 last_link_down_ms=2\n")
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[1]["receivedAtUtc"], "2026-10-15T00:00:00+00:00")
        self.assertEqual(samples[1]["delta"], dict(link_losses=1, reopens=1,
                                                     bus_resets=0, link_down_polls=2))
        self.assertNotIn("do-not-save", json.dumps(samples))


if __name__ == "__main__":
    unittest.main()
