"""Rounded, spacious desktop layout inspired by One UI."""
import tkinter as tk
from tkinter import ttk, filedialog
import webbrowser

import customtkinter as ctk

from .core import VIDEO_QUALITIES, AUDIO_QUALITIES, FRAME_RATES, ENCODING_MODES, URL_INPUT_HEIGHTS
from .motion import MotionButton, animate
from .palette import BACKGROUND, CARD, TEXT, MUTED, INPUT, CONTROL, BUTTON, HOVER, THUMB, BLUE, FONT
from .selectbox import SelectBox
from .textmenu import TextMenu
from .app_icon import set_window_icon
from .background import Wallpaper, WallpaperFrame, WallpaperLabel, WallpaperSwitch
from .version import APP_NAME


def color(value, app):
    return value[1 if app.dark_mode.get() else 0] if isinstance(value, tuple) else value


def button(parent, text, command, *, primary=False, width=100, height=36):
    return MotionButton(parent, text=text, command=command, width=width, height=height,
                         corner_radius=height // 2, font=(FONT, 13, "bold"),
                         fg_color=BLUE if primary else BUTTON, hover_color=("#0757db", "#649dff") if primary else HOVER,
                         text_color="white" if primary else ("#3b4659", "#dbe4f7"), text_color_disabled=("#a5acb8", "#666f80"))


def label(parent, text="", size=14, bold=False, color=TEXT, **kwargs):
    return WallpaperLabel(parent, text=text, font=(FONT, size, "bold" if bold else "normal"),
                        text_color=color, anchor="w", **kwargs)


def combo(parent, variable, values, command, width=140):
    return SelectBox(parent, variable, values, command, width)


class Progress(ctk.CTkProgressBar):
    def configure(self, **kwargs):
        value = kwargs.pop("value", None)
        super().configure(**kwargs)
        if value is not None:
            start = self.get()
            if value == 0:
                animate(self, "value", .001, lambda _: self.set(0))
            else:
                animate(self, "value", .16, lambda t: self.set(start + (value / 100 - start) * t))

    def start(self, interval=None):
        super().start()


