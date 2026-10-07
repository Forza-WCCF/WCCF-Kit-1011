# -*- coding: utf-8 -*-
"""Stand-in for the launcher's scene service, xscnWatch (WCCF 2010-11): loads scene files on request.

    python .work/_xscn_watch.py SECONDS [LOGFILE]

What the real one does (Launcher1011.exe, read 2026-10-04): xscnWatch::Watcher owns the mutex
"xscnWatch::Mutex" and a 0x5CC-byte board "xscnWatch::ComBuf" (FUN_00403680, initialised by FUN_00403640):
    dword 0   request counter (a requester adds 1 after filling a slot)
    dword 1   16 = number of request slots
    dword 2   32 = number of scene entries
    +0x0C     16 request slots x 12 bytes: {type, pid, scene number}   (type 1 = load)
    +0xCC     32 scene entries x 40 bytes: {scene number, state, 8 more dwords}   (state 2 = ready)
A requester (match_Release FUN_005bfb10 / FUN_005bf990) takes the mutex (waits 0x21 ms), looks for its scene
in the entries; if absent it fills a free slot and adds 1 to the counter; once the entry's state is 2 it opens
the mapping "%06ld.xscn" = [4-byte size][the file]. The watcher (FUN_00403870), whenever the counter changed,
handles every filled slot and clears it, then rewrites the whole entry table. Files: data/motion/launcherMotion/
xscn/<number>_<name>.xscn (FUN_00404d50 maps number -> name; FUN_00408140 makes the mapping).

This stand-in reads requests under the mutex, loads OUTSIDE it (some files are 20-37 MB; requesters give up on
the mutex after 33 ms), marks a scene ready (state 2) on the next pass, keeps every scene loaded until it stops,
and logs each request (repeats of one scene in one pass are summed). Requests of other types are logged and the
scene stays loaded.

It WAITS UP TO 250 ms FOR THE MUTEX (the launcher waits 4 ms). Found 2026-10-04: a requester that finds its scene
not ready Sleep(16)s BEFORE releasing the mutex (FUN_005bfb10), so four match engines keep it held almost all the
time and a 4 ms wait starved: 16 requests for scene 471 sat unanswered for ~100 s until a longer wait got in.

A board left open by requesters (they reopen it every pass) is ADOPTED, not refused. It refuses only if
Launcher1011.exe is running or another copy of this stand-in is (marker mutex WCCF::xscnWatchStandIn).
Exit 0 = ran its time, 2 = refused.
"""
import ctypes
import ctypes.wintypes as w
import os
import re
import struct
import sys
import time

GAME = os.path.abspath(os.environ["WCCF_GAME"]) if os.environ.get("WCCF_GAME") else ""   # play.py sets WCCF_GAME: the game's "extracted" folder
XSCN_DIR = os.path.join(GAME, "data", "motion", "launcherMotion", "xscn")
BOARD_SIZE, SLOTS, ENTRIES = 0x5CC, 16, 32
SLOT_AT, ENTRY_AT, ENTRY_SIZE = 0x0C, 0xCC, 40
READY = 2

k = ctypes.windll.kernel32
INVALID = w.HANDLE(-1).value
k.CreateMutexW.restype = w.HANDLE
k.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
k.CreateFileMappingW.restype = w.HANDLE
k.CreateFileMappingW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR]
k.MapViewOfFile.restype = ctypes.c_void_p
k.MapViewOfFile.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_size_t]
k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
k.WaitForSingleObject.restype = w.DWORD
k.ReleaseMutex.argtypes = [w.HANDLE]
k.CloseHandle.argtypes = [w.HANDLE]
ERROR_ALREADY_EXISTS, PAGE_READWRITE, FILE_MAP_ALL_ACCESS = 183, 0x04, 0xF001F
WAIT_OBJECT_0, WAIT_ABANDONED = 0, 0x80


def scene_index():
    """{scene number: file path} from the leading digits of each file name."""
    out = {}
    for name in sorted(os.listdir(XSCN_DIR)):
        m = re.match(r"(\d+)", name)
        if m and name.lower().endswith(".xscn"):
            out[int(m.group(1))] = os.path.join(XSCN_DIR, name)
    return out


def launcher_running():
    out = os.popen('tasklist /FI "IMAGENAME eq Launcher1011.exe" /NH').read()
    return "Launcher1011.exe" in out


class Board:
    """The 0x5CC-byte xscnWatch::ComBuf, read and written as dwords through a mapped view."""

    def __init__(self, view):
        self.view = view

    def get(self, off):
        return ctypes.c_uint32.from_address(self.view + off).value

    def put(self, off, value):
        ctypes.c_uint32.from_address(self.view + off).value = value & 0xFFFFFFFF


