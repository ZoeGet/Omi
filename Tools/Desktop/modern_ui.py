import colorsys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from app import EFFECTS, LegacyDesktopApp

BG = "#F6F8FC"
WHITE = "#FFFFFF"
INK = "#182437"
MUTED = "#8290A4"
LINE = "#E8EDF4"
BLUE = "#3478F6"
PALE = "#ECF3FF"
SIDE = "#F1F4F9"
GREEN = "#20A66A"
RED = "#E45D64"
YELLOW = "#DBA32C"
FONT = "Microsoft YaHei UI"
MODES = (("local", "本地灯光"), ("monitor", "Codex 监控"))


def rounded(canvas, x1, y1, x2, y2, radius, **kwargs):
    return canvas.create_polygon(x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
                                 x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
                                 x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
                                 smooth=True, splinesteps=24, **kwargs)


def label(parent, text=None, *, variable=None, size=10, color=INK, bold=False, **kwargs):
    widget = tk.Label(parent, text=text, textvariable=variable, bg=parent.cget("bg"), fg=color,
                      font=(FONT, size, "bold" if bold else "normal"), anchor="w", **kwargs)
    return widget


class Card(tk.Canvas):
    def __init__(self, parent, *, height=200, padding=20):
        super().__init__(parent, bg=BG, highlightthickness=0, bd=0, height=height)
        self.padding = padding
        self.body = tk.Frame(self, bg=WHITE)
        self.slot = self.create_window(padding, padding, window=self.body, anchor="nw")
        self.bind("<Configure>", self.layout)
        self.minimum_height = height
        self.body.bind("<Configure>", self.fit_content)

    def fit_content(self, event=None):
        needed = max(self.minimum_height, self.body.winfo_reqheight() + 2 * self.padding)
        if int(self.cget("height")) != needed:
            self.configure(height=needed)

    def layout(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        self.delete("surface")
        rounded(self, 1, 1, width - 1, height - 1, 16, fill=WHITE, outline=LINE, tags="surface")
        self.tag_lower("surface")
        self.itemconfigure(self.slot, width=max(1, width - 2 * self.padding), height=max(1, height - 2 * self.padding))


class Button(tk.Canvas):
    def __init__(self, parent, text, command, *, width=130, height=40, variant="outline", textvariable=None):
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"),
                         bd=0, highlightthickness=0, takefocus=True, cursor="hand2")
        self.caption, self.command, self.variant = text, command, variant
        self.hover = False
        self.variable = textvariable
        if textvariable is not None:
            textvariable.trace_add("write", lambda *_: self.paint())
        self.bind("<Configure>", self.paint)
        self.bind("<Enter>", lambda _: self.hovered(True))
        self.bind("<Leave>", lambda _: self.hovered(False))
        self.bind("<Button-1>", self.invoke)
        self.bind("<Return>", self.invoke)
        self.bind("<space>", self.invoke)
        self.bind("<FocusIn>", self.paint)
        self.bind("<FocusOut>", self.paint)
        self.paint()

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if hasattr(self, "variant"):
            self.paint()
        return result

    def hovered(self, value):
        self.hover = value
        self.paint()

    def invoke(self, event=None):
        if str(self.cget("state")) != "disabled":
            self.focus_set()
            self.command()

    def paint(self, event=None):
        self.delete("all")
        width = max(self.winfo_width(), int(self.cget("width"))) if self.winfo_width() < 2 else self.winfo_width()
        height = int(self.cget("height"))
        disabled = str(self.cget("state")) == "disabled"
        if disabled:
            fill, color, border = "#F1F4F8", "#B0BAC8", "#EBEFF4"
        elif self.variant == "accent":
            fill, color, border = ("#2469E4" if self.hover else BLUE), WHITE, BLUE
        elif self.variant == "selected":
            fill, color, border = PALE, BLUE, "#B8D1FD"
        else:
            fill, color, border = ("#F4F7FC" if self.hover else WHITE), "#526279", "#DEE5EF"
        if self.focus_get() is self and not disabled:
            border = BLUE
        rounded(self, 1, 1, width - 1, height - 1, 9, fill=fill, outline=border)
        caption = self.variable.get() if self.variable is not None else self.caption
        self.create_text(width / 2, height / 2, text=caption, fill=color, font=(FONT, 10, "bold" if self.variant == "accent" else "normal"))


