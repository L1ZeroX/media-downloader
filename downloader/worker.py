from __future__ import annotations

import base64
from fractions import Fraction
import io
import json
import os
import ssl
import shutil
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen

from PIL import Image, ImageOps
import certifi
import yt_dlp

from .core import entry_from_info, format_selector, output_stem, publish_file, validate_url


def emit(event: str, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def user_error(error: Exception | str) -> str:
    message = str(error).removeprefix("ERROR: ").strip()
    low = message.lower()
    if any(word in low for word in ("sign in", "login", "log in", "cookies", "private video", "members-only")):
        return "ログインや視聴権限の確認が必要です。初版はログイン不要の公開動画に対応しています。\n" + message
    if "unsupported url" in low:
        return "このURLはyt-dlpで取得できません。動画ページのURLを確認してください。\n" + message
    if "requested format is not available" in low:
        return "指定した画質で取得できる動画がありません。「最高」をお試しください。\n" + message
    return message[:4000]


class Logger:
    def debug(self, message):
        pass

    def warning(self, message):
        emit("log", message=message)

    def error(self, message):
        emit("log", message=message)


def options(tools: dict) -> dict:
    result = {
        "quiet": True, "no_warnings": False, "logger": Logger(),
        "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
        "extractor_retries": 2, "cachedir": False, "noplaylist": True,
        "windowsfilenames": True, "js_runtimes": {},
    }
    if tools.get("ffmpeg"):
        result["ffmpeg_location"] = str(Path(tools["ffmpeg"]).parent)
    if tools.get("deno"):
        result["js_runtimes"] = {"deno": {"path": tools["deno"]}}
    return result


def thumbnail_data(url: str | None, headers: dict | None = None) -> str | None:
    if not url:
        return None
    try:
        validate_url(url)
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0", **(headers or {})}), timeout=12,
                     context=ssl.create_default_context(cafile=certifi.where())) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            return None
        with Image.open(io.BytesIO(raw)) as picture:
            picture = ImageOps.exif_transpose(picture)
            picture.thumbnail((480, 270))
            output = io.BytesIO()
            picture.convert("RGB").save(output, format="JPEG", quality=85)
        return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception:
        return None


def discover(payload: dict):
    pending = []
    seen = set(payload.get("known_keys", []))

    def add(info: dict, fallback: str, container: str | None = None, index: int | None = None):
        if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
            parent = info.get("webpage_url") or fallback
            for position, child in enumerate(info.get("entries") or [], 1):
                if child:
                    add(child, parent, parent, position)
            return
        row = entry_from_info(info, fallback)
        if container and row["url"] == container:
            row.update(container_url=container, container_index=info.get("playlist_index") or index)
        if row["key"] in seen:
            return
        seen.add(row["key"])
        pending.append((row, info))
        emit("entry", item=row)

    for request in payload["urls"]:
        try:
            opts = options(payload["tools"])
            opts.update({"extract_flat": "in_playlist", "lazy_playlist": True,
                         "noplaylist": request["scope"] == "video", "ignoreerrors": True})
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(request["url"], download=False)
                if not info:
                    raise ValueError("動画情報を取得できませんでした。非公開・削除済み・認証要求などの可能性があります。")
                add(info, request["url"])
        except Exception as error:
            emit("source_error", url=request["url"], message=user_error(error))
    emit("listing_done", count=len(pending))
    for row, initial_info in pending:
        try:
            info = initial_info
            if not info.get("formats") and info.get("_type") != "video":
                opts = options(payload["tools"])
                apply_container_options(opts, row)
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = extract_item(ydl, row)
            if not info or info.get("entries") is not None:
                raise ValueError("単一動画の情報を取得できませんでした。")
            detail = {**row, **entry_from_info(info, row["url"])}
            # Keep the original row key so updates always reach the right row.
            detail["key"] = row["key"]
            if detail["live"]:
                raise ValueError("配信中・配信予定のライブは対象外です。公開済みアーカイブのURLをご利用ください。")
            detail["image"] = thumbnail_data(detail["thumbnail"], info.get("http_headers"))
            emit("detail", item=detail)
        except Exception as error:
            emit("item_error", key=row["key"], message=user_error(error))
    emit("discovery_done")


