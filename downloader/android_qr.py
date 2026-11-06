"""Public Android download link and locally rendered, icon-colored QR code."""
import json
import queue
import ssl
import threading
import webbrowser
from urllib.request import Request, urlopen

import certifi
import customtkinter as ctk
import qrcode
from PIL import Image, ImageDraw, ImageOps
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer

from .app_icon import icon_path, set_window_icon
from .popup_theme import action_colors, popup_colors, luminance
from .updates import version_number

RELEASES_URL = "https://github.com/L1ZeroX/youtube-pandora-android/releases"
API_URL = "https://api.github.com/repos/L1ZeroX/youtube-pandora-android/releases?per_page=30"


def latest_apk(releases):
    candidates = []
    for release in releases if isinstance(releases, list) else []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name", "")
        number = version_number(tag)
        if number is None:
            continue
        name = f"YoutubePandora-Android-{tag}.apk"
        url = f"{RELEASES_URL}/download/{tag}/{name}"
        assets = release.get("assets")
        if isinstance(assets, list) and any(isinstance(a, dict) and a.get("name") == name
                and a.get("state") == "uploaded" and a.get("browser_download_url") == url for a in assets):
            candidates.append((number, tag, url))
    if not candidates:
        raise ValueError("公開APKが見つかりませんでした。")
    _, tag, url = max(candidates)
    return tag, url


