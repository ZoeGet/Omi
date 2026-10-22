import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from collector import atomic_json, monitor_lock
from controller import default_monitor_root
from make_hooks import EVENTS
from state_view import LifecycleReader


def read_json(path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def codex_images():
    from host_observer import process_parents
    from process_probe import capture
    images = set()
    for pid in process_parents():
        try:
            image = capture(pid)["imagePath"]
            if Path(image).name.lower() == "codex.exe":
                images.add(image)
        except (OSError, ValueError):
            pass
    return sorted(images)


class MonitorSetup:
    def __init__(self, *, home=None, data=None, runtime=None, root=None):
        self.home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        self.data = Path(data or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OmiPet")
        self.root = Path(root or default_monitor_root()).resolve()
        self.hooks = self.home / "hooks.json"
        self.receipt = self.data / "monitor-setup.json"
        self.runtime = Path(runtime) if runtime else Path(sys.executable).parent if getattr(sys, "frozen", False) else None

    def configuration(self):
        value = read_json(self.hooks, {})
        if not isinstance(value, dict) or not isinstance(value.get("hooks", {}), dict):
            raise ValueError("hooks.json 格式无效，未修改原文件。")
        for groups in value.get("hooks", {}).values():
            if not isinstance(groups, list) or any(not isinstance(g, dict) or not isinstance(g.get("hooks"), list)
                    or any(not isinstance(h, dict) for h in g["hooks"]) for g in groups):
                raise ValueError("hooks.json 结构无法安全合并，未修改原文件。")
        return value

    def owned(self):
        value = read_json(self.receipt)
        if value is not None and (not isinstance(value, dict) or value.get("schema") != 1
                or value.get("home") != str(self.home.resolve()) or not isinstance(value.get("handlers"), dict)):
            raise ValueError("监控安装记录无效，请保留备份后检查。")
        if value is not None:
            try:
                if not isinstance(value["images"], list) or not isinstance(value.get("previousRuntimes", []), list):
                    raise ValueError()
                for record in value.get("previousRuntimes", []) + [value]:
                    if uuid.UUID(record["installationId"]).hex != record["installationId"]:
                        raise ValueError()
                    if not isinstance(record["files"], dict) or any(not isinstance(name, str)
                            or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
                            for name, sha in record["files"].items()):
                        raise ValueError()
                expected = (self.data / "monitor-runtime" / value["installationId"]).resolve()
                if Path(value["runtime"]).resolve() != expected:
                    raise ValueError()
                if set(value["handlers"]) != set(EVENTS) or any(not isinstance(h, dict)
                        or not isinstance(h.get("command"), str) or not isinstance(h.get("commandWindows"), str)
                        for h in value["handlers"].values()):
                    raise ValueError()
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                raise ValueError("监控安装记录损坏，原 Hook 未修改；请保留备份后检查。") from error
        return value

    def remove_owned(self, configuration, receipt):
        result = copy.deepcopy(configuration)
        for event, handler in receipt["handlers"].items():
            groups = result.get("hooks", {}).get(event, [])
            kept = []
            for group in groups:
                hooks = []
                removed = False
                for hook in group["hooks"]:
                    if hook == handler:
                        removed = True
                        continue
                    if hook.get("command") == handler["command"] or hook.get("commandWindows") == handler["commandWindows"]:
                        raise ValueError("Omi Hook 已被手动修改，停止操作以保留你的配置。")
                    hooks.append(hook)
                if hooks or not removed:
                    kept.append(dict(group, hooks=hooks))
            if kept:
                result["hooks"][event] = kept
            else:
                result.get("hooks", {}).pop(event, None)
        return result

    def legacy_hook(self, hook):
        commands = [hook[k] for k in ("command", "commandWindows") if k in hook]
        if hook.get("type") != "command" or not commands:
            return False
        expected = os.path.normcase(str((self.home / "hooks/omipet-monitor/collector.py").resolve()))
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        for command in commands:
            if not isinstance(command, str):
                return False
            count = ctypes.c_int()
            pointer = shell.CommandLineToArgvW(command, ctypes.byref(count))
            if not pointer:
                return False
            try:
                args = [pointer[i] for i in range(count.value)]
            finally:
                kernel.LocalFree(pointer)
            if (len(args) != 2 or Path(args[0]).name.lower() not in ("python.exe", "pythonw.exe", "python")
                    or os.path.normcase(str(Path(args[1]).resolve())) != expected):
                return False
        return True

    def remove_legacy(self, configuration):
        result = copy.deepcopy(configuration)
        for event in EVENTS:
            groups = []
            for group in result.get("hooks", {}).get(event, []):
                hooks = [h for h in group["hooks"] if not self.legacy_hook(h)]
                if hooks or not group["hooks"]:
                    groups.append(dict(group, hooks=hooks))
            if groups:
                result["hooks"][event] = groups
            else:
                result.get("hooks", {}).pop(event, None)
        return result

    def commit(self, configuration, receipt, before):
        self.data.mkdir(parents=True, exist_ok=True)
        backup = self.data / "monitor-backups" / uuid.uuid4().hex
        backup.mkdir(parents=True)
        if before is not None:
            (backup / "hooks.json").write_bytes(before)
        previous = self.receipt.read_bytes() if self.receipt.exists() else None
        if previous is not None:
            (backup / "monitor-setup.json").write_bytes(previous)
        self.home.mkdir(parents=True, exist_ok=True)
        if (self.hooks.read_bytes() if self.hooks.exists() else None) != before:
            raise ValueError("Codex 配置刚被其他程序修改，请重新检测后重试。")
        atomic_json(self.hooks, configuration)
        written = self.hooks.read_bytes()
        try:
            if receipt is None:
                self.receipt.unlink(missing_ok=True)
            else:
                atomic_json(self.receipt, receipt)
        except Exception:
            if self.hooks.read_bytes() == written:
                if before is None:
                    self.hooks.unlink()
                else:
                    temporary = self.hooks.with_name(f"hooks.omi-rollback-{uuid.uuid4().hex}.tmp")
                    temporary.write_bytes(before)
                    os.replace(temporary, self.hooks)
            raise
        return str(backup)

    def install(self, images):
        with monitor_lock(self.home / "omi-setup"):
            return self._install(images)

    def auto_update(self):
        with monitor_lock(self.home / "omi-setup"):
            receipt = self.owned()
            if not receipt:
                return None
            candidates = [Path(p).resolve() for p in codex_images() if Path(p).is_file()]
            images = list(receipt["images"])
            changed = False
            for index, image in enumerate(images):
                old = Path(image).resolve()
                if old in candidates:
                    continue
                if (old.name.lower() != "codex.exe" or not re.fullmatch(r"[a-fA-F0-9]{16}", old.parent.name)
                        or old.parent.parent.name.lower() != "bin"):
                    continue
                matches = [p for p in candidates if p.parent.parent == old.parent.parent
                           and re.fullmatch(r"[a-fA-F0-9]{16}", p.parent.name)]
                if len(matches) > 1:
                    return dict(state="manual-update", message="检测到多个 Codex 版本，请到设置选择需要监控的程序。")
                if matches:
                    images[index] = str(matches[0])
                    changed = True
            if changed:
                status = self.status()
                if not status.get("installed"):
                    return dict(state="manual-update", message="检测到 Codex 路径变化，但监控配置或组件校验异常，请到设置修复。")
                if any(not Path(p).is_file() for p in images):
                    return dict(state="manual-update", message="检测到 Codex 路径变化，其他已选程序不可用，请到设置确认程序列表。")
                runtime = self.runtime
                try:
                    self.runtime = Path(receipt["runtime"])
                    result = self._install(sorted(set(images)), automatic=True)
                finally:
                    self.runtime = runtime
                return dict(result, state="awaiting-event")
            if receipt.get("automaticUpdate"):
                status = self.status()
                return dict(state=status["state"], message=status["message"])
            return None

    def _install(self, images, automatic=False):
        if not self.runtime or not (self.runtime / "omi-device.exe").is_file():
            raise ValueError("请使用完整解压后的 Windows 发行包安装监控。")
        if (not isinstance(images, list) or not images or len(images) > 8
                or any(not isinstance(p, str) or "\0" in p or not Path(p).is_absolute()
                       or Path(p).name.lower() != "codex.exe" or not Path(p).is_file() for p in images)):
            raise ValueError("请选择真实的 Codex.exe；多个版本最多选择 8 个。")
        before = self.hooks.read_bytes() if self.hooks.exists() else None
        configuration = self.configuration()
        toml = self.home / "config.toml"
        if toml.is_file():
            text = re.sub(r"\\+", "/", toml.read_text(encoding="utf-8-sig")).lower()
            if "omipet-monitor" in text or "--collect-hook" in text:
                raise ValueError("config.toml 中存在旧 Omi 入口，无法自动确认归属；请先在 Codex 停用旧入口，原文件未修改。")
        old = self.owned()
        if old:
            configuration = self.remove_owned(configuration, old)
        else:
            configuration = self.remove_legacy(configuration)
        legacy = str(self.home / "hooks" / "omipet-monitor").replace("\\", "/").lower()
        for groups in configuration.get("hooks", {}).values():
            for group in groups:
                for hook in group["hooks"]:
                    command = str(hook.get("commandWindows") or hook.get("command") or "").replace("\\", "/").lower()
                    if legacy in command or "--collect-hook" in command:
                        raise ValueError("检测到旧版或未归属的 Omi Hook；请先在 Codex 中停用并移除旧处理器，再安装，避免重复采集。")
        installation = uuid.uuid4().hex
        destination = self.data / "monitor-runtime" / installation
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.runtime, destination)
        atomic_json(destination / "host-binding-config.json", dict(enabled=True,
            allowedImages=sorted(set(str(Path(p).resolve()) for p in images)), maxSessions=16,
            root=str(self.root), installationId=installation))
        files = {str(p.relative_to(destination)): digest(p) for p in destination.rglob("*") if p.is_file()}
        command = subprocess.list2cmdline([str(destination.resolve() / "omi-device.exe"), "--collect-hook"])
        handlers = {event: dict(type="command", command=command, commandWindows=command, timeout=3,
                               **{"async": event not in ("SessionStart", "Stop", "SessionEnd")}) for event in EVENTS}
        for event, handler in handlers.items():
            configuration.setdefault("hooks", {}).setdefault(event, []).append(dict(hooks=[handler]))
        receipt = dict(schema=1, home=str(self.home.resolve()), installationId=installation,
                       runtime=str(destination.resolve()), files=files, handlers=handlers, images=images,
                       automaticUpdate=automatic,
                       previousRuntimes=old.get("previousRuntimes", []) + [dict(
                           installationId=old["installationId"], files=old["files"])] if old else [])
        backup = self.commit(configuration, receipt, before)
        return dict(backup=backup, root=str(self.root), bindings=str(self.root / "host-bindings.json"),
                    message=("检测到 Codex 版本目录变化，已备份并自动更新监控。请在 Codex 审查并信任新 Omi Hook；若未出现，请重新加载配置或重启 Codex，再执行一次普通工具操作。"
                             if automatic else "监控组件已安装。请在 Codex 审查并信任 Omi Hook，再发送一条消息并重新检测。"))

    def uninstall(self):
        with monitor_lock(self.home / "omi-setup"):
            return self._uninstall()

    def _uninstall(self):
        old = self.owned()
        if not old:
            return dict(message="没有由本程序管理的监控安装。")
        before = self.hooks.read_bytes() if self.hooks.exists() else None
        configuration = self.remove_owned(self.configuration(), old)
        backup = self.commit(configuration, None, before)
        retained = False
        base = (self.data / "monitor-runtime").resolve()
        for record in old.get("previousRuntimes", []) + [old]:
            installation = record["installationId"]
            if not isinstance(installation, str) or uuid.UUID(installation).hex != installation:
                retained = True
                continue
            directory = base / installation
            if not directory.exists():
                continue
            if directory.resolve().parent != base:
                retained = True
                continue
            for name, sha in record["files"].items():
                path = directory / name
                try:
                    if path.resolve().is_relative_to(directory) and path.is_file() and digest(path) == sha:
                        path.unlink()
                    elif path.exists():
                        retained = True
                except OSError:
                    retained = True
            for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                if path.is_dir() and path.resolve().is_relative_to(directory):
                    try:
                        path.rmdir()
                    except OSError:
                        pass
            try:
                directory.rmdir()
            except OSError:
                retained = True
        return dict(backup=backup, message="已移除 Omi Hook 和未修改的采集组件；保留备份与历史状态，不影响其他 Hook。"
                    + (" 部分运行时文件被占用或已修改，已保留。" if retained else ""))

    def status(self):
        result = dict(state="not-installed", installed=False, hookReceived=False, message="尚未配置 Codex 监控", packaged=self.runtime is not None,
                      home=str(self.home), root=str(self.root), candidates=[])
        try:
            result["candidates"] = codex_images()
            configuration = self.configuration()
            receipt = self.owned()
            if not receipt:
                return result
            result["images"] = receipt["images"]
            for event, handler in receipt["handlers"].items():
                if sum(h == handler for g in configuration.get("hooks", {}).get(event, []) for h in g["hooks"]) != 1:
                    return dict(result, state="repair", message="监控 Hook 缺失或重复，请修复配置。")
            destination = Path(receipt["runtime"])
            expected = (self.data / "monitor-runtime" / receipt["installationId"]).resolve()
            if destination.resolve() != expected:
                raise ValueError("运行时路径与安装记录不匹配。")
            for name, sha in receipt["files"].items():
                path = destination / name
                if not path.resolve().is_relative_to(expected) or not path.is_file() or digest(path) != sha:
                    return dict(result, state="repair", message="监控组件缺失或损坏，请修复安装。")
            result["installed"] = True
            marker = read_json(self.root / "hook-receipt.json", {})
            if marker.get("installationId") != receipt["installationId"]:
                return dict(result, state="awaiting-event", message=(
                    "Codex 版本目录已自动更新。请在 Codex 审查并信任新 Omi Hook；若未出现，请重新加载配置或重启 Codex，再执行一次普通工具操作。"
                    if receipt.get("automaticUpdate") else "已配置，等待信任和新事件；安装成功不代表 Hook 已受信任。"))
            result["hookReceived"] = True
            view = LifecycleReader(self.root, self.root / "host-bindings.json", max_age_seconds=30)()
            if any(e.get("sessionId") == marker.get("sessionId") and e.get("hostProcessState") == "running"
                   and e.get("reason") == "observed-lifecycle" for e in view["sessions"]):
                return dict(result, state="ready", message="已收到真实事件，Codex 宿主关联正常。")
            return dict(result, state="awaiting-binding", message="采集器已收到事件，等待新的工具事件确认宿主关联；请让 Codex 执行一个普通操作后重新检测。")
        except (OSError, ValueError, KeyError, TypeError) as error:
            return dict(result, state="error", message=str(error))
