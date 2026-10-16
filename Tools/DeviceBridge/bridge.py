import argparse
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time

from protocol import Limits, ProtocolError, SnapshotMapper
from usb_client import UsbClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "CodexMonitor"))
from state_view import read_bound_view, read_view


SOURCE_REASONS = frozenset(("invalid-session", "invalid-timestamp", "future-timestamp", "source-unavailable",
    "freshness-policy-unset", "observation-expired", "invalid-process-bindings", "process-binding-missing",
    "event-binding-unconfirmed", "event-clock-invalid", "source-unavailable-or-budget-unset",
    "bound-process-unconfirmed", "observed-lifecycle", "source-lock-unavailable",
    "within-explicit-budget", "within-monotonic-budget"))


def positive_seconds(value):
    try:
        result = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected seconds") from error
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Seconds must be finite and positive")
    return result


class Health:
    def __init__(self, max_line_bytes, *, protocol_counter_sink=None,
                 wall_clock=lambda: datetime.now(timezone.utc)):
        self.capacity = max_line_bytes
        self.buffer = bytearray()
        self.dropping = False
        self.protocol_counter_sink = protocol_counter_sink
        self.wall_clock = wall_clock
        self.report = dict(microphoneOk=False, audioSamples=0, audioQueueProblem=False,
                           watchdogOrPanic=False, unexpectedDebugWake=False, maxPollUs=None,
                           monitorLedTransitions={}, localLedFallbacks=0, voiceLedTakeovers=0,
                           wakeSweepStarts=0, recognizedCommandCounts={}, ledColorCommands={},
                           desktopLightCommands=0, lastDesktopLight=None, monitorDisconnectOffs=0)

    def feed(self, data):
        for byte in data:
            if byte == 10:
                if not self.dropping:
                    self.line(bytes(self.buffer).decode("utf-8", "replace").rstrip("\r"))
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                self.buffer.append(byte)
                if len(self.buffer) > self.capacity:
                    self.buffer.clear()
                    self.dropping = True

    def line(self, text):
        if text.startswith("[SYS]") and "mic=ok" in text:
            self.report["microphoneOk"] = True
        audio = re.search(r"queued=(\d+) dropped=(\d+)", text)
        if audio:
            self.report["audioSamples"] += 1
            self.report["audioQueueProblem"] |= any(int(value) for value in audio.groups())
        if re.search(r"task_wdt|Guru Meditation|panic'ed|abort\(\)", text):
            self.report["watchdogOrPanic"] = True
        if "serial wake trigger" in text:
            self.report["unexpectedDebugWake"] = True
        poll = re.search(r"max_poll_us=(\d+)", text)
        if poll:
            self.report["maxPollUs"] = max(self.report["maxPollUs"] or 0, int(poll[1]))
        if text.startswith("[PROTO]"):
            counters = dict((key, int(value)) for key, value in re.findall(
                r"\b(seq|probes|requests|sent|rejected|stalled|stale|write_failures|session_failure|frame_failure|link_losses|filtered_link_gaps|reopens|bus_resets|link_down_polls|last_link_down_ms|max_link_down_ms)=(\d+)", text))
            if counters:
                previous = self.report.get("lastProtocolCounters")
                if self.protocol_counter_sink is not None:
                    keys = ("link_losses", "filtered_link_gaps", "reopens", "bus_resets", "link_down_polls")
                    delta = ({key: counters[key] - previous[key] for key in keys
                              if key in counters and key in previous}
                             if previous is not None else {})
                    self.protocol_counter_sink(dict(receivedAtUtc=self.wall_clock().isoformat(),
                                                     counters=counters, delta=delta))
                self.report.setdefault("firstProtocolCounters", counters)
                self.report["lastProtocolCounters"] = counters
        monitor = re.fullmatch(r"\[LED\] owner=monitor effect=center_expand status=(working|waitingApproval|idle|unknown|offline) brightness=\d+", text)
        if monitor:
            counts = self.report["monitorLedTransitions"]
            counts[monitor[1]] = counts.get(monitor[1], 0) + 1
        if text == "[LED] owner=local reason=fallback":
            self.report["localLedFallbacks"] += 1
        if text == "[LED] owner=local reason=voice":
            self.report["voiceLedTakeovers"] += 1
        if text == "[LED] owner=off reason=monitor-disconnected":
            self.report["monitorDisconnectOffs"] += 1
        if text == "[LED] owner=voice effect=sweep color=white":
            self.report["wakeSweepStarts"] += 1
        recognized = re.match(r"\[ASR\] detected id=(\d+)\b", text)
        if recognized and 1 <= int(recognized[1]) <= 16:
            counts = self.report["recognizedCommandCounts"]
            counts[recognized[1]] = counts.get(recognized[1], 0) + 1
        color = re.fullmatch(r"\[LED\] color=(red|green|blue|yellow|purple|cyan|white)", text)
        if color:
            counts = self.report["ledColorCommands"]
            counts[color[1]] = counts.get(color[1], 0) + 1
        desktop = re.fullmatch(r"\[LED\] owner=desktop revision=(\d+) effect=(\d+) rgb=(\d+),(\d+),(\d+) brightness=(\d+)", text)
        if desktop:
            self.report["desktopLightCommands"] += 1
            self.report["lastDesktopLight"] = dict(zip(
                ("revision", "effect", "red", "green", "blue", "brightness"),
                (int(value) for value in desktop.groups())))


