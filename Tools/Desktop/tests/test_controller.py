from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import ControlSession, SimulatedClient, demo_reader
from protocol import ProtocolError


def setting(**changes):
    return dict(dict(effect="solid", red=0, green=0, blue=255, brightness=16), **changes)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.client = SimulatedClient()
        self.control = ControlSession(self.client, demo_reader)
        self.control.connect()

    def test_manual_control_is_blocked_until_monitor_release(self):
        self.control.monitor()
        self.assertEqual(self.control.state["mode"], "monitor")
        with self.assertRaisesRegex(ProtocolError, "monitor-mode-active"):
            self.control.light(setting())
        self.assertEqual(self.client.device.applied_lights, 0)
        self.control.local()
        self.control.light(setting())
        self.assertEqual(self.client.device.local_light, setting())

    def test_old_firmware_never_receives_unknown_light_operation(self):
        self.control.operations.remove("light")
        with self.assertRaisesRegex(ProtocolError, "light-command-not-supported"):
            self.control.light(setting())
        self.assertEqual(self.client.device.applied_lights, 0)

    def test_invalid_or_voice_blocked_setting_is_not_recorded_as_success(self):
        with self.assertRaises(ProtocolError):
            self.control.light(setting(brightness=True))
        self.client.device.voice_active = True
        with self.assertRaisesRegex(ProtocolError, "voice-active"):
            self.control.light(setting())
        self.assertIsNone(self.control.last_light)
        self.assertEqual(self.client.device.applied_lights, 0)

    def test_duplicate_request_does_not_apply_twice(self):
        request = self.client.host.prepare("light", setting())
        first = self.client.device.receive(request, self.client.now())
        duplicate = self.client.device.receive(request, self.client.now())
        self.assertTrue(first["body"]["ok"])
        self.assertTrue(duplicate["body"]["duplicate"])
        self.assertEqual(self.client.device.applied_lights, 1)

    def test_release_recovers_pending_request_without_replaying_light(self):
        self.control.monitor()
        self.client.host.prepare("heartbeat", {})
        self.control.local()
        self.assertFalse(self.control.monitor_requested)
        self.assertEqual(self.control.state["mode"], "local")
        self.assertFalse(self.control.state["leaseActive"])
        self.assertEqual(self.client.device.applied_lights, 0)

    def test_disconnect_preserves_local_light_and_monitor_reentry_has_new_revision_space(self):
        self.control.light(setting())
        self.control.monitor()
        self.control.local()
        self.control.monitor()
        self.assertEqual(self.control.state["mode"], "monitor")
        self.client.device.disconnect()
        self.assertEqual(self.client.device.local_light, setting())

    def test_monitor_close_turns_off_but_explicit_local_retains_setting(self):
        self.control.light(setting())
        self.control.monitor()
        self.control.close()
        self.assertEqual(self.client.device.monitor_output(), "disconnected")
        self.assertEqual(self.client.device.local_light, setting())
        self.control.connect()
        self.assertEqual(self.client.device.monitor_output(), "local")

    def test_source_failure_keeps_protocol_unknown_and_connected(self):
        self.control.reader = lambda: (_ for _ in ()).throw(OSError("source unavailable"))
        self.control.monitor()
        self.assertEqual(self.control.state["displayStatus"], "unknown")
        self.assertEqual(self.control.state["monitorOutput"], "connected")

    def test_voice_takeover_exits_desktop_monitor_and_preserves_local_on_close(self):
        self.control.light(setting())
        self.control.monitor()
        self.client.device.yield_monitor_to_voice()
        self.control.tick()
        self.assertFalse(self.control.monitor_requested)
        self.control.close()
        self.assertEqual(self.client.device.monitor_output(), "local")


if __name__ == "__main__":
    unittest.main()
