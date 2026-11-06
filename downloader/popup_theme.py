"""Small, cached wallpaper palette shared by selection and editing popovers."""
import colorsys

from PIL import ImageStat

from .background import render, transparency
from .motion import mix
from .palette import BACKGROUND, CARD, HOVER, TEXT, BLUE


def luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


def action_colors(app):
    """Find an image accent, including in dark images, with readable white text."""
    index = 1 if app.dark_mode.get() else 0
    painter = getattr(app, "wallpaper", None)
    if (painter is None or painter.source is None
            or transparency(app.settings.background_transparency) == 100):
        return BLUE[index], ("#0757db", "#649dff")[index], "#ffffff"
    key = (id(painter.source), app.settings.background_crop, index)
    if getattr(painter, "_action_colors_key", None) == key:
        return painter._action_colors
    sample = render(painter.source, (48, 48), app.settings.background_crop, 0, BACKGROUND[index]).quantize(colors=8)
    palette = sample.getpalette()
    candidates = []
    for count, color_index in sample.getcolors():
        rgb = palette[color_index * 3:color_index * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        # Avoid choosing black margins over the actual colored subject.
        candidates.append((count * (.15 + s) * (.05 + v) ** 2, h, s, v))
    _, hue, saturation, _ = max(candidates)
    saturation = min(.72, max(.28, saturation)) if saturation > .08 else 0
    rgb = colorsys.hsv_to_rgb(hue, saturation, .70 if index else .58)
    color = "#" + "".join(f"{round(v * 255):02x}" for v in rgb)
    # Both normal and hover states retain at least 4.5:1 against white text.
    while luminance(color) > .18:
        color = mix(color, "#000000", .06)
    hover = mix(color, "#ffffff", .08)
    if luminance(hover) > .18:
        hover = mix(color, "#000000", .12)
    result = color, hover, "#ffffff"
    painter._action_colors_key, painter._action_colors = key, result
    return result


def popup_colors(widget):
    app = widget
    while app is not None and not hasattr(app, "settings"):
        app = getattr(app, "master", None)
    dark = app.dark_mode.get() if app is not None else True
    index = 1 if dark else 0
    colors = dict(surface=CARD[index], hover=HOVER[index], text=TEXT[index], accent=BLUE[index],
                  selected=("#e8f0ff", "#2b4269")[index], border=("#dde3ed", "#404959")[index],
                  disabled=("#8b919b", "#858d9c")[index])
    painter = getattr(app, "wallpaper", None)
    if (app is None or app.settings.popup_background_colors != "オン" or painter is None
            or painter.source is None or transparency(app.settings.background_transparency) == 100):
        return colors
    settings = app.settings
    key = (id(painter.source), settings.background_crop, settings.background_transparency, dark)
    if getattr(painter, "_popup_colors_key", None) == key:
        return dict(painter._popup_colors)
    # Sample only when the image/crop/theme changes, never during scroll or animation.
    sample = render(painter.source, (48, 48), settings.background_crop,
                    settings.background_transparency, BACKGROUND[index])
    tone = "#" + "".join(f"{round(v):02x}" for v in ImageStat.Stat(sample).mean)
    surface = mix(CARD[index], tone, .35 if dark else .22)
    colors.update(surface=surface, hover=mix(surface, tone, .28), selected=mix(surface, tone, .46),
                  accent=mix(tone, "#ffffff" if dark else "#101318", .68),
                  border=mix(surface, "#ffffff" if dark else "#101318", .18),
                  disabled=mix(surface, TEXT[index], .48))
    painter._popup_colors_key, painter._popup_colors = key, colors
    return dict(colors)