def build(app):
    ctk.set_appearance_mode("dark" if app.dark_mode.get() else "light")
    app.configure(fg_color=BACKGROUND)
    style = ttk.Style(app)
    style.theme_use("clam")
    style.configure("Treeview", font=(FONT, 10), rowheight=43, background=color(CARD, app), fieldbackground=color(CARD, app),
                    foreground=color(TEXT, app), borderwidth=0, relief="flat")
    style.configure("Treeview.Heading", font=(FONT, 9), background=color(CARD, app), foreground=color(MUTED, app), borderwidth=0, padding=(6, 8))
    style.map("Treeview", background=[("selected", "#edf3ff")], foreground=[("selected", "#1556be")])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    outer = ctk.CTkScrollableFrame(app, fg_color="transparent", corner_radius=0)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(2, weight=1, minsize=280)

    scale = outer._get_widget_scaling()
    header = tk.Canvas(outer, height=round(96 * scale), highlightthickness=0, bd=0, bg=color(BACKGROUND, app))
    header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
    header.create_text(0, 5 * scale, text=APP_NAME, anchor="nw", font=(FONT, -round(11 * scale), "bold"), tags="caption")
    header.create_text(0, 24 * scale, text="ダウンロード", anchor="nw", font=(FONT, -round(34 * scale), "bold"), tags="heading")
    header.create_text(0, 76 * scale, text="お気に入りの動画と音声を、ひとつの場所に。", anchor="nw", font=(FONT, -round(13 * scale)), tags="caption")
    headline = WallpaperFrame(header, fg_color=CARD, corner_radius=22)
    headline.place(relx=1, y=round(22 * scale), anchor="ne")
    app.tools_button = button(headline, "環境設定", app.environment, width=106)
    app.tools_button.pack(side="right", padx=8, pady=8)
    app.theme_switch = WallpaperSwitch(headline, text="ダークモード", variable=app.dark_mode, command=app.theme_changed,
                                    progress_color=BLUE, fg_color=("#ccd3e0", "#454c5a"), button_color="white", button_hover_color="#e8edff",
                                    text_color=MUTED, font=(FONT, 12), switch_width=38, switch_height=22, width=145)
    app.theme_switch.pack(side="right", padx=(16, 8), pady=8)

    input_card = WallpaperFrame(outer, fg_color=CARD, corner_radius=24)
    input_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
    input_card.columnconfigure(0, weight=1)
    label(input_card, "リンクを追加", size=16, bold=True).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 4))
    label(input_card, "1行に1つのURL · プレイリスト対応", size=12, color=MUTED).grid(row=0, column=1, sticky="e", padx=20, pady=(14, 4))
    app.url_input = ctk.CTkTextbox(input_card, height=URL_INPUT_HEIGHTS[app.settings.url_input_size], wrap="none", corner_radius=14, border_width=0,
                                  fg_color=INPUT, text_color=TEXT, font=(FONT, 13), activate_scrollbars=True)
    app.url_input.grid(row=1, column=0, sticky="ew", padx=(16, 12), pady=(2, 16))
    app.fetch_button = button(input_card, "＋  情報を取得", app.fetch, primary=True, width=168, height=48)
    app.fetch_button.grid(row=1, column=1, padx=(0, 20), pady=(2, 16))
    app.url_input.bind("<Control-Return>", lambda _: app.fetch())
    app.url_menu = TextMenu(app.url_input)

    center = WallpaperFrame(outer, fg_color="transparent")
    center.grid(row=2, column=0, sticky="nsew", pady=(0, 16))
    center.columnconfigure(0, weight=1)
    center.rowconfigure(0, weight=1)
    queue_card = WallpaperFrame(center, fg_color=CARD, corner_radius=24)
    app.queue_card = queue_card
    queue_card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
    queue_card.columnconfigure(0, weight=1)
    queue_card.rowconfigure(1, weight=1)
    toolbar = ctk.CTkFrame(queue_card, fg_color="transparent")
    toolbar.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 4))
    label(toolbar, "保存する動画", size=16, bold=True).pack(side="left", padx=(0, 12))
    app.select_all = button(toolbar, "全選択", lambda: app.select_items(True), width=65, height=30)
    app.select_all.pack(side="left", padx=(0, 6))
    app.select_none = button(toolbar, "解除", lambda: app.select_items(False), width=55, height=30)
    app.select_none.pack(side="left")
    app.remove_button = button(toolbar, "行を削除", app.remove_item, width=80, height=30)
    app.remove_button.pack(side="right")
    table = tk.Frame(queue_card, bg=color(CARD, app))
    app.table_frame = table
    table.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
    table.columnconfigure(0, weight=1)
    table.rowconfigure(0, weight=1)
    app.tree = ttk.Treeview(table, columns=("check", "title", "site", "duration", "state"), show="headings", selectmode="browse", height=4)
    for name, title, width in (("check", "保存", 40), ("title", "タイトル", 230), ("site", "サイト", 84), ("duration", "時間", 64), ("state", "状態", 105)):
        app.tree.heading(name, text=title)
        app.tree.column(name, width=width, minwidth=width if name != "title" else 120, stretch=name == "title", anchor="w" if name == "title" else "center")
    app.tree.grid(row=0, column=0, sticky="nsew")
    app.queue_empty = tk.Canvas(table, highlightthickness=0, bd=0, height=0, bg=color(CARD, app))
    app.queue_empty.grid(row=1, column=0, sticky="nsew")
    table.bind("<Configure>", lambda _: fit_queue(app), add="+")
    scrollbar = ctk.CTkScrollbar(table, orientation="vertical", command=app.tree.yview, width=12, fg_color=CARD, button_color=("#d7dce5", "#3b4353"), button_hover_color=("#b9c5d8", "#57667f"))
    scrollbar.grid(row=0, column=1, rowspan=2, sticky="ns")
    app.tree.configure(yscrollcommand=scrollbar.set)
    app.tree.tag_configure("failed", foreground="#d23e4a")
    app.tree.tag_configure("done", foreground="#208d68")
    app.tree.bind("<Button-1>", app._click_check)
    app.tree.bind("<space>", app._space_check)
    app.tree.bind("<<TreeviewSelect>>", lambda _: app.preview())

    card = WallpaperFrame(center, fg_color=CARD, corner_radius=24, width=290)
    app.preview_card = card
    card.grid(row=0, column=1, sticky="nsew")
    label(card, "プレビュー", size=14, bold=True).pack(anchor="w", padx=20, pady=(16, 10))
    thumb = ctk.CTkFrame(card, fg_color=THUMB, corner_radius=18)
    thumb.pack(fill="x", padx=16)
    app.preview_image = tk.Label(thumb, text="動画を選ぶと\nサムネイルを表示します", bg=color(THUMB, app), fg=color(MUTED, app),
                                 width=32, height=7, font=(FONT, 10))
    app.preview_image.pack(padx=8, pady=8)
    app.preview_title = label(card, "動画が選択されていません", size=14, bold=True, wraplength=250, justify="left")
    app.preview_title.pack(anchor="w", padx=20, pady=(12, 2))
    app.preview_time = label(card, "", size=12, color=MUTED)
    app.preview_time.pack(anchor="w", padx=20)
    app.preview_error = label(card, "", size=11, color=("#d23e4a", "#ff8590"), wraplength=250, justify="left")
    app.preview_error.pack(anchor="w", padx=20, pady=(4, 12))

    controls = WallpaperFrame(outer, fg_color=CARD, corner_radius=24)
    controls.grid(row=3, column=0, sticky="ew", pady=(0, 16))
    controls.columnconfigure(1, weight=1)
    label(controls, "保存設定", size=16, bold=True, height=22).grid(row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(12, 8))
    app.tools_text = label(controls, "", size=12, color=MUTED)
    app.tools_text.grid(row=0, column=2, columnspan=2, sticky="e", padx=20, pady=(14, 8))
    label(controls, "保存先", size=13, color=MUTED).grid(row=1, column=0, padx=(20, 12))
    app.destination_entry = ctk.CTkEntry(controls, textvariable=app.destination, height=34, corner_radius=12, border_width=0,
                                       fg_color=INPUT, text_color=TEXT, font=(FONT, 12))
    app.destination_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10))
    app.browse_button = button(controls, "変更", app.choose_destination, width=68, height=34)
    app.browse_button.grid(row=1, column=2)
    button(controls, "フォルダーを開く", app.open_destination, width=130, height=34).grid(row=1, column=3, padx=(8, 20))
    settings_row = ctk.CTkFrame(controls, fg_color="transparent")
    settings_row.grid(row=2, column=0, columnspan=4, sticky="ew", padx=20, pady=(12, 16))
    for index in range(4):
        settings_row.columnconfigure(index, weight=1)
    def setting(index, title, variable, values, command, width):
        container = ctk.CTkFrame(settings_row, fg_color="transparent")
        container.grid(row=0, column=index, sticky="ew", padx=(0, 12 if index < 3 else 0))
        label(container, title, size=12, color=MUTED, height=18).pack(anchor="w", pady=(0, 3))
        widget = combo(container, variable, values, command, width)
        widget.pack(fill="x")
        return widget
    app.format_combo = setting(0, "形式", app.media_format, ("MP4", "MP3"), app.format_changed, 110)
    app.quality_combo = setting(1, "画質 / 音質", app.quality, VIDEO_QUALITIES if app.media_format.get() == "MP4" else AUDIO_QUALITIES,
                                lambda _: app.remember_settings(), 150)
    app.fps_combo = setting(2, "フレームレート", app.frame_rate, FRAME_RATES, lambda _: app.remember_settings(), 150)
    app.encoding_combo = setting(3, "変換方式", app.encoding_mode, ENCODING_MODES, lambda _: app.remember_settings(), 170)
    if app.media_format.get() != "MP4":
        app.fps_combo.configure(state="disabled")
        app.encoding_combo.configure(state="disabled")

    footer = WallpaperFrame(app, fg_color=CARD, corner_radius=24)
    # Reserve the download controls before allocating space to the scrollable body.
    footer.pack(side="bottom", fill="x", padx=26, pady=(0, 20))
    outer.pack(fill="both", expand=True, padx=26, pady=(24, 16))
    footer.columnconfigure(0, weight=1)
    label(footer, textvariable=app.overall_text, size=12, color=MUTED).grid(row=0, column=0, sticky="w", padx=20, pady=(14, 0))
    label(footer, textvariable=app.progress_text, size=13, bold=True).grid(row=1, column=0, sticky="w", padx=20)
    buttons = ctk.CTkFrame(footer, fg_color="transparent")
    buttons.grid(row=0, column=1, rowspan=2, sticky="e", padx=20, pady=(14, 0))
    app.retry_button = button(buttons, "失敗分を再試行", lambda: app.start(retry=True), width=126)
    app.retry_button.pack(side="left", padx=(0, 8))
    app.stop_button = button(buttons, "停止", app.stop, width=72)
    app.stop_button.configure(state="disabled")
    app.stop_button.pack(side="left", padx=(0, 8))
    app.start_button = button(buttons, "ダウンロード", app.start, primary=True, width=158, height=44)
    app.start_button.pack(side="left")
    app.progress = Progress(footer, height=8, corner_radius=4, fg_color=BUTTON, progress_color=BLUE)
    app.progress.set(0)
    app.progress.grid(row=2, column=0, columnspan=2, sticky="ew", padx=20, pady=(10, 6))
    label(footer, textvariable=app.status, size=12, color=MUTED, wraplength=1080, justify="left", height=20).grid(row=3, column=0, columnspan=2, sticky="w", padx=20)
    app.log_box = ctk.CTkTextbox(footer, height=34, wrap="word", corner_radius=12, fg_color=("#f7f8fa", "#22262e"), text_color=MUTED,
                                font=(FONT, 11), state="disabled")
    app.log_box.grid(row=4, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 14))
    apply_theme(app)
    apply_layout(app)
    app.wallpaper = Wallpaper(app, outer, [outer._parent_frame, headline, input_card, center, queue_card, card, controls, footer], header)


