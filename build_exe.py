"""Build a portable Windows x64 folder and ZIP, including media tools."""
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import importlib.metadata
import ssl
from urllib.request import urlopen
import certifi
import argparse
import json
from downloader.version import APP_NAME, EXECUTABLE_NAME, STABLE_VERSION, BETA_VERSION

ROOT = Path(__file__).resolve().parent


def main(dist_dir=None, beta=False):
    VERSION = BETA_VERSION if beta else STABLE_VERSION
    channel = ROOT / "build" / "release_channel.json"
    channel.parent.mkdir(exist_ok=True)
    channel.write_text(json.dumps({"beta": beta}), encoding="utf-8")
    dist_dir = Path(dist_dir) if dist_dir is not None else ROOT / "dist"
    icon = ROOT / "assets" / "app.ico"
    if not icon.is_file():
        raise FileNotFoundError(f"Window icon not found: {icon}")
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        if not (ROOT / "tools" / name).exists():
            raise RuntimeError("Run setup.bat before building: missing " + name)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--console", "--hide-console", "hide-early",
        "--name", EXECUTABLE_NAME, "--distpath", str(dist_dir / f"v{VERSION}"), "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--icon", str(icon),
        "--add-data", str(ROOT / "assets") + ";assets",
        "--add-data", str(channel) + ";.",
        "--collect-all", "customtkinter", "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs",
        "--copy-metadata", "yt-dlp", "--copy-metadata", "yt-dlp-ejs", "--copy-metadata", "customtkinter",
        "--hidden-import", "PIL._tkinter_finder", "--exclude-module", "pytest", "--exclude-module", "unittest",
        str(ROOT / "main.py"),
    ], cwd=ROOT, check=True)
    destination = dist_dir / f"v{VERSION}" / EXECUTABLE_NAME
    shutil.copytree(ROOT / "tools", destination / "tools", dirs_exist_ok=True)
    deno_version = subprocess.check_output([str(destination / "tools" / "deno.exe"), "--version"], text=True).split()[1]
    with urlopen(f"https://raw.githubusercontent.com/denoland/deno/v{deno_version}/LICENSE.md",
                 context=ssl.create_default_context(cafile=certifi.where()), timeout=30) as response:
        (destination / "tools" / "LICENSE-Deno.txt").write_bytes(response.read())
    licenses = destination / "licenses"
    licenses.mkdir(exist_ok=True)
    for package in ("yt-dlp", "yt-dlp-ejs", "customtkinter", "Pillow", "requests", "urllib3", "certifi", "mutagen",
                    "pycryptodomex", "brotli", "websockets", "charset-normalizer", "idna", "darkdetect", "packaging", "qrcode", "colorama"):
        distribution = importlib.metadata.distribution(package)
        for file in distribution.files or []:
            if "license" in file.name.lower() or file.name.lower() in ("copying", "notice"):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = licenses / package / file.name
                    target.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, licenses / "LICENSE-Python.txt")
    shutil.copy2(ROOT / "README.md", destination / "README.md")
    (destination / "はじめに.txt").write_text(
        f"{APP_NAME} {VERSION} / Windows 10・11 64bit\n\n"
        "1. ZIPをフォルダーごと展開してください。\n"
        f"2. {EXECUTABLE_NAME}.exeをダブルクリックして起動してください。\n"
        "PythonやFFmpegの個別インストールは不要です。\n"
        "EXEだけを移動せず、_internal・toolsを含むフォルダー全体をコピーしてください。\n\n"
        "MP4/MP3・画質・フレームレート・変換方式を画面で選択できます。\n"
        "通常は「自動（高速）」がおすすめです。GPU使用中ならCPU高速もお試しください。\n"
        "更新は新しいEXE版のフォルダーへ置き換えてください。詳しくはREADME.mdを参照してください。\n",
        encoding="utf-8-sig")
    (destination / "THIRD_PARTY.txt").write_text(
        "Bundled third-party software\n\n"
        "yt-dlp (Unlicense): https://github.com/yt-dlp/yt-dlp\n"
        "yt-dlp-ejs: https://github.com/yt-dlp/ejs\n"
        "CustomTkinter (MIT): https://github.com/TomSchimansky/CustomTkinter\n"
        "Python (PSF License): https://www.python.org/psf/license/\n"
        "Pillow (HPND): https://github.com/python-pillow/Pillow\n"
        "Deno (MIT): https://github.com/denoland/deno\n"
        "FFmpeg: Gyan essentials build, GPL. License is in tools/LICENSE-FFmpeg.txt.\n"
        "Build information and corresponding source revision: https://www.gyan.dev/ffmpeg/builds/\n"
        "FFmpeg source: https://git.ffmpeg.org/ffmpeg.git\n"
        "Other Python package licenses are included in _internal where provided by the build hooks.\n",
        encoding="utf-8")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    archive = release / f"{EXECUTABLE_NAME}-v{VERSION}-Windows-x64.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(f"{EXECUTABLE_NAME}-v{VERSION}") / path.relative_to(destination))
    if not beta:
        shutil.copy2(archive, release / f"{EXECUTABLE_NAME}-Windows-x64.zip")
    print(f"Portable EXE: {destination / (EXECUTABLE_NAME + '.exe')}")
    print(f"Distribution ZIP: {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, help="Separate output directory when the previous EXE is running")
    parser.add_argument("--beta", action="store_true", help="Build the separate beta channel")
    args = parser.parse_args()
    main(args.dist_dir, args.beta)
