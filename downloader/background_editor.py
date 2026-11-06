"""Modal crop editor with a live opacity preview and transactional apply/cancel."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from .app_icon import set_window_icon
from .background import load_image, parse_crop, render, store_image, transparency
from .core import CONFIG_DIR
from .palette import BACKGROUND, CARD, TEXT, MUTED, BLUE, FONT
from .ui import button, label, color


class BackgroundEditor(ctk.CTkToplevel):
    def __init__(self, app, parent):
        super().__init__(parent)
        self.app, self.parent = app, parent
        self.animations_enabled = app.animations_enabled
        self.title("背景画像・トリミング")
        set_window_icon(self)
        width, height = min(960, self.winfo_screenwidth() - 80), min(720, self.winfo_screenheight() - 100)
        self.geometry(f"{width}x{height}")
        self.minsize(min(760, width), min(570, height))
        self.configure(fg_color=BACKGROUND)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.source = app.wallpaper.source.copy() if app.wallpaper.source is not None else None
        self.crop = list(parse_crop(app.settings.background_crop))
        self.fade = tk.IntVar(value=transparency(app.settings.background_transparency))
        self.status = tk.StringVar(value="四隅の丸をドラッグして範囲を変更。枠の内側をドラッグして移動できます。")
        self.results = queue.Queue()
        self.load_id = 0
        self.loading = False
        self.closed = False
        self.timer = None
        self.drag = None
        self.new_selection = False
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        label(self, "背景をカスタマイズ", size=24, bold=True).grid(row=0, column=0, sticky="w", padx=24, pady=(18, 8))
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))
        button(toolbar, "画像を選ぶ", self.choose, primary=True, width=120).pack(side="left")
        button(toolbar, "範囲を選び直す", self.select_new, width=130).pack(side="left", padx=8)
        button(toolbar, "画像全体に戻す", self.reset_crop, width=130).pack(side="left")
        button(toolbar, "背景を解除", self.clear, width=110).pack(side="right")

        panels = ctk.CTkFrame(self, fg_color="transparent")
        panels.grid(row=2, column=0, sticky="nsew", padx=24)
        panels.columnconfigure(0, weight=3)
        panels.columnconfigure(1, weight=2)
        panels.rowconfigure(1, weight=1)
        label(panels, "トリミング", size=14, bold=True).grid(row=0, column=0, sticky="w", pady=(0, 8))
        label(panels, "仕上がりプレビュー", size=14, bold=True).grid(row=0, column=1, sticky="w", padx=(16, 0), pady=(0, 8))
        self.canvas = tk.Canvas(panels, width=420, height=260, highlightthickness=0, bg=color(CARD, app), cursor="crosshair")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.preview = tk.Canvas(panels, width=260, height=260, highlightthickness=0, bg=color(CARD, app))
        self.preview.grid(row=1, column=1, sticky="nsew", padx=(16, 0))
        self.canvas.bind("<ButtonPress-1>", self.begin)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<ButtonRelease-1>", self.end)
        self.canvas.bind("<Configure>", self.schedule)
        self.preview.bind("<Configure>", self.schedule)
        label(self, textvariable=self.status, size=12, color=MUTED, wraplength=width - 60, justify="left").grid(row=3, column=0, sticky="w", padx=24, pady=10)

        settings = ctk.CTkFrame(self, fg_color=CARD, corner_radius=20)
        settings.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 14))
        settings.columnconfigure(1, weight=1)
        label(settings, "背景画像の透明度", size=13, bold=True).grid(row=0, column=0, padx=16, pady=14)
        self.slider = ctk.CTkSlider(settings, from_=0, to=100, number_of_steps=100, variable=self.fade, command=self.fade_changed, progress_color=BLUE)
        self.slider.grid(row=0, column=1, sticky="ew", padx=8, pady=14)
        self.fade_label = label(settings, f"{self.fade.get()}%", size=13, width=54)
        self.fade_label.grid(row=0, column=2, padx=16)
        label(settings, "0%＝画像を濃く表示 ／ 100%＝画像を非表示。操作パネルと文字は透過しません。", size=12,
              color=MUTED, wraplength=width - 100).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 12))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 20))
        label(actions, "PNG / JPEG / WebP / BMP", size=12, color=MUTED).pack(side="left")
        self.apply_button = button(actions, "適用", self.apply, primary=True, width=100)
        self.apply_button.pack(side="right")
        button(actions, "キャンセル", self.cancel, width=110).pack(side="right", padx=8)
        self.after(80, self.poll)
        self.schedule()

    def choose(self):
        path = filedialog.askopenfilename(parent=self, title="背景画像を選択", filetypes=[
            ("画像", "*.png *.jpg *.jpeg *.webp *.bmp"), ("すべてのファイル", "*.*")])
        if not path:
            return
        self.load_id += 1
        request = self.load_id
        self.loading = True
        self.apply_button.configure(state="disabled")
        self.status.set("画像を読み込み中…")
        results = self.results
        def read():
            try:
                results.put((request, load_image(path), None))
            except Exception as error:
                results.put((request, None, str(error)))
        threading.Thread(target=read, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        while not self.results.empty():
            request, image, error = self.results.get_nowait()
            if request != self.load_id:
                continue
            self.loading = False
            self.apply_button.configure(state="normal")
            if error:
                self.status.set("読み込めませんでした。別の画像を選んでください。")
                messagebox.showerror("画像を読み込めません", error, parent=self)
            else:
                self.source = image
                self.reset_crop()
        self.after(80, self.poll)

    def clear(self):
        self.load_id += 1
        self.loading = False
        self.apply_button.configure(state="normal")
        self.source = None
        self.crop = [0., 0., 1., 1.]
        self.status.set("「適用」で標準背景に戻します。")
        self.schedule()

    def select_new(self):
        self.new_selection = True
        self.status.set("画像上をドラッグして新しい範囲を指定してください。")

    def reset_crop(self):
        self.crop = [0., 0., 1., 1.]
        self.new_selection = False
        self.status.set("四隅をドラッグして範囲を変更。枠内をドラッグして移動。端の切り取りは右のプレビューで確認できます。")
        self.schedule()

    def fade_changed(self, value):
        self.fade.set(round(value))
        self.fade_label.configure(text=f"{self.fade.get()}%")
        self.schedule()

    def schedule(self, event=None):
        if not self.closed and self.timer is None:
            self.timer = self.after(20, self.draw)

    def draw(self):
        self.timer = None
        if self.closed:
            return
        canvas = self.canvas
        canvas.delete("all")
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if self.source is None:
            canvas.create_text(width / 2, height / 2, text="「画像を選ぶ」から背景画像を追加", fill=color(MUTED, self.app), font=(FONT, 12))
        else:
            scale = min(max(1, width - 24) / self.source.width, max(1, height - 24) / self.source.height)
            iw, ih = max(1, round(self.source.width * scale)), max(1, round(self.source.height * scale))
            ox, oy = (width - iw) / 2, (height - ih) / 2
            self.image_rect = (ox, oy, iw, ih)
            image = self.source.resize((iw, ih), Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(image, master=self)
            canvas.create_image(ox, oy, anchor="nw", image=self.photo)
            l, t, r, b = self.crop
            x1, y1, x2, y2 = ox + l * iw, oy + t * ih, ox + r * iw, oy + b * ih
            for rect in ((ox, oy, ox + iw, y1), (ox, y2, ox + iw, oy + ih), (ox, y1, x1, y2), (x2, y1, ox + iw, y2)):
                canvas.create_rectangle(*rect, fill="#090b10", stipple="gray50", outline="")
            canvas.create_rectangle(x1, y1, x2, y2, outline="#4388ff", width=2)
            for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill="#4388ff", outline="white")
        pw, ph = max(1, self.preview.winfo_width()), max(1, self.preview.winfo_height())
        aspect = max(1, self.app.winfo_width()) / max(1, self.app.winfo_height())
        w, h = max(1, min(pw - 12, int((ph - 12) * aspect))), max(1, min(ph - 12, int((pw - 12) / aspect)))
        image = render(self.source, (w, h), ",".join(map(str, self.crop)), self.fade.get(), color(BACKGROUND, self.app))
        # Show opaque panel silhouettes so preview reflects the actual wallpaper visibility.
        draw = ImageDraw.Draw(image)
        for top, bottom in ((.16, .35), (.38, .71), (.74, .96)):
            draw.rounded_rectangle((w * .025, h * top, w * .975, h * bottom), radius=max(2, int(w * .02)), fill=color(CARD, self.app))
        self.preview_photo = ImageTk.PhotoImage(image, master=self)
        self.preview.delete("all")
        self.preview.create_image(pw / 2, ph / 2, image=self.preview_photo)

    def point(self, event):
        x, y, w, h = self.image_rect
        return max(0., min(1., (event.x - x) / w)), max(0., min(1., (event.y - y) / h))

    def begin(self, event):
        if self.source is None or not hasattr(self, "image_rect"):
            return
        x, y = self.point(event)
        l, t, r, b = self.crop
        _, _, w, h = self.image_rect
        mode = "new"
        if not self.new_selection:
            for name, cx, cy in (("lt", l, t), ("rt", r, t), ("lb", l, b), ("rb", r, b)):
                if abs(x - cx) * w < 14 and abs(y - cy) * h < 14:
                    mode = name
                    break
            else:
                if l <= x <= r and t <= y <= b:
                    mode = "move"
        self.drag = (mode, x, y, self.crop[:])
        self.new_selection = False

    def move(self, event):
        if self.drag is None:
            return
        mode, x0, y0, old = self.drag
        x, y = self.point(event)
        l, t, r, b = old
        min_w, min_h = min(.01, 1 / self.source.width), min(.01, 1 / self.source.height)
        if mode == "move":
            dx, dy = max(-l, min(1 - r, x - x0)), max(-t, min(1 - b, y - y0))
            self.crop = [l + dx, t + dy, r + dx, b + dy]
        elif mode == "new":
            if abs(x - x0) >= min_w and abs(y - y0) >= min_h:
                self.crop = [min(x, x0), min(y, y0), max(x, x0), max(y, y0)]
        else:
            if "l" in mode:
                l = min(x, r - min_w)
            if "r" in mode:
                r = max(x, l + min_w)
            if "t" in mode:
                t = min(y, b - min_h)
            if "b" in mode:
                b = max(y, t + min_h)
            self.crop = [l, t, r, b]
        self.schedule()

    def end(self, event):
        self.move(event)
        self.drag = None

    def apply(self):
        if self.loading:
            return
        settings = self.app.settings
        old = settings.background_image, settings.background_crop, settings.background_transparency
        try:
            settings.background_image = store_image(self.source, CONFIG_DIR) if self.source is not None else ""
            settings.background_crop = ",".join(f"{v:.8f}" for v in self.crop)
            settings.background_transparency = str(self.fade.get())
            settings.save()
        except (OSError, ValueError) as error:
            settings.background_image, settings.background_crop, settings.background_transparency = old
            messagebox.showerror("背景を保存できません", str(error), parent=self)
            return
        self.app.wallpaper.set_image(self.source)
        self.cancel()

    def cancel(self):
        self.destroy()
        if self.parent.winfo_exists():
            self.parent.grab_set()
            self.parent.focus_set()

    def destroy(self):
        self.closed = True
        # Cancel widget-owned callbacks before destroying the Tcl commands.
        commands = set(self._tclCommands or [])
        for timer in self.tk.splitlist(self.tk.call("after", "info")):
            if self.tk.call("after", "info", timer)[0] in commands:
                self.tk.call("after", "cancel", timer)
        # Drain pending canvas redraws before Tk destroys their image resources.
        for canvas in (getattr(self, "canvas", None), getattr(self, "preview", None)):
            if canvas is not None and canvas.winfo_exists():
                canvas.delete("all")
        self.update_idletasks()
        super().destroy()
