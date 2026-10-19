import argparse
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controller import MAX_JSON_BYTES, default_monitor_root, validate_light, validate_monitor_profile
from worker import DeviceWorker


class EventBuffer:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}

    def put(self, event):
        #  保留各类最新事件及其顺序，后台窗口暂停时不积压状态 / Keep each latest event in order without accumulating status while the window is suspended
        with self.lock:
            self.pending.pop(event["kind"], None)
            self.pending[event["kind"]] = event

    def drain(self):
        with self.lock:
            events = list(self.pending.values())
            self.pending.clear()
        return events


class Backend:
    def __init__(self, *, demo=False):
        self.demo = demo
        self.events = EventBuffer()
        self.worker = None
        self.pairing_worker = None
        self.pairing_socket = None
        self.pairing_stop = threading.Event()
        self.connected = self.busy = False

    def ports(self):
        if self.demo:
            return [dict(device="demo", description="演示设备")]
        from serial.tools import list_ports
        return [dict(device=item.device, description=item.description) for item in list_ports.comports()]

    def drain(self):
        events = self.events.drain()
        for event in events:
            if event["kind"] == "connected":
                self.connected, self.busy = True, False
            elif event["kind"] == "disconnected":
                self.connected = self.busy = False
            elif event["kind"] in ("command", "pairing"):
                self.busy = False
        return events

    def close(self):
        if self.pairing_worker:
            self.pairing_stop.set()
            if self.pairing_socket:
                self.pairing_socket.close()
            self.pairing_worker.join()
            self.pairing_worker = None
        if self.worker:
            self.worker.stop()
            #  等待原工作线程完成既有释放流程，不增加另一套超时 / Wait for the existing worker release flow without introducing another timeout
            self.worker.join()
            self.worker = None

    def dispatch(self, action, body):
        if action == "init":
            root = default_monitor_root()
            return dict(demo=self.demo, root=str(root), bindings=str(root / "host-bindings.json"), ports=self.ports())
        if action == "ports":
            return self.ports()
        if action in ("monitor-setup-status", "monitor-setup-install", "monitor-setup-uninstall"):
            from monitor_setup import MonitorSetup
            setup = MonitorSetup()
            if action == "monitor-setup-status":
                return setup.status()
            if self.demo or self.connected or self.busy or self.worker and self.worker.is_alive():
                raise ValueError("请断开设备后配置监控；演示模式不修改 Codex 配置。")
            if action == "monitor-setup-install":
                if not isinstance(body, dict) or set(body) != {"images"}:
                    raise ValueError("invalid-monitor-setup-request")
                return setup.install(body["images"])
            return setup.uninstall()
        if action == "poll":
            return None
        if action == "paired-devices":
            from wireless_pairing import PairingStore
            return [] if self.demo else PairingStore().devices()
        if action in ("pair", "re-pair", "verify-wireless", "find-wireless", "relocate-wireless"):
            fields = {"address", "code"} if action in ("pair", "re-pair") else {"address", "previous"} if action == "relocate-wireless" else {"address"}
            if (self.demo or self.busy or self.connected or self.pairing_worker and self.pairing_worker.is_alive()
                    or not isinstance(body, dict) or set(body) != fields
                    or any(not isinstance(value, str) or "\0" in value for value in body.values())):
                raise ValueError("invalid-pairing-request")
            from wireless_pairing import endpoint, pair_device, verify_device, relocate_device, PairingSocket
            address = endpoint(body["address"])
            previous = endpoint(body["previous"]) if action == "relocate-wireless" else None
            code = body.get("code", "")
            if action in ("pair", "re-pair") and (len(code) != 6 or not code.isascii() or not code.isdecimal()):
                raise ValueError("配对码必须为六位数字")
            def run_pairing():
                try:
                    def connect(address, pin=None):
                        wire = PairingSocket(address, pin)
                        self.pairing_socket = wire
                        if self.pairing_stop.is_set():
                            wire.close()
                            raise ConnectionError("cancelled")
                        return wire
                    if action == "pair":
                        pair_device(address, code, socket_factory=connect)
                    elif action == "re-pair":
                        pair_device(address, code, socket_factory=connect, replace=True)
                    elif action == "find-wireless":
                        from wireless_discovery import find_device
                        address_found = find_device(address, stop=self.pairing_stop, socket_factory=connect)
                    elif action == "relocate-wireless":
                        address_found = relocate_device(previous, address, socket_factory=connect, stop=self.pairing_stop)
                    else:
                        verify_device(address, socket_factory=connect)
                    self.events.put(dict(kind="pairing", ok=True, command=action,
                                         port=address_found if action in ("find-wireless", "relocate-wireless") else address))
                except Exception:
                    #  网络异常可能包含对端内容，不把原始异常或配对码写入操作记录 / Network errors may contain peer data; never log raw exceptions or pairing codes
                    self.events.put(dict(kind="pairing", ok=False, command=action,
                        error=("重新配对未确认完成：需升级配套固件与语音模型。请唤醒设备后说“开启配对模式”，用屏幕当前地址和新码重试；码有效5分钟，最多5次。若提交后断开，请先验证连接恢复；不要删除原记录。"
                               if action == "re-pair" else "未能在当前网络验证原设备。原配对记录已保留；请确认设备在线、没有其他电脑占用连接、网络未开启客户端隔离，再重试或手动更新地址。"
                               if action in ("find-wireless", "relocate-wireless") else
                               "无线验证未完成：已配对设备换网后，请点击重新查找设备；首次配对请核对地址和六位码。")))
                finally:
                    self.pairing_socket = None
            self.busy = True
            self.pairing_stop.clear()
            self.pairing_worker = threading.Thread(target=run_pairing, name="omi-pairing")
            self.pairing_worker.start()
            return None
        if action == "close":
            self.close()
            return None
        if action in ("connect", "connect-wireless"):
            if self.worker and self.worker.is_alive():
                raise ValueError("connection-already-open")
            if (not isinstance(body, dict) or set(body) != {"port", "root", "bindings"}
                    or any(not isinstance(value, str) or not value or "\0" in value for value in body.values())):
                raise ValueError("invalid-connection-settings")
            wireless = action == "connect-wireless"
            if wireless:
                from wireless_pairing import PairingStore, endpoint
                if self.demo or self.busy or not PairingStore().load(endpoint(body["port"])):
                    raise ValueError("wireless-pairing-required")
            elif body["port"] not in {port["device"] for port in self.ports()}:
                raise ValueError("port-not-found")
            self.worker = DeviceWorker(self.events, port=body["port"], root=Path(body["root"]),
                                       bindings=Path(body["bindings"]), demo=self.demo, wireless=wireless)
            self.busy = True
            self.worker.start()
            return None
        if action == "disconnect":
            if self.worker:
                self.busy = True
                self.worker.stop()
            return None
        if action in ("local", "monitor", "light", "monitor-profile", "monitor-profile-read"):
            if not self.connected or self.busy or not self.worker or not self.worker.is_alive():
                raise ValueError("device-not-ready")
            if action == "light":
                validate_light(body)
            if action == "monitor-profile":
                validate_monitor_profile(body)
            self.worker.submit(action, body)
            self.busy = True
            return None
        raise ValueError("unknown-command")

    def call(self, message):
        events = self.drain()
        try:
            if (not isinstance(message, dict) or set(message) != {"action", "body"}
                    or not isinstance(message["action"], str)):
                raise ValueError("invalid-request")
            action, body = message["action"], message["body"]
            if action not in ("connect", "connect-wireless", "light", "monitor-profile", "pair", "re-pair", "verify-wireless", "find-wireless", "relocate-wireless", "monitor-setup-install") and body is not None:
                raise ValueError("unexpected-body")
            result = dict(ok=True, result=self.dispatch(action, body))
        except Exception as error:
            result = dict(ok=False, error=str(error))
        return dict(result, events=events + self.drain())


def main():
    parser = argparse.ArgumentParser(description="OmiPet device worker over local stdio")
    parser.add_argument("--demo", action="store_true")
    backend = Backend(demo=parser.parse_args().demo)
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        while line := sys.stdin.buffer.readline(MAX_JSON_BYTES + 2):
            try:
                if len(line) > MAX_JSON_BYTES + 1 or not line.endswith(b"\n"):
                    while line and not line.endswith(b"\n"):
                        line = sys.stdin.buffer.readline(MAX_JSON_BYTES + 2)
                    raise ValueError("request-too-large-or-incomplete")
                message = json.loads(line)
                reply = backend.call(message)
            except (ValueError, UnicodeError, RecursionError):
                message = None
                reply = dict(ok=False, error="invalid-json-request", events=backend.drain())
            print(json.dumps(reply, ensure_ascii=False, allow_nan=False), flush=True)
            if reply["ok"] and message["action"] == "close":
                break
    finally:
        #  宿主异常退出导致管道 EOF 时也释放设备 / Release the device when host termination closes the pipe
        backend.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["--collect-hook"]:
        from hook_runner import main as collect_hook
        sys.exit(collect_hook())
    else:
        main()
