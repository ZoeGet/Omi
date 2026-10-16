import queue
import threading
import time

from controller import ControlSession, SimulatedClient, demo_reader, open_usb


class DeviceWorker(threading.Thread):
    def __init__(self, events, *, port, root, bindings, demo=False):
        super().__init__(name="OmiPet device", daemon=False)
        self.events = events
        self.commands = queue.Queue(maxsize=1)
        self.stopping = threading.Event()
        self.port, self.root, self.bindings, self.demo = port, root, bindings, demo
        self.session = self.stream = self.health = None

    def submit(self, command, payload=None):
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

    def run(self):
        try:
            if self.demo:
                self.session = ControlSession(SimulatedClient(), demo_reader)
                self.session.connect()
            else:
                self.session, self.stream, self.health = open_usb(self.port, self.root, self.bindings)
            self.publish("connected", port=self.port, demo=self.demo)
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