def main(argv):
    if not argv or not argv[0].isdigit():
        print(__doc__)
        return 2
    seconds = int(argv[0])
    logf = open(argv[1], "a", encoding="utf-8") if len(argv) > 1 else None
    t0 = time.time()

    def log(msg):
        line = "%7.2f  %s" % (time.time() - t0, msg)
        print(line, flush=True)
        if logf:
            logf.write(line + "\n")
            logf.flush()

    if not GAME or not os.path.isdir(XSCN_DIR):
        log("REFUSED: WCCF_GAME must be the game's extracted folder (play.py sets it)")
        return 2
    index = scene_index()
    log("xscnWatch stand-in: %d scenes in %s (%s), for %d s" % (
        len(index), XSCN_DIR, ", ".join(str(n) for n in sorted(index)), seconds))
    if launcher_running():
        log("REFUSED: Launcher1011.exe is running - it serves the scenes itself")
        return 2
    marker = k.CreateMutexW(None, False, "WCCF::xscnWatchStandIn")
    if not marker or ctypes.GetLastError() == ERROR_ALREADY_EXISTS:
        log("REFUSED: another copy of this stand-in is running")
        return 2
    mutex = k.CreateMutexW(None, False, "xscnWatch::Mutex")
    hboard = k.CreateFileMappingW(INVALID, None, PAGE_READWRITE, 0, BOARD_SIZE, "xscnWatch::ComBuf")
    adopted = ctypes.GetLastError() == ERROR_ALREADY_EXISTS
    if not mutex or not hboard:
        log("could not create the mutex or the board (err %d)" % ctypes.GetLastError())
        return 2
    view = k.MapViewOfFile(hboard, FILE_MAP_ALL_ACCESS, 0, 0, 0)
    board = Board(view)
    if k.WaitForSingleObject(mutex, 5000) not in (WAIT_OBJECT_0, WAIT_ABANDONED):
        log("could not take xscnWatch::Mutex within 5 s - something holds it")
        return 2
    counter_was = board.get(0) if adopted else 0
    if not adopted:
        ctypes.memset(view, 0, BOARD_SIZE)
    else:
        ctypes.memset(view + ENTRY_AT, 0, ENTRIES * ENTRY_SIZE)   # stale entries: requesters will ask again
    board.put(4, SLOTS)
    board.put(8, ENTRIES)
    k.ReleaseMutex(mutex)
    log("board ready (%s): xscnWatch::Mutex + xscnWatch::ComBuf (0x5CC) = [counter %d, 16 slots, 32 entries]" % (
        "ADOPTED - requesters had it open" if adopted else "new", counter_was))

    loaded = {}          # scene -> mapping handle (kept open = scene stays available)
    pending = []         # (type, pid, scene) read from the slots, handled outside the mutex
    last_counter = None  # None: read the slots on the first pass whatever the counter says
    while time.time() - t0 < seconds:
        r = k.WaitForSingleObject(mutex, 250)
        if r in (WAIT_OBJECT_0, WAIT_ABANDONED):
            try:
                counter = board.get(0)
                if counter != last_counter:
                    last_counter = counter
                    for i in range(SLOTS):
                        off = SLOT_AT + 12 * i
                        typ, pid, scene = board.get(off), board.get(off + 4), board.get(off + 8)
                        if typ and pid and 0 < scene < 0x80000000:
                            pending.append((typ, pid, scene))
                        board.put(off, 0)
                        board.put(off + 4, 0)
                        board.put(off + 8, 0)
                ctypes.memset(view + ENTRY_AT, 0, ENTRIES * ENTRY_SIZE)
                for i, scene in enumerate(sorted(loaded)[:ENTRIES]):
                    board.put(ENTRY_AT + ENTRY_SIZE * i, scene)
                    board.put(ENTRY_AT + ENTRY_SIZE * i + 4, READY)
            finally:
                k.ReleaseMutex(mutex)
        repeats = {}
        while pending:
            typ, pid, scene = pending.pop(0)
            if typ != 1:
                log("request type %d for scene %d from pid %d - logged only (scene stays loaded)" % (typ, scene, pid))
                continue
            if scene in loaded:
                n, pids = repeats.get(scene, (0, set()))
                repeats[scene] = (n + 1, pids | {pid})
                continue
            path = index.get(scene)
            if not path:
                log("scene %d asked by pid %d - NO FILE for it in xscn/ (not served)" % (scene, pid))
                continue
            data = open(path, "rb").read()
            name = "%06d.xscn" % scene
            h = k.CreateFileMappingW(INVALID, None, PAGE_READWRITE, 0, len(data) + 4, name)
            v = k.MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, 0) if h else None
            if not v:
                log("scene %d: could not make mapping %s (err %d)" % (scene, name, ctypes.GetLastError()))
                continue
            ctypes.memmove(v, struct.pack("<I", len(data)) + data, len(data) + 4)
            k.UnmapViewOfFile(v)
            loaded[scene] = h
            log("scene %d loaded for pid %d: %s, %d bytes -> mapping %s, marked ready" % (
                scene, pid, os.path.basename(path), len(data), name))
        for scene, (n, pids) in repeats.items():
            log("scene %d asked again %d time(s) by pid %s - already loaded" % (
                scene, n, ", ".join(str(p) for p in sorted(pids))))
        time.sleep(0.005)
    log("stopping after %d s; %d scene(s) were loaded: %s" % (seconds, len(loaded), sorted(loaded)))
    for h in loaded.values():
        k.CloseHandle(h)
    k.UnmapViewOfFile(view)
    k.CloseHandle(hboard)
    k.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
