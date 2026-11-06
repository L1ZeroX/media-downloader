import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
import unittest

from downloader.core import Settings, resolve_tools
from downloader.processes import WindowsJob


@unittest.skipUnless(os.name == "nt", "Windows Job Object test")
class ProcessTreeTests(unittest.TestCase):
    def test_stop_and_owner_close_terminate_ffmpeg_descendant(self):
        ffmpeg = resolve_tools(Settings())["ffmpeg"]
        if not ffmpeg:
            self.skipTest("FFmpeg is required")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        code = """import subprocess,sys
input()
p=subprocess.Popen([sys.argv[1],'-v','error','-f','lavfi','-i','color=size=640x360:rate=30','-f','null','-'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(p.pid,flush=True)
p.wait()
"""
        for action in ("stop", "owner_close"):
            with self.subTest(action=action):
                parent = subprocess.Popen([sys.executable, "-u", "-c", code, ffmpeg], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                job = WindowsJob(parent)
                handle = None
                try:
                    parent.stdin.write("start\n")
                    parent.stdin.close()
                    child_pid = int(parent.stdout.readline())
                    handle = kernel.OpenProcess(0x100000, False, child_pid)
                    self.assertTrue(handle)
                    self.assertEqual(kernel.WaitForSingleObject(handle, 0), 258)
                    job.terminate() if action == "stop" else job.close()
                    parent.wait(timeout=5)
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
                finally:
                    job.close()
                    parent.wait(timeout=5)
                    parent.stdout.close()
                    if handle:
                        kernel.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()
