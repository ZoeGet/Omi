import hashlib
from pathlib import Path
import sys
import unittest
import subprocess
import tempfile
import configparser

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Firmware/scripts"))
from usb_sof_fix import EXPECTED_SHA256, OLD_BLOCK, NEW_BLOCK, patch_source, tick_function


class SofFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path.home() / ".platformio/packages/framework-arduinoespressif32/cores/esp32/HWCDC.cpp"
        if not source.is_file():
            raise unittest.SkipTest("Audited installed HWCDC source unavailable")
        cls.original = source.read_bytes()

    def test_only_audited_counter_block_changes(self):
        fixed = patch_source(self.original).decode("utf-8")
        original = self.original.decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(fixed.replace(NEW_BLOCK, OLD_BLOCK), original)
        self.assertEqual(hashlib.sha256(self.original).hexdigest(), EXPECTED_SHA256)

    def test_threshold_and_tick_registration_unchanged(self):
        fixed = patch_source(self.original).decode("utf-8")
        self.assertIn("#define USJ_DISCONNECT_CONFIRM_PERIOD_MS    5", fixed)
        self.assertIn("esp_register_freertos_tick_hook(usb_serial_jtag_sof_tick_hook)", fixed)
        self.assertEqual(fixed.count(NEW_BLOCK), 1)

    def test_other_sdk_and_double_patch_rejected(self):
        for data in (self.original + b"\n", patch_source(self.original)):
            with self.assertRaises(ValueError):
                patch_source(data)

    def test_extracts_actual_sdk_function(self):
        function = tick_function(self.original.decode("utf-8"))
        self.assertIn(OLD_BLOCK, function)
        self.assertNotIn("ESP_SYSTEM_INIT_FN", function)

    def test_config_generator_requires_explicit_usb_opt_in(self):
        repository = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.ini"
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("create_experiment_config.py")),
                "--output", str(output), "--build-dir", str(repository / "Firmware/.pio/test-sof-config"),
                "--max-json-bytes", "4096", "--rx-bytes-per-loop", "64", "--max-json-depth", "8",
                "--sof-reset-fix"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_config_generator_preserves_stable_configuration(self):
        repository = Path(__file__).resolve().parents[3]
        stable = repository / "Firmware/platformio.ini"
        original = stable.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            for enabled in (False, True):
                output = Path(directory) / (str(enabled) + ".ini")
                arguments = [sys.executable, str(Path(__file__).with_name("create_experiment_config.py")),
                    "--output", str(output), "--build-dir", str(repository / "Firmware/.pio/test-sof-config"),
                    "--max-json-bytes", "4096", "--rx-bytes-per-loop", "64", "--max-json-depth", "8", "--usb",
                    "--max-sessions", "16", "--lease-ms", "5000", "--tx-buffer-bytes", "8192", "--write-wait-ms", "1"]
                if enabled:
                    arguments.append("--sof-reset-fix")
                result = subprocess.run(arguments, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                config = configparser.ConfigParser(interpolation=None)
                config.read(output, encoding="utf-8")
                options = config["env:esp32-s3-devkitc-1"]
                self.assertEqual("board_build.cmake_extra_args" in options, enabled)
                if enabled:
                    self.assertEqual(options["board_build.cmake_extra_args"], "-DOMIPET_USB_SOF_FIX=ON")
            self.assertEqual(stable.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
