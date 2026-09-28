"""Is the CODESYS IDE window responding? Read-only; never touches the IDE itself.

A stalled IDE operation (for example a download that never finishes) can
leave CODESYS "Not Responding" while the session's own heartbeat looks
fine, so the bench snapshot checks the window too.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any

import psutil

IDE_PROCESS_NAME = "CODESYS.exe"


def ide_processes() -> list[int]:
    return [p.pid for p in psutil.process_iter(["name"]) if p.info["name"] == IDE_PROCESS_NAME]


def _top_level_windows(pids: set[int]) -> list[tuple[int, int, str]]:
    user32 = ctypes.windll.user32
    found: list[tuple[int, int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value:
                found.append((pid.value, hwnd, buffer.value))
        return True

    user32.EnumWindows(visit, 0)
    return found


def ide_health() -> dict[str, Any]:
    pids = ide_processes()
    health: dict[str, Any] = {"running": bool(pids), "pids": pids, "notResponding": False, "windows": []}
    if not pids or os.name != "nt":
        return health
    user32 = ctypes.windll.user32
    for pid, hwnd, title in _top_level_windows(set(pids)):
        hung = bool(user32.IsHungAppWindow(hwnd))
        health["windows"].append({"pid": pid, "title": title, "notResponding": hung})
        health["notResponding"] = health["notResponding"] or hung
    return health
