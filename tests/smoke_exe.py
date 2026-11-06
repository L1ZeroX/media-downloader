"""Opt-in packaged EXE verification, with Python absent from the child's PATH."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from downloader.core import cleanup_workspace
from downloader.processes import WindowsJob


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--interpolate", action="store_true", help="Verify beta motion interpolation")
    parser.add_argument("--gpu-interpolate", action="store_true", help="Verify beta RIFE/Vulkan interpolation on a supported GPU")
    parser.add_argument("--external-url", help="Optional additional public video URL")
    args = parser.parse_args()
    executable = Path(args.exe).resolve()
    tools = {name: str(executable.parent / "tools" / (name + ".exe")) for name in ("ffmpeg", "ffprobe", "deno")}
    root = Path(__file__).resolve().parent.parent / ".test-artifacts" / "EXE 検証"
    root.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
    env.update(PATH=str(Path(os.environ["SystemRoot"]) / "System32"), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

    def execute(payload):
        worker = subprocess.Popen([str(executable), "--worker"], cwd=root, env=env, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        job = WindowsJob(worker)
        try:
            stdout, stderr = worker.communicate(json.dumps(payload, ensure_ascii=False) + "\n", timeout=150)
        finally:
            job.close()
            worker.wait(timeout=10)
        events = []
        for line in stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        assert worker.returncode == 0, (worker.returncode, events, stderr)
        return events

    def check_download(url, media_format, fps=None, mode="自動（高速）", interpolate=False):
        workspace = tempfile.mkdtemp(prefix=".media-download-", dir=root)
        try:
            events = execute({"action": "download", "item": {"key": "test", "url": url}, "workspace": workspace,
                              "destination": str(root), "format": media_format,
                              "quality": "192kbps" if media_format == "MP3" else "1080p以下", "fps": fps,
                              "encoding_mode": mode, "interpolate": interpolate, "tools": tools})
            output = next(e["path"] for e in events if e["event"] == "done")
            result = subprocess.run([tools["ffprobe"], "-v", "error", "-show_streams", "-show_format", "-of", "json", output],
                                    capture_output=True, text=True, encoding="utf-8", check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            info = json.loads(result.stdout)
            if interpolate:
                phase = "フレーム補間中（CPU）" if mode == "CPU高速" else "フレーム補間中（GPU / RIFE）"
                assert any(e.get("phase") == phase for e in events), events
                assert abs(float(info["format"]["duration"]) - 2) < .05
            codecs = {s["codec_name"] for s in info["streams"]}
            assert codecs == ({"h264", "aac"} if media_format == "MP4" else {"mp3"}), codecs
            if fps:
                video = next(s for s in info["streams"] if s["codec_type"] == "video")
                assert video["avg_frame_rate"] == f"{fps}/1", video
            record = {"url": url, "format": media_format, "fps": fps, "path": output,
                      "duration": info["format"]["duration"], "codecs": sorted(codecs),
                      "conversion": [e["message"] for e in events if e["event"] == "log" and "変換" in e["message"]]}
            print(json.dumps(record, ensure_ascii=False), flush=True)
            return record
        finally:
            cleanup_workspace(workspace, str(root))

    media = root / "fixture.mp4"
    subprocess.run([tools["ffmpeg"], "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=12",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(media)],
                   check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = []
    try:
        url = f"http://127.0.0.1:{server.server_port}/fixture.mp4"
        results.append(check_download(url, "MP4", 30, "GPU優先"))
        results.append(check_download(url, "MP3"))
        if args.interpolate:
            results.append(check_download(url, "MP4", 60, "CPU高速", interpolate=True))
        if args.gpu_interpolate:
            results.append(check_download(url, "MP4", 60, "GPU優先", interpolate=True))
        if args.live:
            youtube = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
            events = execute({"action": "discover", "urls": [{"url": youtube, "scope": "video"}], "tools": tools})
            detail = next(e["item"] for e in events if e["event"] == "detail")
            assert detail["duration"] == 19 and detail.get("image"), detail
            results.append({"metadata": "YouTube title, duration and thumbnail OK"})
            results.append(check_download(youtube, "MP4", 30))
        if args.external_url:
            results.append(check_download(args.external_url, "MP3"))
    finally:
        server.shutdown()
        server.server_close()
    (root / "report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Packaged EXE smoke test passed.", flush=True)


if __name__ == "__main__":
    main()
