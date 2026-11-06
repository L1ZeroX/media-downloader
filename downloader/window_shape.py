"""Native popup clipping, without a color key that can bleed into rounded edges."""
import ctypes
from ctypes import wintypes
from functools import lru_cache
import os


@lru_cache(maxsize=1)
def windows_api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
    return user32, gdi32


def round_popup(window, width, height, radius):
    if os.name != "nt":
        return
    user32, gdi32 = windows_api()
    # Tk has a client window inside a native wrapper. The region belongs on the wrapper.
    handle = user32.GetAncestor(window.winfo_id(), 2)  # GA_ROOT
    region = gdi32.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1,
                                    max(2, round(radius * 2)), max(2, round(radius * 2)))
    if not region:
        raise ctypes.WinError(ctypes.get_last_error())
    if not user32.SetWindowRgn(handle, region, True):
        gdi32.DeleteObject(region)
        raise ctypes.WinError(ctypes.get_last_error())
    # On success Windows owns the region, and releases it when the window is destroyed.
