import tkinter as tk

import customtkinter as ctk


BG = "#F6F8FC"
WHITE = "#FFFFFF"
INK = "#182437"
MUTED = "#8290A4"
LINE = "#E8EDF4"
BLUE = "#3478F6"
PALE = "#ECF3FF"
SIDE = "#F1F4F9"
FONT = "Microsoft YaHei UI"

ctk.set_appearance_mode("light")
ctk.deactivate_automatic_dpi_awareness()


def pixel_font(parent, size=10, bold=False):
    pixels = round(size * float(parent.tk.call("tk", "scaling")))
    return (FONT, pixels, "bold" if bold else "normal")


class Card(ctk.CTkFrame):
    def __init__(self, parent, *, height=200, padding=20):
        super().__init__(parent, height=height, corner_radius=14, fg_color=WHITE,
                         bg_color=BG, border_color=LINE, border_width=1)
        self.pack_propagate(False)
        self.padding, self.minimum_height = padding, height
        self.body = tk.Frame(self, bg=WHITE)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)
        self.body.bind("<Configure>", self.fit_content)

    def fit_content(self, event=None):
        needed = max(self.minimum_height, self.body.winfo_reqheight() + 2 * self.padding)
        if int(self.cget("height")) != needed:
            self.configure(height=needed)


class Button(ctk.CTkButton):
    def __init__(self, parent, text, command, *, width=130, height=40, variant="outline", textvariable=None):
        self.variant, self.caption, self.command = variant, text, command
        display_text = text or (" " if textvariable is not None else "")
        super().__init__(parent, text=display_text, command=command, textvariable=textvariable,
                         width=width, height=height, font=pixel_font(parent),
                         corner_radius=9, border_width=1, bg_color=parent.cget("bg"),
                         fg_color=WHITE, text_color=INK, text_color_disabled="#A2ADBC")
        self.bind("<Return>", self.invoke)
        self.bind("<space>", self.invoke)
        self.bind("<FocusIn>", self.paint)
        self.bind("<FocusOut>", self.paint)
        tk.Frame.configure(self, takefocus=1)
        self.paint()

    def __getitem__(self, key):
        return self.cget(key)

    def invoke(self, event=None):
        if str(self.cget("state")) != "disabled":
            self.focus_set()
            self.command()

    def configure(self, require_redraw=False, **kwargs):
        super().configure(require_redraw=require_redraw, **kwargs)
        if hasattr(self, "_text_label"):
            self.paint()

    def paint(self, event=None):
        if str(self.cget("state")) == "disabled":
            fill, color, border, hover = "#F1F4F8", "#B0BAC8", "#EBEFF4", "#F1F4F8"
        elif self.variant == "accent":
            fill, color, border, hover = BLUE, WHITE, BLUE, "#2469E4"
        elif self.variant == "selected":
            fill, color, border, hover = PALE, BLUE, "#B8D1FD", "#E2EDFF"
        else:
            fill, color, border, hover = WHITE, "#526279", "#DEE5EF", "#F4F7FC"
        if self.focus_get() is self and str(self.cget("state")) != "disabled":
            border = BLUE
        ctk.CTkButton.configure(self, fg_color=fill, text_color=color, border_color=border, hover_color=hover)


class Navigation(ctk.CTkButton):
    def __init__(self, parent, text, glyph, command):
        self.selected = False
        super().__init__(parent, text=f"{glyph}   {text}", command=command, width=176, height=45,
                         font=pixel_font(parent), corner_radius=10, anchor="w",
                         bg_color=SIDE, fg_color=SIDE, text_color="#647188", hover_color="#E9EEF6")
        self.bind("<Return>", lambda _: command())
        self.bind("<space>", lambda _: command())
        tk.Frame.configure(self, takefocus=1)

    def paint(self, event=None):
        self.configure(fg_color="#E1EBFD" if self.selected else SIDE,
                       text_color="#2567D9" if self.selected else "#647188")


