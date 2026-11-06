"""Create a local venv and install portable dependencies without admin rights."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import venv
import zipfile

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"


def request(url):
    certificates = ROOT / ".venv" / "Lib" / "site-packages" / "certifi" / "cacert.pem"
    context = ssl.create_default_context(cafile=str(certificates)) if certificates.exists() else ssl.create_default_context()
    return urlopen(Request(url, headers={"User-Agent": "SimpleMediaDownloader-Setup/1.0"}), timeout=60, context=context)


def fetch(url):
    with request(url) as response:
        return response.read()


def download(url, target):
    print(f"Downloading: {url}", flush=True)
    with request(url) as response, target.open("wb") as output:
        size = int(response.headers.get("Content-Length", 0))
        count, last = 0, -1
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            count += len(chunk)
            progress = count * 100 // size if size else count // (10 * 1024 * 1024)
            if progress // 10 != last:
                print(f"  {count // (1024 * 1024)} MB" + (f" / {size // (1024 * 1024)} MB" if size else ""), flush=True)
                last = progress // 10


def install_zip(url, names, checksum=None):
    TOOLS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="media-setup-") as directory:
        archive = Path(directory) / "download.zip"
        download(url, archive)
        if checksum:
            with archive.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if actual.lower() != checksum.lower():
                raise RuntimeError("Downloaded archive checksum mismatch. Please retry setup.")
        with zipfile.ZipFile(archive) as bundle:
            for name in names:
                matches = [entry for entry in bundle.infolist() if Path(entry.filename).name == name]
                if len(matches) != 1:
                    raise RuntimeError(f"Archive does not contain one {name}")
                staged = TOOLS / (name + ".new")
                with bundle.open(matches[0]) as source, staged.open("wb") as output:
                    shutil.copyfileobj(source, output)
                staged.replace(TOOLS / name)
            for entry in bundle.infolist():
                if Path(entry.filename).name.lower() in ("license", "license.txt"):
                    license_name = "LICENSE-FFmpeg.txt" if "ffmpeg.exe" in names else "LICENSE-Deno.txt"
                    (TOOLS / license_name).write_bytes(bundle.read(entry))


def install_tools():
    if not all((TOOLS / name).is_file() for name in ("ffmpeg.exe", "ffprobe.exe")):
        url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
        checksum_text = fetch(url + ".sha256").decode().strip()
        match = re.search(r"\b[0-9a-fA-F]{64}\b", checksum_text)
        if not match:
            raise RuntimeError("FFmpeg checksum could not be read.")
        install_zip(url, ("ffmpeg.exe", "ffprobe.exe"), match.group())
    if not (TOOLS / "deno.exe").is_file():
        release = json.loads(fetch("https://api.github.com/repos/denoland/deno/releases/latest"))
        asset = next(x for x in release["assets"] if x["name"] == "deno-x86_64-pc-windows-msvc.zip")
        digest = asset.get("digest") or ""
        install_zip(asset["browser_download_url"], ("deno.exe",), digest.removeprefix("sha256:") if digest.startswith("sha256:") else None)
    for name in ("ffmpeg", "ffprobe", "deno"):
        version_flag = "--version" if name == "deno" else "-version"
        result = subprocess.run([str(TOOLS / (name + ".exe")), version_flag], capture_output=True, text=True, timeout=20)
        result.check_returncode()
        print(result.stdout.splitlines()[0], flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="Upgrade Python dependencies")
    parser.add_argument("--skip-tools", action="store_true", help="Only prepare Python dependencies")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or later is required.")
    environment = ROOT / ".venv"
    python = environment / "Scripts" / "python.exe"
    if not python.exists():
        print("Creating Python virtual environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "-r", str(ROOT / "requirements.txt")], check=True)
    if not args.skip_tools:
        install_tools()
    print("\nSetup complete. Double-click start.bat to launch.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nSetup failed: {error}\nSee README.md for manual installation instructions.", file=sys.stderr)
        raise SystemExit(1)
