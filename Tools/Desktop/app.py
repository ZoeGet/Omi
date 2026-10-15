import argparse
from datetime import datetime
from pathlib import Path
import queue
import tkinter as tk
from tkinter import colorchooser, filedialog, ttk

from controller import default_monitor_root
from worker import DeviceWorker

EFFECTS = {"常亮": "solid", "彩虹": "rainbow", "呼吸灯": "breathe",
           "跑马灯": "sweep", "扩散灯": "centerExpand", "关闭灯光": "off"}
ERRORS = {"monitor-mode-active": "监控模式已锁定手动灯光，请先切回本地模式。",
          "voice-active": "设备正在响应语音，请稍后再应用灯光。",
          "light-command-not-supported": "当前固件未提供手动灯光控制，需要更新支持此功能的固件。",
          "monitor-lights-not-supported": "当前固件未声明监控灯光能力，需要更新支持此功能的固件。",
          "monitor-policy-not-supported": "请先更新设备固件，以支持来源异常绿、断线关灯的新规则。",
          "freshness-challenge-required": "当前固件不支持安全的监控状态有效期校验。",
          "monitor-update-failed": "监控更新失败，正在尝试重新连接；设备按原有规则回退。",
          "local-mode-unconfirmed": "设备尚未确认退出监控，请重试或断开连接。"}


