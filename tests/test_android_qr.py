import unittest
from PIL import Image, ImageFilter
from downloader.android_qr import RELEASES_URL, latest_apk, make_qr, icon_colors


class AndroidQrTests(unittest.TestCase):
    def release(self, tag, **changes):
        name = f"YoutubePandora-Android-{tag}.apk"
        value = {"tag_name": tag, "draft": False, "prerelease": True,
                 "assets": [{"name": name, "state": "uploaded", "browser_download_url": f"{RELEASES_URL}/download/{tag}/{name}"}]}
        value.update(changes)
        return value

    def test_newest_public_apk_includes_prereleases_and_compares_numbers(self):
        tag, url = latest_apk([self.release("v0.2.9"), self.release("v0.2.10"), self.release("v1.0.0", draft=True), self.release("v2.0.0", assets=[])])
        self.assertEqual(tag, "v0.2.10")
        self.assertTrue(url.endswith("/YoutubePandora-Android-v0.2.10.apk"))

    def test_unexpected_asset_links_are_not_used(self):
        release = self.release("v1.0.0")
        release["assets"][0]["browser_download_url"] = "https://example.com/app.apk"
        with self.assertRaises(ValueError):
            latest_apk([None, release, self.release("bad-tag")])

    def test_qr_colors_follow_icon_and_ignore_transparent_padding(self):
        blue = Image.new("RGBA", (64, 64), (0, 150, 255, 255))
        red = Image.new("RGBA", (64, 64), (220, 30, 60, 255))
        self.assertNotEqual(icon_colors(blue), icon_colors(red))
        clear = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
        clear.paste(blue.crop((0, 0, 32, 32)), (16, 16))
        self.assertEqual(icon_colors(clear), icon_colors(blue))

    def test_styled_qr_decodes_with_logo_at_display_size(self):
        try:
            import zxingcpp
        except ImportError:
            self.skipTest("Install zxing-cpp for independent QR decoding checks")
        for url in (RELEASES_URL, self.release("v0.2.3")["assets"][0]["browser_download_url"]):
            image = make_qr(url)
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
            for size in (360, 450, 540):
                shown = image.resize((size, size), Image.Resampling.LANCZOS)
                for sample in (shown, shown.convert("L"), shown.filter(ImageFilter.GaussianBlur(.4))):
                    decoded = zxingcpp.read_barcode(sample)
                    self.assertIsNotNone(decoded, (url, size))
                    self.assertEqual(decoded.text, url)


if __name__ == "__main__":
    unittest.main()
