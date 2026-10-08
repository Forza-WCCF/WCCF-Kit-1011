# -*- coding: utf-8 -*-
"""kit_common.py - what setup.py and play.py share: the kit's folders, its settings file, the game folder's shape,
and which WCCF 2010-11 programs are running (found by their full path, so nothing else on the PC is touched)."""
import ctypes
import ctypes.wintypes as w
import hashlib
import json
import os

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(SCRIPTS)
BIN = os.path.join(KIT, "bin")
OVERLAY = os.path.join(KIT, "overlay")
DATA = os.path.join(KIT, "data")
LOGS = os.path.join(DATA, "logs")
SAVE = os.path.join(DATA, "save")
SETTINGS = os.path.join(DATA, "settings.json")
GAME_EXES = ("client_release.exe", "control_release.exe", "match_release.exe", "logowin.exe", "fpr_emu.exe")


def sha256(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return hashlib.sha256(path_or_bytes).hexdigest().upper()
    h = hashlib.sha256()
    with open(path_or_bytes, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest().upper()


def load_settings():
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    os.makedirs(DATA, exist_ok=True)
    with open(SETTINGS + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(SETTINGS + ".tmp", SETTINGS)


def find_game(path):
    """the sbwg "extracted" folder from a path to it or to the folder above it, else None"""
    if not path:
        return None
    path = os.path.abspath(path.strip().strip('"'))
    for p in (path, os.path.join(path, "extracted")):
        if all(os.path.isfile(os.path.join(p, n)) for n in ("client_Release.exe", "control_Release.exe",
                                                             "match_Release.exe")):
            return p
    return None


def seat_dir(game):
    return os.path.join(os.path.dirname(game), "seat1")


def misc_dir(game):
    return os.path.join(os.path.dirname(game), "misc")


def english_on():
    """True if ENGLISH.exe (english.py) has English in place: its list of Sega's backed-up files is not empty"""
    try:
        with open(os.path.join(DATA, "english_backup", "manifest.json"), encoding="utf-8") as f:
            return bool(json.load(f))
    except (OSError, ValueError):
        return False


# ---- the club card: is a session open? (2026-10-06) ------------------------------------------------------------
# The game marks a session open on the card itself: at START it writes USER_INJUSTICE_FLAG = 1 (and counts the
# session in USER_INJUSTICE_NUM if the last one never closed), and the locker-room save after each match writes 0.
# A cut in between (a crash, a stop) loses that match and costs a "bad ending" (penalties from 2).  Positions from
# the exe's own field tables (docs\research\CLUB-CARD-2010-11.md, .work\research\club_card\decode_club_card.py):
# copy A = blocks 8-112, copy B = blocks 113-217, each 0x68C bytes of MSB-first bits + a checksum the game reads.
CARD_BYTES = 16 + 256 * 16                       # the kit's card file: a 16-byte header + 256 blocks
_COPIES = (16 + 8 * 16, 16 + 8 * 16 + 0x690)     # where copy A and copy B start in the file
_PAYLOAD = 0x68C
_FLAG_BIT, _COUNT_BIT, _COUNT_BITS = 595, 596, 7   # USER_INJUSTICE_FLAG, USER_INJUSTICE_NUM


def _bits(buf, start, width):
    v = 0
    for k in range(width):
        i = start + k
        v = (v << 1) | ((buf[i >> 3] >> (7 - (i & 7))) & 1)
    return v


def card_session(card, since=None):
    """(state, bad endings) of a club card file, read as the game reads it (copy A if its checksum is good, else
    copy B).  state: "none" no file; "unreadable" wrong size or no good copy; "new" no club made yet; "open" the
    game marked a session open and wrote the card after `since` (a time: this run's start); "cut" marked open but
    not written since then (the last session never closed); "closed" the last save was a locker-room save.
    With since=None every mark counts as "open".  Bad endings is None when unknown."""
    try:
        with open(card, "rb") as f:
            raw = f.read(CARD_BYTES + 1)
        written = os.path.getmtime(card)
    except OSError:
        return "none", None
    if len(raw) != CARD_BYTES:
        return "unreadable", None
    if raw[5] | raw[6] << 8 == 0xFFFF:
        return "new", None
    copies = []
    for start in _COPIES:
        copy = raw[start:start + 0x690]
        total = sum(int.from_bytes(copy[i:i + 4], "little") for i in range(0, _PAYLOAD, 4)) & 0xFFFFFFFF
        copies.append((copy, total, int.from_bytes(copy[_PAYLOAD:_PAYLOAD + 4], "little")))
    if any(total == 0 and stored == 0 for _c, total, stored in copies):
        return "unreadable", None                  # the game refuses a card with an empty copy (error 0xA)
    for copy, total, stored in copies:
        if stored == total or stored == (total + 1) & 0xFFFFFFFF:
            bad = _bits(copy, _COUNT_BIT, _COUNT_BITS)
            if not _bits(copy, _FLAG_BIT, 1):
                return "closed", bad
            return ("open" if since is None or written > since else "cut"), bad
    return "unreadable", None


# ---- processes -----------------------------------------------------------------------------------------------
class _PE32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", w.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.CreateToolhelp32Snapshot.restype = w.HANDLE
_k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
_k.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(_PE32)]
_k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(_PE32)]
_k.OpenProcess.restype = w.HANDLE
_k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
_k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
_k.CloseHandle.argtypes = [w.HANDLE]


def processes():
    """[(pid, parent pid, exe name, full path or '')] of every process"""
    out = []
    snap = _k.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
    if not snap or snap == w.HANDLE(-1).value:
        return out
    e = _PE32()
    e.dwSize = ctypes.sizeof(e)
    ok = _k.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile, ""))
        ok = _k.Process32NextW(snap, ctypes.byref(e))
    _k.CloseHandle(snap)
    full = []
    for pid, ppid, name, _ in out:
        path = ""
        h = _k.OpenProcess(0x1000, False, pid)         # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            buf, n = ctypes.create_unicode_buffer(1024), w.DWORD(1024)
            if _k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                path = buf.value
            _k.CloseHandle(h)
        full.append((pid, ppid, name, path))
    return full