class Navigation(tk.Canvas):
    def __init__(self, parent, text, glyph, command):
        super().__init__(parent, height=45, width=176, bg=SIDE, highlightthickness=0,
                         bd=0, cursor="hand2", takefocus=True)
        self.caption, self.glyph, self.command = text, glyph, command
        self.selected = self.hover = False
        self.bind("<Configure>", self.paint)
        self.bind("<Button-1>", lambda _: command())
        self.bind("<Return>", lambda _: command())
        self.bind("<space>", lambda _: command())
        self.bind("<Enter>", lambda _: self.hovered(True))
        self.bind("<Leave>", lambda _: self.hovered(False))

    def hovered(self, state):
        self.hover = state
        self.paint()

    def paint(self, event=None):
        self.delete("all")
        width = self.winfo_width()
        if self.selected or self.hover:
            rounded(self, 0, 1, width - 1, 44, 11, fill="#E1EBFD" if self.selected else "#E9EEF6", outline="")
        color = "#2567D9" if self.selected else "#647188"
        self.create_text(25, 23, text=self.glyph, fill=color, font=("Segoe UI Symbol", 16))
        self.create_text(51, 23, text=self.caption, fill=color, anchor="w", font=(FONT, 10, "bold" if self.selected else "normal"))


class ModeRow(Button):
    def __init__(self, parent, text, command):
        self.selected = False
        height = max(48, tkfont.Font(parent, family=FONT, size=10).metrics("linespace") + 20)
        super().__init__(parent, text, command, width=300, height=height)

    def invoke(self, event=None):
        if not self.selected:
            super().invoke(event)

    def paint(self, event=None):
        self.delete("all")
        width = self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))
        height = int(self.cget("height"))
        disabled = str(self.cget("state")) == "disabled"
        fill = PALE if self.selected else "#F6F8FB"
        color = "#53647C" if disabled else INK
        accent = "#A8B8CE" if disabled else BLUE
        border = BLUE if self.focus_get() is self and not disabled else fill
        rounded(self, 1, 1, width - 1, height - 1, 10, fill=fill, outline=border)
        cy = height / 2
        self.create_oval(15, cy - 8, 31, cy + 8, outline=accent, width=2)
        self.create_polygon(22, cy - 4, 22, cy + 4, 27, cy, fill=accent, outline="")
        self.create_text(45, cy, text=self.caption, anchor="w", fill=color, font=(FONT, 10))
        x = width - 57
        track = accent if self.selected else "#CBD4E2"
        rounded(self, x, cy - 12, x + 42, cy + 12, 12, fill=track, outline="")
        knob = x + 30 if self.selected else x + 12
        self.create_oval(knob - 9, cy - 9, knob + 9, cy + 9, fill=WHITE, outline="")


