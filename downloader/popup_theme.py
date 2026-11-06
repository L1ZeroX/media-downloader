"""Small, cached wallpaper palette shared by selection and editing popovers."""
from PIL import ImageStat

from .background import render, transparency
from .motion import mix
from .palette import BACKGROUND, CARD, HOVER, TEXT, BLUE


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