def fetch_apk():
    request = Request(API_URL, headers={"Accept": "application/vnd.github+json",
        "User-Agent": "YoutubePandora-Android-QR", "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=10, context=ssl.create_default_context(cafile=certifi.where())) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise ValueError("リリース情報が大きすぎます。")
    return latest_apk(json.loads(body))


def icon_colors(icon):
    # Ignore transparent padding and pick two dominant, distinct icon colors.
    small = icon.convert("RGBA").resize((64, 64))
    pixels = [small.getpixel((x,y))[:3] for y in range(64) for x in range(64) if small.getpixel((x,y))[3] > 220]
    strip = Image.new("RGB", (max(1, len(pixels)), 1), "#1769ab")
    if pixels:
        strip.putdata(pixels)
    sample = strip.quantize(colors=6)
    palette = sample.getpalette()
    colors = [tuple(palette[i*3:i*3+3]) for _, i in sorted(sample.getcolors(), reverse=True)]
    first = colors[0]
    second = next((c for c in colors[1:] if sum(abs(a-b) for a,b in zip(c,first)) > 60), first)
    def darken(rgb):
        while luminance("#" + "".join(f"{v:02x}" for v in rgb)) > .16:
            rgb = tuple(round(v * .94) for v in rgb)
        return rgb
    return darken(first), darken(second)


def make_qr(url, icon=None):
    if icon is None:
        with Image.open(icon_path()) as source:
            icon = source.convert("RGBA")
    else:
        icon = icon.convert("RGBA")
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=8, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    mono = qr.make_image(image_factory=StyledPilImage,
                         module_drawer=RoundedModuleDrawer(radius_ratio=.65)).get_image().convert("L")
    draw = ImageDraw.Draw(mono)
    # Smooth continuous finder rings instead of individually rounded squares.
    for x, y in ((4,4), (4+qr.modules_count-7,4), (4,4+qr.modules_count-7)):
        draw.rectangle((x*8,y*8,(x+7)*8-1,(y+7)*8-1),fill=255)
        for inset, fill, radius in ((0,0,10),(1,255,6),(2,0,4)):
            draw.rounded_rectangle(((x+inset)*8,(y+inset)*8,(x+7-inset)*8-1,(y+7-inset)*8-1),radius=radius,fill=fill)
    a, b = icon_colors(icon)
    b = tuple(round(v * .8) for v in b)
    size = mono.width
    ramp = Image.new("RGB", (size, 1))
    ramp.putdata([tuple(round(c+(d-c)*x/(size-1)) for c,d in zip(a,b)) for x in range(size)])
    gradient = ramp.resize((size,size))
    result = Image.composite(gradient, Image.new("RGB",mono.size,"white"), ImageOps.invert(mono))
    # Small opaque white backing; retain the original icon and full quiet zone.
    side = (int(qr.modules_count * .15) // 2 * 2 + 1) * 8
    offset = (size-side)//2
    ImageDraw.Draw(result).rounded_rectangle((offset,offset,offset+side-1,offset+side-1),radius=10,fill="white")
    logo = ImageOps.contain(icon,(side-12,side-12),Image.Resampling.LANCZOS)
    result.paste(logo,((size-logo.width)//2,(size-logo.height)//2),logo)
    return result


def show_android_qr(app):
    existing = getattr(app, "android_qr_window", None)
    if existing is not None and existing.winfo_exists():
        existing.lift()
        return existing
    window = ctk.CTkToplevel(app)
    app.android_qr_window = window
    window.withdraw()
    set_window_icon(window)
    colors = popup_colors(app)
    accent, hover, foreground = action_colors(app)
    window.title("Android版をダウンロード")
    window.geometry("450x560")
    window.resizable(False, False)
    window.transient(app)
    window.configure(fg_color=colors["surface"])
    ctk.CTkLabel(window,text="スマホで読み取ってダウンロード",font=("Yu Gothic UI",19,"bold"),
                text_color=colors["text"]).pack(pady=(20,4))
    status = ctk.CTkLabel(window,text="最新のAPKを確認しています…",text_color=colors["text"],wraplength=410)
    status.pack()
    picture = ctk.CTkLabel(window,text="QRコードを準備中…",width=360,height=360,text_color=colors["text"])
    picture.pack(pady=10)
    hint = ctk.CTkLabel(window,text="AndroidのカメラでQRコードを読み取ってください。",text_color=colors["text"],wraplength=410)
    hint.pack()
    actions = ctk.CTkFrame(window,fg_color="transparent")
    actions.pack(pady=14)
    target = {"url": RELEASES_URL}
    def open_link():
        try:
            if not webbrowser.open(target["url"]):
                raise OSError("ブラウザーを開けませんでした。")
        except Exception as error:
            app.log(f"Android版のページを開けません: {error}")
    link = ctk.CTkButton(actions,text="PCでリンクを開く",command=open_link,state="disabled",
        fg_color=accent,hover_color=hover,text_color=foreground,corner_radius=18)
    link.pack(side="left",padx=5)
    ctk.CTkButton(actions,text="閉じる",command=window.destroy,width=85,corner_radius=18,
        fg_color=colors["hover"],text_color=colors["text"]).pack(side="left",padx=5)
    results = queue.Queue()
    def work():
        try:
            try:
                tag, url = fetch_apk()
                caption = f"Android版 {tag} · APKを直接ダウンロード"
            except Exception:
                url, caption = RELEASES_URL, "最新情報を取得できないため、配布ページを表示します。"
            results.put((url, caption, make_qr(url), None))
        except Exception as error:
            results.put((RELEASES_URL,"QRコードを作成できませんでした。",None,str(error)))
    def poll():
        window.qr_timer = None
        try:
            url, caption, image, error = results.get_nowait()
        except queue.Empty:
            window.qr_timer = window.after(80,poll)
            return
        target["url"] = url
        status.configure(text=caption)
        link.configure(state="normal")
        if image is not None:
            window.qr_image = ctk.CTkImage(light_image=image,dark_image=image,size=(360,360))
            picture.configure(image=window.qr_image,text="")
        else:
            picture.configure(text="下のボタンから配布ページを開けます。")
            app.log("QRコード生成エラー: " + error)
    threading.Thread(target=work,daemon=True).start()
    window.qr_timer = window.after(80,poll)
    def cleanup(event):
        if event.widget is window and window.qr_timer is not None:
            window.after_cancel(window.qr_timer)
            window.qr_timer = None
    window.bind("<Destroy>",cleanup)
    window.bind("<Escape>",lambda _: window.destroy())
    window.deiconify()
    return window
