import tempfile
import unittest
from pathlib import Path

from downloader.core import (Settings, cleanup_workspace, duration_text, entry_from_info,
                             find_tool, output_stem, publish_file, validate_url, youtube_mixed_url)
from downloader.worker import conversion_args


class CoreTests(unittest.TestCase):
    def test_settings_roundtrip_and_invalid_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "設定.json"
            settings = Settings(destination="D:/日本語 path", media_format="MP3", audio_quality="320kbps",
                                url_input_size="大きめ", show_preview="オフ", show_log="オフ")
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)
            path.write_text('{"media_format":"bad","audio_quality":"bad","destination":null}', encoding="utf-8")
            self.assertEqual(Settings.load(path).media_format, "MP4")
            self.assertEqual(Settings.load(path).audio_quality, "192kbps")
            self.assertEqual(Settings.load(path).url_input_size, "標準")
            path.write_text('{"url_input_size":"bad","show_preview":false,"show_log":"bad"}', encoding="utf-8")
            self.assertEqual(Settings.load(path), Settings())
            path.write_text("broken", encoding="utf-8")
            self.assertEqual(Settings.load(path), Settings())

    def test_urls_and_youtube_identity(self):
        for value in ("file:///a.mp4", "https://", "https://user:password@example.com/video", "bad"):
            with self.assertRaises(ValueError):
                validate_url(value)
        self.assertTrue(youtube_mixed_url("https://www.youtube.com/watch?v=abc&list=xyz"))
        self.assertFalse(youtube_mixed_url("https://evil-youtube.com/watch?v=abc&list=xyz"))
        self.assertFalse(youtube_mixed_url("https://youtube.com/playlist?list=xyz"))
        flat = entry_from_info({"id": "abc", "ie_key": "Youtube", "url": "abc"})
        full = entry_from_info({"id": "abc", "extractor": "youtube", "webpage_url": "https://youtu.be/abc"})
        self.assertEqual(flat["key"], full["key"])
        self.assertEqual(flat["url"], "https://www.youtube.com/watch?v=abc")

    def test_missing_metadata(self):
        self.assertEqual(duration_text(None), "時間不明")
        self.assertEqual(duration_text(float("nan")), "時間不明")
        self.assertEqual(duration_text(0), "0:00")
        self.assertEqual(duration_text(3661), "1:01:01")
        self.assertIsNone(entry_from_info({"id": "a"})["thumbnail"])

    def test_atomic_publish_never_overwrites(self):
        with tempfile.TemporaryDirectory(prefix="日本語 path ") as folder:
            root = Path(folder)
            source = root / "input.mp4"
            existing = root / "test.mp4"
            existing.write_bytes(b"original")
            source.write_bytes(b"new")
            result = publish_file(source, root, "test", "mp4")
            self.assertEqual(existing.read_bytes(), b"original")
            self.assertEqual(result.name, "test (1).mp4")
            self.assertEqual(result.read_bytes(), b"new")
            self.assertNotIn("/", output_stem('日本語 : / * ?', 'id/1'))

    def test_cleanup_refuses_outside_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            unrelated = root / "important"
            unrelated.mkdir()
            with self.assertRaises(ValueError):
                cleanup_workspace(str(unrelated), str(root))
            self.assertTrue(unrelated.exists())
            work = root / ".media-download-test"
            work.mkdir()
            (work / "temp").write_text("partial")
            cleanup_workspace(str(work), str(root))
            self.assertFalse(work.exists())

    def test_invalid_explicit_tool_does_not_fall_back(self):
        self.assertIsNone(find_tool("ffmpeg", "Z:/not-a-real-folder/ffmpeg.exe"))

    def test_conversion_copies_only_compatible_streams(self):
        streams = [{"index": 0, "codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "height": 720},
                   {"index": 1, "codec_type": "audio", "codec_name": "aac"}]
        args = conversion_args(Path("in"), Path("out"), {"streams": streams}, "MP4", "1080p以下")
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        self.assertEqual(args[args.index("-c:a") + 1], "copy")
        streams[0].update(codec_name="vp9", height=1440)
        streams[1]["codec_name"] = "opus"
        args = conversion_args(Path("in"), Path("out"), {"streams": streams}, "MP4", "720p以下")
        self.assertIn("libx264", args)
        self.assertIn("scale=-2:720", args[args.index("-vf") + 1])
        self.assertEqual(args[args.index("-c:a") + 1], "aac")

    def test_fps_change_requires_encoding_but_matching_fps_copies(self):
        streams = [{"index": 0, "codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", "height": 720,
                    "avg_frame_rate": "30/1"}]
        args = conversion_args(Path("in"), Path("out"), {"streams": streams}, "MP4", "1080p以下", 30)
        self.assertEqual(args[args.index("-c:v") + 1], "copy")
        args = conversion_args(Path("in"), Path("out"), {"streams": streams}, "MP4", "1080p以下", 60, "h264_nvenc")
        self.assertIn("h264_nvenc", args)
        self.assertIn("fps=60", args[args.index("-vf") + 1])

    def test_mp3_requires_audio(self):
        with self.assertRaisesRegex(ValueError, "音声"):
            conversion_args(Path("in"), Path("out"), {"streams": []}, "MP3", "192kbps")


if __name__ == "__main__":
    unittest.main()
