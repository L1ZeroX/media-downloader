"""Install the pinned optional GPU interpolation engine for Windows beta builds."""
import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
import zipfile

from setup_app import ROOT, download, fetch

URL = "https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-windows.zip"
SHA256 = "d8e4d772d26cd8006ef0ad0bc82eb191b53c68677d1ae2f42506d74cbbbea606"
FILES = ("rife-ncnn-vulkan.exe", "vcomp140.dll", "LICENSE", "README.md",
         "rife-v4.6/flownet.bin", "rife-v4.6/flownet.param")
LICENSES = {
    "LICENSE-RIFE-model.txt": "https://raw.githubusercontent.com/hzwer/arXiv2020-RIFE/main/LICENSE",
    "LICENSE-ncnn.txt": "https://raw.githubusercontent.com/Tencent/ncnn/master/LICENSE.txt",
    "LICENSE-libwebp.txt": "https://raw.githubusercontent.com/webmproject/libwebp/main/COPYING",
    "LICENSE-dirent.txt": "https://raw.githubusercontent.com/tronkko/dirent/master/LICENSE",
}


def install(archive=None):
    destination = ROOT / "tools" / "rife"
    with tempfile.TemporaryDirectory(prefix="pandora-rife-") as temporary:
        archive = Path(archive) if archive else Path(temporary) / "rife.zip"
        if not archive.exists():
            download(URL, archive)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
                raise RuntimeError("RIFEの配布ZIPのハッシュが一致しません。")
        stage = Path(temporary) / "ready"
        with zipfile.ZipFile(archive) as bundle:
            prefix = "rife-ncnn-vulkan-20221029-windows/"
            for name in FILES:
                path = stage / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bundle.read(prefix + name))
        for name, url in LICENSES.items():
            (stage / name).write_bytes(fetch(url))
        (stage / "THIRD_PARTY.txt").write_text(
            "RIFE ncnn Vulkan 20221029 / model rife-v4.6\n"
            f"Upstream binary: {URL}\nSHA256: {SHA256}\n"
            "RIFE and RIFE model: MIT; ncnn: BSD-3-Clause; libwebp: BSD; dirent: MIT.\n"
            "vcomp140.dll: Microsoft Visual C++ OpenMP runtime, included in the upstream Windows archive.\n"
            "Microsoft runtime terms: https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/\n",
            encoding="utf-8")
        shutil.copytree(stage, destination, dirs_exist_ok=True)
    print("GPU interpolation engine installed:", destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, help="Use a previously downloaded official archive")
    install(parser.parse_args().archive)
