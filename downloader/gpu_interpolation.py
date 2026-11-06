"""Bounded RIFE/Vulkan batches, with one continuous decoder and encoder.

One lookahead frame crosses each batch boundary. It is not emitted twice, so
restarting RIFE does not create frozen frames or shift the audio timeline.
"""
from contextlib import ExitStack
from fractions import Fraction
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from PIL import Image

from .core import ROOT

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def engine_paths():
    home = ROOT / "tools" / "rife"
    executable, model = home / "rife-ncnn-vulkan.exe", home / "rife-v4.6"
    if not executable.is_file() or not all((model / f"flownet.{ext}").is_file() for ext in ("bin", "param")):
        raise RuntimeError("RIFEがありません。GPU補間対応ベータ版のZIPをフォルダーごと展開してください。")
    return executable, model


def frame_plan(video, quality):
    rate = Fraction(0)
    for field in ("avg_frame_rate", "r_frame_rate"):
        try:
            rate = Fraction(video.get(field) or "0")
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            break
    if not 1 <= rate < 60:
        raise ValueError("GPU補間の入力fpsを確認できません。")
    width, height = int(video["width"]), int(video["height"])
    rotation = next((float(s.get("rotation", 0)) for s in video.get("side_data_list", []) if "rotation" in s), 0)
    try:
        sar = float(Fraction(video.get("sample_aspect_ratio", "1:1").replace(":", "/")))
    except (ValueError, ZeroDivisionError):
        sar = 1
    width = round(width * (sar if sar > 0 else 1))
    if round(rotation) % 180:
        width, height = height, width
    cap = {"720p以下": 720, "1080p以下": 1080}.get(quality)
    if cap and height > cap:
        width, height = round(width * cap / height), cap
    width, height = max(2, (width + 1)//2*2), max(2, (height + 1)//2*2)
    # Integer multiplication keeps exact frame positions across batch boundaries.
    factor = math.ceil(Fraction(60) / rate)
    # Bound temporary images to about 512 MiB uncompressed, not the video length.
    batch = max(2, min(120, (512 * 1024**2) // (width * height * 3 * (factor + 1)) - 1))
    return rate, width, height, factor, batch


def _tail(path):
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 3000))
        return stream.read().decode("utf-8", "replace")


def _stop(process):
    if process.poll() is None:
        process.kill()
    process.wait()
    for stream in (process.stdin, process.stdout):
        if stream:
            try:
                stream.close()
            except OSError:
                pass


def _gpu(executable, model, folder):
    first, second, output = [folder / name for name in ("probe-a.png", "probe-b.png", "probe-out.png")]
    Image.new("RGB", (64, 64), "red").save(first)
    Image.new("RGB", (64, 64), "blue").save(second)
    result = subprocess.run([str(executable), "-0", str(first), "-1", str(second), "-o", str(output),
                             "-m", str(model), "-g", "0", "-j", "1:1:1"],
                            capture_output=True, timeout=60, creationflags=FLAGS)
    log = result.stderr.decode("utf-8", "replace")
    devices = dict(re.findall(r"^\[(\d+) ([^\]]+)\]  queueC=", log, re.MULTILINE))
    if not devices:
        raise RuntimeError("Vulkan対応GPUが見つかりません。GPUドライバーを確認してください。\n" + log[-1500:])
    # Prefer a discrete NVIDIA/AMD device over an integrated Intel adapter.
    index = next((i for i, name in devices.items() if "NVIDIA" in name or "Radeon RX" in name), next(iter(devices)))
    if index == "0" and (result.returncode or not output.is_file()):
        raise RuntimeError("GPU補間の動作確認に失敗しました。\n" + log[-1500:])
    return index, devices[index]


def interpolate_video(source, target, tools, metadata, quality, encoder, encoder_options, emit):
    executable, model = engine_paths()
    video = next(s for s in metadata["streams"] if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"))
    audio = next((s for s in metadata["streams"] if s.get("codec_type") == "audio"), None)
    duration = float(video.get("duration") or metadata.get("format", {}).get("duration") or 0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("GPU補間に必要な動画時間を取得できません。")
    rate, width, height, factor, batch = frame_plan(video, quality)
    frame_size = width * height * 3
    minimum_space = frame_size * (batch + 1) * (factor + 1) + 64 * 1024**2
    if shutil.disk_usage(source.parent).free < minimum_space:
        raise RuntimeError("GPU補間の一時画像を保存する空き容量が不足しています。")
    emit("progress", phase="GPU補間を準備中", percent=None)
    with tempfile.TemporaryDirectory(prefix="rife-", dir=source.parent) as temporary, ExitStack() as stack:
        folder = Path(temporary)
        device, name = _gpu(executable, model, folder)
        emit("log", message=f"GPUフレーム補間: RIFE 4.6 / Vulkan / {name} / 映像変換: {encoder}")
        inputs, outputs = folder / "input", folder / "output"
        inputs.mkdir(); outputs.mkdir()
        decode_log, encode_log = folder / "decode.log", folder / "encode.log"
        decode = subprocess.Popen([tools["ffmpeg"], "-v", "error", "-nostdin", "-i", str(source),
                                   "-map", f"0:{video['index']}", "-an", "-sn", "-vf",
                                   f"scale={width}:{height},setsar=1,fps={rate}",
                                   "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                                  stdout=subprocess.PIPE, stderr=stack.enter_context(decode_log.open("wb")), creationflags=FLAGS)
        stack.callback(_stop, decode)
        command = [tools["ffmpeg"], "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
                   "-framerate", str(rate * factor), "-f", "image2pipe", "-vcodec", "png", "-i", "pipe:0"]
        if audio:
            command += ["-i", str(source)]
        command += ["-map", "0:v:0"]
        if audio:
            command += ["-map", f"1:{audio['index']}", "-c:a", "copy"] if audio.get("codec_name") == "aac" else ["-map", f"1:{audio['index']}", "-c:a", "aac", "-b:a", "192k"]
        command += [*encoder_options, "-vf", "fps=60", "-pix_fmt", "yuv420p", "-t", str(duration),
                    "-movflags", "+faststart", str(target)]
        encode = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                  stderr=stack.enter_context(encode_log.open("wb")), creationflags=FLAGS)
        stack.callback(_stop, encode)

        def read_frame():
            raw = decode.stdout.read(frame_size)
            if raw and len(raw) != frame_size:
                raise RuntimeError("動画フレームを最後まで読み取れませんでした。")
            return raw

        completed, started = 0, time.monotonic()
        carry = read_frame()
        while carry:
            # Only two raw frames reside in Python memory. PNGs are removed per batch.
            count, last, eof = 1, carry, False
            Image.frombytes("RGB", (width, height), carry).save(inputs / "00000001.png", compress_level=1)
            while count <= batch:
                raw = read_frame()
                if not raw:
                    eof = True
                    raw = last  # Duplicate lookahead only, to retain the final interval.
                count += 1
                Image.frombytes("RGB", (width, height), raw).save(inputs / f"{count:08d}.png", compress_level=1)
                last = raw
                if eof:
                    break
            intervals = count - 1
            rife_log = folder / "rife.log"
            with rife_log.open("wb") as log:
                process = subprocess.Popen([str(executable), "-i", str(inputs), "-o", str(outputs),
                                            "-m", str(model), "-g", device, "-j", "2:1:2",
                                            "-n", str(count * factor), "-f", "%08d.png"],
                                           stdout=subprocess.DEVNULL, stderr=log, creationflags=FLAGS)
                deadline = time.monotonic() + max(120, count * factor * 5)
                try:
                    while process.poll() is None:
                        made = min(intervals * factor, sum(1 for _ in outputs.glob("*.png")))
                        current = (completed + made / factor) / float(rate)
                        elapsed = time.monotonic() - started
                        speed = current / elapsed if elapsed else 0
                        emit("progress", phase="フレーム補間中（GPU / RIFE）",
                             percent=min(99.0, current / duration * 100), downloaded=None, total=None, speed=None,
                             conversion_speed=speed, eta=max(0, duration-current)/speed if speed else None)
                        if time.monotonic() > deadline:
                            raise RuntimeError("GPU補間が時間内に応答しませんでした。")
                        time.sleep(.3)
                    if process.returncode:
                        raise RuntimeError("RIFEのGPU補間に失敗しました。\n" + _tail(rife_log))
                finally:
                    _stop(process)
            try:
                for number in range(1, intervals * factor + 1):
                    encode.stdin.write((outputs / f"{number:08d}.png").read_bytes())
                encode.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                raise RuntimeError("補間フレームの保存に失敗しました。\n" + _tail(encode_log)) from error
            for directory in (inputs, outputs):
                for path in directory.iterdir():
                    path.unlink()
            completed += intervals
            carry = None if eof else last
        if decode.wait(timeout=60):
            raise RuntimeError("動画の読み取りに失敗しました。\n" + _tail(decode_log))
        if not completed:
            raise RuntimeError("補間する動画フレームがありません。")
        emit("progress", phase="補間した動画を保存中", percent=99.0)
        encode.stdin.close()
        if encode.wait(timeout=120):
            raise RuntimeError("補間した動画の保存に失敗しました。\n" + _tail(encode_log))