class Bridge:
    def __init__(self, client, reader, *, interval_seconds, clock=time.monotonic,
                 wall_clock=lambda: datetime.now(timezone.utc), reopen=lambda: None,
                 allow_fresh_display=False, delivery_reserve_seconds=0,
                 monotonic_ns=time.monotonic_ns):
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("Explicit positive interval required")
        if (type(delivery_reserve_seconds) not in (int, float)
                or not math.isfinite(delivery_reserve_seconds) or delivery_reserve_seconds < 0):
            raise ValueError("Delivery reserve must be finite and nonnegative")
        if allow_fresh_display and delivery_reserve_seconds <= 0:
            raise ValueError("Fresh display requires an explicit delivery reserve")
        self.client, self.reader = client, reader
        self.interval, self.clock, self.wall_clock = interval_seconds, clock, wall_clock
        self.monotonic_ns = monotonic_ns
        self.reopen = reopen
        self.allow_fresh_display = allow_fresh_display
        self.delivery_reserve_seconds = delivery_reserve_seconds
        self.mapper = SnapshotMapper()
        self.previous = None
        self.unknown_reasons = {}
        self.report = dict(observationsOnly=True, physicalLedControl=False,
                           freshnessPolicy=("explicit-bound-reserved" if allow_fresh_display
                                            else "unset-display-unknown"), connections=0, cycles=0,
                           acknowledgedSnapshots=0, communicationErrors=0, sourceProblems={},
                           connectionResets=0,
                           sourceStates={}, observationChanges=0, observationTimestampAdvances=0,
                           latestObservationAtUtc=None, lastObservedCounts={},
                           lastDisplayedCounts={}, nonUnknownSnapshotCycles=0,
                           acknowledgedDeviceDisplays={}, firstNonUnknownAckAtUtc=None,
                           firstUnknownAckAfterNonUnknownAtUtc=None,
                           unknownReasons={}, lastUnknownSnapshot=None,
                           lastDeviceState=None, releaseConfirmed=False, stoppedBy=None)

    def _connect(self):
        self.reopen()
        welcome = self.client.connect()
        self.report["connections"] += 1
        self.report["capabilities"] = welcome["body"]
        self.report["freshnessChallengeSupported"] = self.client.host.freshness_challenge
        self.mapper = SnapshotMapper()
        if self.interval * 1000 >= self.client.host.lease_ms:
            raise ValueError("Send interval must be shorter than the negotiated lease")

    def _body(self):
        problem = None
        display_policy = None
        try:
            view = self.reader()
            state = view.get("sourceState", "invalid")
            if state not in ("readable", "missing", "unreadable", "invalid", "empty", "unavailable"):
                state = "invalid"
            if (not self.allow_fresh_display or not self.client.host.freshness_challenge
                    or view.get("bindingState") != "event-correlated"
                    or "evaluatedAtMonotonicNs" not in view):
                display_policy = "fresh-display-unavailable"
                view = dict(view, maxAgeSeconds=None,
                            sessions=[dict(entry, displayStatus="unknown") for entry in view["sessions"]])
            body = self.mapper.convert(view, self.client.host.limits, now=self.wall_clock(),
                                       delivery_reserve_seconds=self.delivery_reserve_seconds,
                                       monotonic_ns=self.monotonic_ns)
        except ProtocolError as error:
            if str(error) == "alias-capacity-reconnect-required":
                raise
            state, problem = "invalid", "source-or-capacity-invalid"
            body = self.mapper.convert(dict(evaluatedAtUtc=self.wall_clock().isoformat(),
                maxAgeSeconds=None, sourceState="invalid", sessions=[]), self.client.host.limits)
            view = dict(sessions=[])
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            state, problem = "invalid", "source-or-capacity-invalid"
            body = self.mapper.convert(dict(evaluatedAtUtc=self.wall_clock().isoformat(),
                maxAgeSeconds=None, sourceState="invalid", sessions=[]), self.client.host.limits)
            view = dict(sessions=[])
        counts = self.report["sourceStates"]
        counts[state] = counts.get(state, 0) + 1
        if problem:
            counts = self.report["sourceProblems"]
            counts[problem] = counts.get(problem, 0) + 1
        observed = dict(Counter(entry["observed"] for entry in body["sessions"]))
        self.report["lastObservedCounts"] = observed
        self.report["lastDisplayedCounts"] = dict(Counter(entry["display"] for entry in body["sessions"]))
        if body["overallStatus"] != "unknown":
            self.report["nonUnknownSnapshotCycles"] += 1
        current = body["sessions"]
        if self.previous is not None and current != self.previous:
            self.report["observationChanges"] += 1
        self.previous = current
        timestamps = [entry.get("lastObservedAtUtc") for entry in view["sessions"]
                      if isinstance(entry.get("lastObservedAtUtc"), str)]
        latest = max(timestamps, default=None)
        prior = self.report["latestObservationAtUtc"]
        if latest is not None and (prior is None or latest > prior):
            self.report["observationTimestampAdvances"] += 1
            self.report["latestObservationAtUtc"] = latest
        reasons = Counter()
        if body["overallStatus"] == "unknown":
            for entry in view["sessions"]:
                if entry.get("displayStatus") == "unknown":
                    reason = entry.get("reason")
                    reasons[reason if isinstance(reason, str) and reason in SOURCE_REASONS
                            else (display_policy if reason is None and display_policy else "unclassified")] += 1
            source_reason = view.get("sourceReason")
            if isinstance(source_reason, str) and source_reason in SOURCE_REASONS:
                reasons[source_reason] += 1
            if not reasons:
                reasons[problem or display_policy or ("source-" + state if state != "readable"
                                                      else "delivery-budget-exhausted")] += 1
        self.unknown_reasons = dict(reasons)
        return body

    def step(self):
        self.report["cycles"] += 1
        try:
            if self.client.host is None:
                self._connect()
            challenge_seq = None
            if self.allow_fresh_display and self.client.host.freshness_challenge:
                challenge_seq = self.client.host.next_seq
                challenge = self.client.request("heartbeat", {})
                if not challenge["ok"]:
                    raise ProtocolError("freshness-challenge-rejected")
            body = self._body()
            if challenge_seq is not None and body["overallStatus"] != "unknown":
                body["challengeSeq"] = challenge_seq
            reply = self.client.request("snapshot", body)
            if not reply["ok"]:
                raise ProtocolError("snapshot-rejected")
            self.report["lastDeviceState"] = reply["state"]
            if reply["state"]["displayStatus"] not in (body["overallStatus"], "unknown"):
                raise ProtocolError("display-mismatch")
            if not self.allow_fresh_display and reply["state"]["displayStatus"] != "unknown":
                raise ProtocolError("observations-only-display-mismatch")
            device_display = reply["state"]["displayStatus"]
            displays = self.report["acknowledgedDeviceDisplays"]
            displays[device_display] = displays.get(device_display, 0) + 1
            if device_display == "unknown":
                reasons = (self.unknown_reasons if body["overallStatus"] == "unknown"
                           else {"device-display-unknown": 1})
                counts = Counter(self.report["unknownReasons"])
                counts.update(reasons)
                self.report["unknownReasons"] = dict(counts)
                self.report["lastUnknownSnapshot"] = dict(atUtc=self.wall_clock().isoformat(),
                                                          reasons=reasons)
            if device_display != "unknown" and self.report["firstNonUnknownAckAtUtc"] is None:
                self.report["firstNonUnknownAckAtUtc"] = self.wall_clock().isoformat()
            elif (device_display == "unknown" and self.report["firstNonUnknownAckAtUtc"] is not None
                  and self.report["firstUnknownAckAfterNonUnknownAtUtc"] is None):
                self.report["firstUnknownAckAfterNonUnknownAtUtc"] = self.wall_clock().isoformat()
            self.report["acknowledgedSnapshots"] += 1
            return True
        except (OSError, TimeoutError, ProtocolError) as error:
            if isinstance(error, ProtocolError) and str(error) == "device-reopened-reconnect-required":
                self.report["connectionResets"] += 1
            else:
                self.report["communicationErrors"] += 1
                self.report["lastCommunicationErrorType"] = type(error).__name__
            self.client.host = None
            return False
        finally:
            self.client.round_trips.clear()

    def release(self):
        try:
            host = self.client.host
            if host is None:
                if not self.report["connections"] and not self.report["cycles"]:
                    return
                self._connect()
            elif host.pending is not None or host.invalidated:
                self._connect()
            reply = (self.client.request("release", {"disconnect": True})
                     if getattr(self.client.host, "monitor_green_off", False) else self.client.release())
            self.report["lastDeviceState"] = reply["state"]
            self.report["releaseConfirmed"] = (reply["ok"] and reply["state"]["mode"] == "local"
                                                 and not reply["state"]["leaseActive"])
        except (OSError, TimeoutError, ProtocolError):
            self.report["releaseConfirmed"] = False
        finally:
            self.client.round_trips.clear()

    def run(self, *, duration_seconds=None, should_stop=lambda: False, wait=time.sleep):
        if duration_seconds is not None and (not math.isfinite(duration_seconds) or duration_seconds <= 0):
            raise ValueError("Duration must be finite and positive, or omitted")
        started = self.clock()
        try:
            while True:
                if should_stop():
                    self.report["stoppedBy"] = "stop-request"
                    break
                elapsed = self.clock() - started
                if duration_seconds is not None and elapsed >= duration_seconds:
                    self.report["stoppedBy"] = "duration"
                    break
                self.step()
                delay = self.interval
                if duration_seconds is not None:
                    delay = min(delay, max(0, duration_seconds - (self.clock() - started)))
                wait(delay)
        except KeyboardInterrupt:
            self.report["stoppedBy"] = "keyboard-interrupt"
        finally:
            self.release()
            self.report["elapsedSeconds"] = self.clock() - started
        return self.report


