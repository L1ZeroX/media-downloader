"""Glass-backed heading overlay; native Treeview still handles columns and resizing."""
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from .palette import CARD, FONT, TEXT


class QueueHeading(tk.Canvas):
    def __init__(self, app, tree):
        super().__init__(tree, height=36, bd=0, highlightthickness=0, takefocus=False,
                         bg=CARD[int(app.dark_mode.get())])
        self.app, self.tree = app, tree
        self.hover = self.pressed = None
        self.timer = None
        self.closed = False
        self.key = None
        self.photo = None
        self.place(x=0, y=0, relwidth=1, height=36)
        tree.bind("<Configure>", lambda _: self.schedule(), add="+")
        tree.configure(xscrollcommand=lambda *_: self.schedule())
        self.bind("<Configure>", lambda _: self.schedule())
        self.bind("<Motion>", self.motion)
        self.bind("<Leave>", self.leave)
        for sequence in ("<ButtonPress-1>", "<B1-Motion>", "<ButtonRelease-1>", "<MouseWheel>"):
            self.bind(sequence, lambda event, seq=sequence: self.forward(seq, event))
        self.bind("<Destroy>", self.destroyed)
        self.schedule()

    def schedule(self):
        if not self.closed and self.timer is None:
            self.timer = self.after_idle(self.render)

    def destroyed(self, event):
        if event.widget is self:
            self.closed = True
            if self.timer:
                self.after_cancel(self.timer)
                self.timer = None

    def column_at(self, x):
        value = self.tree.identify_column(x)
        return int(value[1:]) - 1 if value else None

    def motion(self, event):
        resizing = self.tree.identify_region(event.x, event.y) == "separator"
        self.configure(cursor="sb_h_double_arrow" if resizing else "")
        self.hover = None if resizing else self.column_at(event.x)
        self.schedule()

    def leave(self, _):
        self.hover = None
        self.schedule()

    def forward(self, sequence, event):
        if sequence == "<ButtonPress-1>":
            self.pressed = self.column_at(event.x)
        elif sequence == "<ButtonRelease-1>":
            self.pressed = None
        options = dict(x=event.x, y=event.y)
        if sequence == "<MouseWheel>":
            options["delta"] = event.delta
        self.tree.event_generate(sequence, **options)
        self.schedule()
        return "break"

    def render(self):
        self.timer = None
        if self.closed or self.winfo_width() < 2:
            return
        columns = self.tree.cget("columns")
        widths = tuple(self.tree.column(name, "width") for name in columns)
        offset = round(self.tree.xview()[0] * sum(widths))
        width = self.winfo_width()
        colors = getattr(self.app, "_queue_colors", {})
        normal = colors.get("normal", CARD[int(self.app.dark_mode.get())])
        hover = colors.get("hover", normal)
        pressed = colors.get("pressed", hover)
        text = colors.get("text", TEXT[int(self.app.dark_mode.get())])
        key = (width, widths, offset, normal, hover, pressed, text, self.hover, self.pressed)
        if self.key == key:
            return
        self.key = key
        scale = 3
        image = Image.new("RGBA", (width * scale, 36 * scale))
        draw = ImageDraw.Draw(image)
        self.delete("heading_text")
        x = -offset
        for index, (column, span) in enumerate(zip(columns, widths)):
            fill = pressed if index == self.pressed else hover if index == self.hover else normal
            draw.rounded_rectangle(((x+2)*scale, 3*scale, (x+span-3)*scale, 32*scale), radius=11*scale, fill=fill)
            self.create_text(x+span/2, 18, text=self.tree.heading(column, "text"), fill=text,
                             font=(FONT, 9), width=max(20, span-12), tags="heading_text")
            x += span
        image = image.resize((width, 36), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image, master=self.app)
        if self.find_withtag("heading_pills"):
            self.itemconfigure("heading_pills", image=self.photo)
        else:
            self.create_image(0, 0, anchor="nw", image=self.photo, tags="heading_pills")
        self.tag_lower("heading_pills")
        if self.find_withtag("wallpaper"):
            self.tag_lower("wallpaper")
