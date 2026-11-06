import tempfile
import unittest
from pathlib import Path

from PIL import Image

from downloader.background import parse_crop, transparency, render, load_image, store_image, glass_image
from downloader.core import Settings


class BackgroundTests(unittest.TestCase):
    def test_glass_settings_and_softened_edges(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"panel_transparency":"999", "panel_blur":"-2"}')
            settings = Settings.load(path)
            self.assertEqual((settings.panel_transparency, settings.panel_blur), ("85", "0"))
            path.write_text('{"panel_transparency":"nan", "panel_blur":"bad"}')
            self.assertEqual(Settings.load(path), Settings())
            settings.panel_transparency, settings.panel_blur = "55", "18"
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)
        image = Image.new("RGB", (100, 100), "black")
        image.paste("white", (50, 0, 100, 100))
        crisp = glass_image(image, 60, 0, "black")
        soft = glass_image(image, 60, 18, "black")
        self.assertEqual(glass_image(image, 0, 0, "#191c23").getpixel((50, 50)), (25, 28, 35))
        self.assertGreater(soft.getpixel((45, 50))[0], crisp.getpixel((45, 50))[0])
        self.assertLess(soft.getpixel((55, 50))[0], crisp.getpixel((55, 50))[0])

    def test_invalid_settings_and_roundtrip(self):
        for crop in ("nan,0,1,1", "0,0,0,1", "-1,0,1,1", "0,0,2,1", "broken", "0,0,1,1,2"):
            self.assertEqual(parse_crop(crop), (0, 0, 1, 1))
        self.assertEqual(transparency("bad"), 35)
        self.assertEqual(transparency("150"), 100)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = Settings(background_crop="0.1,0.2,0.8,0.9", background_transparency="70")
            settings.save(path)
            self.assertEqual(Settings.load(path), settings)
            path.write_text('{"background_crop":"nan,0,1,1", "background_transparency":"invalid"}')
            self.assertEqual(Settings.load(path), Settings())

    def test_crop_pixels_opacity_endpoints_and_transparent_png(self):
        image = Image.new("RGBA", (100, 50), "red")
        image.paste("blue", (50, 0, 100, 50))
        self.assertEqual(render(image, (20, 20), "0.5,0,1,1", 0, "black").getpixel((10, 10)), (0, 0, 255))
        self.assertEqual(render(image, (20, 20), "0.5,0,1,1", 100, "#202020").getpixel((10, 10)), (32, 32, 32))
        self.assertEqual(render(image, (20, 20), "0.5,0,1,1", 50, "black").getpixel((10, 10)), (0, 0, 128))
        invisible = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
        self.assertEqual(render(invisible, (20, 20), "0,0,1,1", 0, "#ffffff").getpixel((5, 5)), (255, 255, 255))

    def test_private_copy_survives_original_removal_and_is_deduplicated(self):
        with tempfile.TemporaryDirectory(prefix="背景 画像 ") as folder:
            source = Path(folder) / "元画像.png"
            Image.new("RGB", (240, 120), "green").save(source)
            before = source.read_bytes()
            image = load_image(source)
            target = store_image(image, Path(folder) / "設定")
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(store_image(image, Path(folder) / "設定"), target)
            source.unlink()
            self.assertEqual(load_image(target).size, (240, 120))

    def test_exif_orientation_and_invalid_image(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "rotated.jpg"
            image = Image.new("RGB", (240, 120), "red")
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)
            self.assertEqual(load_image(source).size, (120, 240))
            source.write_text("not an image")
            with self.assertRaises(OSError):
                load_image(source)
