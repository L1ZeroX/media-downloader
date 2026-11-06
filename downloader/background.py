"""Local wallpaper loading, cropping and compositing. Never modifies the source."""
import hashlib
import io
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
import warnings

import customtkinter as ctk
from PIL import Image, ImageOps, ImageTk, ImageStat, ImageFilter, ImageDraw

from .palette import BACKGROUND, CARD


def bounded_int(value, low, high, default):
    try:
        return max(low, min(high, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def glass_image(picture, amount, radius, tint):
    """Blur once at quarter resolution; scrolling only crops this cached surface."""
    if radius:
        small = picture.resize((max(1, picture.width // 4), max(1, picture.height // 4)), Image.Resampling.BILINEAR)
        blurred = small.filter(ImageFilter.GaussianBlur(radius / 4)).resize(picture.size, Image.Resampling.BILINEAR)
    else:
        blurred = picture
    return Image.blend(Image.new("RGB", picture.size, tint), blurred, amount / 100)


def parse_crop(value):
    try:
        box = tuple(float(x) for x in value.split(","))
        if len(box) == 4 and all(math.isfinite(v) for v in box):
            left, top, right, bottom = box
            if 0 <= left < right <= 1 and 0 <= top < bottom <= 1:
                return box
    except (ValueError, TypeError, AttributeError):
        pass
    return (0., 0., 1., 1.)


def transparency(value):
    try:
        return max(0, min(100, int(value)))
    except (ValueError, TypeError, OverflowError):
        return 35


def load_image(path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if source.width * source.height > 36_000_000:
                raise ValueError("画像が大きすぎます。3600万画素以下の画像を選んでください。")
            source = ImageOps.exif_transpose(source)
            source.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            return source.convert("RGBA")


def cropped(image, crop):
    left, top, right, bottom = parse_crop(crop)
    width, height = image.size
    x, y = min(width - 1, int(left * width)), min(height - 1, int(top * height))
    return image.crop((x, y, max(x + 1, int(right * width)), max(y + 1, int(bottom * height))))


def render(image, size, crop, fade, base):
    result = Image.new("RGB", size, base)
    if image is not None and transparency(fade) < 100:
        foreground = ImageOps.fit(cropped(image, crop), size, Image.Resampling.LANCZOS)
        if foreground.mode != "RGBA":
            foreground = foreground.convert("RGBA")
        alpha = foreground.getchannel("A").point(lambda a: round(a * (1 - transparency(fade) / 100)))
        result.paste(foreground, (0, 0), alpha)
    return result


def store_image(image, directory):
    """Retain a normalized copy so moving the original cannot break the wallpaper."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    folder = Path(directory) / "backgrounds"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (hashlib.sha256(data).hexdigest() + ".png")
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(target)
    return str(target)


class WallpaperFrame(ctk.CTkFrame):
    """Paint the wallpaper behind the normal opaque, rounded card surface."""
    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        painter = getattr(self.winfo_toplevel(), "wallpaper", None)
        if painter:
            painter.schedule()


class WallpaperLabel(ctk.CTkLabel):
    """Keep native text geometry/accessibility, paint text over the glass canvas."""
    def __init__(self, *args, **kwargs):
        self._variable = kwargs.get("textvariable")
        self._trace = None
        super().__init__(*args, **kwargs)
        if isinstance(self._variable, tk.Variable):
            self._trace = self._variable.trace_add("write", self._changed)

    def _changed(self, *args):
        painter = getattr(self.winfo_toplevel(), "wallpaper", None)
        if painter:
            painter.schedule()

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        self._changed()

    def configure(self, **kwargs):
        super().configure(**kwargs)
        self._changed()

    def destroy(self):
        if self._trace:
            self._variable.trace_remove("write", self._trace)
        super().destroy()


class WallpaperSwitch(ctk.CTkSwitch):
    """Let the compositor cover the switch's separate background and text label."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bg_canvas.bind("<Button-1>", self.toggle)
        self._bg_canvas.bind("<Enter>", self._on_enter)
        self._bg_canvas.bind("<Leave>", self._on_leave)
        self._canvas.configure(takefocus=True)
        self._canvas.bind("<space>", lambda _: self.toggle())

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        painter = getattr(self.winfo_toplevel(), "wallpaper", None)
        if painter:
            painter.schedule()


class Wallpaper:
    def __init__(self, app, outer, frames, header):
        self.app, self.outer, self.frames, self.header = app, outer, frames, header
        self.source = None
        self.photos = {}
        self.timer = None
        self.closed = False
        self._scroll_updating = False
        self._picture_key = None
        self._picture = None
        self._glass_key = None
        self._popup_colors_key = None
        self._glass = None
        self._tile_keys = {}
        self._plain_key = None
        self._painting = False
        self._dirty = True
        self._last_state = None
        self._surfaces = []
        self._labels = []
        self._cards = {frame for frame in frames if isinstance(frame, WallpaperFrame) and frame.cget("fg_color") != "transparent"}
        def collect(widget, card=None):
            if widget in self._cards:
                card = widget
            if card is not None and hasattr(widget, "_canvas"):
                self._surfaces.append((widget, card))
                if isinstance(widget, WallpaperLabel):
                    self._labels.append(widget)
            for child in widget.winfo_children():
                if not isinstance(child, tk.Toplevel):
                    collect(child, card)
        collect(app)
        self.results = queue.Queue()
        self.root_label = tk.Label(app, bd=0)
        self.body_label = tk.Label(outer, bd=0)
        self.root_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.root_label.lower()
        self.body_label.place(x=0, y=0, relwidth=1, relheight=1)
        self.body_label.lower()
        app.bind("<Configure>", self.schedule, add="+")
        app.bind("<Destroy>", self.on_destroy, add="+")
        outer._parent_canvas.configure(yscrollcommand=self.on_scroll)
        # Scroll and repaint in one event, before Tk presents the moved child windows.
        # CTk's wheel handler and the scrollbar must both use this path.
        canvas = outer._parent_canvas
        original_yview = canvas.yview
        def yview(*args):
            result = original_yview(*args)
            if args and not self.closed:
                self.paint()
            return result
        canvas.yview = yview
        canvas.yview_moveto = lambda fraction: yview("moveto", fraction)
        canvas.yview_scroll = lambda number, what: yview("scroll", number, what)
        outer._scrollbar.configure(command=yview)
        if app.settings.background_image:
            path = app.settings.background_image
            results = self.results
            def read():
                try:
                    results.put((load_image(path), None))
                except Exception as error:
                    results.put((None, str(error)))
            threading.Thread(target=read, daemon=True).start()
            app.after(80, self.poll)
        self.schedule()

    def poll(self):
        if self.closed:
            return
        try:
            source, error = self.results.get_nowait()
        except queue.Empty:
            self.app.after(80, self.poll)
            return
        # The settings dialog may have already replaced the wallpaper while loading.
        if not getattr(self, "replaced", False):
            self.source = source
            if error:
                self.app.log("背景画像を読み込めません。標準背景で起動しました: " + error)
            self.schedule()
            from .ui import fit_queue
            fit_queue(self.app)

    def set_image(self, image):
        self.replaced = True
        self.source = image
        self._picture_key = None
        self._glass_key = None
        self._popup_colors_key = None
        from .ui import fit_queue
        fit_queue(self.app)
        self.schedule()

    def on_destroy(self, event):
        if event.widget is self.app:
            self.closed = True
            if self.timer:
                self.app.after_cancel(self.timer)
                self.timer = None

    def on_scroll(self, first, last):
        if self.closed or self._scroll_updating:
            return
        self._scroll_updating = True
        try:
            # CTkScrollbar.set() flushes idle drawing: update the wallpaper FIRST.
            self.paint()
            self.outer._scrollbar.set(first, last)
        finally:
            self._scroll_updating = False

    def viewport_position(self, widget):
        """Use document coordinates even before Tk moves the native child windows."""
        current, x, y = widget, 0, 0
        while current is not self.outer and current is not self.app:
            x += current.winfo_x()
            y += current.winfo_y()
            current = current.master
        if current is self.outer:
            canvas = self.outer._parent_canvas
            return (round(canvas.winfo_rootx() - self.app.winfo_rootx() + x - canvas.canvasx(0)),
                    round(canvas.winfo_rooty() - self.app.winfo_rooty() + y - canvas.canvasy(0)))
        return widget.winfo_rootx() - self.app.winfo_rootx(), widget.winfo_rooty() - self.app.winfo_rooty()

    def schedule(self, event=None):
        if event is not None and event.widget is not self.app and event.widget.winfo_toplevel() is not self.app:
            return
        self._dirty = True
        if not self.closed and self.timer is None:
            self.timer = self.app.after(45, self.paint)

    def paint(self):
        if self.closed or self._painting:
            return
        if self.timer is not None:
            self.app.after_cancel(self.timer)
            self.timer = None
        settings = self.app.settings
        state = (id(self.source), self.app.winfo_width(), self.app.winfo_height(),
                 settings.background_crop, settings.background_transparency,
                 settings.panel_transparency, settings.panel_blur, self.app.dark_mode.get(),
                 self.outer._parent_canvas.canvasy(0))
        if not self._dirty and self._last_state == state:
            return
        self._dirty = False
        self._last_state = state
        self._painting = True
        try:
            self._paint()
        finally:
            self._painting = False

    def _paint(self):
        if self.closed:
            return
        app = self.app
        base = BACKGROUND[1 if app.dark_mode.get() else 0]
        enabled = bool(self.source is not None and transparency(app.settings.background_transparency) < 100
                       and bounded_int(app.settings.panel_transparency, 0, 85, 0))
        if getattr(self, "_glass_enabled", None) != enabled:
            self._glass_enabled = enabled
            from .ui import fit_queue
            fit_queue(app)
        if self.source is None or transparency(app.settings.background_transparency) == 100:
            plain_key = (base, app.settings.panel_transparency)
            if self._plain_key == plain_key:
                return
            self._plain_key = plain_key
            for label in (self.root_label, self.body_label):
                label.configure(image="", bg=base)
            for frame in self.frames:
                frame._canvas.delete("wallpaper")
                frame._canvas.itemconfigure("inner_parts", state="normal")
            self.header.delete("wallpaper")
            self.header.configure(bg=base)
            self.header.itemconfigure("heading", fill="#f1f3f7" if app.dark_mode.get() else "#15171b")
            self.header.itemconfigure("caption", fill="#c3cad6" if app.dark_mode.get() else "#505866")
            self.photos.clear()
            self._tile_keys.clear()
            self._restore_surfaces()
            return
        self._plain_key = None
        size = (max(1, app.winfo_width()), max(1, app.winfo_height()))
        key = (id(self.source), size, app.settings.background_crop, app.settings.background_transparency, base)
        if self._picture_key != key:
            self._picture = render(self.source, size, app.settings.background_crop, app.settings.background_transparency, base)
            self._picture_key = key
        picture = self._picture
        amount = bounded_int(app.settings.panel_transparency, 0, 85, 0)
        blur = bounded_int(app.settings.panel_blur, 0, 40, 18)
        glass_key = (key, amount, blur)
        if amount and self._glass_key != glass_key:
            self._glass = glass_image(picture, amount, blur, CARD[1 if app.dark_mode.get() else 0])
            self._glass_key = glass_key

        def photo(widget, glass=False, rounded=None):
            x, y = self.viewport_position(widget)
            dimensions = (max(1, widget.winfo_width()), max(1, widget.winfo_height()))
            tile_key = (glass_key if glass else key, x, y, dimensions, rounded)
            if self._tile_keys.get(widget) == tile_key:
                return self.photos[widget]
            tile = Image.new("RGB", dimensions, base)
            # paste clips automatically and fills offscreen portions with the theme color.
            tile.paste(self._glass if glass and rounded is None else picture, (-x, -y))
            if glass and rounded is not None:
                layer = Image.new("RGB", dimensions, CARD[1 if app.dark_mode.get() else 0])
                layer.paste(self._glass, (-x, -y))
                mask = Image.new("L", dimensions)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, dimensions[0] - 1, dimensions[1] - 1), radius=rounded, fill=255)
                tile.paste(layer, (0, 0), mask)
            result = self.photos.get(widget)
            if result is not None and (result.width(), result.height()) == tile.size:
                result.paste(tile)
            else:
                result = ImageTk.PhotoImage(tile, master=app)
            self.photos[widget] = result
            self._tile_keys[widget] = tile_key
            return result

        for label in (self.root_label, self.body_label):
            label.configure(image=photo(label), bg=base)
        for frame in self.frames:
            canvas = frame._canvas
            is_glass = bool(amount and frame in self._cards)
            radius = round(frame.cget("corner_radius") * frame._get_widget_scaling()) if is_glass else None
            if canvas.find_withtag("wallpaper"):
                canvas.itemconfigure("wallpaper", image=photo(canvas, is_glass, radius))
            else:
                canvas.create_image(0, 0, anchor="nw", image=photo(canvas, is_glass, radius), tags="wallpaper")
            canvas.tag_lower("wallpaper")
            # Transparent layout containers reveal the wallpaper; cards stay readable.
            canvas.itemconfigure("inner_parts", state="hidden" if is_glass or frame.cget("fg_color") == "transparent" else "normal")
            canvas.itemconfigure("background_parts", state="hidden")
        if amount:
            for widget, card in self._surfaces:
                if widget in self.frames or not widget.winfo_ismapped():
                    continue
                canvas = widget._canvas
                if not canvas.winfo_ismapped():
                    continue
                if canvas.find_withtag("wallpaper"):
                    canvas.itemconfigure("wallpaper", image=photo(canvas, True))
                else:
                    canvas.create_image(0, 0, anchor="nw", image=photo(canvas, True), tags="wallpaper")
                canvas.tag_lower("wallpaper")
                canvas.itemconfigure("background_parts", state="hidden")
                if isinstance(widget, (ctk.CTkFrame, WallpaperLabel)) and widget.cget("fg_color") == "transparent":
                    canvas.itemconfigure("inner_parts", state="hidden")
                if isinstance(widget, WallpaperLabel):
                    self._draw_label(widget)
                elif isinstance(widget, WallpaperSwitch):
                    bg = widget._bg_canvas
                    if bg.find_withtag("wallpaper"):
                        bg.itemconfigure("wallpaper", image=photo(bg, True))
                    else:
                        bg.create_image(0, 0, anchor="nw", image=photo(bg, True), tags="wallpaper")
                    bg.tag_lower("wallpaper")
                    self._draw_text(widget, widget._text_label, bg)
                    tk.Misc.lift(widget._canvas, bg)
            empty = app.queue_empty
            if empty.winfo_ismapped():
                if empty.find_withtag("wallpaper"):
                    empty.itemconfigure("wallpaper", image=photo(empty, True))
                else:
                    empty.create_image(0, 0, anchor="nw", image=photo(empty, True), tags="wallpaper")
        else:
            self._restore_surfaces()
        if self.header.find_withtag("wallpaper"):
            self.header.itemconfigure("wallpaper", image=photo(self.header))
        else:
            self.header.create_image(0, 0, anchor="nw", image=photo(self.header), tags="wallpaper")
        self.header.tag_lower("wallpaper")
        self.header.configure(bg=base)
        hx, hy = self.viewport_position(self.header)
        sx, sy = max(0, min(size[0] - 1, hx)), max(0, min(size[1] - 1, hy))
        sample = picture.crop((sx, sy, max(sx + 1, min(size[0], hx + 400)), max(sy + 1, min(size[1], hy + 96))))
        bright = ImageStat.Stat(sample.convert("L")).mean[0] > 145
        self.header.itemconfigure("heading", fill="#15171b" if bright else "#f1f3f7")
        self.header.itemconfigure("caption", fill="#3b414b" if bright else "#e0e5ee")

    def _draw_label(self, widget):
        self._draw_text(widget, widget._label, widget._canvas)

    def _draw_text(self, widget, native, canvas):
        native.lower(canvas)
        value = str(native.cget("text"))
        signature = (value, native.winfo_x(), native.winfo_y(), native.winfo_width(), native.winfo_height(),
                     str(native.cget("font")), str(native.cget("fg")), str(native.cget("wraplength")), str(native.cget("justify")))
        if getattr(widget, "_glass_text_signature", None) == signature and canvas.find_withtag("glass_text"):
            return
        widget._glass_text_signature = signature
        canvas.delete("glass_text")
        canvas.create_text(native.winfo_x() + native.winfo_width() / 2, native.winfo_y() + native.winfo_height() / 2,
                           text=value, font=native.cget("font"), fill=native.cget("fg"),
                           width=native.cget("wraplength"), justify=native.cget("justify"), tags="glass_text")

    def _restore_surfaces(self):
        for widget, _ in self._surfaces:
            if widget in self.frames:
                continue
            canvas = widget._canvas
            canvas.delete("wallpaper", "glass_text")
            canvas.itemconfigure("inner_parts", state="normal")
            canvas.itemconfigure("background_parts", state="normal")
            if isinstance(widget, WallpaperLabel):
                widget._label.lift(canvas)
            elif isinstance(widget, WallpaperSwitch):
                bg = widget._bg_canvas
                bg.delete("wallpaper", "glass_text")
                widget._text_label.lift(bg)
                tk.Misc.lift(widget._canvas, bg)
                self.photos.pop(bg, None)
                self._tile_keys.pop(bg, None)
            self.photos.pop(canvas, None)
            self._tile_keys.pop(canvas, None)
        if hasattr(self.app, "queue_empty"):
            self.app.queue_empty.delete("wallpaper")
