from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes


class FrameRateTracker:
    """Track incoming frames over a short rolling window."""

    def __init__(self, window_seconds: float = 1.0):
        self.window_seconds = max(float(window_seconds), 0.1)
        self._samples: list[tuple[float, int]] = []

    def add(self, frame_count: int, now: float | None = None) -> None:
        count = max(int(frame_count), 0)
        if count:
            self._samples.append((time.monotonic() if now is None else float(now), count))

    def frames_per_second(self, now: float | None = None) -> float:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - self.window_seconds
        self._samples = [(stamp, count) for stamp, count in self._samples if stamp > cutoff]
        total = sum(count for _, count in self._samples)
        return total / self.window_seconds


def memory_warning_threshold_bytes(
    total_memory_bytes: int,
    absolute_limit_bytes: int = 2 * 1024**3,
    system_fraction: float = 0.60,
) -> int:
    """Return the lower of the configured absolute and physical-memory limits."""
    return max(1, min(int(absolute_limit_bytes), int(total_memory_bytes * system_fraction)))


def process_memory_bytes() -> int | None:
    """Return resident memory for this process on supported desktop platforms."""
    if sys.platform == "win32":
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_info = psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(
            wintypes.HANDLE(ctypes.windll.kernel32.GetCurrentProcess()),
            ctypes.byref(counters), counters.cb
        ):
            return None
        return int(counters.WorkingSetSize)
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/statm", encoding="ascii") as handle:
                resident_pages = int(handle.read().split()[1])
            return resident_pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "darwin":
        buffer = ctypes.create_string_buffer(256)
        proc_lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        proc_pid_rusage = proc_lib.proc_pid_rusage
        proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        proc_pid_rusage.restype = ctypes.c_int
        if proc_pid_rusage(os.getpid(), 2, ctypes.byref(buffer)) == 0:
            return int(ctypes.c_uint64.from_buffer(buffer, 64).value)
    return None


def system_memory_bytes() -> int | None:
    """Return physical RAM size on Windows, Linux or macOS."""
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return None
    if sys.platform.startswith("linux"):
        try:
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (ValueError, OSError):
            return None
    if sys.platform == "darwin":
        total = ctypes.c_uint64()
        size = ctypes.c_size_t(ctypes.sizeof(total))
        sysctlbyname = ctypes.CDLL(None).sysctlbyname
        sysctlbyname.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        sysctlbyname.restype = ctypes.c_int
        if sysctlbyname(b"hw.memsize", ctypes.byref(total), ctypes.byref(size), None, 0) == 0:
            return int(total.value)
    return None
