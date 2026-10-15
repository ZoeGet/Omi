from pathlib import Path
import sys
import tkinter as tk
from tkinter import font as tkfont
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modern_ui import Button, Card, ModernDesktopApp


class LayoutTests(unittest.TestCase):
    def dispose(self, window):
        window.update_idletasks()
        for callback in window.tk.call("after", "info"):
            window.after_cancel(callback)
        window.destroy()

    def test_summary_and_mode_rows_fit_at_multiple_font_scales(self):
        for scaling in (1.3333333333, 1.6666666667, 2.0):
            with self.subTest(scaling=scaling):
                window = tk.Tk()
                try:
                    window.tk.call("tk", "scaling", scaling)
                    app = ModernDesktopApp(window, demo=True)
                    window.geometry("1060x780+10000+10000")
                    window.update()
                    summary = app.preview_summary
                    font = tkfont.Font(font=summary.cget("font"))
                    self.assertGreaterEqual(summary.winfo_height(), font.metrics("linespace") + 8)
                    self.assertGreaterEqual(summary.winfo_height(), summary.winfo_reqheight())
                    self.assertLessEqual(summary.winfo_y() + summary.winfo_height(), summary.master.winfo_height())
                    local, monitor = app.local_button, app.monitor_button
                    self.assertGreater(monitor.winfo_y(), local.winfo_y())
                    self.assertEqual(local.winfo_width(), monitor.winfo_width())
                    for row in app.mode_rows.values():
                        self.assertGreaterEqual(row.winfo_height(), row.winfo_reqheight())
                        for item in row.find_all():
                            if row.type(item) == "text":
                                x1, y1, x2, y2 = row.bbox(item)
                                self.assertGreaterEqual(y1, 0)
                                self.assertLessEqual(y2, row.winfo_height())
                                self.assertLessEqual(x2, row.winfo_width() - 65)
                    app.page_host.canvas.yview_moveto(1)
                    window.update_idletasks()
                    self.assertAlmostEqual(app.page_host.canvas.yview()[1], 1.0)
                    self.assertEqual(len(app.quick_preview.find_all()), 14)
                finally:
                    self.dispose(window)

    def test_mode_switches_are_exclusive_and_follow_confirmed_state(self):
        window = tk.Tk()
        window.withdraw()
        try:
            app = ModernDesktopApp(window, demo=True)
            requested = []
            app.command = requested.append
            app.connected = True
            app.snapshot = dict(operations=["light"], monitorLights=True, monitorGreenOff=True,
                                monitorRequested=False, state=dict(mode="local", monitorOutput="local"))
            app._controls()
            self.assertTrue(app.local_button.selected)
            app.monitor_button.invoke()
            self.assertEqual(requested, ["monitor"])
            self.assertFalse(app.monitor_button.selected)
            app.snapshot.update(monitorRequested=True, state=dict(mode="monitor", monitorOutput="connected"))
            app._controls()
            self.assertFalse(app.local_button.selected)
            self.assertTrue(app.monitor_button.selected)
            app.monitor_button.invoke()
            self.assertEqual(requested, ["monitor"])
            app.local_button.invoke()
            self.assertEqual(requested, ["monitor", "local"])
            app.snapshot["state"] = None
            app._controls()
            self.assertFalse(app.local_button.selected)
            self.assertFalse(app.monitor_button.selected)
        finally:
            self.dispose(window)

    def test_pages_fit_minimum_window_and_monitor_locks_all_light_actions(self):
        try:
            window = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk display unavailable")
        try:
            app = ModernDesktopApp(window, demo=True)
            window.geometry("1060x780+10000+10000")
            window.update()
            for page in app.pages:
                app.show_page(page)
                window.update_idletasks()
                for card in app.pages[page].winfo_children():
                    if isinstance(card, Card):
                        self.assertLessEqual(card.winfo_y() + card.winfo_height(), app.pages[page].winfo_height())
                def inspect(widget):
                    for child in widget.winfo_children():
                        if child.winfo_manager() and isinstance(child, (tk.Label, Button)):
                            self.assertGreaterEqual(child.winfo_height(), child.winfo_reqheight(),
                                                    f"{page}: compressed {child.winfo_class()} {child}")
                        inspect(child)
                inspect(app.pages[page])
            app.connected = True
            app.snapshot = dict(operations=["light"], monitorLights=True, monitorGreenOff=True, monitorRequested=True)
            app._controls()
            for widget in (app.apply_button, app.color_button, *app.swatch_buttons, *app.effect_tiles.values()):
                self.assertEqual(str(widget.cget("state")), "disabled")
            self.assertEqual(str(app.local_button.cget("state")), "normal")
        finally:
            self.dispose(window)


if __name__ == "__main__":
    unittest.main()
