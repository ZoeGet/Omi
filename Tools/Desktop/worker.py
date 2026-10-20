import queue
import threading
import time

from controller import ControlSession, SimulatedClient, demo_reader, open_usb, open_wifi

RECONNECT_DELAYS = (2, 4, 8, 16, 30)


class DeviceWorker(threading.Thread):
    def __init__(self, events, *, port, root, bindings, demo=False, wireless=False):
        super().__init__(name="OmiPet device", daemon=False)
        self.events = events
        self.commands = queue.Queue(maxsize=1)
        self.command_lock = threading.Lock()
        self.recovering = False
        self.stopping = threading.Event()
        self.port, self.root, self.bindings, self.demo = port, root, bindings, demo
        self.wireless = wireless
        self.session = self.stream = self.health = None

    def submit(self, command, payload=None):
        with self.command_lock:
            if self.recovering or self.stopping.is_set():
                raise ValueError("device-not-ready")
            self.commands.put_nowait((command, payload))

    def stop(self):
        self.stopping.set()

    def publish(self, kind, **values):
        self.events.put(dict(kind=kind, **values))
        #  界面只消费汇总诊断，成功或失败通知后均丢弃明细 / The UI consumes summary diagnostics; discard traces after success or failure notifications
        if self.session:
            self.session.client.round_trips.clear()

    def status(self):
        self.publish("status", **self.session.snapshot(),
                     health=dict(self.health.report) if self.health else {})

    def open(self, monitor=False):
        if self.demo:
            self.session = ControlSession(SimulatedClient(), demo_reader)
            self.session.connect()
        else:
            connect = open_wifi if self.wireless else open_usb
            self.session, self.stream, self.health = connect(self.port, self.root, self.bindings)
        if monitor:
            self.session.monitor()

    def recover(self, error):
        with self.command_lock:
            self.recovering = True
        monitor = bool(self.session and self.session.monitor_requested)
        while True:
            try:
                command, _ = self.commands.get_nowait()
                self.publish("command", command=command, ok=False, error="connection-interrupted")
            except queue.Empty:
                break
        for attempt, delay in enumerate(RECONNECT_DELAYS, 1):
            #  身份和能力错误需人工处理，不自动配对或降级验证 / Identity and capability errors require manual action, never automatic pairing or weaker verification
            retryable = isinstance(error, (OSError, TimeoutError)) or str(error) in {
                "monitor-update-failed", "wireless-disconnected", "wireless-send-failed",
                "wireless-receive-failed", "wireless-unavailable", "discovery-required", "partial-write-reconnect-required",
                "device-reopened-reconnect-required",
            }
            if not retryable or self.demo:
                raise error
            self.publish("reconnecting", attempt=attempt, delay=delay)
            if self.stream:
                self.stream.close()
            self.session = self.stream = self.health = None
            if self.stopping.wait(delay):
                return False
            try:
                self.open(monitor)
                if self.stopping.is_set():
                    return False
                self.publish("connected", port=self.port, transport="wifi" if self.wireless else "usb")
                self.status()
                with self.command_lock:
                    self.recovering = False
                return True
            except Exception as next_error:
                error = next_error
        raise RuntimeError("reconnect-exhausted") from None

    def run(self):
        try:
            try:
                self.open()
            except Exception as error:
                if not self.recover(error):
                    return
            else:
                if self.stopping.is_set():
                    return
                self.publish("connected", port=self.port, demo=self.demo, transport="wifi" if self.wireless else "usb")
                self.status()
            next_tick = time.monotonic() + 1
            while not self.stopping.is_set():
                try:
                    command, payload = self.commands.get(timeout=min(0.1, max(0, next_tick - time.monotonic())))
                except queue.Empty:
                    command = None
                if command:
                    try:
                        if command == "local":
                            self.session.local()
                        elif command == "monitor":
                            self.session.monitor()
                        elif command == "monitor-profile-read":
                            self.session.read_monitor_profile()
                        elif command == "monitor-profile":
                            self.session.set_monitor_profile(payload)
                        elif command == "light":
                            self.session.light(payload)
                        else:
                            raise ValueError("unknown-command")
                        self.publish("command", command=command, ok=True)
                    except Exception as error:
                        self.publish("command", command=command, ok=False, error=str(error))
                    self.status()
                if time.monotonic() >= next_tick:
                    try:
                        self.session.tick()
                        self.status()
                    except Exception as error:
                        self.publish("update-error", error=str(error))
                        if not self.recover(error):
                            break
                    next_tick = time.monotonic() + 1
        except Exception as error:
            self.publish("connection-error", error=str(error))
        finally:
            released = False
            if self.session:
                try:
                    self.session.close()
                    released = True
                except Exception:
                    pass
            if self.stream:
                self.stream.close()
            monitor_off = bool(self.session and self.session.state and self.session.state.get("monitorOutput") == "disconnected")
            self.publish("disconnected", releaseConfirmed=released, monitorOff=monitor_off)
