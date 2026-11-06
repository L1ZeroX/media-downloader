from __future__ import annotations

import base64
import io
import os
from pathlib import Path
import queue
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import Image, ImageTk
import customtkinter as ctk

from .core import (AUDIO_QUALITIES, VIDEO_QUALITIES, Settings, cleanup_workspace,
                   duration_text, resolve_tools, size_text, validate_url, youtube_mixed_url)
from .processes import WorkerProcess
from .app_icon import set_app_identity, set_window_icon
from .version import VERSION


class Application(ctk.CTk):
    def __init__(self):
        set_app_identity()
        super().__init__()
        set_window_icon(self)
        self.title(f"Media Downloader {VERSION} — yt-dlp")
        width = min(1200, self.winfo_screenwidth() - 80)
        height = min(940, self.winfo_screenheight() - 100)
        self.compact_layout = height < 900
        left = max(0, (self.winfo_screenwidth() - width) // 2)
        top = max(0, (self.winfo_screenheight() - height - 40) // 2)
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.minsize(min(1080, width), min(860, height))
        self.configure(fg_color="#f3f4f6")
        self.settings = Settings.load()
        self.events = queue.Queue()
        self.worker = None
        self.mode = ""
        self.items = {}
        self.pending = []
        self.current = None
        self.workspace = None
        self.closing = False
        self.completed = self.failed = self.total = 0
        self.source_errors = 0
        self.discovery_finished = False
        self.photo = None
        self.indeterminate = False
        self.destination = tk.StringVar(value=self.settings.destination)
        self.media_format = tk.StringVar(value=self.settings.media_format)
        self.quality = tk.StringVar(value=self.settings.video_quality if self.settings.media_format == "MP4" else self.settings.audio_quality)
        self.frame_rate = tk.StringVar(value=self.settings.frame_rate)
        self.encoding_mode = tk.StringVar(value=self.settings.encoding_mode)
        self.dark_mode = tk.BooleanVar(value=self.settings.appearance == "ダーク")
        self.animations_enabled = tk.BooleanVar(value=self.settings.animations == "オン")
        self.status = tk.StringVar(value="URLを貼り付けて「情報を取得」を押してください。")
        self.progress_text = tk.StringVar(value="待機中")
        self.overall_text = tk.StringVar(value="選択 0 / 0 件")
        self._build()
        self._refresh_tools()
        self.protocol("WM_DELETE_WINDOW", self.close)
        if self.animations_enabled.get():
            from .motion import animate
            self.attributes("-alpha", 0)
            self.after(20, lambda: animate(self, "startup", .22, lambda t: self.attributes("-alpha", t)))
        self.after(80, self._poll)

    def _build(self):
        from .ui import build
        build(self)

    def log(self, message):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", str(message) + "\n")
        if int(self.log_box.index("end-1c").split(".")[0]) > 250:
            self.log_box.delete("1.0", "50.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def remember_settings(self):
        if self.settings.media_format == "MP4":
            if self.quality.get() in VIDEO_QUALITIES:
                self.settings.video_quality = self.quality.get()
        elif self.quality.get() in AUDIO_QUALITIES:
            self.settings.audio_quality = self.quality.get()
        self.settings.destination = self.destination.get().strip()
        self.settings.frame_rate = self.frame_rate.get()
        self.settings.encoding_mode = self.encoding_mode.get()
        self.settings.appearance = "ダーク" if self.dark_mode.get() else "ライト"
        self.settings.animations = "オン" if self.animations_enabled.get() else "オフ"
        self.settings.media_format = self.media_format.get()
        try:
            self.settings.save()
        except OSError as error:
            self.log(f"設定を保存できませんでした: {error}")

    def format_changed(self, _=None):
        new_format = self.media_format.get()
        self.remember_settings()
        choices = VIDEO_QUALITIES if new_format == "MP4" else AUDIO_QUALITIES
        self.quality_combo.configure(values=choices)
        self.quality.set(self.settings.video_quality if new_format == "MP4" else self.settings.audio_quality)
        self.fps_combo.configure(state="readonly" if new_format == "MP4" else "disabled")
        self.encoding_combo.configure(state="readonly" if new_format == "MP4" else "disabled")

    def _refresh_tools(self):
        tools = resolve_tools(self.settings)
        missing = [name for name, path in tools.items() if not path]
        self.tools_text.configure(text="環境: 準備OK" if not missing else "不足: " + ", ".join(missing))
        if missing:
            self.status.set("必要なツールが不足しています。「環境設定」または setup.bat で準備してください。")
        return tools

    def environment(self):
        from .ui import environment
        environment(self)

    def theme_changed(self):
        from .ui import apply_theme
        apply_theme(self, transition=True)
        self.remember_settings()

    def choose_destination(self):
        path = filedialog.askdirectory(initialdir=self.destination.get() if Path(self.destination.get()).is_dir() else str(Path.home()))
        if path:
            self.destination.set(path)
            self.remember_settings()

    def open_destination(self):
        path = Path(self.destination.get()).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
            os.startfile(path)
        except OSError as error:
            messagebox.showerror("保存先", str(error), parent=self)

    def _busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.fetch_button, self.start_button, self.retry_button, self.browse_button, self.tools_button,
                       self.select_all, self.select_none, self.remove_button, self.destination_entry):
            widget.configure(state=state)
        self.format_combo.configure(state="disabled" if busy else "readonly")
        self.quality_combo.configure(state="disabled" if busy else "readonly")
        self.fps_combo.configure(state="readonly" if not busy and self.media_format.get() == "MP4" else "disabled")
        self.encoding_combo.configure(state="readonly" if not busy and self.media_format.get() == "MP4" else "disabled")
        self.stop_button.configure(state="normal" if busy else "disabled")

    def _row(self, key):
        item = self.items[key]
        values = ("☑" if item["selected"] else "☐", item["title"], item["site"], duration_text(item.get("duration")), item["state"])
        tag = "failed" if item["state"] == "失敗" else "done" if item["state"] == "完了" else ""
        if self.tree.exists(key):
            self.tree.item(key, values=values, tags=(tag,))
        else:
            self.tree.insert("", "end", iid=key, values=values, tags=(tag,))
        self._counts()

    def _counts(self):
        if self.mode == "download":
            self.overall_text.set(f"全体 {self.completed + self.failed} / {self.total} 件処理済み  ·  完了 {self.completed}  /  失敗 {self.failed}")
        else:
            self.overall_text.set(f"選択 {sum(item['selected'] for item in self.items.values())} / {len(self.items)} 件")

    def _click_check(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell" or self.tree.identify_column(event.x) != "#1":
            return
        key = self.tree.identify_row(event.y)
        self._toggle(key)

    def _space_check(self, _):
        selection = self.tree.selection()
        if selection:
            self._toggle(selection[0])
        return "break"

    def _toggle(self, key):
        if key in self.items and self.mode != "download":
            self.items[key]["selected"] = not self.items[key]["selected"]
            self._row(key)

    def select_items(self, selected):
        for key, item in self.items.items():
            item["selected"] = selected
            self._row(key)

    def remove_item(self):
        for key in self.tree.selection():
            del self.items[key]
            self.tree.delete(key)
        self._counts()
        self.preview()

    def preview(self):
        self._preview_generation = getattr(self, "_preview_generation", 0) + 1
        generation = self._preview_generation
        selection = self.tree.selection()
        self.photo = None
        if not selection or selection[0] not in self.items:
            self.preview_image.configure(image="", text="動画を選択すると\nサムネイルを表示します", width=32, height=7)
            self.preview_title.configure(text="動画が選択されていません")
            self.preview_time.configure(text="")
            self.preview_error.configure(text="")
            return
        item = self.items[selection[0]]
        self.preview_title.configure(text=item["title"][:240])
        fps_text = f"  ·  {item['fps']:g}fps" if isinstance(item.get("fps"), (int, float)) else ""
        self.preview_time.configure(text=f"{item['site']}  ·  {duration_text(item.get('duration'))}" + fps_text)
        self.preview_error.configure(text=item.get("error", "")[:180])
        try:
            if not item.get("image"):
                raise ValueError()
            picture = Image.open(io.BytesIO(base64.b64decode(item["image"])))
            picture.thumbnail((260, 147))
            picture = picture.convert("RGB")
            background = Image.new("RGB", picture.size, "#262a33" if self.dark_mode.get() else "#f0f3f8")
            from .motion import animate
            def show(amount):
                if generation != self._preview_generation:
                    return
                self.photo = ImageTk.PhotoImage(Image.blend(background, picture, amount))
                self.preview_image.configure(image=self.photo, text="", width=260, height=147)
            animate(self, "thumbnail", .18, show)
        except Exception:
            self.preview_image.configure(image="", text="サムネイルを取得中…" if item["state"] == "情報取得中" else "サムネイルを取得できません", width=32, height=7)

    def fetch(self):
        if self.worker:
            return
        lines = list(dict.fromkeys(line.strip() for line in self.url_input.get("1.0", "end").splitlines() if line.strip()))
        if not lines:
            messagebox.showinfo("URL入力", "動画またはプレイリストのURLを入力してください。", parent=self)
            return
        requests = []
        try:
            for line in lines:
                validate_url(line)
                scope = "playlist"
                if youtube_mixed_url(line):
                    answer = messagebox.askyesnocancel("取得する範囲", "このURLには動画とプレイリストの両方が含まれています。\n\nはい：プレイリスト全体\nいいえ：この動画だけ\nキャンセル：追加を中止\n\n" + line, parent=self)
                    if answer is None:
                        return
                    scope = "playlist" if answer else "video"
                requests.append({"url": line, "scope": scope})
        except ValueError as error:
            messagebox.showerror("URL入力", str(error), parent=self)
            return
        self.source_errors = 0
        self.discovery_finished = False
        self.mode = "discover"
        self._busy(True)
        self.status.set("一覧を取得しています。停止すると取得済みの項目を残します。")
        self._progress({"phase": "情報を取得中", "percent": None})
        try:
            self.worker = WorkerProcess({"action": "discover", "urls": requests, "tools": self._refresh_tools(), "known_keys": list(self.items)}, self.events)
        except Exception as error:
            self.mode = ""
            self._busy(False)
            self._reset_progress("開始できませんでした")
            self.status.set(str(error))

    def start(self, retry=False):
        if self.worker:
            return
        keys = [key for key, item in self.items.items() if item["selected"] and (item["state"] == "失敗" if retry else item["state"] != "完了")]
        if not keys:
            messagebox.showinfo("保存する動画", "対象の動画にチェックを入れてください。完了済みの動画は除外されます。", parent=self)
            return
        tools = self._refresh_tools()
        if not all(tools.values()):
            self.environment()
            return
        try:
            if not self.destination.get().strip():
                raise ValueError("保存先を指定してください。")
            destination = Path(self.destination.get()).expanduser().resolve()
            destination.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=destination):
                pass
        except (OSError, ValueError) as error:
            messagebox.showerror("保存先に書き込めません", str(error), parent=self)
            return
        self.destination.set(str(destination))
        self.remember_settings()
        fps = int(self.frame_rate.get().removesuffix("fps")) if self.frame_rate.get() != "元のまま" and self.media_format.get() == "MP4" else None
        self.batch = {"destination": str(destination), "format": self.media_format.get(), "quality": self.quality.get(), "fps": fps, "encoding_mode": self.encoding_mode.get(), "tools": tools}
        self.pending = keys
        self.total = len(keys)
        self.completed = self.failed = 0
        self.mode = "download"
        self._busy(True)
        for key in keys:
            self.items[key].update(state="待機中", error="")
            self._row(key)
        self._next()

    def _next(self):
        if not self.pending or self.closing:
            self.mode = ""
            self.current = None
            self._busy(False)
            self._reset_progress(f"完了 {self.completed} 件 / 失敗 {self.failed} 件")
            self.status.set("処理が終了しました。失敗した動画は選択して詳細を確認できます。" if self.failed else "すべての保存が完了しました。")
            return
        self.current = self.pending.pop(0)
        item = self.items[self.current]
        item.update(state="取得中", error="")
        self._row(self.current)
        self.tree.selection_set(self.current)
        self.tree.see(self.current)
        self.status.set(item["title"])
        self._progress({"phase": "開始しています", "percent": None})
        try:
            self.workspace = tempfile.mkdtemp(prefix=".media-download-", dir=self.batch["destination"])
            request_item = {key: value for key, value in item.items() if key != "image"}
            self.worker = WorkerProcess({"action": "download", "item": request_item, "workspace": self.workspace, **self.batch}, self.events)
        except Exception as error:
            self._item_error(self.current, str(error))
            self.failed += 1
            self._cleanup()
            self.after(0, self._next)

    def _cleanup(self):
        if self.workspace:
            try:
                cleanup_workspace(self.workspace, self.batch["destination"])
            except (OSError, ValueError) as error:
                self.log(f"一時ファイルを削除できませんでした: {self.workspace}\n{error}")
            self.workspace = None

    def stop(self):
        self.pending = []
        if self.worker:
            self.status.set("処理を停止しています…")
            self.stop_button.configure(state="disabled")
            self.worker.stop()

    def _item_error(self, key, message):
        if key not in self.items:
            return
        self.items[key].update(state="失敗", error=message)
        self._row(key)
        self.log(f"{self.items[key]['title']}: {message}")
        self.preview()

    def _progress(self, event):
        percent = event.get("percent")
        if percent is None and not self.indeterminate:
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
            self.indeterminate = True
        elif percent is not None:
            if self.indeterminate:
                self.progress.stop()
                self.indeterminate = False
            self.progress.configure(mode="determinate", value=percent)
        phase = event["phase"]
        parts = [phase, f"{percent:.1f}%" if percent is not None else "処理中"]
        if event.get("downloaded") is not None:
            parts += [f"{size_text(event['downloaded'])} / {'約' if event.get('estimated') and event.get('total') else ''}{size_text(event.get('total'))}"]
        if event.get("speed"):
            parts += [size_text(event["speed"]) + "/s"]
        if event.get("conversion_speed"):
            parts += [f"変換速度 {event['conversion_speed']:.1f}x"]
        if event.get("eta") is not None:
            parts += ["残り " + duration_text(event["eta"])]
        self.progress_text.set("  ·  ".join(parts))
        if self.current and self.mode == "download":
            self.items[self.current]["state"] = phase
            self._row(self.current)

    def _reset_progress(self, text):
        self.progress.stop()
        self.indeterminate = False
        self.progress.configure(mode="determinate", value=0)
        self.progress_text.set(text)

    def _handle(self, event):
        kind = event.get("event")
        if kind == "entry":
            item = event["item"]
            if item["key"] not in self.items:
                self.items[item["key"]] = {**item, "selected": True, "state": "情報取得中", "error": ""}
                self._row(item["key"])
                if not self.tree.selection():
                    self.tree.selection_set(item["key"])
        elif kind in ("detail", "download_detail"):
            item = event["item"]
            if item["key"] in self.items:
                self.items[item["key"]].update(item)
                if kind == "detail":
                    self.items[item["key"]].update(state="待機中", error="")
                self._row(item["key"])
                if self.tree.selection() == (item["key"],):
                    self.preview()
        elif kind == "listing_done":
            self.status.set(f"{event['count']} 件を追加しました。動画時間・サムネイルを取得中です。")
        elif kind == "discovery_done":
            self.discovery_finished = True
        elif kind == "source_error":
            self.source_errors += 1
            self.log(f"{event['url']}: {event['message']}")
        elif kind == "item_error":
            self._item_error(event["key"], event["message"])
        elif kind == "log":
            self.log(event["message"])
        elif kind == "progress":
            self._progress(event)
        elif kind == "done":
            self.items[self.current].update(state="完了", path=event["path"])
            self.completed += 1
            self._row(self.current)
            self.log("保存しました: " + event["path"])
        elif kind == "error":
            if self.mode == "download":
                self._item_error(self.current, event["message"])
            else:
                self.source_errors += 1
                self.log(event["message"])
        elif kind == "exit":
            self.worker = None
            self._cleanup()
            if self.mode == "download":
                item = self.items[self.current]
                if item["state"] != "完了":
                    if event["stopped"]:
                        item.update(state="停止", error="")
                        self._row(self.current)
                    else:
                        if item["state"] != "失敗":
                            self._item_error(self.current, event.get("error") or "取得プロセスが予期せず終了しました。")
                        self.failed += 1
                        self._counts()
                if not event["stopped"] and not self.closing:
                    self._next()
                    return
            else:
                for key, item in self.items.items():
                    if item["state"] == "情報取得中":
                        item["state"] = "待機中"
                        self._row(key)
                self.status.set(f"情報取得が終了しました。保存する動画を選択してください。URL取得エラー: {self.source_errors} 件" if self.discovery_finished else "情報取得を停止しました。取得済みの項目は保存できます。")
            self.mode = ""
            self.current = None
            self._busy(False)
            self._reset_progress("停止しました" if event["stopped"] else "準備完了")
            self._counts()
            self.preview()
            if event["stopped"]:
                self.status.set("停止しました。待機中の動画は残っています。「ダウンロード開始」で再開できます。")
            if self.closing:
                self.destroy()

    def _poll(self):
        for _ in range(100):
            try:
                token, event = self.events.get_nowait()
            except queue.Empty:
                break
            if self.worker and token == self.worker.token:
                self._handle(event)
            if self.closing and self.worker is None:
                return
        self.after(80, self._poll)

    def close(self):
        self.remember_settings()
        self.closing = True
        if self.worker:
            self.stop()
        else:
            self.destroy()


def main():
    Application().mainloop()


if __name__ == "__main__":
    main()
