import json
import os
from pathlib import Path
import sys

STABLE_VERSION = "1.4.6"
BETA_VERSION = "1.5.0-beta.1"
if getattr(sys, "frozen", False):
    IS_BETA = json.loads((Path(sys._MEIPASS) / "release_channel.json").read_text())["beta"]
else:
    IS_BETA = os.environ.get("PANDORA_BETA") == "1"
APP_NAME = "Youtube Pandora!" + (" Beta" if IS_BETA else "")
EXECUTABLE_NAME = "YoutubePandora"
VERSION = BETA_VERSION if IS_BETA else STABLE_VERSION
