"""Short, cancellable UI transitions; no background rendering loops."""
import time
import tkinter as tk
import customtkinter as ctk


def enabled(widget):
    variable = getattr(widget.winfo_toplevel(), "animations_enabled", None)
    return variable.get() if variable is not None else True


def mix(start, end, amount):
    channels = [round(int(start[i:i + 2], 16) * (1 - amount) + int(end[i:i + 2], 16) * amount) for i in (1, 3, 5)]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def animate(widget, name, duration, update, complete=None):
    jobs = getattr(widget, "_motion_jobs", {})
    widget._motion_jobs = jobs
    previous = jobs.pop(name, None)
    if previous:
        try:
            widget.after_cancel(previous)
        except tk.TclError:
            pass
    if not enabled(widget):
        update(1.0)
        if complete:
            complete()
        return
    started = time.monotonic()

    def step():
        try:
            if not widget.winfo_exists():
                return
            fraction = min(1.0, (time.monotonic() - started) / duration)
            eased = 1 - (1 - fraction) ** 3
            update(eased)
            if fraction < 1:
                jobs[name] = widget.after(16, step)
            else:
                jobs.pop(name, None)
                if complete:
                    complete()
        except tk.TclError:
            jobs.pop(name, None)
    step()


class MotionButton(ctk.CTkButton):
    def destroy(self):
        try:
            commands = set(self._tclCommands or [])
            for timer in self.tk.splitlist(self.tk.call("after", "info")):
                if self.tk.call("after", "info", timer)[0] in commands:
                    self.tk.call("after", "cancel", timer)
        except tk.TclError:
            pass
        super().destroy()

    def _paint(self, color):
        self._visual_color = color
        self._canvas.itemconfig("inner_parts", outline=color, fill=color)
        if self._text_label is not None:
            self._text_label.configure(bg=color)
        if self._image_label is not None:
            self._image_label.configure(bg=color)

    def _transition(self, target):
        start = getattr(self, "_visual_color", self._apply_appearance_mode(self._fg_color))
        animate(self, "hover", .14, lambda t: self._paint(mix(start, target, t)))

    def _on_enter(self, event=None):
        super()._on_enter(event)
        if self._state == "normal":
            self._transition(self._apply_appearance_mode(self._hover_color or self._fg_color))

    def _on_leave(self, event=None):
        super()._on_leave(event)
        self._transition(self._apply_appearance_mode(self._fg_color))
