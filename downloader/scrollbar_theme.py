"""Apply cached wallpaper accents to main-window and dialog scrollbars."""
import customtkinter as ctk
from .motion import mix
from .palette import CARD
from .popup_theme import action_colors


def apply_scrollbar_colors(app, root=None):
    accent = action_colors(app)[0]
    base = CARD[int(app.dark_mode.get())]
    colors = (mix(base, accent, .65), mix(base, accent, .9))
    def visit(widget):
        if isinstance(widget, ctk.CTkScrollbar) and getattr(widget, "_pandora_colors", None) != colors:
            widget.configure(button_color=colors[0], button_hover_color=colors[1], fg_color="transparent")
            widget._pandora_colors = colors
        for child in widget.winfo_children():
            visit(child)
    visit(root or app)
