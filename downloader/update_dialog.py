"""Theme-aware update notices, always created on Tk's UI thread."""
import webbrowser
import customtkinter as ctk

from .app_icon import set_window_icon
from .popup_theme import popup_colors, action_colors
from .version import VERSION


def show_update_dialog(app, update=None, message=""):
    window = ctk.CTkToplevel(app)
    window.withdraw()
    set_window_icon(window)
    colors = popup_colors(app)
    accent, hover, foreground = action_colors(app)
    window.title("アプリの更新")
    window.configure(fg_color=colors["surface"])
    window.geometry("570x440" if update else "570x235")
    window.minsize(480, 350 if update else 220)
    window.transient(app)
    window.columnconfigure(0, weight=1)
    window.rowconfigure(2, weight=1)
    heading = ("ベータ版をダウンロード" if "-beta." in update.version else "新しいバージョンがあります") if update else "バージョンチェック"
    ctk.CTkLabel(window, text=heading, text_color=colors["text"], font=("Yu Gothic UI", 21, "bold")).grid(row=0, column=0, sticky="w", padx=24, pady=(24, 10))
    text = f"現在 {VERSION} → 新しいバージョン {update.version}" if update else message
    ctk.CTkLabel(window, text=text, text_color=colors["text"], wraplength=500, justify="left").grid(row=1, column=0, sticky="w", padx=24, pady=(0, 12))
    if update:
        notes = ctk.CTkTextbox(window, fg_color=colors["hover"], text_color=colors["text"], corner_radius=16, wrap="word")
        notes.grid(row=2, column=0, sticky="nsew", padx=24)
        notes.insert("1.0", update.notes)
        notes.configure(state="disabled")
        ctk.CTkLabel(window, text="ZIPをすべて展開し、アプリを閉じて新しいフォルダーから起動してください。", wraplength=500, justify="left", text_color=colors["text"]).grid(row=3, column=0, sticky="w", padx=24, pady=(10, 0))
    actions = ctk.CTkFrame(window, fg_color="transparent")
    actions.grid(row=4, column=0, sticky="ew", padx=24, pady=20)
    def open_url(url):
        try:
            if not webbrowser.open(url):
                raise OSError("ブラウザーを開けませんでした。")
        except Exception as error:
            app.log(f"更新ページを開けません: {error} / {url}")
    ctk.CTkButton(actions, text="あとで" if update else "閉じる", command=window.destroy, width=90,
                  corner_radius=18, fg_color=colors["hover"], text_color=colors["text"]).pack(side="right")
    if update:
        ctk.CTkButton(actions, text="ZIPをダウンロード", command=lambda: open_url(update.download_url),
                      corner_radius=18, fg_color=accent, hover_color=hover, text_color=foreground).pack(side="right", padx=8)
        ctk.CTkButton(actions, text="更新内容", command=lambda: open_url(update.page_url), width=85,
                      corner_radius=18, fg_color=colors["hover"], text_color=colors["text"]).pack(side="left")
    window.bind("<Escape>", lambda _: window.destroy())
    from .scrollbar_theme import apply_scrollbar_colors
    apply_scrollbar_colors(app, window)
    if app.animations_enabled.get():
        window.attributes("-alpha", 0)
    window.deiconify()
    window.grab_set()
    if app.animations_enabled.get():
        from .motion import animate
        animate(window, "startup", .18, lambda t: window.attributes("-alpha", t))
    return window