def main():
    parser = argparse.ArgumentParser(description="Foreground observations-only Codex USB bridge; no light commands")
    parser.add_argument("--port", required=True)
    parser.add_argument("--root", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "OmiPet/codex-monitor-probe-v2")
    parser.add_argument("--max-json-bytes", type=int, required=True)
    parser.add_argument("--max-sessions", type=int, required=True)
    parser.add_argument("--interval-seconds", type=positive_seconds, required=True)
    parser.add_argument("--timeout-seconds", type=positive_seconds, required=True)
    parser.add_argument("--retries", type=int, required=True)
    parser.add_argument("--duration-seconds", type=positive_seconds)
    parser.add_argument("--max-age-seconds", type=positive_seconds,
                        help="Explicit event age budget; requires process bindings")
    parser.add_argument("--process-bindings", type=Path,
                        help="Explicit session-to-process identities checked on every snapshot")
    parser.add_argument("--monitor-lights", action="store_true",
                        help="Report that the installed experimental firmware renders physical monitor LEDs")
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--protocol-trace", type=Path,
                        help="Write timestamped, parsed [PROTO] counters as JSON Lines")
    args = parser.parse_args()
    if args.retries < 0:
        parser.error("Retries must be nonnegative")
    if (args.max_age_seconds is None) != (args.process_bindings is None):
        parser.error("Freshness budget and process bindings must be supplied together")
    if args.monitor_lights and args.max_age_seconds is None:
        parser.error("Physical monitor LEDs require explicit freshness and process bindings")
    limits = Limits(args.max_json_bytes, args.max_sessions)
    health = Health(limits.max_json_bytes + 8)
    import serial
    stream = serial.Serial()
    stream.port, stream.baudrate = args.port, 115200
    stream.dtr = stream.rts = False
    stream.timeout = min(args.timeout_seconds, args.interval_seconds)
    stream.write_timeout = args.timeout_seconds
    client = UsbClient(stream, limits, timeout_seconds=args.timeout_seconds, retries=args.retries,
                       on_bytes=health.feed)
    def reopen():
        if stream.is_open:
            stream.close()
        stream.open()
    if args.max_age_seconds is None:
        reader = lambda: read_view(args.root)
    else:
        def reader():
            try:
                bindings = json.loads(args.process_bindings.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, UnicodeError):
                bindings = None
            return read_bound_view(args.root, bindings, max_age_seconds=args.max_age_seconds)
    delivery_reserve = ((args.timeout_seconds + stream.write_timeout) * (args.retries + 1)
                        if args.max_age_seconds is not None else 0)
    bridge = Bridge(client, reader, interval_seconds=args.interval_seconds, reopen=reopen,
                    allow_fresh_display=args.max_age_seconds is not None,
                    delivery_reserve_seconds=delivery_reserve)
    stopping = threading.Event()
    def should_stop():
        return stopping.is_set() or (args.stop_file is not None and args.stop_file.exists())
    report = bridge.report
    report.update(startedAtUtc=datetime.now(timezone.utc).isoformat(), port=args.port,
                  intervalSeconds=args.interval_seconds, timeoutSeconds=args.timeout_seconds,
                  retries=args.retries, requestedDurationSeconds=args.duration_seconds,
                  deliveryReserveSeconds=delivery_reserve)
    report["physicalLedControl"] = args.monitor_lights
    report["visualVerified"] = False
    args.report.parent.mkdir(parents=True, exist_ok=True)
    if args.protocol_trace is not None:
        args.protocol_trace.parent.mkdir(parents=True, exist_ok=True)
    trace_context = (args.protocol_trace.open("x", encoding="utf-8")
                     if args.protocol_trace is not None else nullcontext(None))
    with trace_context as trace, args.report.open("x", encoding="utf-8") as output:
        if trace is not None:
            def write_protocol_counter(sample):
                trace.write(json.dumps(sample, ensure_ascii=False) + "\n")
                trace.flush()
            health.protocol_counter_sink = write_protocol_counter
            report["protocolTrace"] = str(args.protocol_trace)
        try:
            if should_stop():
                report["stoppedBy"] = "stop-request"
            else:
                print("Bridge running: observations only; Ctrl+C or stop file to release.", flush=True)
                bridge.run(duration_seconds=args.duration_seconds, should_stop=should_stop, wait=stopping.wait)
            report["result"] = ("pass" if report["acknowledgedSnapshots"] > 0
                                and report["communicationErrors"] == 0 and report["releaseConfirmed"] else "incomplete")
            if report["result"] == "pass" and report["connectionResets"]:
                report["result"] = "pass-with-recovery"
        except Exception as error:
            report.update(result="fail", errorType=type(error).__name__)
            raise
        finally:
            if stream.is_open:
                stream.close()
            report.update(finishedAtUtc=datetime.now(timezone.utc).isoformat(), health=health.report)
            report["usbDiagnostics"] = client.diagnostics
            output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            output.flush()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["result"] in ("pass", "pass-with-recovery") else 1


if __name__ == "__main__":
    sys.exit(main())
