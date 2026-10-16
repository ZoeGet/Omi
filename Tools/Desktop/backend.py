import argparse
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controller import MAX_JSON_BYTES, default_monitor_root, validate_light
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
            elif event["kind"] == "command":
                self.busy = False
            elif event["kind"] == "pairing":
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
        if action == "poll":
            return None
        if action == "paired-devices":
            from wireless_pairing import PairingStore
            return [] if self.demo else PairingStore().devices()
        if action in ("pair", "verify-wireless"):
            fields = {"address", "code"} if action == "pair" else {"address"}
            if (self.demo or self.busy or self.pairing_worker and self.pairing_worker.is_alive()
                    or not isinstance(body, dict) or set(body) != fields
                    or any(not isinstance(value, str) or "\0" in value for value in body.values())):
                raise ValueError("invalid-pairing-request")
            from wireless_pairing import endpoint, pair_device, verify_device, PairingSocket
            address = endpoint(body["address"])
            code = body.get("code", "")
            if action == "pair" and (len(code) != 6 or not code.isascii() or not code.isdecimal()):
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
                    else:
                        verify_device(address, socket_factory=connect)
                    self.events.put(dict(kind="pairing", ok=True, command=action))
                except Exception:
                    #  网络异常可能包含对端内容，不把原始异常或配对码写入操作记录 / Network errors may contain peer data; never log raw exceptions or pairing codes
                    self.events.put(dict(kind="pairing", ok=False, command=action,
                        error="无线验证未完成：请核对地址、屏幕配对码和网络；若最后确认丢失，可点击验证连接。"))
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
        if action == "connect":
            if self.worker and self.worker.is_alive():
                raise ValueError("connection-already-open")
            if (not isinstance(body, dict) or set(body) != {"port", "root", "bindings"}
                    or any(not isinstance(value, str) or not value or "\0" in value for value in body.values())):
                raise ValueError("invalid-connection-settings")
            if body["port"] not in {port["device"] for port in self.ports()}:
                raise ValueError("port-not-found")
            self.worker = DeviceWorker(self.events, port=body["port"], root=Path(body["root"]),
                                       bindings=Path(body["bindings"]), demo=self.demo)
            self.busy = True
            self.worker.start()
            return None
        if action == "disconnect":
            if self.worker:
                self.busy = True
                self.worker.stop()
            return None
        if action in ("local", "monitor", "light"):
            if not self.connected or self.busy or not self.worker or not self.worker.is_alive():
                raise ValueError("device-not-ready")
            if action == "light":
                validate_light(body)
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
            if action not in ("connect", "light", "pair", "verify-wireless") and body is not None:
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
    main()