class LegacyDesktopApp:
    def __init__(self, window, *, demo=False):
        self.window, self.demo = window, demo
        self.worker = None
        self.events = queue.Queue()
        self.connected = self.busy = self.closing = False
        self.snapshot = {}
        self.rgb = (255, 255, 255)
        self.port = tk.StringVar(value="演示设备" if demo else "")
        self.connection_text = tk.StringVar(value="未连接")
        self.mode_text = tk.StringVar(value="等待连接设备")
        self.status_text = tk.StringVar(value="—")
        self.detail_text = tk.StringVar(value="连接 USB 后读取设备支持的功能。")
        self.light_hint = tk.StringVar(value="请先连接设备。")
        self.color_text = tk.StringVar(value="#FFFFFF")
        self.brightness = tk.DoubleVar(value=16)
        self.brightness_text = tk.StringVar(value="16 / 255")
        self.effect = tk.StringVar(value="常亮")
        self.root_path = tk.StringVar(value=str(default_monitor_root()))
        self.bindings_path = tk.StringVar(value=str(default_monitor_root() / "host-bindings.json"))
        self.health_text = tk.StringVar(value="暂无设备诊断")
        self._style()
        self._build()
        self.refresh_ports()
        self._controls()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.after(100, self.poll)

    def _style(self):
        self.window.title("OmiPet 控制台" + (" · 演示" if self.demo else ""))
        self.window.geometry("1080x740")
        self.window.minsize(920, 660)
        self.window.configure(bg="#10151d")
        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10), background="#18212d",
                        foreground="#e7edf5", fieldbackground="#101821", bordercolor="#2d3b4d")
        style.configure("TFrame", background="#10151d")
        style.configure("Card.TFrame", background="#18212d")
        style.configure("TLabel", background="#10151d", foreground="#e7edf5")
        style.configure("Muted.TLabel", foreground="#9dadbf")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 24, "bold"))
        style.configure("Value.TLabel", font=("Microsoft YaHei UI", 19, "bold"))
        style.configure("TButton", padding=(15, 9), background="#28384d")
        style.map("TButton", background=[("active", "#38516e"), ("disabled", "#202936")],
                  foreground=[("disabled", "#64758b")])
        style.configure("Accent.TButton", background="#2869d8")
        style.map("Accent.TButton", background=[("active", "#3d7bea"), ("disabled", "#26344a")])
        style.configure("TNotebook", background="#10151d", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(24, 12), background="#18212d")
        style.map("TNotebook.Tab", background=[("selected", "#29496d")])
        style.map("TCombobox", fieldbackground=[("readonly", "#101821")],
                  foreground=[("disabled", "#64758b")])

    def _build(self):
        outer = ttk.Frame(self.window, padding=26)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="OmiPet", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="设备控制台", style="Muted.TLabel", padding=(16, 12)).pack(side="left")
        ttk.Label(header, textvariable=self.connection_text).pack(side="right")
        if self.demo:
            ttk.Label(outer, text="演示模式 · 所有反馈来自模拟设备，不控制实体 OmiPet。",
                      foreground="#f4c36a").pack(anchor="w", pady=(8, 0))
        connection = ttk.Frame(outer, padding=(0, 18))
        connection.pack(fill="x")
        ttk.Label(connection, text="USB 设备").pack(side="left", padx=(0, 10))
        self.port_box = ttk.Combobox(connection, textvariable=self.port, width=36, state="readonly")
        self.port_box.pack(side="left")
        self.refresh_button = ttk.Button(connection, text="刷新", command=self.refresh_ports)
        self.refresh_button.pack(side="left", padx=8)
        self.connect_button = ttk.Button(connection, text="连接", style="Accent.TButton", command=self.connect)
        self.connect_button.pack(side="left", padx=4)
        self.disconnect_button = ttk.Button(connection, text="断开", command=self.disconnect)
        self.disconnect_button.pack(side="left", padx=4)
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        overview, lights, pairing, settings = [ttk.Frame(tabs, padding=24) for _ in range(4)]
        for frame, title in zip((overview, lights, pairing, settings), ("设备概览", "灯光与灯效", "无线配对", "设置")):
            tabs.add(frame, text=title)
        self._overview(overview)
        self._lights(lights)
        ttk.Label(pairing, text="无线配对", style="Value.TLabel").pack(anchor="w")
        ttk.Label(pairing, text="USB 连接可直接使用已支持的设备控制。\n无线安全配对尚未接入设备，当前不能输入或发送配对码。",
                  style="Muted.TLabel", wraplength=780, justify="left").pack(anchor="w", pady=18)
        ttk.Label(pairing, text="已确认的配对方式：屏幕随机六位码 · 5 分钟有效 · 最多 5 次失败\n未配对设备重启开启；已配对设备重启不重新开放。",
                  wraplength=780, justify="left").pack(anchor="w", pady=10)
        ttk.Entry(pairing, state="disabled", width=20).pack(anchor="w", pady=10)
        ttk.Button(pairing, text="设备尚未支持无线配对", state="disabled").pack(anchor="w")
        self._settings(settings)
        ttk.Label(outer, textvariable=self.detail_text, style="Muted.TLabel", wraplength=980).pack(anchor="w", pady=(16, 0))

    def _overview(self, frame):
        ttk.Label(frame, text="控制模式", style="Value.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=self.mode_text, style="Muted.TLabel").pack(anchor="w", pady=(8, 16))
        row = ttk.Frame(frame)
        row.pack(anchor="w")
        self.local_button = ttk.Button(row, text="本地灯光", command=lambda: self.command("local"))
        self.local_button.pack(side="left", padx=(0, 12))
        self.monitor_button = ttk.Button(row, text="Codex 监控", command=lambda: self.command("monitor"))
        self.monitor_button.pack(side="left")
        ttk.Label(frame, text="监控模式下锁定手动调灯；语音优先。下方显示设备确认的监控状态，语音可接管实际灯光。",
                  style="Muted.TLabel").pack(anchor="w", pady=(14, 22))
        ttk.Label(frame, textvariable=self.status_text, style="Value.TLabel").pack(anchor="w")
        ttk.Label(frame, textvariable=self.health_text, style="Muted.TLabel", wraplength=850).pack(anchor="w", pady=10)
        ttk.Label(frame, text="操作记录", padding=(0, 8)).pack(anchor="w")
        self.log_box = tk.Text(frame, height=7, bg="#101821", fg="#aebed0", relief="flat",
                               font=("Microsoft YaHei UI", 9), state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)

    def _lights(self, frame):
        ttk.Label(frame, text="本地灯光", style="Value.TLabel").grid(row=0, column=0, columnspan=4, sticky="w")
        ttk.Label(frame, textvariable=self.light_hint, style="Muted.TLabel", wraplength=800).grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(8, 25))
        ttk.Label(frame, text="灯效").grid(row=2, column=0, sticky="w", padx=(0, 18))
        self.effect_box = ttk.Combobox(frame, textvariable=self.effect, values=list(EFFECTS), state="readonly", width=24)
        self.effect_box.grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Label(frame, text="颜色").grid(row=3, column=0, sticky="w", pady=20)
        self.color_button = ttk.Button(frame, textvariable=self.color_text, command=self.choose_color)
        self.color_button.grid(row=3, column=1, sticky="w")
        swatches = ttk.Frame(frame)
        swatches.grid(row=4, column=1, columnspan=3, sticky="w")
        self.swatch_buttons = []
        for color in ("#FFFFFF", "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF"):
            button = tk.Button(swatches, bg=color, activebackground=color, width=4, height=1,
                               relief="flat", command=lambda value=color: self.set_color(value))
            button.pack(side="left", padx=(0, 10))
            self.swatch_buttons.append(button)
        ttk.Label(frame, text="亮度").grid(row=5, column=0, sticky="w", pady=24)
        self.brightness_scale = ttk.Scale(frame, from_=0, to=255, variable=self.brightness,
                                          command=self.brightness_changed, length=420)
        self.brightness_scale.grid(row=5, column=1, columnspan=2, sticky="w")
        ttk.Label(frame, textvariable=self.brightness_text).grid(row=5, column=3, padx=18)
        self.apply_button = ttk.Button(frame, text="应用灯光设置", style="Accent.TButton", command=self.apply_light)
        self.apply_button.grid(row=6, column=1, sticky="w", pady=18)
        ttk.Label(frame, text="设置只在点击“应用”后发送；收到设备确认后才记录为已接受。\n语音可能随后改变灯光，界面中的颜色是本次编辑值。",
                  style="Muted.TLabel", justify="left").grid(row=7, column=0, columnspan=4, sticky="w", pady=12)

    def _settings(self, frame):
        ttk.Label(frame, text="Codex 状态来源", style="Value.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        self.setting_entries = []
        for row, (label, variable, directory) in enumerate((("状态目录", self.root_path, True),
                                                            ("宿主绑定文件", self.bindings_path, False)), 1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 14), pady=18)
            entry = ttk.Entry(frame, textvariable=variable, width=66)
            entry.grid(row=row, column=1, sticky="ew")
            button = ttk.Button(frame, text="选择", command=lambda var=variable, folder=directory: self.browse(var, folder))
            button.grid(row=row, column=2, padx=10)
            self.setting_entries.extend((entry, button))
        ttk.Label(frame, text="连接时读取上述位置；修改后需重新连接。\n状态缺失、绑定失败或观测过期时显示未知并由设备回退。\n沿用已确认参数：1 秒更新、2 秒 USB 超时、1 次重试、30 秒观测预算。",
                  style="Muted.TLabel", justify="left", wraplength=800).grid(row=3, column=0, columnspan=3, sticky="w", pady=25)
        frame.columnconfigure(1, weight=1)

    def browse(self, variable, directory):
        value = filedialog.askdirectory() if directory else filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if value:
            variable.set(value)

    def refresh_ports(self):
        if self.demo:
            self.port_box["values"] = ("演示设备",)
            return
        from serial.tools import list_ports
        self.port_choices = {f"{item.device} · {item.description}": item.device for item in list_ports.comports()}
        self.port_box["values"] = tuple(self.port_choices)
        if self.port.get() not in self.port_choices:
            self.port.set(next(iter(self.port_choices)) if len(self.port_choices) == 1 else "")

    def connect(self):
        if self.worker and self.worker.is_alive():
            return
        port = "演示设备" if self.demo else self.port_choices.get(self.port.get())
        if not port:
            self.detail_text.set("请选择要连接的 USB 设备。")
            return
        self.busy = True
        self.connection_text.set("连接中…")
        self.worker = DeviceWorker(self.events, port=port, root=Path(self.root_path.get()),
                                   bindings=Path(self.bindings_path.get()), demo=self.demo)
        self.worker.start()
        self._controls()

    def disconnect(self):
        if self.worker:
            self.busy = True
            self.worker.stop()
            self.connection_text.set("正在释放连接…")
            self._controls()

    def command(self, kind, payload=None):
        if not self.connected or self.busy:
            return
        try:
            self.worker.submit(kind, payload)
            self.busy = True
            self._controls()
        except queue.Full:
            self.detail_text.set("上一条操作仍在处理。")

    def choose_color(self):
        value = colorchooser.askcolor(self.color_text.get(), title="选择灯光颜色")[1]
        if value:
            self.set_color(value)

    def set_color(self, value):
        self.color_text.set(value.upper())
        self.rgb = tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))

    def brightness_changed(self, value):
        self.brightness_text.set(f"{round(float(value))} / 255")

    def apply_light(self):
        self.command("light", dict(effect=EFFECTS[self.effect.get()], red=self.rgb[0], green=self.rgb[1],
                                   blue=self.rgb[2], brightness=round(float(self.brightness.get()))))

    def _controls(self):
        active = self.connected and not self.busy and not self.closing
        monitoring = self.snapshot.get("monitorRequested", False)
        supported = "light" in self.snapshot.get("operations", ())
        light_enabled = active and not monitoring and supported
        for widget in (self.local_button, self.monitor_button):
            widget.configure(state="normal" if active else "disabled")
        self.monitor_button.configure(state="normal" if active and self.snapshot.get("monitorLights") and self.snapshot.get("monitorGreenOff") else "disabled")
        for widget in (self.color_button, self.apply_button, self.brightness_scale, *self.swatch_buttons):
            widget.configure(state="normal" if light_enabled else "disabled")
        self.effect_box.configure(state="readonly" if light_enabled else "disabled")
        self.connect_button.configure(state="normal" if not self.connected and not self.busy and not self.closing else "disabled")
        self.disconnect_button.configure(state="normal" if self.connected and not self.busy and not self.closing else "disabled")
        self.port_box.configure(state="readonly" if not self.connected and not self.busy else "disabled")
        self.refresh_button.configure(state="normal" if not self.connected and not self.busy else "disabled")
        for widget in self.setting_entries:
            widget.configure(state="disabled" if self.connected or self.busy else "normal")
        if monitoring:
            self.light_hint.set("Codex 监控模式已锁定手动灯光。请在设备概览中切回“本地灯光”。")
        elif not self.connected:
            self.light_hint.set("请先连接设备。")
        elif not supported:
            self.light_hint.set("当前固件未提供手动灯光命令；需要更新支持上位机控制的固件。")
        else:
            self.light_hint.set("本地模式可设置颜色、亮度和灯效。")

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{datetime.now():%H:%M:%S}  {text}\n")
        if int(self.log_box.index("end-1c").split(".")[0]) > 200:
            self.log_box.delete("1.0", "2.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def poll(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind = event["kind"]
            if kind == "connected":
                self.connected, self.busy = True, False
                self.connection_text.set("演示设备已连接" if self.demo else f"已连接 · {event['port']}")
                self.log("设备握手成功。")
            elif kind == "status":
                self.snapshot = event
                state = event.get("state") or {}
                monitoring = event["monitorRequested"]
                self.mode_text.set("Codex 监控模式" if monitoring else "本地灯光模式")
                names = {"working": "工作中 · 红色扩散", "waitingApproval": "等待审批 · 黄色扩散",
                         "idle": "空闲 · 绿色扩散", "unknown": "来源未知 · 绿色扩散", "offline": "来源离线 · 绿色扩散"}
                self.status_text.set(names.get(state.get("displayStatus"), "等待设备确认") if monitoring else "手动灯光可按设备能力设置")
                diagnostics, health = event["diagnostics"], event["health"]
                self.health_text.set(f"USB 超时 {diagnostics.get('replyTimeouts', 0)} 次 · 解码错误 {diagnostics.get('decodeIssues', 0)} 次"
                                     + (" · 麦克风正常" if health.get("microphoneOk") else ""))
            elif kind == "command":
                self.busy = False
                if event["ok"]:
                    text = {"local": "设备已确认切回本地模式。", "monitor": "已启动 Codex 状态监控。", "light": "设备已接受灯光设置。"}[event["command"]]
                else:
                    text = ERRORS.get(event["error"], "操作失败：" + event["error"])
                self.detail_text.set(text)
                self.log(text)
            elif kind in ("connection-error", "update-error"):
                text = ERRORS.get(event["error"], "连接或更新失败：" + event["error"])
                self.detail_text.set(text)
                if kind == "connection-error":
                    self.log(text)
                else:
                    self.snapshot["state"] = None
                    self.status_text.set("通信中断 · 等待恢复")
            elif kind == "disconnected":
                self.connected = self.busy = False
                self.snapshot = {}
                self.connection_text.set("未连接")
                self.mode_text.set("等待连接设备")
                text = ("连接已关闭，设备确认监控灯关闭。" if event.get("monitorOff") else "连接已关闭，设备确认回到本地模式。") if event["releaseConfirmed"] else "连接已关闭；未收到释放确认，设备按原有租约检测断联后处理。"
                self.detail_text.set(text)
                self.log(text)
            self._controls()
        if self.closing and (self.worker is None or not self.worker.is_alive()):
            self.window.destroy()
            return
        self.window.after(100, self.poll)

    def close(self):
        self.closing = True
        self.detail_text.set("正在释放设备连接并退出…")
        if self.worker:
            self.worker.stop()
        self._controls()


def main():
    parser = argparse.ArgumentParser(description="OmiPet Windows desktop control console")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--legacy", action="store_true", help="Open the retained previous interface for comparison")
    args = parser.parse_args()
    window = tk.Tk()
    if args.legacy:
        app = LegacyDesktopApp(window, demo=args.demo)
    else:
        from modern_ui import ModernDesktopApp
        app = ModernDesktopApp(window, demo=args.demo)
    if args.smoke_test:
        window.withdraw()
        window.update_idletasks()
        assert str(app.apply_button["state"]) == "disabled"
        app.connected = True
        app.snapshot = dict(operations=["light"], monitorRequested=False)
        app._controls()
        assert str(app.apply_button["state"]) == "normal"
        app.snapshot["monitorRequested"] = True
        app._controls()
        assert str(app.apply_button["state"]) == "disabled"
        assert str(app.effect_box["state"]) == "disabled"
        assert str(app.local_button["state"]) == "normal"
        window.destroy()
        print("PASS desktop UI capability and monitor-mode locks")
        return
    window.mainloop()


if __name__ == "__main__":
    main()
