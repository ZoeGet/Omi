from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_multinet_commands import check_and_generate


class CommandGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.h"
        self.words = self.root / "build/commands.txt"
        self.generated = self.root / "include/generated.h"
        self.runtime = self.root / "runtime.h"
        original = Path(__file__).resolve().parents[2] / "include/multinet_command_recognizer.h"
        self.runtime.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
        self.commands = [(number, "ce shi " + chr(96 + number)) for number in range(1, 17)]

    def generate(self, commands):
        entries = ",\n".join(f'{{{number}, "{phrase}"}}' for number, phrase in commands)
        self.config.write_text("const auto kVoiceCommandPhrases[] = {" + entries + "};", encoding="utf-8")
        check_and_generate(self.config, self.words, self.runtime, self.generated)

    def test_missing_output_directories_are_created_and_both_outputs_match(self):
        self.generate(self.commands)
        self.assertEqual(self.words.read_text(encoding="utf-8"), "".join(f"{n} {p}\n" for n, p in self.commands))
        generated = self.generated.read_text(encoding="utf-8")
        for number, phrase in self.commands:
            self.assertIn(f'{{{number}, "{phrase}"}}', generated)
        self.assertIn('kGeneratedWakePhrasePinyin[] = "ce shi a"', generated)

    def test_invalid_configuration_produces_no_outputs(self):
        cases = [[], self.commands[1:], self.commands + [(17, self.commands[1][1])],
                 self.commands + [(17, "a" * 64)], self.commands + [(17, "ce3 shi")],
                 self.commands + [(17, "ce shi a")] * 185]
        for commands in cases:
            with self.subTest(commands=len(commands)):
                with self.assertRaises(ValueError):
                    self.generate(commands)
                self.assertFalse(self.words.exists())
                self.assertFalse(self.generated.exists())

    def test_runtime_id_mismatch_is_rejected_before_writing(self):
        text = self.runtime.read_text(encoding="utf-8")
        changed, count = re.subn(r"(kWakePhraseCommandId\s*=\s*)1\b", r"\g<1>99", text)
        self.assertEqual(count, 1)
        self.runtime.write_text(changed, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.generate(self.commands)
        self.assertFalse(self.words.exists())
        self.assertFalse(self.generated.exists())


if __name__ == "__main__":
    unittest.main()
