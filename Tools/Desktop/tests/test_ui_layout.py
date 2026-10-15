from pathlib import Path
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modern_ui import Button, Card, ModernDesktopApp


class LayoutTests(unittest.TestCase):
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
            window.destroy()


if __name__ == "__main__":
    unittest.main()
