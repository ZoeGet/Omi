import json
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor_setup import MonitorSetup, read_json
from make_hooks import EVENTS


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.runtime = self.base / "portable" / "omi-device"
        self.runtime.mkdir(parents=True)
        (self.runtime / "omi-device.exe").write_bytes(b"test runtime")
        (self.runtime / "_internal").mkdir()
        (self.runtime / "_internal" / "python.dll").write_bytes(b"test dependency")
        self.image = self.base / "Codex.exe"
        self.image.write_bytes(b"test image")
        self.setup = MonitorSetup(home=self.base / "codex", data=self.base / "data", runtime=self.runtime,
                                  root=self.base / "state")
        self.images = patch("monitor_setup.codex_images", return_value=[str(self.image)])
        self.images.start()
        self.addCleanup(self.images.stop)
        self.other = dict(hooks={"Stop": [dict(matcher="*", hooks=[dict(type="command", command="other-tool")])]}, extra=True)
        self.setup.home.mkdir()
        self.setup.hooks.write_text(json.dumps(self.other), encoding="utf-8-sig")

    def install(self):
        return self.setup.install([str(self.image)])

    def version_image(self, version, family="Codex"):
        image = self.base / family / "bin" / version / "codex.exe"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"test codex")
        return image

    def test_auto_update_replaces_only_same_family_and_preserves_other_hooks(self):
        old = self.version_image("a" * 16)
        new = self.version_image("b" * 16)
        self.setup.install([str(old), str(self.image)])
        before = self.setup.hooks.read_bytes()
        receipt = self.setup.owned()
        old.unlink()
        with patch("monitor_setup.codex_images", return_value=[str(new), str(self.image)]):
            result = self.setup.auto_update()
            updated = self.setup.owned()
            self.assertEqual(result["state"], "awaiting-event")
            self.assertIn("信任", result["message"])
            self.assertEqual({Path(p) for p in updated["images"]}, {new, self.image})
            self.assertNotEqual(updated["installationId"], receipt["installationId"])
            self.assertEqual((Path(result["backup"]) / "hooks.json").read_bytes(), before)
            self.assertEqual(read_json(self.setup.hooks)["hooks"]["Stop"][0], self.other["hooks"]["Stop"][0])
            self.assertTrue(updated["automaticUpdate"])
            self.assertEqual(self.setup.auto_update()["state"], "awaiting-event")
            self.assertEqual(self.setup.owned(), updated)
            self.setup.root.mkdir(exist_ok=True)
            (self.setup.root / "hook-receipt.json").write_text(json.dumps(dict(
                installationId=updated["installationId"], sessionId="current")), encoding="utf-8")
            with patch("monitor_setup.LifecycleReader") as reader:
                reader.return_value.return_value = dict(sessions=[dict(
                    sessionId="current", hostProcessState="running", reason="observed-lifecycle")])
                self.assertEqual(self.setup.auto_update()["state"], "ready")

    def test_auto_update_does_not_install_or_guess_unrelated_or_multiple_versions(self):
        old = self.version_image("a" * 16)
        new = self.version_image("b" * 16)
        other = self.version_image("c" * 16, "Unrelated")
        with patch("monitor_setup.codex_images", return_value=[str(new)]):
            self.assertIsNone(self.setup.auto_update())
        self.setup.install([str(old)])
        before = self.setup.hooks.read_bytes()
        for candidates in ([], [str(other)], [str(old), str(new)]):
            with patch("monitor_setup.codex_images", return_value=candidates):
                self.assertIsNone(self.setup.auto_update())
            self.assertEqual(self.setup.hooks.read_bytes(), before)
        another = self.version_image("d" * 16)
        with patch("monitor_setup.codex_images", return_value=[str(new), str(another)]):
            self.assertEqual(self.setup.auto_update()["state"], "manual-update")
        self.assertEqual(self.setup.hooks.read_bytes(), before)

    def test_auto_update_stops_on_corruption_or_modified_hooks(self):
        old = self.version_image("a" * 16)
        new = self.version_image("b" * 16)
        self.setup.install([str(old)])
        before = self.setup.hooks.read_bytes()
        exe = Path(self.setup.owned()["runtime"]) / "omi-device.exe"
        exe.write_bytes(b"modified")
        with patch("monitor_setup.codex_images", return_value=[str(new)]):
            self.assertEqual(self.setup.auto_update()["state"], "manual-update")
        self.assertEqual(self.setup.hooks.read_bytes(), before)
        self.setup.install([str(old)])
        configuration = read_json(self.setup.hooks)
        configuration["hooks"]["Stop"][-1]["hooks"][0]["timeout"] = 99
        self.setup.hooks.write_text(json.dumps(configuration), encoding="utf-8")
        before = self.setup.hooks.read_bytes()
        with patch("monitor_setup.codex_images", return_value=[str(new)]):
            self.assertEqual(self.setup.auto_update()["state"], "manual-update")
        self.assertEqual(self.setup.hooks.read_bytes(), before)

    def test_install_repair_preserve_others_backup_and_independent_runtime(self):
        original = self.setup.hooks.read_bytes()
        reply = self.install()
        self.assertEqual((Path(reply["backup"]) / "hooks.json").read_bytes(), original)
        first = self.setup.owned()
        self.assertEqual(read_json(self.setup.hooks)["hooks"]["Stop"][0], self.other["hooks"]["Stop"][0])
        self.assertEqual(self.setup.status()["state"], "awaiting-event")
        self.install()
        second = self.setup.owned()
        self.assertNotEqual(first["runtime"], second["runtime"])
        self.assertEqual(len(second["previousRuntimes"]), 1)
        configuration = read_json(self.setup.hooks)
        self.assertEqual(sum(len(g["hooks"]) for groups in configuration["hooks"].values() for g in groups), len(EVENTS) + 1)
        (self.runtime / "omi-device.exe").unlink()
        self.assertEqual(self.setup.status()["state"], "awaiting-event")
        self.assertTrue((Path(second["runtime"]) / "omi-device.exe").is_file())
        self.setup.uninstall()
        self.assertEqual(read_json(self.setup.hooks), self.other)
        self.assertFalse(Path(first["runtime"]).exists())
        self.assertFalse(Path(second["runtime"]).exists())
        self.assertEqual(self.setup.status()["state"], "not-installed")

    def test_modified_own_hook_is_never_removed_or_overwritten(self):
        self.install()
        configuration = read_json(self.setup.hooks)
        configuration["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 12
        self.setup.hooks.write_text(json.dumps(configuration), encoding="utf-8")
        original = self.setup.hooks.read_bytes()
        for action in (self.install, self.setup.uninstall):
            with self.assertRaisesRegex(ValueError, "手动修改"):
                action()
            self.assertEqual(self.setup.hooks.read_bytes(), original)

    def test_damaged_runtime_and_missing_handlers_request_repair(self):
        self.install()
        runtime = Path(self.setup.owned()["runtime"])
        (runtime / "omi-device.exe").write_bytes(b"changed")
        self.assertEqual(self.setup.status()["state"], "repair")
        self.install()
        configuration = read_json(self.setup.hooks)
        configuration["hooks"].pop("SessionStart")
        self.setup.hooks.write_text(json.dumps(configuration), encoding="utf-8")
        self.assertEqual(self.setup.status()["state"], "repair")
        self.install()
        self.assertEqual(self.setup.status()["state"], "awaiting-event")
        self.setup.uninstall()
        self.assertEqual((runtime / "omi-device.exe").read_bytes(), b"changed")

    def test_damaged_install_receipt_cannot_remove_hooks_or_runtime(self):
        self.install()
        receipt = self.setup.owned()
        receipt['previousRuntimes'] = [dict(installationId='../outside', files={})]
        self.setup.receipt.write_text(json.dumps(receipt), encoding='utf-8')
        before = self.setup.hooks.read_bytes()
        self.assertEqual(self.setup.status()['state'], 'error')
        with self.assertRaisesRegex(ValueError, '安装记录损坏'):
            self.setup.uninstall()
        self.assertEqual(self.setup.hooks.read_bytes(), before)

    def test_invalid_configuration_and_legacy_hooks_are_not_overwritten(self):
        cases = [b"{broken", b"[]", b'{"hooks":{"Stop":{}}}', json.dumps(dict(hooks={"Stop": [dict(hooks=[dict(
            type="command", command=f'python "{self.setup.home / "hooks/omipet-monitor/collector.py"}" --unexpected')])]})).encode()]
        for data in cases:
            self.setup.hooks.write_bytes(data)
            with self.assertRaises(ValueError):
                self.install()
            self.assertEqual(self.setup.hooks.read_bytes(), data)

    def test_known_legacy_migrates_but_preserves_other_handlers_and_original_backup(self):
        legacy = dict(type="command", command=f'python "{self.setup.home / "hooks/omipet-monitor/collector.py"}"')
        configuration = self.other.copy()
        configuration["hooks"] = dict(Stop=[dict(hooks=[legacy, dict(type="command", command="other-tool")])])
        self.setup.hooks.write_text(json.dumps(configuration), encoding="utf-8")
        before = self.setup.hooks.read_bytes()
        reply = self.install()
        hooks = read_json(self.setup.hooks)["hooks"]["Stop"]
        self.assertEqual(hooks[0]["hooks"], [dict(type="command", command="other-tool")])
        self.assertEqual(len(hooks), 2)
        self.assertEqual((Path(reply["backup"]) / "hooks.json").read_bytes(), before)

    def test_inline_legacy_configuration_requires_review_and_is_preserved(self):
        toml = self.setup.home / 'config.toml'
        toml.write_text('command = "old-omipet-monitor"', encoding='utf-8')
        before = self.setup.hooks.read_bytes()
        with self.assertRaisesRegex(ValueError, 'config.toml'):
            self.install()
        self.assertEqual(self.setup.hooks.read_bytes(), before)
        self.assertEqual(toml.read_text(), 'command = "old-omipet-monitor"')

    def test_embedded_hook_collects_privately_without_decision_output(self):
        import hook_runner
        import collector
        self.install()
        receipt = self.setup.owned()
        exe = Path(receipt['runtime']) / 'omi-device.exe'
        payload = dict(session_id='setup-test', turn_id='t1', hook_event_name='UserPromptSubmit',
                       prompt='PRIVATE_CONTENT', tool_input={'command': 'PRIVATE_CONTENT'})
        valid = json.dumps(payload).encode()
        for source in (valid, b'invalid-json', b'{}'):
            marker = self.setup.root / 'hook-receipt.json'
            marker.unlink(missing_ok=True)
            with patch.object(collector, 'collect', collector.collect), patch.dict('os.environ'), \
                 patch('sys.executable', str(exe)), patch('sys.stdin', io.TextIOWrapper(io.BytesIO(source))), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(hook_runner.main(), 0)
                self.assertEqual(output.getvalue(), '')
            self.assertEqual(marker.exists(), source == valid)
        for path in self.setup.root.glob('*.json*'):
            self.assertNotIn('PRIVATE_CONTENT', path.read_text(encoding='utf-8'))

    def test_invalid_images_and_source_mode_do_not_write_hooks(self):
        for images in ([], [str(self.base / "missing.exe")], [str(self.runtime / "omi-device.exe")], [str(self.image)] * 9, [None]):
            with self.assertRaises(ValueError):
                self.setup.install(images)
        self.assertEqual(read_json(self.setup.hooks), self.other)
        self.setup.runtime = None
        with self.assertRaisesRegex(ValueError, "发行包"):
            self.install()

    def test_receipt_write_failure_restores_original_hooks(self):
        original = self.setup.hooks.read_bytes()
        from monitor_setup import atomic_json
        def fail(path, value):
            if path == self.setup.receipt:
                raise OSError("receipt failed")
            atomic_json(path, value)
        with patch("monitor_setup.atomic_json", side_effect=fail):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(self.setup.hooks.read_bytes(), original)
        self.assertFalse(self.setup.receipt.exists())

    def test_concurrent_configuration_change_is_preserved(self):
        before = self.setup.hooks.read_bytes()
        self.setup.hooks.write_text('{"other":"changed"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "其他程序"):
            self.setup.commit({}, None, before)
        self.assertEqual(read_json(self.setup.hooks), dict(other="changed"))

    def test_old_receipts_do_not_prove_trust_or_ready_and_only_live_binding_is_ready(self):
        self.install()
        self.setup.root.mkdir()
        marker = self.setup.root / "hook-receipt.json"
        marker.write_text(json.dumps(dict(installationId="old")), encoding="utf-8")
        self.assertEqual(self.setup.status()["state"], "awaiting-event")
        self.assertTrue(self.setup.status()['installed'])
        self.assertFalse(self.setup.status()['hookReceived'])
        marker.write_text(json.dumps(dict(installationId=self.setup.owned()["installationId"], sessionId='current')), encoding="utf-8")
        with patch("monitor_setup.LifecycleReader") as reader:
            reader.return_value.return_value = dict(sessions=[])
            self.assertEqual(self.setup.status()["state"], "awaiting-binding")
            self.assertTrue(self.setup.status()['hookReceived'])
            reader.return_value.return_value = dict(sessions=[dict(sessionId='other', hostProcessState="running", reason="observed-lifecycle")])
            self.assertEqual(self.setup.status()["state"], "awaiting-binding")
            reader.return_value.return_value = dict(sessions=[dict(sessionId='current', hostProcessState="running", reason="observed-lifecycle")])
            self.assertEqual(self.setup.status()["state"], "ready")


if __name__ == "__main__":
    unittest.main()
