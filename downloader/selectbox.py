"""Custom rounded selection popover, replacing the native Tk menu."""
import tkinter as tk
import customtkinter as ctk

from .motion import MotionButton, animate
from .palette import BLUE, CARD, CONTROL, FONT, HOVER, TEXT
from .window_shape import round_popup


class SelectBox(MotionButton):
    def __init__(self, master, variable, values, command, width=140):
        self.variable = variable
        self.values = list(values)
        self.selection_command = command
        self.selection_state = "readonly"
        self.popup = None
        self.outside_binding = None
        self.option_buttons = []
        # CTkButton only creates its label and expanding canvas grid for nonempty text.
        super().__init__(master, textvariable=variable, text=variable.get() or " ", command=self.open, width=width, height=38,
                         anchor="w", corner_radius=12, border_spacing=8, fg_color=CONTROL, hover_color=HOVER,
                         text_color=TEXT, text_color_disabled=("#a5acb8", "#666f80"), font=(FONT, 13))
        self.arrow = ctk.CTkLabel(self, text="⌄", width=24, height=20, fg_color="transparent", text_color=TEXT,
                                 font=(FONT, 18, "bold"))
        self.arrow.place(relx=1, x=-12, rely=.5, anchor="e")
        self.arrow.bind("<ButtonRelease-1>", lambda _: self.open())
        self.bind("<space>", lambda _: self.open())
        self.bind("<Return>", lambda _: self.open())
        self.bind("<Down>", lambda _: self.open())
        self._canvas.configure(takefocus=True)

    def configure(self, **kwargs):
        values = kwargs.pop("values", None)
        if values is not None:
            self.values = list(values)
            self.close()
        if "state" in kwargs:
            self.selection_state = kwargs["state"]
            kwargs["state"] = "disabled" if self.selection_state == "disabled" else "normal"
            if self.selection_state == "disabled":
                self.close()
        super().configure(**kwargs)
        if hasattr(self, "arrow"):
            self.arrow.configure(text_color=("#a5acb8", "#666f80") if self.selection_state == "disabled" else TEXT)

    def _paint(self, color):
        super()._paint(color)
        if hasattr(self, "arrow"):
            self.arrow.configure(fg_color=color)

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        if hasattr(self, "arrow"):
            self.arrow.configure(fg_color="transparent")

    def cget(self, attribute_name):
        if attribute_name == "state":
            return self.selection_state
        if attribute_name == "values":
            return self.values
        return super().cget(attribute_name)

    def get(self):
        return self.variable.get()

    def set(self, value):
        self.variable.set(value)

    def open(self):
        if self.selection_state == "disabled":
            return
        if self.popup is not None:
            self.close()
            return
        root = self.winfo_toplevel()
        active = getattr(root, "_active_selectbox", None)
        if active is not None and active is not self:
            active.close()
        root._active_selectbox = self
        popup = self.popup = tk.Toplevel(root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(root)
        popup.animations_enabled = root.animations_enabled
        popup.configure(bg=self._apply_appearance_mode(CARD))
        popup.attributes("-alpha", 0)
        frame = ctk.CTkFrame(popup, fg_color=CARD, bg_color=CARD, corner_radius=18, border_width=1,
                             border_color=("#dde3ed", "#404959"))
        frame.pack(fill="both", expand=True)
        self.option_buttons = []
        self.focus_index = self.values.index(self.variable.get()) if self.variable.get() in self.values else 0
        for index, value in enumerate(self.values):
            selected = value == self.variable.get()
            item = MotionButton(frame, text=("✓   " if selected else "     ") + value, anchor="w", height=40,
                                corner_radius=12, border_spacing=14, font=(FONT, 14, "bold" if selected else "normal"),
                                fg_color=("#e8f0ff", "#2b4269") if selected else CARD, hover_color=HOVER,
                                text_color=BLUE if selected else TEXT, command=lambda v=value: self.choose(v))
            item.pack(fill="x", padx=8, pady=(8 if index == 0 else 2, 8 if index == len(self.values) - 1 else 0))
            self.option_buttons.append(item)
        self.arrow.configure(text="⌃")
        popup.update_idletasks()
        scaling = self._get_widget_scaling()
        width = max(self.winfo_width(), round(190 * scaling))
        height = frame.winfo_reqheight()
        x = min(self.winfo_rootx(), self.winfo_screenwidth() - width - 12)
        bottom = self.winfo_rooty() + self.winfo_height() + 7
        above = bottom + height > self.winfo_screenheight() - 48
        top = self.winfo_rooty() - height - 7 if above else bottom
        popup.geometry(f"{width}x{height}+{x}+{top}")
        popup.update_idletasks()
        round_popup(popup, width, height, 18 * scaling)
        popup.deiconify()
        popup.lift()
        popup.focus_force()

        def reveal(amount):
            # Keep the menu's layout stable; fade and slide the whole shaped window.
            offset = round(6 * scaling * (1 - amount))
            y = top + offset if above else top - offset
            popup.geometry(f"{width}x{height}+{x}+{y}")
            popup.attributes("-alpha", amount)
        animate(popup, "reveal", .18, reveal)
        popup.bind("<Escape>", lambda _: self.close(restore_focus=True))
        popup.bind("<Up>", lambda _: self.move(-1))
        popup.bind("<Down>", lambda _: self.move(1))
        popup.bind("<Return>", lambda _: self.choose(self.values[self.focus_index]))
        popup.bind("<space>", lambda _: self.choose(self.values[self.focus_index]))
        popup.bind("<Tab>", lambda _: self.close(restore_focus=True))
        popup.bind("<FocusOut>", lambda _: popup.after(40, self._check_focus) if self.popup is popup else None)
        self.outside_binding = root.bind("<ButtonPress-1>", lambda _: self.close(), add="+")

    def move(self, step):
        self.focus_index = (self.focus_index + step) % len(self.values)
        for index, button in enumerate(self.option_buttons):
            button.configure(border_width=1 if index == self.focus_index else 0, border_color=BLUE)
        return "break"

    def choose(self, value):
        self.variable.set(value)
        self.close(restore_focus=True)
        if self.selection_command:
            self.selection_command(value)

    def _check_focus(self):
        if self.popup is None:
            return
        try:
            focus = self.popup.focus_get()
            if focus is None or focus.winfo_toplevel() is not self.popup:
                self.close()
        except tk.TclError:
            self.close()

    def close(self, restore_focus=False):
        root = self.winfo_toplevel()
        if self.outside_binding:
            root.unbind("<ButtonPress-1>", self.outside_binding)
            self.outside_binding = None
        if self.popup is not None:
            popup, self.popup = self.popup, None
            # Cancel pending callbacks without deleting widget-owned Tcl commands twice.
            commands = set(popup._tclCommands or [])
            for timer in popup.tk.splitlist(popup.tk.call("after", "info")):
                script = popup.tk.call("after", "info", timer)[0]
                if script in commands:
                    popup.tk.call("after", "cancel", timer)
            popup.destroy()
            self.option_buttons = []
            self.arrow.configure(text="⌄")
        if getattr(root, "_active_selectbox", None) is self:
            root._active_selectbox = None
        if restore_focus:
            self._canvas.focus_set()

    def destroy(self):
        self.close()
        super().destroy()