def fit_queue(app):
    """Keep native rows/keyboard navigation; reveal glass in the unused list area."""
    glass = (int(app.settings.panel_transparency) > 0 and app.wallpaper.source is not None
             and int(app.settings.background_transparency) < 100) if hasattr(app, "wallpaper") else False
    table = app.table_frame
    if glass:
        # Native headings consume about 36 px; row height is controlled by our style.
        rows = min(len(app.items), max(0, (table.winfo_height() - 36) // 43))
        if int(app.tree.cget("height")) != rows:
            app.tree.configure(height=rows)
        table.rowconfigure(0, weight=0)
        table.rowconfigure(1, weight=1)
    else:
        table.rowconfigure(0, weight=1)
        table.rowconfigure(1, weight=0)
        if int(app.tree.cget("height")) != 4:
            app.tree.configure(height=4)


def apply_layout(app):
    """Resize existing widgets without disturbing input, selection or queue state."""
    app.url_input.configure(height=URL_INPUT_HEIGHTS[app.settings.url_input_size])
    if app.settings.show_preview == "オン":
        app.preview_card.grid()
        app.queue_card.grid_configure(padx=(0, 16))
    else:
        app.preview_card.grid_remove()
        app.queue_card.grid_configure(padx=0)
    if app.settings.show_log == "オン":
        app.log_box.grid()
    else:
        app.log_box.grid_remove()


def apply_theme(app, transition=False):
    ctk.set_appearance_mode("dark" if app.dark_mode.get() else "light")
    style = ttk.Style(app)
    style.configure("Treeview", background=color(CARD, app), fieldbackground=color(CARD, app), foreground=color(TEXT, app))
    app.tree.tag_configure("failed", foreground="#ff8590" if app.dark_mode.get() else "#d23e4a")
    app.tree.tag_configure("done", foreground="#60d5a9" if app.dark_mode.get() else "#208d68")
    app.table_frame.configure(bg=color(CARD, app))
    app.queue_empty.configure(bg=color(CARD, app))
    app.preview_image.configure(bg=color(THUMB, app), fg=color(MUTED, app))
    if transition:
        app.preview()
    apply_action_colors(app)
    if hasattr(app, "wallpaper"):
        app.wallpaper.schedule()


def apply_action_colors(app):
    from .popup_theme import action_colors
    from .queue_theme import apply_queue_colors
    colors = action_colors(app)
    apply_queue_colors(app, colors[0])
    if getattr(app, "_action_colors", None) == colors:
        return
    app._action_colors = colors
    foreground, hover, text = colors
    for widget in (app.fetch_button, app.start_button):
        job = getattr(widget, "_motion_jobs", {}).pop("hover", None)
        if job:
            widget.after_cancel(job)
        widget.configure(fg_color=foreground, hover_color=hover, text_color=text)
        widget._paint(foreground)


def environment(app):
    window = ctk.CTkToplevel(app)
    set_window_icon(window)
    window.title("環境設定")
    window.geometry(f"760x{min(760, app.winfo_screenheight() - 100)}")
    window.minsize(640, 480)
    window.configure(fg_color=BACKGROUND)
    window.animations_enabled = app.animations_enabled
    window.transient(app)
    window.grab_set()
    actions = ctk.CTkFrame(window, fg_color="transparent")
    actions.pack(side="bottom", fill="x", padx=20, pady=(0, 16))
    frame = ctk.CTkScrollableFrame(window, fg_color=CARD, corner_radius=24)
    frame.pack(fill="both", expand=True, padx=20, pady=20)
    frame.columnconfigure(1, weight=1)
    label(frame, "外部ツール", size=22, bold=True).grid(row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(16, 4))
    label(frame, "空欄なら同梱ツールを自動検出します。FFmpegとffprobeは同じフォルダーに置いてください。", size=12,
          color=MUTED, wraplength=670).grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 16))
    variables = {}
    for index, (key, title) in enumerate((("ffmpeg", "FFmpeg"), ("deno", "Deno")), 2):
        variable = tk.StringVar(value=getattr(app.settings, key))
        variables[key] = variable
        label(frame, title, size=13).grid(row=index, column=0, padx=(20, 12), pady=6)
        ctk.CTkEntry(frame, textvariable=variable, height=38, corner_radius=12, border_width=0, fg_color=CONTROL, text_color=TEXT).grid(row=index, column=1, sticky="ew", pady=6)
        def choose(v=variable):
            path = filedialog.askopenfilename(parent=window, filetypes=[("実行ファイル", "*.exe"), ("すべて", "*.*")])
            if path:
                v.set(path)
        button(frame, "参照", choose, width=72).grid(row=index, column=2, padx=(8, 20))
    label(frame, "Python版: setup.batで準備、update.batで更新できます。\nEXE版: 同梱のtoolsフォルダーごと配置してください。", size=12, color=MUTED,
          justify="left").grid(row=4, column=0, columnspan=3, sticky="w", padx=20, pady=(14, 8))
    label(frame, "表示・レイアウト", size=22, bold=True).grid(row=5, column=0, columnspan=3, sticky="w", padx=20, pady=(20, 8))
    label(frame, "URL入力欄の高さ", size=13).grid(row=6, column=0, sticky="w", padx=20, pady=8)
    size = tk.StringVar(value=app.settings.url_input_size)
    combo(frame, size, tuple(URL_INPUT_HEIGHTS), None, width=220).grid(row=6, column=1, sticky="ew", padx=(0, 20), pady=8)
    display_variables = {}
    for row, (key, title) in enumerate((("show_preview", "サムネイルのプレビューを表示"), ("show_log", "詳細ログを表示"), ("animations", "アニメーション")), 7):
        variable = tk.StringVar(value=getattr(app.settings, key))
        display_variables[key] = variable
        ctk.CTkSwitch(frame, text=title, variable=variable, onvalue="オン", offvalue="オフ",
                      text_color=TEXT, progress_color=BLUE, font=(FONT, 13)).grid(row=row, column=0, columnspan=3, sticky="w", padx=20, pady=9)
    label(frame, "保存するとすぐに反映され、次回起動時にも引き継がれます。", size=12,
          color=MUTED).grid(row=10, column=0, columnspan=3, sticky="w", padx=20, pady=(8, 20))
    label(frame, "背景画像", size=22, bold=True).grid(row=11, column=0, columnspan=3, sticky="w", padx=20, pady=(8, 8))
    def edit_background():
        from .background_editor import BackgroundEditor
        BackgroundEditor(app, window)
    button(frame, "画像・トリミング・透過・ぼかし", edit_background, width=300).grid(row=12, column=0, columnspan=3, sticky="w", padx=20, pady=8)
    label(frame, "背景は専用画面の「適用」で保存します。元画像は変更しません。", size=12,
          color=MUTED).grid(row=13, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 20))
    from .version import VERSION
    label(frame, f"アプリの更新 · 現在 {VERSION}", size=22, bold=True).grid(row=14, column=0, columnspan=3, sticky="w", padx=20, pady=8)
    label(frame, "起動時にGitHubの公開版を確認し、新しいバージョンがあると通知します。", size=12,
          color=MUTED).grid(row=15, column=0, columnspan=3, sticky="w", padx=20, pady=8)
    def check_updates():
        window.destroy()
        app.check_updates(manual=True)
    button(frame, "新しいバージョンを確認", check_updates, width=240).grid(row=16, column=0, columnspan=3, sticky="w", padx=20, pady=(8, 20))
    links = ctk.CTkFrame(actions, fg_color="transparent")
    links.pack(side="left")
    button(links, "FFmpeg", lambda: webbrowser.open("https://www.gyan.dev/ffmpeg/builds/"), width=95).pack(side="left")
    button(links, "Deno", lambda: webbrowser.open("https://docs.deno.com/runtime/getting_started/installation/"), width=80).pack(side="left", padx=8)
    def save():
        for key, variable in variables.items():
            setattr(app.settings, key, variable.get().strip())
        app.settings.url_input_size = size.get()
        for key, variable in display_variables.items():
            setattr(app.settings, key, variable.get())
        app.animations_enabled.set(app.settings.animations == "オン")
        apply_layout(app)
        app.remember_settings()
        app._refresh_tools()
        window.destroy()
    button(actions, "保存", save, primary=True, width=96).pack(side="right")
    button(actions, "キャンセル", window.destroy, width=96).pack(side="right", padx=8)