class PageViewport(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self.content = tk.Frame(self.canvas, bg=BG)
        self.slot = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", self.resize)
        self.content.bind("<Configure>", self.resize)
        self.winfo_toplevel().bind("<MouseWheel>", self.wheel, add=True)

    def resize(self, event=None):
        width = max(1, self.canvas.winfo_width())
        self.canvas.itemconfigure(self.slot, width=width)
        self.canvas.configure(scrollregion=(0, 0, width, self.content.winfo_reqheight()))

    def wheel(self, event):
        if (str(event.widget).startswith(str(self)) and not isinstance(event.widget, tk.Text)
                and self.canvas.yview() != (0.0, 1.0)):
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
            return "break"


class Swatch(Button):
    def __init__(self, parent, color, command):
        self.color = color
        self.selected = False
        super().__init__(parent, "", command, width=34, height=34)

    def paint(self, event=None):
        self.delete("all")
        disabled = str(self.cget("state")) == "disabled"
        border = BLUE if self.selected and not disabled else WHITE
        self.create_oval(1, 1, 32, 32, fill=WHITE, outline=border, width=2)
        self.create_oval(6, 6, 27, 27, fill=self.color if not disabled else "#E1E6EF",
                         outline="#DEE4EF" if self.color == "#FFFFFF" or disabled else self.color)


class ModernDesktopApp(LegacyDesktopApp):
    def _style(self):
        self.window.title("OmiPet · 设备控制中心" + (" · 演示" if self.demo else ""))
        self.window.geometry("1160x820")
        self.window.minsize(1060, 780)
        self.window.configure(bg=BG)
        self.window.option_add("*Font", (FONT, 10))
        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure("TCombobox", padding=8, fieldbackground=WHITE, background=WHITE,
                        foreground=INK, bordercolor="#DFE6F0", arrowcolor=MUTED,
                        lightcolor=WHITE, darkcolor=WHITE, selectbackground=PALE, selectforeground=INK)
        style.map("TCombobox", fieldbackground=[("readonly", WHITE), ("disabled", "#F6F7FA")],
                  foreground=[("disabled", "#A2ADBC")])
        style.configure("TEntry", padding=9, fieldbackground=WHITE, foreground=INK,
                        bordercolor="#DFE6F0", lightcolor=WHITE, darkcolor=WHITE)
        style.configure("Horizontal.TScale", background=WHITE, troughcolor="#E6EEFB", borderwidth=0)

    def _build(self):
        self.navigation = {}
        self.pages = {}
        self.page_title = tk.StringVar(value="设备概览")
        self.page_subtitle = tk.StringVar(value="让设备状态清晰可见，让每一次控制简单直接。")
        self.summary_title = tk.StringVar(value="等待连接")
        self.summary_note = tk.StringVar(value="连接你的 OmiPet，开始管理桌面上的光。")
        self.metric_microphone = tk.StringVar(value="等待数据")
        self.metric_errors = tk.StringVar(value="0 次")
        self.metric_owner = tk.StringVar(value="本地")
        self.preview_note = tk.StringVar(value="常亮 · #FFFFFF · 亮度 16")
        self.mode_hint = tk.StringVar(value="监控中锁定手动调灯，语音可接管。")
        sidebar = tk.Frame(self.window, bg=SIDE, width=202)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDE)
        brand.pack(fill="x", padx=19, pady=(26, 28))
        mark = tk.Canvas(brand, width=38, height=38, bg=SIDE, bd=0, highlightthickness=0)
        mark.pack(side="left", padx=(0, 10))
        rounded(mark, 0, 0, 38, 38, 12, fill=BLUE, outline="")
        mark.create_arc(8, 9, 30, 31, start=185, extent=170, style="arc", outline=WHITE, width=2)
        mark.create_oval(12, 14, 15, 17, fill=WHITE, outline="")
        mark.create_oval(23, 14, 26, 17, fill=WHITE, outline="")
        title_box = tk.Frame(brand, bg=SIDE)
        title_box.pack(side="left")
        label(title_box, "OmiPet", size=17, bold=True).pack(anchor="w")
        label(title_box, "桌面设备控制中心", size=8, color=MUTED).pack(anchor="w", pady=(1, 0))
        for key, text, glyph in (("overview", "设备概览", "⌂"), ("lights", "灯光与灯效", "☼"),
                                  ("pairing", "连接与配对", "⌁"), ("diagnostics", "运行记录", "≡")):
            nav = Navigation(sidebar, text, glyph, lambda value=key: self.show_page(value))
            nav.pack(fill="x", padx=13, pady=4)
            self.navigation[key] = nav
        bottom = tk.Frame(sidebar, bg=SIDE)
        bottom.pack(side="bottom", fill="x", padx=13, pady=18)
        settings_nav = Navigation(bottom, "设置", "⚙", lambda: self.show_page("settings"))
        settings_nav.pack(fill="x")
        self.navigation["settings"] = settings_nav
        tk.Frame(bottom, bg="#E0E6F0", height=1).pack(fill="x", padx=10, pady=16)
        label(bottom, "OmiPet Desktop", size=9, color=MUTED).pack(anchor="w", padx=12)
        label(bottom, "0.3  ·  USB 控制台", size=8, color="#A2ACBB").pack(anchor="w", padx=12, pady=(3, 0))

        main = tk.Frame(self.window, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        top = tk.Frame(main, bg=WHITE, height=66)
        top.pack(fill="x")
        top.pack_propagate(False)
        label(top, "设备工作台", size=11, bold=True).pack(side="left", padx=28)
        label(top, " /  OmiPet", size=10, color=MUTED).pack(side="left")
        self.connection_badge = label(top, variable=self.connection_text, size=9, color=MUTED, padx=13, pady=6)
        self.connection_badge.pack(side="right", padx=26)
        tk.Frame(main, bg=LINE, height=1).pack(fill="x")
        if self.demo:
            label(main, "演示模式 · 仅模拟界面与设备反馈，不操作实体设备", size=9, color="#BA8C25", padx=28, pady=5).pack(fill="x")
        area = tk.Frame(main, bg=BG)
        area.pack(fill="both", expand=True, padx=26, pady=(19, 0))
        heading = tk.Frame(area, bg=BG)
        heading.pack(fill="x", pady=(0, 13))
        label(heading, variable=self.page_title, size=21, bold=True).pack(anchor="w")
        label(heading, variable=self.page_subtitle, size=9, color=MUTED).pack(anchor="w", pady=(6, 0))
        self.page_host = PageViewport(area)
        self.page_host.pack(fill="both", expand=True)
        for name in ("overview", "lights", "pairing", "diagnostics", "settings"):
            page = tk.Frame(self.page_host.content, bg=BG)
            self.pages[name] = page
        self._overview_page(self.pages["overview"])
        self._lighting_page(self.pages["lights"])
        self._pairing_page(self.pages["pairing"])
        self._diagnostics_page(self.pages["diagnostics"])
        self._settings_page(self.pages["settings"])
        footer = tk.Frame(main, bg=BG, height=45)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        footer_text = label(footer, variable=self.detail_text, size=8, color=MUTED, wraplength=830)
        footer_text.pack(side="left", padx=28)
        footer.bind("<Configure>", lambda event: footer_text.configure(wraplength=max(1, event.width - 56)))
        self.effect.trace_add("write", lambda *_: self._preview())
        self.brightness_changed(self.brightness.get())
        self.show_page("overview")

    def _heading(self, parent, title, caption=None):
        label(parent, title, size=12, bold=True).pack(anchor="w")
        if caption:
            label(parent, caption, size=8, color=MUTED).pack(anchor="w", pady=(5, 0))

    def _overview_page(self, page):
        page.columnconfigure((0, 1), weight=1, uniform="overview")
        connection = Card(page, height=205)
        connection.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        body = connection.body
        self._heading(body, "设备连接", "通过 USB 连接电脑与 OmiPet")
        port_row = tk.Frame(body, bg=WHITE)
        port_row.pack(fill="x", pady=(16, 13))
        self.port_box = ttk.Combobox(port_row, textvariable=self.port, state="readonly", width=25)
        self.port_box.pack(side="left", fill="x", expand=True)
        self.refresh_button = Button(port_row, "↻", self.refresh_ports, width=38, height=36)
        self.refresh_button.pack(side="right", padx=(8, 0))
        buttons = tk.Frame(body, bg=WHITE)
        buttons.pack(fill="x")
        self.connect_button = Button(buttons, "连接设备", self.connect, width=143, variant="accent")
        self.connect_button.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.disconnect_button = Button(buttons, "断开连接", self.disconnect, width=118)
        self.disconnect_button.pack(side="left", fill="x", expand=True)

        mode = Card(page, height=205)
        mode.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        body = mode.body
        self._heading(body, "控制模式", "选择灯光由你控制，或跟随 Codex 状态")
        choices = tk.Frame(body, bg=WHITE)
        choices.pack(fill="x", pady=(15, 10))
        self.mode_rows = {}
        for key, title in MODES:
            row = ModeRow(choices, title, lambda value=key: self.command(value))
            row.pack(fill="x", pady=(0, 8))
            self.mode_rows[key] = row
        self.local_button = self.mode_rows["local"]
        self.monitor_button = self.mode_rows["monitor"]
        label(body, variable=self.mode_hint, size=9, color=MUTED, wraplength=350, justify="left").pack(anchor="w")

        status = Card(page, height=210)
        status.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(0, 16))
        body = status.body
        self._heading(body, "监控状态")
        center = tk.Frame(body, bg=WHITE)
        center.pack(fill="x", pady=(16, 12))
        self.status_dot = tk.Canvas(center, width=50, height=50, bg=WHITE, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 14))
        words = tk.Frame(center, bg=WHITE)
        words.pack(side="left", fill="x", expand=True)
        label(words, variable=self.summary_title, size=18, bold=True).pack(anchor="w")
        label(words, variable=self.summary_note, size=8, color=MUTED, wraplength=290, justify="left").pack(anchor="w", pady=(5, 0))
        legend = tk.Frame(body, bg=WHITE)
        legend.pack(fill="x", pady=(5, 0))
        for color, text in ((GREEN, "无任务 / 完成"), (RED, "运行中"), (YELLOW, "待审批")):
            label(legend, "●", size=9, color=color).pack(side="left", padx=(0, 4))
            label(legend, text, size=8, color=MUTED).pack(side="left", padx=(0, 15))

        light = Card(page, height=210)
        light.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        body = light.body
        self._heading(body, "灯光空间", "自定义属于你的桌面氛围")
        self.quick_preview = tk.Canvas(body, height=42, bg=WHITE, highlightthickness=0)
        self.quick_preview.pack(fill="x", pady=(6, 4))
        self.quick_preview.bind("<Configure>", lambda _: self._preview())
        self.preview_summary = label(body, variable=self.preview_note, size=10, color="#637187", pady=4, justify="left")
        self.preview_summary.pack(fill="x")
        self.preview_summary.bind("<Configure>", lambda event: self.preview_summary.configure(wraplength=max(1, event.width)))
        Button(body, "调整灯光  →", lambda: self.show_page("lights"), width=143, height=34).pack(anchor="e", pady=(6, 0))

        metrics = Card(page, height=85, padding=16)
        metrics.grid(row=2, column=0, columnspan=2, sticky="ew")
        body = metrics.body
        for index, (title, value) in enumerate((("连接方式", "USB 直连"), ("麦克风", self.metric_microphone),
                                                 ("通信异常", self.metric_errors), ("当前归属", self.metric_owner))):
            column = tk.Frame(body, bg=WHITE)
            column.pack(side="left", fill="both", expand=True, padx=(12, 0))
            label(column, title, size=8, color=MUTED).pack(anchor="w")
            label(column, value if isinstance(value, str) else None, variable=None if isinstance(value, str) else value,
                  size=11, bold=True).pack(anchor="w", pady=(6, 0))

    def _lighting_page(self, page):
        page.columnconfigure(0, weight=3, uniform="lights")
        page.columnconfigure(1, weight=2, uniform="lights")
        controls = Card(page, height=439)
        controls.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8), pady=(0, 16))
        body = controls.body
        self._heading(body, "编辑灯光", "颜色、亮度与灯效一起应用")
        color_row = tk.Frame(body, bg=WHITE)
        color_row.pack(fill="x", pady=(18, 10))
        label(color_row, "灯光颜色", size=10, bold=True).pack(side="left")
        self.color_button = Button(color_row, "", self.choose_color, textvariable=self.color_text, width=125, height=34)
        self.color_button.pack(side="right")
        palette = tk.Frame(body, bg=WHITE)
        palette.pack(fill="x", pady=(0, 16))
        self.swatch_buttons = []
        for color in ("#FFFFFF", "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF"):
            button = Swatch(palette, color, lambda value=color: self.set_color(value))
            button.pack(side="left", padx=(0, 9))
            self.swatch_buttons.append(button)
        brightness = tk.Frame(body, bg=WHITE)
        brightness.pack(fill="x", pady=(0, 10))
        label(brightness, "灯光亮度", size=10, bold=True).pack(side="left")
        label(brightness, variable=self.brightness_text, size=9, color=BLUE).pack(side="right")
        self.brightness_scale = ttk.Scale(body, from_=0, to=255, variable=self.brightness, command=self.brightness_changed)
        self.brightness_scale.pack(fill="x", pady=(0, 18))
        label(body, "灯效", size=10, bold=True).pack(anchor="w", pady=(0, 10))
        effect_grid = tk.Frame(body, bg=WHITE)
        effect_grid.pack(fill="x")
        effect_grid.columnconfigure((0, 1, 2), weight=1, uniform="effects")
        self.effect_tiles = {}
        for index, name in enumerate(EFFECTS):
            tile = Button(effect_grid, name, lambda value=name: self.effect.set(value), width=102, height=41)
            tile.grid(row=index // 3, column=index % 3, sticky="ew", padx=(0 if index % 3 == 0 else 5, 0), pady=(0, 8))
            self.effect_tiles[name] = tile
        self.effect_box = next(iter(self.effect_tiles.values()))
        label(body, "彩虹使用独立色谱，关闭灯光保留编辑参数。", size=8, color=MUTED).pack(anchor="w", pady=(10, 0))

        preview = Card(page, height=217)
        preview.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        self._heading(preview.body, "灯光预览", "编辑效果示意 · 非设备实时读回")
        self.preview = tk.Canvas(preview.body, height=158, bg=WHITE, highlightthickness=0)
        self.preview.pack(fill="both", expand=True, pady=(5, 0))
        self.preview.bind("<Configure>", lambda _: self._preview())
        rules = Card(page, height=210)
        rules.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(0, 16))
        self._heading(rules.body, "监控灯光规则")
        for text, color in (("无任务 / 完成 / 来源异常", GREEN), ("运行中", RED), ("待审批", YELLOW)):
            row = tk.Frame(rules.body, bg=WHITE)
            row.pack(fill="x", pady=(10, 0))
            label(row, "●", size=9, color=color).pack(side="left", padx=(0, 8))
            label(row, text, size=9, color="#68768B").pack(side="left")
        label(rules.body, "均为扩散灯 · 连接断开则关灯", size=8, color=MUTED).pack(anchor="w", pady=(11, 0))
        apply = Card(page, height=78, padding=15)
        apply.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.apply_button = Button(apply.body, "应用灯光设置", self.apply_light, width=160, height=44, variant="accent")
        self.apply_button.pack(side="right")
        label(apply.body, variable=self.light_hint, size=9, color=MUTED, wraplength=540, justify="left").pack(side="left", padx=5)

    def _pairing_page(self, page):
        card = Card(page, height=385)
        card.pack(fill="x")
        self._heading(card.body, "连接你的 OmiPet", "目前支持 USB 直连；无线安全配对正在接入")
        illustration = tk.Canvas(card.body, height=84, bg=WHITE, highlightthickness=0)
        illustration.pack(fill="x", pady=12)
        illustration.create_oval(6, 12, 68, 74, fill=PALE, outline="")
        illustration.create_text(37, 43, text="⌁", font=("Segoe UI Symbol", 30), fill=BLUE)
        illustration.create_text(94, 33, text="无线配对准备中", anchor="w", font=(FONT, 15, "bold"), fill=INK)
        illustration.create_text(94, 60, text="准备就绪后，可使用设备屏幕上的六位码完成配对。", anchor="w", font=(FONT, 9), fill=MUTED)
        steps = tk.Frame(card.body, bg=WHITE)
        steps.pack(fill="x", pady=12)
        for number, title, detail in (("01", "同一局域网", "电脑与设备连接相同网络"), ("02", "查看配对码", "六位数字，五分钟内有效"), ("03", "完成身份验证", "配对成功后使用无线控制")):
            column = tk.Frame(steps, bg=WHITE)
            column.pack(side="left", fill="both", expand=True)
            label(column, number, size=11, color=BLUE, bold=True).pack(anchor="w")
            label(column, title, size=10, bold=True).pack(anchor="w", pady=7)
            label(column, detail, size=8, color=MUTED).pack(anchor="w")
        Button(card.body, "无线配对尚未就绪", lambda: None, width=180, variant="accent").pack(anchor="w", pady=(19, 0))
        card.body.winfo_children()[-1].configure(state="disabled")

    def _diagnostics_page(self, page):
        card = Card(page, height=460)
        card.pack(fill="both", expand=True)
        self._heading(card.body, "操作与连接记录", "用于查看操作结果；不显示对话内容和敏感信息")
        label(card.body, variable=self.health_text, size=9, color=MUTED).pack(anchor="w", pady=(15, 18))
        self.log_box = tk.Text(card.body, height=14, bg="#F8FAFE", fg="#647188", bd=0, padx=16, pady=14,
                               relief="flat", font=(FONT, 9), state="disabled", wrap="word", selectbackground="#DCE9FF")
        self.log_box.pack(fill="both", expand=True)

    def _settings_page(self, page):
        card = Card(page, height=267)
        card.pack(fill="x", pady=(0, 16))
        self._heading(card.body, "Codex 状态来源", "连接设备时读取以下位置，修改后重新连接即可生效")
        self.setting_entries = []
        for title, variable, folder in (("状态目录", self.root_path, True), ("宿主绑定文件", self.bindings_path, False)):
            label(card.body, title, size=9, color="#627087").pack(anchor="w", pady=(17, 7))
            row = tk.Frame(card.body, bg=WHITE)
            row.pack(fill="x")
            entry = ttk.Entry(row, textvariable=variable)
            entry.pack(side="left", fill="x", expand=True)
            button = Button(row, "选择", lambda value=variable, directory=folder: self.browse(value, directory), width=73, height=36)
            button.pack(side="right", padx=(10, 0))
            self.setting_entries.extend((entry, button))
        about = Card(page, height=143)
        about.pack(fill="x")
        self._heading(about.body, "关于 OmiPet Desktop")
        label(about.body, "专注于设备连接、灯光与 Codex 工作状态。", size=10, color="#68768B").pack(anchor="w", pady=(13, 7))
        label(about.body, "USB 更新周期 1 秒 · 连接中断由设备按原有租约检测后关灯", size=8, color=MUTED).pack(anchor="w")

    def show_page(self, name):
        titles = {"overview": ("设备概览", "让设备状态清晰可见，让每一次控制简单直接。"),
                  "lights": ("灯光与灯效", "一点颜色，一种氛围。为你的桌面设置合适的光。"),
                  "pairing": ("连接与配对", "从 USB 直连开始，逐步连接你的无线桌面。"),
                  "diagnostics": ("运行记录", "查看设备连接与最近的操作结果。"),
                  "settings": ("设置", "管理状态来源与应用配置。")}
        for key, page in self.pages.items():
            page.pack_forget()
            self.navigation[key].selected = key == name
            self.navigation[key].paint()
        self.pages[name].pack(fill="both", expand=True)
        self.page_host.canvas.yview_moveto(0)
        self.page_title.set(titles[name][0])
        self.page_subtitle.set(titles[name][1])
        self.window.after_idle(self._preview)

    def _controls(self):
        active = self.connected and not self.busy and not self.closing
        monitoring = self.snapshot.get("monitorRequested", False)
        supported = "light" in self.snapshot.get("operations", ())
        enabled = active and not monitoring and supported
        for row in self.mode_rows.values():
            row.selected = False
            row.configure(state="disabled")
        self.local_button.configure(state="normal" if active else "disabled")
        monitor_ready = self.snapshot.get("monitorLights") and self.snapshot.get("monitorGreenOff")
        self.mode_hint.set("请更新设备固件，以启用新的监控灯光规则。" if self.connected and not monitor_ready
                           else "监控中锁定手动调灯，语音可接管。")
        self.monitor_button.configure(state="normal" if active and monitor_ready else "disabled")
        confirmed_state = self.snapshot.get("state") or {}
        self.local_button.selected = not monitoring and confirmed_state.get("mode") == "local"
        self.monitor_button.selected = monitoring and confirmed_state.get("monitorOutput") == "connected"
        self.local_button.paint()
        self.monitor_button.paint()
        for widget in (self.color_button, self.apply_button, self.brightness_scale, *self.swatch_buttons, *self.effect_tiles.values()):
            widget.configure(state="normal" if enabled else "disabled")
        self.connect_button.configure(state="normal" if not self.connected and not self.busy and not self.closing else "disabled")
        self.disconnect_button.configure(state="normal" if self.connected and not self.busy and not self.closing else "disabled")
        self.port_box.configure(state="readonly" if not self.connected and not self.busy else "disabled")
        self.refresh_button.configure(state="normal" if not self.connected and not self.busy else "disabled")
        for widget in self.setting_entries:
            widget.configure(state="disabled" if self.connected or self.busy else "normal")
        if monitoring:
            hint = "监控模式已锁定手动调灯，请先切回本地灯光。"
        elif not self.connected:
            hint = "连接设备后，选择颜色与灯效，再点击应用。"
        elif not supported:
            hint = "当前设备需要更新固件才能使用手动灯光。"
        else:
            hint = "本地模式可手动调灯，点击应用后发送到设备。"
        self.light_hint.set(hint)
        self.connection_badge.configure(fg=GREEN if self.connected else MUTED)
        self._status()
        self._preview()

    def _status(self):
        state = self.snapshot.get("state") or {}
        monitoring = self.snapshot.get("monitorRequested", False)
        status = state.get("displayStatus", "unknown")
        if not self.connected:
            title, note, color = "等待连接", "连接设备后，工作状态会显示在这里。", "#A5B1C2"
        elif not monitoring:
            title, note, color = "本地灯光", "灯光由手动设置或语音控制。", BLUE
        elif not state or state.get("monitorOutput") == "disconnected":
            title, note, color = "连接中断", "设备检测到断联后关灯，等待重新连接。", "#A5B1C2"
        else:
            title, note, color = {"working": ("运行中", "红色扩散灯 · Codex 正在处理任务", RED),
                                  "waitingApproval": ("等待审批", "黄色扩散灯 · 请在 Codex 中处理审批", YELLOW),
                                  "idle": ("任务已完成", "绿色扩散灯 · 当前无待处理任务", GREEN),
                                  "unknown": ("待机 / 来源未知", "绿色扩散灯 · 暂时没有可用的任务状态", GREEN),
                                  "offline": ("来源离线", "绿色扩散灯 · 设备连接仍在保持", GREEN)}.get(status, ("待机", "绿色扩散灯", GREEN))
        self.summary_title.set(title)
        self.summary_note.set(note)
        self.status_dot.delete("all")
        self.status_dot.create_oval(0, 0, 49, 49, fill="#F3F6FB", outline="")
        self.status_dot.create_oval(15, 15, 34, 34, fill=color, outline="")
        health = self.snapshot.get("health", {})
        diagnostics = self.snapshot.get("diagnostics", {})
        self.metric_microphone.set("正常" if health.get("microphoneOk") else "等待数据")
        self.metric_errors.set(f"{diagnostics.get('replyTimeouts', 0) + diagnostics.get('decodeIssues', 0)} 次")
        self.metric_owner.set("Codex 监控" if monitoring else "本地控制")

    def set_color(self, value):
        super().set_color(value)
        self._preview()

    def brightness_changed(self, value):
        self.brightness_text.set(f"{round(float(value) / 255 * 100)}%")
        if hasattr(self, "preview"):
            self._preview()

    def _preview(self):
        if not hasattr(self, "preview"):
            return
        self.preview_note.set(f"{self.effect.get()} · {self.color_text.get()} · 亮度 {round(self.brightness.get() / 255 * 100)}%")
        for swatch in self.swatch_buttons:
            swatch.selected = swatch.color == self.color_text.get()
            swatch.paint()
        for name, tile in self.effect_tiles.items():
            tile.variant = "selected" if self.effect.get() == name else "outline"
            tile.paint()
        for canvas in (self.quick_preview, self.preview):
            canvas.delete("all")
            width = canvas.winfo_width()
            if width < 2:
                continue
            height = canvas.winfo_height()
            center = height / 2
            rounded(canvas, 8, center - 23, width - 8, center + 23, 18, fill="#F4F7FD", outline="")
            spacing = (width - 52) / 12
            for index in range(13):
                if self.effect.get() == "彩虹":
                    rgb = tuple(round(v * 255) for v in colorsys.hsv_to_rgb(index / 13, 0.75, 0.95))
                elif self.effect.get() == "关闭灯光":
                    rgb = (204, 212, 225)
                else:
                    factor = max(0.16, 1 - abs(index - 6) / 7) if self.effect.get() in ("扩散灯", "跑马灯") else 1
                    rgb = tuple(round(240 * (1 - factor) + v * factor) for v in self.rgb)
                color = "#%02x%02x%02x" % rgb
                x = 26 + index * spacing
                canvas.create_oval(x - 5, center - 5, x + 5, center + 5, fill=color, outline="#DDE5F0" if rgb == (255, 255, 255) else "")
            if canvas is self.preview:
                canvas.create_text(width / 2, center + 48, text=self.effect.get(), fill=INK, font=(FONT, 11, "bold"))
