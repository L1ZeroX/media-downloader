from __future__ import annotations

import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "SimpleMediaDownloader"
VIDEO_QUALITIES = ("1080p以下", "720p以下", "最高")
AUDIO_QUALITIES = ("192kbps", "320kbps", "128kbps")
FRAME_RATES = ("元のまま", "24fps", "30fps", "60fps")
ENCODING_MODES = ("自動（高速）", "GPU優先", "CPU高速")
URL_INPUT_HEIGHTS = {"コンパクト": 72, "標準": 112, "大きめ": 180}


@dataclass
class Settings:
    destination: str = str(Path.home() / "Downloads")
    media_format: str = "MP4"
    video_quality: str = "1080p以下"
    audio_quality: str = "192kbps"
    frame_rate: str = "元のまま"
    encoding_mode: str = "自動（高速）"
    appearance: str = "ダーク"
    animations: str = "オン"
    url_input_size: str = "標準"
    show_preview: str = "オン"
    show_log: str = "オン"
    background_image: str = ""
    background_crop: str = "0,0,1,1"
    background_transparency: str = "35"
    ffmpeg: str = ""
    deno: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        try:
            raw = json.loads((path or CONFIG_DIR / "settings.json").read_text(encoding="utf-8"))
            result = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__ and isinstance(v, str)})
            if result.media_format not in ("MP4", "MP3"):
                result.media_format = "MP4"
            if result.video_quality not in VIDEO_QUALITIES:
                result.video_quality = VIDEO_QUALITIES[0]
            if result.audio_quality not in AUDIO_QUALITIES:
                result.audio_quality = AUDIO_QUALITIES[0]
            if result.frame_rate not in FRAME_RATES:
                result.frame_rate = FRAME_RATES[0]
            if result.encoding_mode not in ENCODING_MODES:
                result.encoding_mode = ENCODING_MODES[0]
            if result.appearance not in ("ライト", "ダーク"):
                result.appearance = "ダーク"
            if result.animations not in ("オン", "オフ"):
                result.animations = "オン"
            if result.url_input_size not in URL_INPUT_HEIGHTS:
                result.url_input_size = "標準"
            for key in ("show_preview", "show_log"):
                if getattr(result, key) not in ("オン", "オフ"):
                    setattr(result, key, "オン")
            from .background import parse_crop, transparency
            result.background_crop = ",".join(f"{v:g}" for v in parse_crop(result.background_crop))
            result.background_transparency = str(transparency(result.background_transparency))
            return result
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or CONFIG_DIR / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)


def duration_text(seconds: float | None) -> str:
    if seconds is None or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        return "時間不明"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def size_text(value: float | None) -> str:
    if value is None:
        return "不明"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return "不明"


def validate_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("http:// または https:// から始まる動画URLを入力してください。")
    return value


def youtube_mixed_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if not (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")):
        return False
    query = parse_qs(parsed.query)
    return "list" in query and ("v" in query or host == "youtu.be" or parsed.path.startswith(("/shorts/", "/live/")))


def entry_from_info(info: dict, fallback: str = "") -> dict:
    extractor = str(info.get("extractor_key") or info.get("ie_key") or info.get("extractor") or "generic")
    video_id = str(info.get("id") or "")
    url = info.get("webpage_url") or info.get("original_url") or info.get("url") or fallback
    if extractor.lower().startswith("youtube") and video_id and info.get("_type") not in ("playlist", "multi_video"):
        extractor = "Youtube"
        url = f"https://www.youtube.com/watch?v={video_id}"
    # Only extractor identity + id, never a signed media URL, is used for deduplication.
    key = f"{extractor.lower()}:{video_id}" if video_id else str(url)
    if extractor.lower() == "generic":
        key = f"generic:{url}#{video_id}"
    return {
        "key": key, "url": str(url), "id": video_id, "title": info.get("title") or video_id or str(url),
        "site": extractor, "duration": info.get("duration"), "fps": info.get("fps"),
        "thumbnail": info.get("thumbnail") or next((x.get("url") for x in reversed(info.get("thumbnails") or []) if x.get("url")), None),
        "live": bool(info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming")),
    }


def find_tool(name: str, configured: str = "") -> str | None:
    extension = ".exe" if os.name == "nt" else ""
    if configured:
        path = Path(configured.strip().strip('"')).expanduser()
        if path.is_dir():
            path /= name + extension
        return str(path.resolve()) if path.is_file() else None
    bundled = ROOT / "tools" / (name + extension)
    return str(bundled) if bundled.is_file() else shutil.which(name)


def resolve_tools(settings: Settings) -> dict:
    ffmpeg = find_tool("ffmpeg", settings.ffmpeg)
    ffprobe = find_tool("ffprobe", str(Path(ffmpeg).parent)) if ffmpeg else None
    return {"ffmpeg": ffmpeg, "ffprobe": ffprobe, "deno": find_tool("deno", settings.deno)}


def format_selector(media_format: str, quality: str) -> str:
    if media_format == "MP3":
        return "bestaudio/best"
    limit = {"1080p以下": 1080, "720p以下": 720}.get(quality)
    # Generic/direct URLs may omit height; probe and enforce the limit after download.
    restriction = f"[height<=?{limit}]" if limit else ""
    return f"bestvideo{restriction}+bestaudio/best{restriction}/bestvideo{restriction}"


def output_stem(title: str, video_id: str, site: str = "") -> str:
    def clean(value: str, limit: int) -> str:
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:limit].rstrip(" .")
        return value or "video"
    # Limits are conservative for legacy Windows path length constraints.
    return f"{clean(title, 75)} [{clean(site, 18)}-{clean(video_id, 32)}]"


def publish_file(source: Path, destination: Path, stem: str, extension: str) -> Path:
    """Publish a completed file without overwriting another file, even in a race."""
    index = 0
    while True:
        suffix = f" ({index})" if index else ""
        target = destination / f"{stem}{suffix}.{extension}"
        try:
            if os.name == "nt":
                # Windows rename is atomic and fails if the target already exists.
                source.rename(target)
            else:
                os.link(source, target)
                source.unlink()
            return target
        except FileExistsError:
            index += 1


def cleanup_workspace(path: str, destination: str) -> None:
    original = Path(path)
    candidate, parent = original.resolve(), Path(destination).resolve()
    if candidate.parent != parent or not candidate.name.startswith(".media-download-") or original.is_symlink() or original.is_junction():
        raise ValueError("作業フォルダーの範囲外です。")
    if candidate.exists():
        shutil.rmtree(candidate)
