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
from PIL import Image, ImageOps, ImageTk, ImageStat

from .palette import BACKGROUND


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

    def set_image(self, image):
        self.replaced = True
        self.source = image
        self._picture_key = None
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
        if not self.closed and self.timer is None:
            self.timer = self.app.after(45, self.paint)

    def paint(self):
        if self.timer is not None:
            self.app.after_cancel(self.timer)
            self.timer = None
        if self.closed:
            return
        app = self.app
        base = BACKGROUND[1 if app.dark_mode.get() else 0]
        if self.source is None or transparency(app.settings.background_transparency) == 100:
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
            return
        size = (max(1, app.winfo_width()), max(1, app.winfo_height()))
        key = (id(self.source), size, app.settings.background_crop, app.settings.background_transparency, base)
        if self._picture_key != key:
            self._picture = render(self.source, size, app.settings.background_crop, app.settings.background_transparency, base)
            self._picture_key = key
        picture = self._picture
        previous_photos = self.photos
        self.photos = {}

        def photo(widget):
            x, y = self.viewport_position(widget)
            tile = Image.new("RGB", (max(1, widget.winfo_width()), max(1, widget.winfo_height())), base)
            # paste clips automatically and fills offscreen portions with the theme color.
            tile.paste(picture, (-x, -y))
            result = previous_photos.get(widget)
            if result is not None and (result.width(), result.height()) == tile.size:
                result.paste(tile)
            else:
                result = ImageTk.PhotoImage(tile, master=app)
            self.photos[widget] = result
            return result

        for label in (self.root_label, self.body_label):
            label.configure(image=photo(label), bg=base)
        for frame in self.frames:
            canvas = frame._canvas
            if canvas.find_withtag("wallpaper"):
                canvas.itemconfigure("wallpaper", image=photo(canvas))
            else:
                canvas.create_image(0, 0, anchor="nw", image=photo(canvas), tags="wallpaper")
            canvas.tag_lower("wallpaper")
            # Transparent layout containers reveal the wallpaper; cards stay readable.
            canvas.itemconfigure("inner_parts", state="hidden" if frame.cget("fg_color") == "transparent" else "normal")
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
