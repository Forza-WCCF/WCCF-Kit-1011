# -*- coding: utf-8 -*-
"""Switch off QuickEdit ("click selects text") in another program's console window.  While a console is in
selection mode, the program writing to it is FROZEN: on 2026-10-04 a click on the "WCCF control" window froze the
control server, and both screens fell to Error 3000.  With QuickEdit off, a click does nothing.

    python .work/_no_quickedit.py PID [PID ...]

Exit 0 = done for all.  Prints one line per process: the console input mode before and after.
"""
import ctypes
import ctypes.wintypes as w
import sys

k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateFileW.restype = w.HANDLE
k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
k.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
k.SetConsoleMode.argtypes = [w.HANDLE, w.DWORD]
k.CloseHandle.argtypes = [w.HANDLE]
k.AttachConsole.argtypes = [w.DWORD]
ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
INVALID = w.HANDLE(-1).value


def fix(pid):
    """-> (ok, message).  Runs while attached to that program's console."""
    if not k.AttachConsole(pid):
        return False, "cannot attach to its console (err %d) - it may have none" % ctypes.get_last_error()
    try:
        h = k.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        if not h or h == INVALID:
            return False, "no console input (err %d)" % ctypes.get_last_error()
        mode = w.DWORD()
        k.GetConsoleMode(h, ctypes.byref(mode))
        new = (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS
        ok = bool(k.SetConsoleMode(h, new))
        after = w.DWORD()
        k.GetConsoleMode(h, ctypes.byref(after))
        k.CloseHandle(h)
        return ok and not (after.value & ENABLE_QUICK_EDIT_MODE), "mode 0x%04X -> 0x%04X" % (mode.value, after.value)
    finally:
        k.FreeConsole()


def main(argv):
    if not argv or not all(a.isdigit() for a in argv):
        print("usage: python _no_quickedit.py PID [PID ...]")
        return 2
    results = []
    k.FreeConsole()                                    # a process can sit in one console at a time
    for a in argv:
        ok, msg = fix(int(a))
        results.append((a, ok, msg))
    k.AttachConsole(0xFFFFFFFF)                        # back to the console we were started from, to report
    out = open("CONOUT$", "w")
    for a, ok, msg in results:
        out.write("pid %s: %s (%s)\n" % (a, "QuickEdit OFF" if ok else "NOT changed", msg))
    out.close()
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
