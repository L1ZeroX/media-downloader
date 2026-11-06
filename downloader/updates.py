"""Read public GitHub releases without credentials or installing anything."""
from dataclasses import dataclass
import json
import re
import ssl
from urllib.request import Request, urlopen

import certifi

REPOSITORY = "L1ZeroX/media-downloader"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=30"
MAX_RESPONSE = 2 * 1024 * 1024


@dataclass(frozen=True)
class Update:
    version: str
    page_url: str
    download_url: str
    notes: str


def version_number(value):
    match = re.fullmatch(r"v?(\d{1,9})\.(\d{1,9})\.(\d{1,9})", str(value))
    return tuple(map(int, match.groups())) if match else None


def newest_release(releases, current):
    installed = version_number(current)
    if installed is None or not isinstance(releases, list):
        raise ValueError("バージョン情報の形式が正しくありません。")
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        number = version_number(tag)
        if number is None or number <= installed:
            continue
        version = tag.removeprefix("v")
        name = f"YoutubePandora-v{version}-Windows-x64.zip"
        download = f"{RELEASES_URL}/download/{tag}/{name}"
        assets = release.get("assets")
        if not isinstance(assets, list) or not any(
            isinstance(a, dict) and a.get("name") == name and a.get("state") == "uploaded"
            and a.get("browser_download_url") == download for a in assets
        ):
            continue
        candidates.append((number, Update(version, f"{RELEASES_URL}/tag/{tag}", download,
                                          str(release.get("body") or "更新内容はリリースページをご確認ください。")[:3000])))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def check_for_update(current):
    request = Request(API_URL, headers={"Accept": "application/vnd.github+json",
                      "User-Agent": f"YoutubePandora-Windows/{current}", "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=10, context=ssl.create_default_context(cafile=certifi.where())) as response:
        body = response.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise ValueError("バージョン情報が大きすぎます。")
    return newest_release(json.loads(body), current)
