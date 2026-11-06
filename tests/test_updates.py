import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError

from downloader.updates import (newest_release, version_number, check_for_update,
                                RELEASES_URL, MAX_RESPONSE)


def release(version, **overrides):
    tag = "v" + version
    name = f"YoutubePandora-v{version}-Windows-x64.zip"
    return {"tag_name": tag, "draft": False, "prerelease": False, "body": "更新内容",
            "assets": [{"name": name, "state": "uploaded", "browser_download_url": f"{RELEASES_URL}/download/{tag}/{name}"}], **overrides}


class UpdateTests(unittest.TestCase):
    def test_versions_are_numeric_and_validated(self):
        self.assertGreater(version_number("v1.10.0"), version_number("1.9.9"))
        for bad in ("v1", "1.2.x", "1.2.3-rc1", "../1.2.3", "1.2.3\n", None):
            self.assertIsNone(version_number(bad))

    def test_selects_highest_newer_version_regardless_of_order(self):
        update = newest_release([release("1.9.9"), release("1.11.0"), release("1.10.0")], "1.9.9")
        self.assertEqual(update.version, "1.11.0")
        self.assertTrue(update.download_url.endswith("YoutubePandora-v1.11.0-Windows-x64.zip"))
        self.assertIsNone(newest_release([release("1.9.9"), release("1.8.0")], "1.9.9"))

    def test_excludes_drafts_prereleases_and_missing_windows_assets(self):
        self.assertIsNone(newest_release([release("2.0.0", draft=True), release("3.0.0", prerelease=True),
                                        release("4.0.0", assets=[]), release("5.0.0", assets=None), None], "1.0.0"))

    def test_rejects_wrong_asset_links_and_unfinished_uploads(self):
        for field, value in (("browser_download_url", "https://example.com/download.exe"), ("state", "starter"), ("name", "source.zip")):
            item = release("2.0.0")
            item["assets"][0][field] = value
            self.assertIsNone(newest_release([item], "1.0.0"))

    def test_handles_empty_list_and_rejects_malformed_response(self):
        self.assertIsNone(newest_release([], "1.0.0"))
        with self.assertRaises(ValueError):
            newest_release({"message": "API error"}, "1.0.0")
        self.assertEqual(len(newest_release([release("2.0.0", body="a" * 10000)], "1.0.0").notes), 3000)

    @patch("downloader.updates.urlopen")
    def test_fetch_uses_timeout_bounded_read_and_public_request(self, open_url):
        response = MagicMock()
        response.read.return_value = json.dumps([release("2.0.0")]).encode()
        open_url.return_value.__enter__.return_value = response
        self.assertEqual(check_for_update("1.0.0").version, "2.0.0")
        response.read.assert_called_once_with(MAX_RESPONSE + 1)
        self.assertEqual(open_url.call_args.kwargs["timeout"], 10)
        self.assertFalse(open_url.call_args.args[0].has_header("Authorization"))

    @patch("downloader.updates.urlopen", side_effect=URLError("offline"))
    def test_offline_does_not_claim_up_to_date(self, _):
        with self.assertRaises(URLError):
            check_for_update("1.0.0")

    @patch("downloader.updates.urlopen")
    def test_rejects_oversized_payload(self, open_url):
        open_url.return_value.__enter__.return_value.read.return_value = b" " * (MAX_RESPONSE + 1)
        with self.assertRaises(ValueError):
            check_for_update("1.0.0")
