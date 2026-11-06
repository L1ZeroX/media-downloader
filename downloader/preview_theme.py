"""Thumbnail-derived color for the preview heading and title badges."""
import colorsys

from .motion import mix
from .palette import BUTTON, TEXT
from .popup_theme import luminance


def thumbnail_colors(image, dark):
    sample = image.convert("RGB").resize((48, 48)).quantize(colors=12)
    palette = sample.getpalette()
    candidates = []
    for count, index in sample.getcolors():
        rgb = palette[index * 3:index * 3 + 3]
        hue, saturation, value = colorsys.rgb_to_hsv(*(part / 255 for part in rgb))
        # Prefer the colored subject to black letterboxing.
        candidates.append((count * (.15 + saturation) * (.05 + value) ** 2, hue, saturation))
    _, hue, saturation = max(candidates)
    saturation = min(.55, max(.18, saturation)) if saturation > .08 else 0
    rgb = colorsys.hsv_to_rgb(hue, saturation, .72 if dark else .62)
    background = "#" + "".join(f"{round(part * 255):02x}" for part in rgb)
    while luminance(background) > .18:
        background = mix(background, "#000000", .04)
    return background, "#ffffff"


def apply_preview_colors(app, image=None, image_key=None):
    dark = app.dark_mode.get()
    key = (image_key if image is not None else None, dark)
    if getattr(app, "_preview_color_key", object()) == key:
        return
    colors = thumbnail_colors(image, dark) if image is not None else (BUTTON[int(dark)], TEXT[int(dark)])
    app._preview_color_key = key
    app._preview_colors = colors
    for widget in (app.preview_heading, app.preview_title):
        widget.configure(fg_color=colors[0], text_color=colors[1])
