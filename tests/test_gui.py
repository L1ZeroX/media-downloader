from pathlib import Path
import tempfile
import gc
import time
import ctypes
from ctypes import wintypes
import os
import unittest
from unittest.mock import patch

from downloader.app import Application
from downloader.core import Settings
from downloader.window_shape import windows_api


class GuiStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(destination=self.directory.name)
        self.load_patch = patch.object(Settings, "load", return_value=self.settings)
        self.save_patch = patch.object(Settings, "save")
        self.load_patch.start()
        self.save_patch.start()
        self.app = Application()
        self.app.withdraw()

    def tearDown(self):
        for callback in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.tk.call("after", "cancel", callback)
        self.app.destroy()
        self.load_patch.stop()
        self.save_patch.stop()
        del self.app
        gc.collect()  # Dispose Tcl objects on their owning thread before worker tests start.
        self.directory.cleanup()

    def add(self, key):
        self.app._handle({"event": "entry", "item": {"key": key, "url": "https://example.com/" + key,
                            "title": "テスト " + key, "site": "test", "duration": None}})
        self.app.items[key]["state"] = "待機中"

    def test_selection_quality_memory_and_unknown_progress(self):
        self.add("first")
        self.add("second")
        self.app._toggle("first")
        self.assertFalse(self.app.items["first"]["selected"])
        self.app.quality.set("720p以下")
        self.app.media_format.set("MP3")
        self.app.format_changed()
        self.assertEqual(self.app.quality.get(), "192kbps")
        self.app.quality.set("320kbps")
        self.app.media_format.set("MP4")
        self.app.format_changed()
        self.assertEqual(self.app.quality.get(), "720p以下")
        self.assertEqual(self.settings.audio_quality, "320kbps")
        self.app._progress({"phase": "映像取得", "percent": None, "downloaded": 2000})
        self.assertTrue(self.app.indeterminate)
        self.assertIn("不明", self.app.progress_text.get())
        self.app._progress({"phase": "変換中", "percent": 50})
        self.assertFalse(self.app.indeterminate)

    def test_theme_switch_and_animation_preferences(self):
        self.app.dark_mode.set(False)
        self.app.theme_changed()
        self.assertEqual(self.settings.appearance, "ライト")
        self.assertEqual(self.app.table_frame.cget("bg"), "#ffffff")
        self.app.dark_mode.set(True)
        self.app.theme_changed()
        self.assertEqual(self.app.table_frame.cget("bg"), "#191c23")
        self.app.animations_enabled.set(False)
        self.app.remember_settings()
        self.app.progress.configure(value=75)
        self.assertAlmostEqual(self.app.progress.get(), .75)
        self.assertEqual(self.settings.animations, "オフ")

    def test_url_context_paste_replaces_selection_and_handles_empty_clipboard(self):
        editor = self.app.url_menu.editor
        editor.insert("1.0", "before old after")
        editor.tag_add("sel", "1.7", "1.10")
        with patch.object(editor, "clipboard_get", return_value="https://example.com/1\r\nhttps://example.com/2"):
            self.app.url_menu.execute("paste")
        self.assertEqual(editor.get("1.0", "end-1c"), "before https://example.com/1\nhttps://example.com/2 after")
        self.app.url_menu.select_all()
        with patch.object(self.app.url_menu, "clipboard_text", return_value=""):
            self.app.url_menu.execute("paste")
        self.assertTrue(editor.get("1.0", "end-1c").startswith("before"))

    def test_url_context_menu_keyboard_and_outside_dismissal(self):
        self.app.animations_enabled.set(False)
        self.app.deiconify()
        self.app.update()
        menu = self.app.url_menu
        with patch.object(menu, "clipboard_text", return_value="https://example.com/video"):
            editor = menu.editor
            editor.event_generate("<Button-3>", x=10, y=10)
            self.app.update()
            self.assertIsNotNone(menu.popup)
            self.assertEqual(menu.actions, ["paste"])
            menu.move(1)
            menu.popup.event_generate("<Return>")
            self.app.update()
            self.assertEqual(editor.get("1.0", "end-1c"), "https://example.com/video")
            self.assertIsNone(menu.popup)
            menu.open_keyboard()
            self.app.update()
            self.app.event_generate("<ButtonPress-1>")
            self.assertIsNone(menu.popup)

    def test_layout_preserves_input_queue_and_keeps_download_controls_visible(self):
        from downloader.ui import apply_layout
        self.add("first")
        self.app.url_input.insert("1.0", "https://example.com/video")
        self.app.geometry("1080x720")
        self.app.deiconify()
        for size, height in (("大きめ", 180), ("コンパクト", 72), ("標準", 112)):
            self.settings.url_input_size = size
            self.settings.show_preview = "オフ"
            self.settings.show_log = "オフ"
            apply_layout(self.app)
            self.app.update()
            self.assertEqual(self.app.url_input.cget("height"), height)
            self.assertFalse(self.app.preview_card.winfo_ismapped())
            self.assertFalse(self.app.log_box.winfo_ismapped())
            self.assertLess(self.app.start_button.winfo_rooty() + self.app.start_button.winfo_height(),
                            self.app.winfo_rooty() + self.app.winfo_height())
        self.settings.show_preview = self.settings.show_log = "オン"
        apply_layout(self.app)
        self.app.update()
        self.assertTrue(self.app.preview_card.winfo_ismapped())
        self.assertTrue(self.app.log_box.winfo_ismapped())
        self.assertIn("first", self.app.items)
        self.assertEqual(self.app.url_input.get("1.0", "end-1c"), "https://example.com/video")

    def test_custom_popover_selects_and_disabled_controls_do_not_open(self):
        self.app.animations_enabled.set(False)
        self.app.deiconify()
        self.app.attributes("-alpha", 1)
        self.app.update()
        self.app.format_combo.open()
        self.app.update()
        self.assertIsNotNone(self.app.format_combo.popup)
        self.app.format_combo.move(1)
        self.app.format_combo.choose(self.app.format_combo.values[self.app.format_combo.focus_index])
        self.assertEqual(self.app.media_format.get(), "MP3")
        self.assertIsNone(self.app.format_combo.popup)
        self.app.fps_combo.open()
        self.assertIsNone(self.app.fps_combo.popup)
        self.app.quality_combo.open()
        self.assertIsNotNone(self.app.quality_combo.popup)
        self.app.event_generate("<ButtonPress-1>")
        self.app.update()
        self.assertIsNone(self.app.quality_combo.popup)

    def test_selection_text_and_background_fill_the_control_after_resize(self):
        self.app.animations_enabled.set(False)
        self.app.deiconify()
        self.app.attributes("-alpha", 1)
        for width in (1080, 1400):
            self.app.geometry(f"{width}x940")
            self.app.update()
            for control in (self.app.format_combo, self.app.quality_combo, self.app.fps_combo, self.app.encoding_combo):
                with self.subTest(width=width, value=control.get()):
                    self.assertIsNotNone(control._text_label, "The selected value must have a visible label")
                    self.assertEqual(control._text_label.cget("text"), control.get())
                    self.assertGreater(control._text_label.winfo_width(), 10)
                    self.assertAlmostEqual(control._canvas.winfo_width(), control.winfo_width(), delta=1)

    @unittest.skipUnless(os.name == "nt", "Native Windows popup clipping")
    def test_popup_corners_are_clipped_without_a_transparent_color(self):
        self.app.animations_enabled.set(False)
        self.app.deiconify()
        self.app.attributes("-alpha", 1)
        self.app.update()
        user32, gdi32 = windows_api()
        user32.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
        user32.GetWindowRgn.restype = ctypes.c_int
        gdi32.PtInRegion.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_int]
        gdi32.PtInRegion.restype = wintypes.BOOL
        for dark in (False, True):
            self.app.dark_mode.set(dark)
            self.app.theme_changed()
            self.app.update()
            self.app.quality_combo.open()
            popup = self.app.quality_combo.popup
            popup.update_idletasks()
            self.assertEqual(popup.attributes("-transparentcolor"), "")
            width, height = popup.winfo_width(), popup.winfo_height()
            region = gdi32.CreateRoundRectRgn(0, 0, 1, 1, 1, 1)
            try:
                self.assertNotEqual(user32.GetWindowRgn(user32.GetAncestor(popup.winfo_id(), 2), region), 0)
                self.assertTrue(gdi32.PtInRegion(region, width // 2, height // 2))
                for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
                    self.assertFalse(gdi32.PtInRegion(region, x, y), (dark, x, y))
            finally:
                gdi32.DeleteObject(region)
                self.app.quality_combo.close()

    def test_closing_animated_popover_cancels_pending_frames(self):
        errors = []
        self.app.report_callback_exception = lambda *args: errors.append(args)
        self.app.deiconify()
        self.app.update()
        self.app.quality_combo.open()
        self.app.update()
        self.app.quality_combo.close()
        deadline = time.monotonic() + .25
        while time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertFalse(errors, errors)

    @patch("downloader.app.WorkerProcess")
    def test_queue_continues_after_error_and_retry_only_failed(self, process):
        self.add("first")
        self.add("second")
        with patch.object(self.app, "_refresh_tools", return_value={"ffmpeg": "x", "ffprobe": "y", "deno": "z"}):
            self.app.start()
            self.assertEqual(self.app.current, "first")
            self.app._handle({"event": "error", "message": "network failed"})
            self.app._handle({"event": "exit", "code": 1, "stopped": False})
            self.assertEqual(self.app.current, "second")
            self.app._handle({"event": "done", "path": str(Path(self.directory.name) / "ok.mp4")})
            self.app._handle({"event": "exit", "code": 0, "stopped": False})
            self.assertEqual((self.app.completed, self.app.failed), (1, 1))
            self.app.start(retry=True)
            self.assertEqual(self.app.current, "first")
            self.assertEqual(self.app.total, 1)
            self.app._handle({"event": "exit", "code": 1, "stopped": True})
            self.assertEqual(self.app.items["first"]["state"], "停止")


if __name__ == "__main__":
    unittest.main()