def apply_container_options(opts: dict, row: dict):
    if row.get("container_url"):
        opts.update(noplaylist=False, playlist_items=str(row["container_index"]))


def extract_item(ydl, row: dict) -> dict | None:
    info = ydl.extract_info(row.get("container_url") or row["url"], download=False)
    if not row.get("container_url") or not info:
        return info

    def find(current):
        if "entries" in current:
            for child in current.get("entries") or []:
                if child:
                    result = find(child)
                    if result:
                        return result
            return None
        return current if str(current.get("id")) == row["id"] else None

    return find(info)


def probe(path: Path, ffprobe: str) -> dict:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise RuntimeError("メディア情報の確認に失敗しました。\n" + result.stderr[-2000:])
    return json.loads(result.stdout)


def stream_fps(stream: dict) -> float | None:
    for field in ("avg_frame_rate", "r_frame_rate"):
        try:
            value = float(Fraction(stream.get(field) or "0/1"))
            if value > 0:
                return value
        except (ValueError, ZeroDivisionError):
            pass
    return None


def encoder_args(encoder: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", "20", "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-preset", "veryfast", "-global_quality", "20"]
    if encoder == "h264_amf":
        return ["-c:v", encoder, "-quality", "speed", "-rc", "cqp", "-qp_i", "20", "-qp_p", "22"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def conversion_args(source: Path, target: Path, metadata: dict, media_format: str, quality: str,
                    fps: int | None = None, encoder: str = "libx264") -> list[str]:
    streams = metadata.get("streams", [])
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    video = next((s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")), None)
    args = ["-hide_banner", "-nostdin", "-n", "-i", str(source)]
    if media_format == "MP3":
        if not audio:
            raise ValueError("この動画には音声トラックがありません。")
        args += ["-map", f"0:{audio['index']}", "-vn", "-c:a", "libmp3lame", "-b:a", quality.replace("kbps", "k"), "-id3v2_version", "3"]
    else:
        if not video:
            raise ValueError("このURLには映像トラックがありません。音声のみの場合はMP3を選択してください。")
        args += ["-map", f"0:{video['index']}"]
        if audio:
            args += ["-map", f"0:{audio['index']}"]
        cap = {"1080p以下": 1080, "720p以下": 720}.get(quality)
        resize = cap is not None and video.get("height", 0) > cap
        change_fps = fps is not None and (stream_fps(video) is None or abs(stream_fps(video) - fps) > .001)
        compatible_video = video.get("codec_name") == "h264" and video.get("pix_fmt") in ("yuv420p", "yuvj420p") and not resize and not change_fps
        if compatible_video:
            args += ["-c:v", "copy"]
        else:
            args += encoder_args(encoder) + ["-pix_fmt", "yuv420p"]
            filters = [f"scale=-2:{cap}"] if resize else []
            if change_fps:
                filters.append(f"fps={fps}")
            filters.append("pad=ceil(iw/2)*2:ceil(ih/2)*2")
            args += ["-vf", ",".join(filters)]
        if audio:
            args += ["-c:a", "copy"] if audio.get("codec_name") == "aac" else ["-c:a", "aac", "-b:a", "192k"]
        args += ["-movflags", "+faststart"]
    return args + ["-progress", "pipe:1", "-nostats", str(target)]


def choose_encoder(ffmpeg: str, video: dict, quality: str, fps: int | None, mode: str = "自動（高速）") -> str:
    if mode == "CPU高速":
        return "libx264"
    width, height = int(video.get("width") or 640), int(video.get("height") or 360)
    cap = {"1080p以下": 1080, "720p以下": 720}.get(quality)
    if cap and height > cap:
        width, height = round(width * cap / height / 2) * 2, cap
    width, height = (width + 1) // 2 * 2, (height + 1) // 2 * 2
    rate = fps or stream_fps(video) or 30
    if mode == "自動（高速）" and width * height < 1280 * 720:
        return "libx264"  # For small frames, GPU setup/transfer often costs more than encoding.
    candidates = ["h264_nvenc", "h264_qsv", "h264_amf"]
    monitor = shutil.which("nvidia-smi")
    if mode == "自動（高速）" and monitor:
        try:
            usage = subprocess.run([monitor, "--query-gpu=utilization.encoder", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=2,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            loads = [int(line.strip()) for line in usage.stdout.splitlines() if line.strip().isdigit()]
            if loads and loads[0] >= 60:
                candidates.remove("h264_nvenc")
                emit("log", message="NVIDIAの動画エンコーダーが混雑しているため、別の変換方式を使用します。")
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Probe an actual encode, not just a compiled-in encoder name. Drivers/devices may be absent.
    for encoder in candidates:
        try:
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"color=size={width}x{height}:rate={rate}",
                 "-frames:v", "1", *encoder_args(encoder), "-pix_fmt", "yuv420p", "-f", "null", "-"],
                capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if result.returncode == 0:
                return encoder
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "libx264"


def run_conversion(command: list[str], source: Path, duration: float, phase: str):
    emit("progress", phase=phase, percent=None, downloaded=None, total=None, speed=None, eta=None)
    with (source.parent / "ffmpeg.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        values = {}
        for line in process.stdout:
            key, _, value = line.strip().partition("=")
            values[key] = value
            if key == "progress":
                try:
                    current = int(values.get("out_time_us", "0")) / 1_000_000
                    speed = float(values.get("speed", "0").strip().removesuffix("x"))
                except ValueError:
                    current, speed = 0, 0
                emit("progress", phase=phase, percent=min(99.9, max(0, current / duration * 100)) if duration else None,
                     downloaded=None, total=None, speed=None, conversion_speed=speed,
                     eta=max(0, duration - current) / speed if duration and speed > 0 else None)
        process.stdout.close()
        if process.wait():
            log.seek(0)
            raise RuntimeError("変換に失敗しました。\n" + log.read()[-3000:])


def convert(source: Path, target: Path, tools: dict, media_format: str, quality: str, fps: int | None = None,
            encoding_mode: str = "自動（高速）"):
    metadata = probe(source, tools["ffprobe"])
    duration = float(metadata.get("format", {}).get("duration") or 0)
    args = conversion_args(source, target, metadata, media_format, quality, fps)
    encoder = "libx264"
    phase = "音声変換中" if media_format == "MP3" else "高速保存"
    needs_encode = "-c:v" in args and args[args.index("-c:v") + 1] != "copy"
    if needs_encode:
        emit("progress", phase="GPUを確認中", percent=None)
        video = next(s for s in metadata["streams"] if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"))
        encoder = choose_encoder(tools["ffmpeg"], video, quality, fps, encoding_mode)
        args = conversion_args(source, target, metadata, media_format, quality, fps, encoder)
        phase = "CPU変換中" if encoder == "libx264" else "GPU変換中"
        emit("log", message=f"映像変換: {encoder} / フレームレート: {str(fps) + 'fps' if fps else '元のまま'}")
    elif media_format == "MP4":
        emit("log", message="映像は再圧縮せず、高速保存します。")
        if "-c:a" in args and args[args.index("-c:a") + 1] != "copy":
            phase = "音声変換中"
    try:
        run_conversion([tools["ffmpeg"], *args], source, duration, phase)
    except RuntimeError:
        if not needs_encode or encoder == "libx264":
            raise
        emit("log", message="GPU変換に失敗したため、CPU高速変換で再試行します。")
        target.unlink(missing_ok=True)
        args = conversion_args(source, target, metadata, media_format, quality, fps, "libx264")
        run_conversion([tools["ffmpeg"], *args], source, duration, "CPU変換中")
    output_info = probe(target, tools["ffprobe"])
    streams = output_info.get("streams", [])
    if media_format == "MP3":
        if not any(s.get("codec_name") == "mp3" for s in streams):
            raise RuntimeError("MP3の検証に失敗しました。")
    else:
        if not any(s.get("codec_name") == "h264" for s in streams):
            raise RuntimeError("MP4の映像検証に失敗しました。")
        if any(s.get("codec_type") == "audio" and s.get("codec_name") != "aac" for s in streams):
            raise RuntimeError("MP4の音声検証に失敗しました。")
        if fps is not None:
            video = next(s for s in streams if s.get("codec_type") == "video")
            if stream_fps(video) is None or abs(stream_fps(video) - fps) > .01:
                raise RuntimeError("出力フレームレートの検証に失敗しました。")
    return output_info


def download(payload: dict):
    row = payload["item"]
    workspace = Path(payload["workspace"])
    tools = payload["tools"]
    last_progress = 0.0

    def progress(data):
        nonlocal last_progress
        if data.get("status") != "downloading":
            return
        now = time.monotonic()
        if now - last_progress < .15:
            return
        last_progress = now
        downloaded = data.get("downloaded_bytes", 0)
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        fmt = data.get("info_dict", {})
        phase = "音声取得" if fmt.get("vcodec") == "none" else "映像取得"
        emit("progress", phase=phase, percent=min(100, downloaded / total * 100) if total else None,
             downloaded=downloaded, total=total, estimated=not bool(data.get("total_bytes")),
             speed=data.get("speed"), eta=data.get("eta"))

    def postprocess(data):
        if data.get("status") in ("started", "processing"):
            emit("progress", phase="結合・後処理中", percent=None, downloaded=None, total=None, speed=None, eta=None)

    def reject_live(info, *, incomplete=False):
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return "配信中・配信予定のライブは対象外です。"
        return None

    opts = options(tools)
    opts.update({"format": format_selector(payload["format"], payload["quality"]),
                 "outtmpl": str(workspace / "source.%(ext)s"), "merge_output_format": "mkv",
                 "progress_hooks": [progress], "postprocessor_hooks": [postprocess],
                 "match_filter": reject_live, "overwrites": False, "noplaylist": True})
    if payload["format"] == "MP4":
        # Preserve resolution/frame-rate priority, then prefer codecs that can be copied.
        opts["format_sort"] = ["res", f"fps:{payload['fps']}" if payload.get("fps") else "fps", "vcodec:h264", "acodec:aac"]
    apply_container_options(opts, row)
    emit("progress", phase="動画情報を確認中", percent=None, downloaded=None, total=None, speed=None, eta=None)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = extract_item(ydl, row)
        if not info or "entries" in info:
            raise ValueError("単一動画を取得できませんでした。URLを確認してください。")
        if reject_live(info):
            raise ValueError(reject_live(info))
        detail = entry_from_info(info, row["url"])
        detail["key"] = row["key"]
        emit("download_detail", item=detail)
        info = ydl.process_ie_result(info, download=True)
    # With a fixed source basename, yt-dlp leaves exactly one finished media file.
    sources = [p for p in workspace.glob("source.*") if p.suffix.lower() not in (".part", ".ytdl", ".temp", ".json")]
    if len(sources) != 1:
        raise RuntimeError("取得した動画ファイルを特定できませんでした。")
    target = workspace / ("converted." + payload["format"].lower())
    output_info = convert(sources[0], target, tools, payload["format"], payload["quality"], payload.get("fps"), payload.get("encoding_mode", "自動（高速）"))
    if not detail.get("duration"):
        detail["duration"] = float(output_info.get("format", {}).get("duration") or 0) or None
        emit("download_detail", item=detail)
    final = publish_file(target, Path(payload["destination"]), output_stem(detail["title"], detail["id"], detail["site"]), payload["format"].lower())
    emit("done", path=str(final))


def main():
    # Frozen Python ignores PYTHONIOENCODING; keep the IPC wire format UTF-8 explicitly.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        payload = json.loads(sys.stdin.readline())
        if payload["action"] == "discover":
            discover(payload)
        elif payload["action"] == "download":
            download(payload)
        else:
            raise ValueError("不明な処理です。")
    except Exception as error:
        emit("error", message=user_error(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
