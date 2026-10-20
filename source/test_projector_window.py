"""Exercise the unmodified PR DLL in fakegame, using only a scratch window.

The window is hidden after its hook is installed, before any fullscreen command.
No actual game, account, player settings, or server is used.
"""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

repo = Path(__file__).resolve().parent.parent
temp = tempfile.TemporaryDirectory(prefix="wccf-projector-window-")
out = Path(temp.name)
shutil.copy2(repo / "source/build/fakegame.exe", out / "fakegame.exe")
u = c.WinDLL("user32", use_last_error=True)
u.GetWindowLongW.argtypes = [w.HWND, c.c_int]
u.GetWindowLongW.restype = w.LONG
u.SetWindowLongW.argtypes = [w.HWND, c.c_int, w.LONG]
u.SetWindowLongW.restype = w.LONG
u.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
u.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
u.ShowWindow.argtypes = [w.HWND, c.c_int]
u.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
u.SendMessageW.restype = c.c_ssize_t
u.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
u.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
u.MonitorFromWindow.restype = w.HANDLE
class MI(c.Structure):
    _fields_ = [("cbSize", w.DWORD), ("monitor", w.RECT), ("work", w.RECT), ("flags", w.DWORD)]
u.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(MI)]
callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
u.EnumWindows.argtypes = [callback_type, w.LPARAM]
checks = []

def check(label, actual, expected):
    checks.append({"label": label, "actual": actual, "expected": expected, "pass": actual == expected})

def rect(hwnd, client=False):
    r = w.RECT()
    (u.GetClientRect if client else u.GetWindowRect)(hwnd, c.byref(r))
    return [r.left, r.top, r.right, r.bottom]

def log_text():
    p = out / "wccfpanel_projector.log"
    return p.read_text(errors="replace") if p.exists() else ""

def await_log(needle, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if needle in log_text():
            return True
        time.sleep(.05)
    return False

env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("WCCF", "MXHOOK"))}
env.update(WCCFPANEL_ROLE="projector", WCCFPANEL_DRYKEYS="1", WCCF_LOGS=str(out))
with (out / "stdout.txt").open("w") as log:
    p = subprocess.Popen([str(out / "fakegame.exe"), str(repo / "programs/wccfpanel.dll"), "wait:60000"],
                         cwd=out, env=env, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        ready = await_log("mouse hooked on window")
        if not ready and any(s in log_text() for s in ("throwaway CreateDevice failed", "Direct3DCreate9 failed")):
            print("projector window input: skipped - no Direct3D 9 device here")
            sys.exit(0)
        assert ready, "projector hook unavailable: " + log_text()
        wins = []
        @callback_type
        def each(hwnd, _):
            pid = w.DWORD()
            u.GetWindowThreadProcessId(hwnd, c.byref(pid))
            if pid.value == p.pid:
                wins.append(hwnd)
            return True
        u.EnumWindows(each, 0)
        hwnd = max(wins, key=lambda h: (rect(h)[2] - rect(h)[0]) * (rect(h)[3] - rect(h)[1]))
        u.ShowWindow(hwnd, 0)
        # SetWindowPlacement deliberately clamps fully offscreen saved rectangles.
        # Test restore from an ordinary monitor position while keeping it hidden.
        u.SetWindowPos(hwnd, None, 70, 80, 0, 0, 0x15)
        initial = rect(hwnd)
        check("resizable frame", bool(u.GetWindowLongW(hwnd, -16) & 0x40000), True)
        # AdjustWindowRect with the actual style preserves the requested client area.
        r = w.RECT(0, 0, 640, 400)
        u.AdjustWindowRect(c.byref(r), u.GetWindowLongW(hwnd, -16), False)
        u.SetWindowPos(hwnd, None, 0, 0, r.right - r.left, r.bottom - r.top, 0x16)
        check("resize composition", await_log("own swap chain 640x400 "), True)
        normal = rect(hwnd)
        mi = MI(c.sizeof(MI))
        assert u.GetMonitorInfoW(u.MonitorFromWindow(hwnd, 2), c.byref(mi))
        monitor = [mi.monitor.left, mi.monitor.top, mi.monitor.right, mi.monitor.bottom]
        def key(vk, repeat=False):
            u.SendMessageW(hwnd, 0x100, vk, 1 | ((1 << 30) if repeat else 0))
            u.SendMessageW(hwnd, 0x101, vk, 1 | (1 << 30) | (1 << 31))
            time.sleep(.15)
        key(0x7A)
        check("F11 fills its monitor", rect(hwnd), monitor)
        key(0x7A, True)
        check("held F11 does not toggle", rect(hwnd), monitor)
        key(0x1B)
        check("Esc restores original placement", rect(hwnd), normal)
        key(0x7A)
        key(0x7A)
        check("F11 round trip", rect(hwnd), normal)
        time.sleep(u.GetDoubleClickTime() / 1000 + .1)
        for _ in range(2):
            u.SendMessageW(hwnd, 0x201, 1, (100 << 16) | 100)
            u.SendMessageW(hwnd, 0x202, 0, (100 << 16) | 100)
            time.sleep(.03)
        check("double click enters fullscreen", rect(hwnd), monitor)
        key(0x1B)
        check("double click then Esc round trip", rect(hwnd), normal)
        # Two distant clicks are not a Windows double click.
        time.sleep(u.GetDoubleClickTime() / 1000 + .1)
        for x, y in ((30, 30), (550, 350)):
            u.SendMessageW(hwnd, 0x201, 1, (y << 16) | x)
            u.SendMessageW(hwnd, 0x202, 0, (y << 16) | x)
            time.sleep(.03)
        check("distant clicks keep the window", rect(hwnd), normal)
        key(0x7A)
        time.sleep(u.GetDoubleClickTime() / 1000 + .1)
        for x, y in ((30, 30), (550, 350)):
            u.SendMessageW(hwnd, 0x201, 1, (y << 16) | x)
            u.SendMessageW(hwnd, 0x202, 0, (y << 16) | x)
            time.sleep(.03)
        check("distant clicks keep fullscreen", rect(hwnd), monitor)
        key(0x1B)
        u.SendMessageW(hwnd, 0x203, 1, (100 << 16) | 100)
        check("native double click enters fullscreen", rect(hwnd), monitor)
        key(0x1B)
        u.SendMessageW(hwnd, 0x201, 1, (100 << 16) | 100)
        u.SendMessageW(hwnd, 0x202, 0, (100 << 16) | 100)
        u.SendMessageW(hwnd, 8, 0, 0)  # WM_KILLFOCUS breaks a manual click pair
        u.SendMessageW(hwnd, 0x201, 1, (100 << 16) | 100)
        u.SendMessageW(hwnd, 0x202, 0, (100 << 16) | 100)
        check("focus loss breaks a click pair", rect(hwnd), normal)
        check("process remains healthy", p.poll(), None)
    finally:
        p.terminate()
        p.wait(timeout=10)
(out / "results.json").write_text(json.dumps(checks, indent=2))
for item in checks:
    print(("PASS" if item["pass"] else "FAIL") + " " + item["label"] +
          ("" if item["pass"] else " " + repr(item)))
print("projector window input: %d/%d checks passed" % (sum(x["pass"] for x in checks), len(checks)))
temp.cleanup()
sys.exit(any(not x["pass"] for x in checks))
