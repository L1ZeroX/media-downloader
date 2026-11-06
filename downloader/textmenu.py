"""Themed editing menu for the URL textbox; clipboard access is user initiated."""
import tkinter as tk
import customtkinter as ctk

from .motion import MotionButton, animate
from .palette import CARD, TEXT, HOVER, BLUE, FONT
from .window_shape import round_popup
from .popup_theme import popup_colors


class TextMenu:
    def __init__(self, textbox):
        self.textbox = textbox
        self.editor = textbox._textbox
        self.root = textbox.winfo_toplevel()
        self.popup = None
        self.outside_binding = None
        textbox.bind("<Button-3>", self.open)
        textbox.bind("<Shift-F10>", self.open_keyboard)
        textbox.bind("<Menu>", self.open_keyboard)
        textbox.bind("<Control-a>", lambda _: self.select_all())
        self.editor.bind("<Destroy>", lambda _: self.close(), add="+")

    def clipboard_text(self):
        try:
            return self.editor.clipboard_get().replace("\r\n", "\n").replace("\r", "\n")
        except tk.TclError:
            return ""

    def select_all(self):
        self.editor.tag_add("sel", "1.0", "end-1c")
        self.editor.mark_set("insert", "end-1c")
        return "break"

    def execute(self, action):
        self.close(restore_focus=True)
        editor = self.editor
        if action == "all":
            return self.select_all()
        selected = editor.tag_ranges("sel")
        if action in ("copy", "cut") and selected:
            editor.clipboard_clear()
            editor.clipboard_append(editor.get(*selected))
        if editor.cget("state") == "disabled":
            return "break"
        if action == "cut" and selected:
            editor.delete(*selected)
        elif action == "paste":
            value = self.clipboard_text()
            if value:
                if selected:
                    editor.mark_set("insert", selected[0])
                    editor.delete(*selected)
                editor.insert("insert", value)
                editor.see("insert")
        return "break"

    def open_keyboard(self, event=None):
        return self.open()

    def open(self, event=None):
        self.close()
        active = getattr(self.root, "_active_selectbox", None)
        if active:
            active.close()
        self.root._active_selectbox = self
        colors = self.menu_colors = popup_colors(self.textbox)
        editor = self.editor
        editor.focus_set()
        if event is not None and not editor.tag_ranges("sel"):
            editor.mark_set("insert", f"@{event.x},{event.y}")
        popup = self.popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.root)
        popup.animations_enabled = self.root.animations_enabled
        popup.configure(bg=colors["surface"])
        popup.attributes("-alpha", 0)
        frame = ctk.CTkFrame(popup, fg_color=colors["surface"], bg_color=colors["surface"], corner_radius=18,
                             border_width=1, border_color=colors["border"])
        frame.pack(fill="both", expand=True)
        selected = bool(editor.tag_ranges("sel"))
        editable = editor.cget("state") != "disabled"
        entries = (("paste", "貼り付け       Ctrl+V", editable and bool(self.clipboard_text())),
                   ("copy", "コピー           Ctrl+C", selected),
                   ("cut", "切り取り       Ctrl+X", editable and selected),
                   ("all", "すべて選択   Ctrl+A", bool(editor.get("1.0", "end-1c"))))
        self.buttons = []
        self.actions = []
        for index, (action, title, available) in enumerate(entries):
            item = MotionButton(frame, text=title, anchor="w", width=220, height=38,
                                corner_radius=12, border_spacing=14, font=(FONT, 13),
                                fg_color=colors["surface"], hover_color=colors["hover"], text_color=colors["text"],
                                text_color_disabled=colors["disabled"],
                                state="normal" if available else "disabled",
                                command=lambda a=action: self.execute(a))
            item.pack(fill="x", padx=8, pady=(8 if index == 0 else 2, 8 if index == 3 else 0))
            if available:
                self.buttons.append(item)
                self.actions.append(action)
        self.focus_index = -1
        popup.update_idletasks()
        width, height = frame.winfo_reqwidth(), frame.winfo_reqheight()
        if event is not None:
            x, y = event.x_root, event.y_root
        else:
            caret = editor.bbox("insert") or (8, 8, 0, 20)
            x, y = editor.winfo_rootx() + caret[0], editor.winfo_rooty() + caret[1] + caret[3]
        x = max(0, min(x, editor.winfo_screenwidth() - width - 12))
        y = max(0, min(y, editor.winfo_screenheight() - height - 48))
        popup.geometry(f"{width}x{height}+{x}+{y}")
        popup.update_idletasks()
        round_popup(popup, width, height, 18 * self.textbox._get_widget_scaling())
        popup.deiconify()
        popup.lift()
        popup.focus_force()
        animate(popup, "reveal", .16, lambda t: popup.attributes("-alpha", t))
        popup.bind("<Escape>", lambda _: self.close(True))
        popup.bind("<Tab>", lambda _: self.close(True))
        popup.bind("<Up>", lambda _: self.move(-1))
        popup.bind("<Down>", lambda _: self.move(1))
        popup.bind("<Return>", lambda _: self.execute(self.actions[max(0, self.focus_index)]) if self.actions else None)
        popup.bind("<FocusOut>", lambda _: popup.after(40, self.check_focus) if self.popup is popup else None)
        self.outside_binding = self.root.bind("<ButtonPress-1>", lambda _: self.close(), add="+")
        return "break"

    def move(self, step):
        if self.buttons:
            self.focus_index = (self.focus_index + step) % len(self.buttons)
            for index, button in enumerate(self.buttons):
                button.configure(border_width=1 if index == self.focus_index else 0, border_color=self.menu_colors["accent"])
        return "break"

    def check_focus(self):
        if self.popup is not None:
            focus = self.popup.focus_get()
            if focus is None or focus.winfo_toplevel() is not self.popup:
                self.close()

    def close(self, restore_focus=False):
        if self.outside_binding:
            self.root.unbind("<ButtonPress-1>", self.outside_binding)
            self.outside_binding = None
        if self.popup is not None:
            popup, self.popup = self.popup, None
            commands = set(popup._tclCommands or [])
            for timer in popup.tk.splitlist(popup.tk.call("after", "info")):
                if popup.tk.call("after", "info", timer)[0] in commands:
                    popup.tk.call("after", "cancel", timer)
            popup.destroy()
        if getattr(self.root, "_active_selectbox", None) is self:
            self.root._active_selectbox = None
        if restore_focus:
            self.editor.focus_set()
