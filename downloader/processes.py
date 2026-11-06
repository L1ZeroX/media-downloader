"""Worker isolation, JSON events and Windows process-tree lifetime management."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from ctypes import wintypes

from .core import ROOT


class WindowsJob:
    def __init__(self, process: subprocess.Popen):
        self.lock = threading.RLock()
        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            getattr(self.kernel, name).argtypes = args
            getattr(self.kernel, name).restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = EXTENDED_LIMIT()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self):
        with self.lock:
            if self.handle:
                self.kernel.TerminateJobObject(self.handle, 1)

    def close(self):
        with self.lock:
            if self.handle:
                self.kernel.CloseHandle(self.handle)
                self.handle = None


class WorkerProcess:
    def __init__(self, payload: dict, events: queue.Queue):
        self.token = uuid.uuid4().hex
        self.events = events
        self.stopped = False
        self.job = None
        executable = sys.executable
        if os.path.basename(executable).lower() == "pythonw.exe":
            executable = os.path.join(os.path.dirname(executable), "python.exe")
        command = [executable, "--worker"] if getattr(sys, "frozen", False) else [executable, "-u", "-m", "downloader.worker"]
        self.process = subprocess.Popen(
            command, cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        try:
            # Worker waits for input; its children cannot escape the job before assignment.
            if os.name == "nt":
                self.job = WindowsJob(self.process)
        except Exception:
            self.process.kill()
            self.process.wait()
            if self.job:
                self.job.close()
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                stream.close()
            raise
        self.stderr_tail = ""
        threading.Thread(target=self._read_stderr, daemon=True).start()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._send, args=(payload,), daemon=True).start()

    def _send(self, payload):
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            if not self.stopped:
                self.events.put((self.token, {"event": "error", "message": f"取得プロセスへ接続できませんでした: {error}"}))
        finally:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def _read_stderr(self):
        for line in self.process.stderr:
            self.stderr_tail = (self.stderr_tail + line)[-8000:]
        self.process.stderr.close()

    def _read(self):
        for line in self.process.stdout:
            try:
                event = json.loads(line)
                self.events.put((self.token, event))
            except (ValueError, TypeError):
                pass
        self.process.stdout.close()
        code = self.process.wait()
        if self.job:
            self.job.close()
        self.events.put((self.token, {"event": "exit", "code": code, "stopped": self.stopped, "error": self.stderr_tail}))

    def stop(self):
        self.stopped = True
        if self.job:
            self.job.terminate()
        elif self.process.poll() is None:
            import signal
            os.killpg(self.process.pid, signal.SIGTERM)
