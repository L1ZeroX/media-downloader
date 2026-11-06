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
    def test_add_link_button_appends_clipboard_without_replacing_existing_urls(self):
        self.app.url_input.insert("1.0", "https://example.com/first")
        self.app.url_input._textbox.tag_add("sel", "1.0", "1.end")
        with patch.object(self.app.url_menu, "clipboard_text", return_value=" https://example.com/second\nhttps://example.com/third "):
            self.app.paste_button.invoke()
        self.assertEqual(self.app.url_input.get("1.0", "end-1c"),
                         "https://example.com/first\nhttps://example.com/second\nhttps://example.com/third\n")
        before = self.app.url_input.get("1.0", "end-1c")
        with patch.object(self.app.url_menu, "clipboard_text", return_value=""):
            self.app.paste_button.invoke()
        self.assertEqual(before, self.app.url_input.get("1.0", "end-1c"))

    def test_thumbnail_badges_follow_selection_cache_and_missing_images(self):
        from PIL import Image
        import base64
        import io
        from downloader import preview_theme
        from downloader.palette import BUTTON, TEXT
        from downloader.popup_theme import luminance
        def thumbnail(color):
            stream = io.BytesIO()
            Image.new("RGB", (160, 90), color).save(stream, format="PNG")
            return base64.b64encode(stream.getvalue()).decode()
        self.app.animations_enabled.set(False)
        self.app.deiconify(); self.app.update()
        for key, color in (("purple", "#795780"), ("green", "#306d49")):
            self.add(key)
            self.app.items[key]["image"] = thumbnail(color)
        self.app.tree.selection_set("purple"); self.app.preview(); self.app.update()
        self.app.items["purple"].update(site="Youtube", duration=246, fps=30)
        self.app.preview(); self.app.update()
        purple = self.app.preview_title.cget("fg_color")
        self.assertEqual([b.cget("text") for b in self.app.preview_meta], ["Youtube", "4:06", "30fps"])
        self.assertTrue(all(b.winfo_ismapped() and b.cget("fg_color") == purple for b in self.app.preview_meta))
        self.assertEqual(purple, self.app.preview_heading.cget("fg_color"))
        self.assertGreaterEqual(1.05 / (luminance(purple) + .05), 4.5)
        self.assertGreater(self.app.preview_title.cget("corner_radius"), 0)
        with patch.object(preview_theme, "thumbnail_colors", wraps=preview_theme.thumbnail_colors) as extract:
            self.app.preview()
            self.app.wallpaper.set_image(Image.new("RGB", (100, 100), "#a01010"))
            self.app.wallpaper.paint()
            extract.assert_not_called()
            self.assertEqual(purple, self.app.preview_title.cget("fg_color"))
        self.app.tree.selection_set("green"); self.app.preview()
        self.assertNotEqual(purple, self.app.preview_title.cget("fg_color"))
        self.app.dark_mode.set(False); self.app.theme_changed()
        self.assertEqual(self.app.preview_title.cget("text_color"), "#ffffff")
        self.app.items["green"]["image"] = "invalid image"
        self.app.preview()
        self.assertEqual(self.app.preview_title.cget("fg_color"), BUTTON[0])
        self.app.tree.selection_remove(self.app.tree.selection()); self.app.preview()
        self.assertEqual(self.app.preview_heading.cget("text_color"), TEXT[0])
        self.assertFalse(any(b.winfo_manager() for b in self.app.preview_meta))

    def test_queue_headings_follow_wallpaper_and_cache_rounded_images(self):
        from PIL import Image
        from tkinter import ttk
        from downloader import queue_theme
        self.app.deiconify(); self.app.update()
        self.app.wallpaper.set_image(Image.new("RGB", (100, 100), "#7d3f92"))
        self.app.wallpaper.paint()
        purple = dict(self.app._queue_colors)
        self.assertEqual(self.settings.popup_background_colors, "オフ")
        layout = str(ttk.Style(self.app).layout("Treeview.Heading"))
        self.assertIn("Pandora.Heading.surface", layout)
        self.assertNotIn("Treeheading.cell", layout)
        self.assertNotIn("#ffffff", (purple["normal"], purple["hover"], purple["pressed"]))
        with patch.object(queue_theme, "heading_image", wraps=queue_theme.heading_image) as render:
            self.app.wallpaper.schedule(); self.app.wallpaper.paint()
            render.assert_not_called()
        self.app.wallpaper.set_image(Image.new("RGB", (100, 100), "#217a52"))
        self.app.wallpaper.paint()
        self.assertNotEqual(purple["normal"], self.app._queue_colors["normal"])
        self.app.dark_mode.set(False); self.app.theme_changed()
        self.assertEqual(self.app._queue_colors["text"], "#15171b")
        self.settings.background_transparency = "100"
        self.app.wallpaper.paint()
        self.assertEqual(self.app._queue_colors_key[0], "#1769f6")
        image = queue_theme.heading_image("#623e80")
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(image.getpixel((20, 18))[3], 255)

    def test_rounded_headings_keep_column_resize_and_row_check(self):
        self.app.animations_enabled.set(False)
        self.app.deiconify(); self.app.update()
        tree = self.app.tree
        edge = sum(tree.column(name, "width") for name in ("check", "title", "site"))
        separator = next(x for x in range(edge-4, edge+4) if tree.identify_region(x, 15) == "separator")
        before = tree.column("site", "width")
        self.app.queue_heading.event_generate("<ButtonPress-1>", x=separator, y=15)
        self.app.queue_heading.event_generate("<B1-Motion>", x=separator+30, y=15)
        self.app.queue_heading.event_generate("<ButtonRelease-1>", x=separator+30, y=15)
        self.app.update()
        self.assertGreater(tree.column("site", "width"), before)
        self.add("heading-check"); self.app.update()
        x, y, width, height = tree.bbox("heading-check", "check")
        tree.event_generate("<ButtonPress-1>", x=x+width//2, y=y+height//2)
        tree.event_generate("<ButtonRelease-1>", x=x+width//2, y=y+height//2)
        self.assertFalse(self.app.items["heading-check"]["selected"])

    def test_action_buttons_follow_wallpaper_without_popup_setting(self):
        from PIL import Image
        from downloader import popup_theme
        from downloader.palette import BLUE
        self.app.deiconify()
        self.app.update()
        self.assertEqual(self.settings.popup_background_colors, "オフ")
        self.app.wallpaper.set_image(Image.new("RGB", (100, 100), "#982f58"))
        self.app.wallpaper.paint()
        first = self.app.fetch_button.cget("fg_color")
        scrollbar_color = self.app.queue_scrollbar.cget("button_color")
        self.assertEqual(first, self.app.paste_button.cget("fg_color"))
        self.assertEqual(scrollbar_color, self.app.wallpaper.outer._scrollbar.cget("button_color"))
        self.assertNotEqual(first, BLUE[1])
        self.assertEqual(first, self.app.start_button.cget("fg_color"))
        with patch.object(popup_theme, "render", wraps=popup_theme.render) as render:
            self.app.wallpaper.schedule()
            self.app.wallpaper.paint()
            render.assert_not_called()
        self.app.animations_enabled.set(False)
        self.app.fetch_button._on_enter()
        self.assertEqual(self.app.fetch_button._visual_color, self.app.fetch_button.cget("hover_color"))
        self.app.fetch_button._on_leave()
        self.assertEqual(self.app.fetch_button._visual_color, first)
        self.app.dark_mode.set(False)
        self.app.theme_changed()
        self.assertNotEqual(self.app.fetch_button.cget("fg_color"), first)
        self.assertNotEqual(self.app.queue_scrollbar.cget("button_color"), scrollbar_color)
        self.app.start_button.configure(state="disabled")
        self.app.wallpaper.set_image(Image.new("RGB", (100, 100), "green"))
        self.app.wallpaper.paint()
        self.assertEqual(self.app.start_button.cget("state"), "disabled")
        self.assertNotEqual(self.app.fetch_button.cget("fg_color"), first)
        self.settings.background_transparency = "100"
        self.app.wallpaper.paint()
        self.assertEqual(self.app.fetch_button.cget("fg_color"), BLUE[0])
        self.settings.background_transparency = "0"
        self.app.wallpaper.set_image(None)
        self.app.wallpaper.paint()
        self.assertEqual(self.app.start_button.cget("fg_color"), BLUE[0])

    def test_wallpaper_popup_palette_and_triangle_indicators(self):
        from PIL import Image
        from downloader import popup_theme
        self.app.deiconify()
        self.app.update()
        self.app.animations_enabled.set(False)
        self.app.wallpaper.set_image(Image.new("RGB", (100, 100), "#d155aa"))
        self.settings.popup_background_colors = "オン"
        expected = popup_theme.popup_colors(self.app)
        self.assertNotEqual(expected["surface"], "#191c23")
        with patch.object(popup_theme, "render", wraps=popup_theme.render) as render:
            self.assertEqual(popup_theme.popup_colors(self.app), expected)
            render.assert_not_called()
        combo = self.app.format_combo
        self.assertEqual(combo.arrow.cget("text"), "▼")
        combo.open()
        self.assertEqual(combo.arrow.cget("text"), "▲")
        self.assertEqual(combo.popup.cget("bg"), expected["surface"])
        self.assertEqual(combo.option_buttons[1].cget("fg_color"), expected["surface"])
        combo.close()
        self.assertEqual(combo.arrow.cget("text"), "▼")
        self.app.url_input.insert("1.0", "https://example.com")
        self.app.url_menu.open()
        self.assertEqual(self.app.url_menu.popup.cget("bg"), expected["surface"])
        self.app.url_menu.close()
        self.app.dark_mode.set(False)
        self.app.theme_changed()
        self.assertNotEqual(popup_theme.popup_colors(self.app)["surface"], expected["surface"])
        self.settings.background_transparency = "100"
        self.assertEqual(popup_theme.popup_colors(self.app)["surface"], "#ffffff")
        self.settings.background_transparency = "0"
        self.settings.popup_background_colors = "オフ"
        self.assertEqual(popup_theme.popup_colors(self.app)["surface"], "#ffffff")

    def test_theme_switch_background_matches_glass_and_restores(self):
        from PIL import Image, ImageTk
        self.app.deiconify()
        self.app.update()
        self.settings.panel_transparency = "55"
        self.app.wallpaper.set_image(Image.new("RGB", (1200, 1000), "#a85372"))
        self.app.update()
        wallpaper, switch = self.app.wallpaper, self.app.theme_switch
        wallpaper.paint()
        heading = self.app.queue_heading
        x, y = wallpaper.viewport_position(heading)
        self.assertEqual(ImageTk.getimage(wallpaper.photos[heading]).getpixel((40, 0))[:3],
                         wallpaper._glass.getpixel((x + 40, y)))
        self.assertEqual(ImageTk.getimage(heading.photo).getpixel((40, 0))[3], 0)
        canvas = switch._bg_canvas
        x, y = wallpaper.viewport_position(canvas)
        actual = ImageTk.getimage(wallpaper.photos[canvas]).getpixel((50, 10))[:3]
        self.assertEqual(actual, wallpaper._glass.getpixel((x + 50, y + 10)))
        self.assertEqual(canvas.itemcget("glass_text", "text"), "ダークモード")
        switch._bg_canvas.event_generate("<Button-1>")
        self.assertFalse(self.app.dark_mode.get())
        wallpaper.paint()
        self.assertTrue(canvas.find_withtag("glass_text"))
        self.settings.panel_transparency = "0"
        wallpaper.paint()
        self.assertFalse(canvas.find_withtag("wallpaper"))
        self.assertFalse(canvas.find_withtag("glass_text"))

    def test_glass_scroll_cached_pixels_labels_and_restore(self):
        from PIL import Image, ImageTk
        from downloader import background, ui
        self.app.deiconify()
        self.app.update()
        wallpaper = self.app.wallpaper
        self.settings.panel_transparency = "55"
        self.settings.background_transparency = "0"
        wallpaper.set_image(Image.effect_noise((1200, 1000), 70).convert("RGB"))
        self.add("first")
        self.app.update()
        wallpaper.paint()
        with patch.object(background, "render", wraps=background.render) as render, \
             patch.object(background, "glass_image", wraps=background.glass_image) as blur, \
             patch.object(ImageTk.PhotoImage, "paste", autospec=True) as upload:
            wallpaper.paint()
            render.assert_not_called()
            blur.assert_not_called()
            upload.assert_not_called()
        with patch.object(background, "render", wraps=background.render) as render, \
             patch.object(background, "glass_image", wraps=background.glass_image) as blur:
            for fraction in (1., 0., .5):
                wallpaper.outer._parent_canvas.yview_moveto(fraction)
                empty = self.app.queue_empty
                x, y = wallpaper.viewport_position(empty)
                actual = ImageTk.getimage(wallpaper.photos[empty]).getpixel((5, 5))[:3]
                self.assertEqual(actual, wallpaper._glass.getpixel((x + 5, y + 5)))
            render.assert_not_called()
            blur.assert_not_called()
        self.app.progress_text.set("GPU変換中 42.0%")
        wallpaper.paint()
        text = [str(label._canvas.itemcget("glass_text", "text")) for label in wallpaper._labels]
        self.assertIn("GPU変換中 42.0%", text)
        self.assertEqual(self.app.tree.cget("height"), 1)
        for i in range(30):
            self.add(str(i))
        self.app.update()
        self.app.tree.selection_set("29")
        self.app.tree.see("29")
        self.app.update_idletasks()
        self.assertTrue(self.app.tree.bbox("29"))
        self.app._space_check(None)
        self.assertFalse(self.app.items["29"]["selected"])
        self.app.dark_mode.set(False)
        ui.apply_theme(self.app)
        wallpaper.paint()
        self.assertEqual(wallpaper._glass_key[0][-1], "#f3f4f6")
        self.settings.panel_transparency = "0"
        wallpaper.paint()
        self.app.update_idletasks()
        self.assertFalse(self.app.queue_empty.find_withtag("wallpaper"))
        self.assertFalse(self.app.queue_heading.find_withtag("wallpaper"))
        for label in wallpaper._labels:
            self.assertFalse(label._canvas.find_withtag("glass_text"))
        self.assertEqual(self.app.tree.cget("height"), 4)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = Settings(destination=self.directory.name)
        self.load_patch = patch.object(Settings, "load", return_value=self.settings)
        self.save_patch = patch.object(Settings, "save")
        self.load_patch.start()
        self.save_patch.start()
        self.update_patch = patch("downloader.updates.check_for_update", return_value=None)
        self.update_patch.start()
        self.app = Application()
        self.app.withdraw()

    def tearDown(self):
        self.app.update_idletasks()  # Drain ttk theme events before destroying the Tcl interpreter.
        for callback in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.tk.call("after", "cancel", callback)
        self.app.destroy()
        self.load_patch.stop()
        self.save_patch.stop()
        self.update_patch.stop()
        del self.app
        gc.collect()  # Dispose Tcl objects on their owning thread before worker tests start.
        self.directory.cleanup()

    def add(self, key):
        self.app._handle({"event": "entry", "item": {"key": key, "url": "https://example.com/" + key,
                            "title": "テスト " + key, "site": "test", "duration": None}})
        self.app.items[key]["state"] = "待機中"

    def test_update_popup_waits_for_download_and_uses_theme(self):
        from downloader.updates import Update
        from downloader.popup_theme import popup_colors
        self.app.animations_enabled.set(False)
        self.app.deiconify()
        self.app.update()
        self.app.mode = "download"
        self.app._receive_update({"update": Update("9.0.0", "https://github.com/L1ZeroX/media-downloader/releases", "https://github.com/L1ZeroX/media-downloader/releases", "テスト用の更新内容"), "message": "", "manual": False})
        self.app._show_pending_update()
        self.assertIsNone(self.app._update_dialog)
        self.app.mode = ""
        with patch.object(self.app, "state", return_value="zoomed"):
            self.app._show_pending_update()
        self.app.update()
        dialog = self.app._update_dialog
        self.assertTrue(dialog.winfo_viewable())
        self.assertEqual(dialog.cget("fg_color"), popup_colors(self.app)["surface"])
        self.assertEqual(self.app.grab_current(), dialog)
        dialog.destroy()
        self.app._show_pending_update()
        self.assertIsNone(self.app._update_notice)

    def test_automatic_check_failure_is_quiet_but_manual_is_visible(self):
        event = {"update": None, "manual": False, "error": "offline", "message": "通信できません"}
        self.app._receive_update(event)
        self.assertIsNone(self.app._update_notice)
        self.app._receive_update({**event, "manual": True})
        self.assertEqual(self.app._update_notice["message"], "通信できません")

    def test_version_network_result_is_delivered_through_queue(self):
        with patch("downloader.updates.check_for_update", return_value=None) as check:
            self.app.check_updates(manual=True)
            token, event = self.app.events.get(timeout=2)
            self.assertEqual(token, "app-update")
            self.assertTrue(self.app._update_checking)
            self.app._receive_update(event)
            self.assertFalse(self.app._update_checking)
            self.assertTrue(event["manual"])
            check.assert_called_once()

    def test_wallpaper_editor_apply_cancel_crop_and_reset(self):
        from PIL import Image
        from types import SimpleNamespace
        from downloader.background_editor import BackgroundEditor
        self.app.deiconify()
        self.app.update()
        dialog = BackgroundEditor(self.app, self.app)
        dialog.source = Image.new("RGB", (400, 300), "blue")
        dialog.crop = [.1, .1, .9, .9]
        dialog.update()
        dialog.draw()
        ox, oy, iw, ih = dialog.image_rect
        dialog.begin(SimpleNamespace(x=ox + .1 * iw, y=oy + .1 * ih))
        dialog.end(SimpleNamespace(x=ox + .3 * iw, y=oy + .25 * ih))
        self.assertAlmostEqual(dialog.crop[0], .3)
        self.assertAlmostEqual(dialog.crop[1], .25)
        dialog.fade_changed(65)
        dialog.panel_fade.set(55)
        dialog.panel_blur.set(24)
        dialog.popup_colors.set("オン")
        with patch("downloader.background_editor.CONFIG_DIR", Path(self.directory.name)):
            dialog.apply()
        self.assertEqual(self.settings.background_transparency, "65")
        self.assertEqual((self.settings.panel_transparency, self.settings.panel_blur), ("55", "24"))
        self.assertEqual(self.settings.popup_background_colors, "オン")
        self.assertTrue(Path(self.settings.background_image).is_file())
        self.assertIsNotNone(self.app.wallpaper.source)
        saved = self.settings.background_image
        dialog = BackgroundEditor(self.app, self.app)
        dialog.clear()
        dialog.panel_fade.set(5)
        dialog.popup_colors.set("オフ")
        dialog.cancel()
        self.assertEqual(self.settings.panel_transparency, "55")
        self.assertEqual(self.settings.popup_background_colors, "オン")
        self.assertEqual(self.settings.background_image, saved)
        self.app.theme_changed()
        self.app.wallpaper.paint()
        self.assertTrue(self.app.wallpaper.photos)
        self.settings.background_transparency = "100"
        self.app.wallpaper.paint()
        self.app.update_idletasks()
        self.assertFalse(self.app.wallpaper.photos)
        self.assertIsNotNone(self.app.wallpaper.source)
        self.settings.background_transparency = "0"
        self.app.wallpaper.paint()
        self.assertTrue(self.app.wallpaper.photos)
        dialog = BackgroundEditor(self.app, self.app)
        dialog.clear()
        dialog.apply()
        self.assertEqual(self.settings.background_image, "")
        self.assertIsNone(self.app.wallpaper.source)
        self.app.wallpaper.paint()
        self.app.update_idletasks()

    def test_wallpaper_failed_save_keeps_previous_settings(self):
        from PIL import Image
        from downloader.background_editor import BackgroundEditor
        dialog = BackgroundEditor(self.app, self.app)
        dialog.source = Image.new("RGB", (30, 30), "red")
        old = self.settings.background_image
        with patch("downloader.background_editor.CONFIG_DIR", Path(self.directory.name)), \
             patch.object(Settings, "save", side_effect=OSError("read only")), \
             patch("downloader.background_editor.messagebox.showerror") as error:
            dialog.apply()
            error.assert_called_once()
        self.assertEqual(self.settings.background_image, old)
        self.assertIsNone(self.app.wallpaper.source)
        dialog.cancel()

    def test_wallpaper_is_fixed_immediately_during_scroll_without_rescaling(self):
        from PIL import Image, ImageTk
        from downloader import background
        self.app.deiconify()
        self.app.update()
        wallpaper = self.app.wallpaper
        source = Image.new("RGB", (1200, 1000))
        for y in range(source.height):
            source.paste((y % 251, y // 4, 90), (0, y, source.width, y + 1))
        self.settings.background_transparency = "0"
        wallpaper.set_image(source)
        canvas = wallpaper.outer._parent_canvas
        with patch.object(background, "render", wraps=background.render) as render:
            wallpaper.paint()
            for fraction in (.5, 0., 1., .2):
                canvas.yview_moveto(fraction)
                # No update(), timer or idle wait: the frame about to display is correct.
                scroll_y = round(canvas.canvasy(0))
                x = canvas.winfo_rootx() - self.app.winfo_rootx() + 10
                y = canvas.winfo_rooty() - self.app.winfo_rooty() + 10
                tile = ImageTk.getimage(wallpaper.photos[wallpaper.body_label])
                self.assertEqual(tile.getpixel((10, scroll_y + 10))[:3], wallpaper._picture.getpixel((x, y)))
            self.assertEqual(render.call_count, 1)

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