class ModeRow(ctk.CTkFrame):
    def __init__(self, parent, text, command):
        self.selected, self._state, self._ready = False, "normal", False
        self.command = command
        super().__init__(parent, height=48, corner_radius=10, fg_color="#F6F8FB",
                         bg_color=WHITE, border_width=0)
        self.content = tk.Frame(self, bg="#F6F8FB")
        self.content.pack(fill="both", expand=True, padx=14, pady=9)
        self.icon = tk.Label(self.content, text="◉", bg="#F6F8FB", fg=BLUE, font=(FONT, 12))
        self.icon.pack(side="left", padx=(0, 10))
        self.title_label = tk.Label(self.content, text=text, bg="#F6F8FB", fg=INK, font=(FONT, 10))
        self.title_label.pack(side="left")
        self.switch_var = tk.IntVar(self, value=0)
        self.switch = ctk.CTkSwitch(self.content, text="", width=44, height=26,
                                    switch_width=42, switch_height=24, corner_radius=12,
                                    button_color=WHITE, button_hover_color=WHITE,
                                    fg_color="#CAD4E3", progress_color=BLUE,
                                    variable=self.switch_var, command=self.request_switch)
        self.switch.pack(side="right", padx=(12, 0))
        for widget in (self.content, self.icon, self.title_label):
            widget.bind("<Button-1>", self.invoke)
        self.bind("<Return>", self.invoke)
        self.bind("<space>", self.invoke)
        self.bind("<Button-1>", self.invoke)
        self.bind("<FocusIn>", self.paint)
        self.bind("<FocusOut>", self.paint)
        tk.Frame.configure(self, takefocus=1)
        self._ready = True
        self.paint()

    def __getitem__(self, key):
        return self.cget(key)

    def cget(self, key):
        return self._state if key == "state" else super().cget(key)

    def configure(self, require_redraw=False, **kwargs):
        self._state = kwargs.pop("state", self._state)
        super().configure(require_redraw=require_redraw, **kwargs)
        if self._ready:
            self.paint()

    def request_switch(self):
        self.switch_var.set(int(self.selected))
        self.invoke()

    def invoke(self, event=None):
        if self._state != "disabled" and not self.selected:
            self.focus_set()
            self.command()

    def paint(self, event=None):
        fill = PALE if self.selected else "#F6F8FB"
        border = BLUE if self.focus_get() is self and self._state != "disabled" else fill
        ctk.CTkFrame.configure(self, fg_color=fill, border_width=1, border_color=border)
        self.content.configure(bg=fill)
        self.icon.configure(bg=fill, fg=MUTED if self._state == "disabled" else BLUE)
        self.title_label.configure(bg=fill, fg=MUTED if self._state == "disabled" else INK)
        self.switch.configure(state=self._state, progress_color="#A8B8CE" if self._state == "disabled" else BLUE)
        self.switch_var.set(int(self.selected))


class PageViewport(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview,
                                         width=10, corner_radius=5, border_spacing=2,
                                         fg_color=BG, button_color="#C0CDDF", button_hover_color="#93A6C2")
        self.scrollbar_visible = False
        self._visibility_job = None
        self.content = tk.Frame(self.canvas, bg=BG)
        self.slot = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", self.resize)
        self.content.bind("<Configure>", self.resize)
        self.winfo_toplevel().bind("<MouseWheel>", self.wheel, add=True)

    def resize(self, event=None):
        width = max(1, self.canvas.winfo_width())
        self.canvas.itemconfigure(self.slot, width=width)
        height = self.content.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if self._visibility_job is None:
            self._visibility_job = self.after_idle(self.update_visibility)

    def update_visibility(self):
        self._visibility_job = None
        if self.canvas.winfo_height() <= 1:
            return
        needed = self.content.winfo_reqheight() > self.canvas.winfo_height()
        if needed != self.scrollbar_visible:
            self.scrollbar_visible = needed
            if needed:
                self.scrollbar.grid(row=0, column=1, sticky="ns", padx=(6, 0))
            else:
                self.scrollbar.grid_forget()
                self.canvas.yview_moveto(0)
            #  隐藏后重新计算列宽，归还滚动条占位 / Recompute column width so a hidden scrollbar leaves no gutter
            self.columnconfigure(1, minsize=0)

    def wheel(self, event):
        if (str(event.widget).startswith(str(self)) and not isinstance(event.widget, tk.Text)
                and self.scrollbar_visible and event.delta):
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"