def game_processes(game):
    """the WCCF 2010-11 programs running from this game's folders (extracted, seat1, misc)"""
    root = os.path.normcase(os.path.dirname(os.path.abspath(game))) + os.sep
    return [p for p in processes() if p[2].lower() in GAME_EXES and os.path.normcase(p[3]).startswith(root)]


def kill(pid):
    h = _k.OpenProcess(0x0001, False, pid)              # PROCESS_TERMINATE
    if not h:
        return False
    ok = bool(_k.TerminateProcess(h, 1))
    _k.CloseHandle(h)
    return ok


# ---- what is listening, which pipes exist, a process's windows ------------------------------------------------
class _TcpRow(ctypes.Structure):
    _fields_ = [("state", w.DWORD), ("laddr", w.DWORD), ("lport", w.DWORD), ("raddr", w.DWORD), ("rport", w.DWORD)]


def listening_ports():
    """TCP ports something listens on (IPv4) - from Windows' own table, not netstat's translated text"""
    ip = ctypes.WinDLL("iphlpapi")
    for _ in range(5):
        size = w.DWORD(0)
        ip.GetTcpTable(None, ctypes.byref(size), False)
        buf = ctypes.create_string_buffer(size.value + 1024)
        size = w.DWORD(len(buf))
        if ip.GetTcpTable(buf, ctypes.byref(size), False) == 0:
            n = ctypes.c_uint32.from_buffer(buf).value
            rows = (_TcpRow * n).from_buffer(buf, 4)
            return {((r.lport & 0xFF) << 8) | ((r.lport >> 8) & 0xFF) for r in rows if r.state == 2}   # 2 = LISTEN
    return set()


def pipes():
    try:
        return {n.lower() for n in os.listdir("\\\\.\\pipe\\")}
    except OSError:
        return set()


_u = ctypes.WinDLL("user32")
_u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
_u.IsWindowVisible.argtypes = [w.HWND]
_u.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
_u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
_u.ShowWindowAsync.argtypes = [w.HWND, ctypes.c_int]


def windows_of(pid):
    """the visible top-level windows of a process"""
    found = []
    cb_t = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def cb(h, _lp):
        p = w.DWORD()
        _u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and _u.IsWindowVisible(h):
            found.append(h)
        return True
    _u.EnumWindows(cb_t(cb), 0)
    return found


def top_windows(pid):
    """[(window, class name, title, visible)] of every top-level window of a process (a console window counts as
    the program's that writes to it)"""
    found = []
    cb_t = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    def cb(h, _lp):
        p = w.DWORD()
        _u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid:
            c, t = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
            _u.GetClassNameW(h, c, 256)
            _u.GetWindowTextW(h, t, 256)
            found.append((h, c.value, t.value, bool(_u.IsWindowVisible(h))))
        return True
    _u.EnumWindows(cb_t(cb), 0)
    return found


SHOWN_CLASSES = ("#32770", "ConsoleWindowClass")     # a dialog, a console: what the server and the scripts open


def hide_windows(pid):
    """hide every visible top-level window of a process; -> their titles.  Asynchronous: it never waits for the
    program (a stuck one included), so the windows go a moment later"""
    out = []
    for h, _c, t, vis in top_windows(pid):
        if vis:
            _u.ShowWindowAsync(h, 0)                    # SW_HIDE
            out.append(t)
    return out


def show_windows(pid):
    """show a process's hidden dialog and console windows again, without taking the keyboard - never its other
    hidden windows (Windows' own helpers such as "Default IME"); -> their titles"""
    out = []
    for h, c, t, vis in top_windows(pid):
        if c in SHOWN_CLASSES and not vis:
            _u.ShowWindowAsync(h, 4)                    # SW_SHOWNOACTIVATE
            out.append(t)
    return out
