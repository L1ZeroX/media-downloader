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


def set_titlebar_color(window, mode):
    """Update DWM directly without CTk's withdraw/deiconify cycle."""
    if os.name != "nt":
        return
    from ctypes import wintypes
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.GetAncestor(window.winfo_id(), 2)
    dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.DwmSetWindowAttribute.restype = ctypes.c_long
    value = ctypes.c_int(mode.lower() == "dark")
    if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)):
        dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
