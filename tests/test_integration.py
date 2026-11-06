from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
import io
from contextlib import redirect_stdout
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image

from downloader.core import Settings, cleanup_workspace, resolve_tools
from downloader.processes import WorkerProcess
from downloader.worker import probe, convert, run_conversion, stream_fps


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = resolve_tools(Settings())
        if not cls.tools["ffmpeg"] or not cls.tools["ffprobe"]:
            raise unittest.SkipTest("Run setup.bat to enable FFmpeg integration tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="日本語 media test ")
        cls.root = Path(cls.temporary.name)
        cls.media = cls.root / "fixture.webm"
        subprocess.run([cls.tools["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                        "-c:v", "libvpx-vp9", "-c:a", "libopus", str(cls.media)], check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        Image.new("RGB", (320, 180), "blue").save(cls.root / "poster.jpg")
        (cls.root / "playlist.html").write_text('<html><title>Playlist test</title><video controls poster="poster.jpg"><source src="fixture.webm" type="video/webm"></video><video controls poster="poster.jpg"><source src="fixture.webm?second=1" type="video/webm"></video></html>', encoding="utf-8")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.root)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/fixture.webm"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temporary.cleanup()

    def run_worker(self, payload):
        events = queue.Queue()
        worker = WorkerProcess(payload, events)
        result = []
        try:
            while True:
                token, event = events.get(timeout=60)
                self.assertEqual(token, worker.token)
                result.append(event)
                if event["event"] == "exit":
                    return result
        finally:
            if worker.process.poll() is None:
                worker.stop()
                worker.process.wait(timeout=10)

    def test_real_download_mp4_and_mp3(self):
        for media_format, quality in (("MP4", "1080p以下"), ("MP3", "192kbps")):
            with self.subTest(format=media_format):
                destination = self.root / ("保存先 " + media_format)
                destination.mkdir(exist_ok=True)
                workspace = tempfile.mkdtemp(prefix=".media-download-", dir=destination)
                try:
                    events = self.run_worker({"action": "download", "item": {"key": "test", "url": self.url},
                                              "workspace": workspace, "destination": str(destination), "format": media_format,
                                              "quality": quality, "tools": self.tools})
                    self.assertEqual(events[-1]["code"], 0, events)
                    completed = [e for e in events if e["event"] == "done"]
                    self.assertEqual(len(completed), 1, events)
                    path = Path(completed[0]["path"])
                    metadata = probe(path, self.tools["ffprobe"])
                    codecs = {s["codec_name"] for s in metadata["streams"]}
                    self.assertEqual(codecs, {"h264", "aac"} if media_format == "MP4" else {"mp3"})
                    self.assertAlmostEqual(float(metadata["format"]["duration"]), 2, delta=.2)
                    progress = [e for e in events if e["event"] == "progress"]
                    self.assertTrue(any("変換中" in e["phase"] for e in progress))
                finally:
                    cleanup_workspace(workspace, str(destination))

    def test_metadata_partial_failure_and_dedup(self):
        bad = self.url.replace("fixture.webm", "missing.webm")
        events = self.run_worker({"action": "discover", "urls": [{"url": bad, "scope": "video"},
                                  {"url": self.url, "scope": "video"}, {"url": self.url, "scope": "video"}],
                                  "tools": self.tools})
        self.assertEqual(len([e for e in events if e["event"] == "source_error"]), 1)
        self.assertEqual(len([e for e in events if e["event"] == "entry"]), 1)
        self.assertEqual(len([e for e in events if e["event"] == "detail"]), 1)
        self.assertTrue(any(e["event"] == "discovery_done" for e in events))

    def test_html_playlist_and_selecting_second_item(self):
        url = self.url.replace("fixture.webm", "playlist.html")
        events = self.run_worker({"action": "discover", "urls": [{"url": url, "scope": "playlist"}], "tools": self.tools})
        entries = [e["item"] for e in events if e["event"] == "entry"]
        self.assertEqual(len(entries), 2, events)
        details = [e["item"] for e in events if e["event"] == "detail"]
        self.assertEqual(len(details), 2, events)
        self.assertTrue(all(e.get("image") for e in details))
        destination = self.root / "playlist selection"
        destination.mkdir(exist_ok=True)
        workspace = tempfile.mkdtemp(prefix=".media-download-", dir=destination)
        try:
            events = self.run_worker({"action": "download", "item": details[1], "workspace": workspace,
                                     "destination": str(destination), "format": "MP4", "quality": "720p以下", "tools": self.tools})
            self.assertEqual(events[-1]["code"], 0, events)
            self.assertEqual(len(list(destination.glob("*.mp4"))), 1)
        finally:
            cleanup_workspace(workspace, str(destination))

    def test_stop_during_network_wait(self):
        class SlowHandler(QuietHandler):
            def do_GET(self):
                self.server.entered.set()
                self.server.release.wait(10)
        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        server.entered = threading.Event()
        server.release = threading.Event()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        events = queue.Queue()
        worker = WorkerProcess({"action": "discover", "urls": [{"url": f"http://127.0.0.1:{server.server_port}/slow", "scope": "video"}], "tools": self.tools}, events)
        try:
            self.assertTrue(server.entered.wait(10))
            start = time.monotonic()
            worker.stop()
            worker.process.wait(timeout=5)
            self.assertLess(time.monotonic() - start, 5)
            while True:
                _, event = events.get(timeout=5)
                if event["event"] == "exit":
                    self.assertTrue(event["stopped"])
                    break
        finally:
            worker.stop()
            server.release.set()
            server.shutdown()
            server.server_close()

    def test_selected_frame_rate_and_gpu_failure_fallback(self):
        destination = self.root / "fps output.mp4"
        attempts = []

        def controlled_run(command, source, duration, phase):
            attempts.append(command)
            if len(attempts) == 1:
                destination.write_bytes(b"partial GPU output")
                raise RuntimeError("Simulated GPU device failure")
            run_conversion(command, source, duration, phase)

        with patch("downloader.worker.choose_encoder", return_value="h264_nvenc"), \
             patch("downloader.worker.run_conversion", side_effect=controlled_run), redirect_stdout(io.StringIO()):
            output = convert(self.media, destination, self.tools, "MP4", "720p以下", 30)
        self.assertEqual(len(attempts), 2)
        self.assertIn("h264_nvenc", attempts[0])
        self.assertIn("libx264", attempts[1])
        video = next(s for s in output["streams"] if s["codec_type"] == "video")
        self.assertAlmostEqual(stream_fps(video), 30)
        self.assertAlmostEqual(float(output["format"]["duration"]), 2, delta=.2)


if __name__ == "__main__":
    unittest.main()
