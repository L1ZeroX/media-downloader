"""Rounded image-backed ttk headings without native white hover backgrounds."""
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk

from .motion import mix
from .palette import CARD, TEXT


def heading_image(color):
    # Nine-slice image: keep the rounded ends while the title column expands.
    scale = 3
    image = Image.new("RGBA", (40 * scale, 36 * scale))
    ImageDraw.Draw(image).rounded_rectangle((2 * scale, 3 * scale, 37 * scale, 32 * scale),
                                           radius=11 * scale, fill=color)
    return image.resize((40, 36), Image.Resampling.LANCZOS)


def apply_queue_colors(app, accent):
    dark = app.dark_mode.get()
    index = 1 if dark else 0
    key = (accent, dark)
    if getattr(app, "_queue_colors_key", None) == key:
        return
    base = CARD[index]
    normal = mix(base, accent, .26 if dark else .12)
    hover = mix(base, accent, .43 if dark else .24)
    pressed = mix(base, accent, .56 if dark else .34)
    pixels = [heading_image(color) for color in (normal, hover, pressed)]
    style = ttk.Style(app)
    if not hasattr(app, "_queue_heading_images"):
        app._queue_heading_images = [ImageTk.PhotoImage(image, master=app) for image in pixels]
        normal_image, hover_image, pressed_image = app._queue_heading_images
        style.element_create("Pandora.Heading.surface", "image", normal_image,
                             ("pressed", pressed_image), ("active", hover_image),
                             border=(14, 16, 14, 16), padding=0, sticky="nswe")
        style.layout("Treeview.Heading", [("Pandora.Heading.surface", {"sticky": "nswe", "children": [
            ("Treeheading.padding", {"sticky": "nswe", "children": [("Treeheading.text", {"sticky": "we"})]})
        ]})])
    else:
        for photo, image in zip(app._queue_heading_images, pixels):
            photo.paste(image)
    style.configure("Treeview.Heading", foreground=TEXT[index])
    style.map("Treeview.Heading", foreground=[("active", TEXT[index]), ("pressed", TEXT[index])])
    style.map("Treeview", background=[("selected", pressed)], foreground=[("selected", TEXT[index])])
    app._queue_colors_key = key
    app._queue_colors = dict(normal=normal, hover=hover, pressed=pressed, text=TEXT[index])
