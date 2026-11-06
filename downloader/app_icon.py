"""Use the same multi-resolution icon for Windows, Tk and the executable."""
import ctypes
import os
from pathlib import Path
import sys


def icon_path():
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "assets" / "app.ico"


def set_app_identity():
    if os.name == "nt":
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.c_long
        result = set_id("L1ZeroX.MediaDownloader")
        if result != 0:
            raise OSError(f"SetCurrentProcessExplicitAppUserModelID failed: {result:#x}")


def set_window_icon(window):
    if os.name == "nt":
        window.iconbitmap(default=str(icon_path()))
