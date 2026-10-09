# -*- coding: utf-8 -*-
"""Launch a WCCF 2010-11 program UNDER A DEBUGGER (no admin, no WER, no cdb needed) with the shared
memory in place, and report crashes: address, registers, the crashing thread's start address, and
the return addresses on its stack, named from the Ghidra index.

    python _debug_launch.py [timeout_s=60] [client|control|match] [follow] [nomosuppl] [debugheap] [nomaps] [hide] [arg=X ...] [dir=FOLDER]

INVALID-PARAMETER STOPS (exit code 0xC0000417, added 2026-10-05): the game's runtime (MSVCR90.dll) ends the program
itself through _invoke_watson - no exception, so a debugger sees only the exit code. A breakpoint on _invoke_watson
(armed in every debugged process that loads msvcr90.dll) prints the stopping thread's callers, then lets it end as
before. Seat 1 ended this way on 2026-10-05 06:08 at a match start, with nothing else in its log.
nomaps: do not create or write the shared memory - for tests only, while a running stack uses it.
hide: the program starts with its windows hidden (STARTUPINFO SW_HIDE) - play.py gives it to the server unless
"debug" (2026-10-06): the server's console and its settings window, which a player never needs, and where a click
could stop the server (the console's text selection). "play.py show" shows them.

WINDOWS' THROTTLING OFF (added 2026-10-05): every debugged process (and its children) is told never to be slowed:
SetProcessInformation(ProcessPowerThrottling) opting out of timer coarsening and of efficiency mode. Windows 11
ignores timeBeginPeriod(1) for a program whose window is minimized or covered - the server's own window starts
minimized - so its Sleep(16)+Sleep(1) loop took ~31 ms instead of ~17, at the edge of the 33 ms the projector's
live-match feed needs, and the projector's matches stuttered (measured: the server's main thread woke 62/s throttled,
146/s with only the timer opt-out, reproduced twice).
While this debugger handles an event, Windows holds EVERY thread of the program (a game's video player alone starts
21 threads at once), so the debugger runs at high priority, unthrottled, and times each event: any that takes over
50 ms is printed, and the end prints count / mean / max per kind of event.

dir=FOLDER runs the program from another game folder (e.g. ../wccf1011-revd/sbwg/seat1, a player cabinet's
linked copy - 2026-10-04); its debug channel then goes to _dbg_<prog>_<folder name>.txt. The shared memory is
always built from the main folder's files (same content).

Why: this PC produces no WER crash reports and has no debugger installed. Python becomes the
debuggee's debugger (CreateProcess with a debug flag), pumps the Win32 debug loop, prints every
access violation and every fatal (second-chance) exception in detail.

follow: also debug every process the target starts (DEBUG_PROCESS) - e.g. control's four
match_Release.exe - and report how each one ends (exit code, or the crash in detail). Without it
(DEBUG_ONLY_THIS_PROCESS) children are only watched from outside: started / gone.

THE DEBUG HEAP IS SWITCHED OFF (_NO_DEBUG_HEAP=1, inherited by children) unless "debugheap" is given.
A process created under a debugger otherwise gets Windows' debug heap; on 2026-10-03 that made control
so slow it never reached the step where the bare run crashes (its hook log has no
wccf_match_connect0), and that was misread as "stable under the debugger".

Mappings: the 3 SBWG_*.moai from the disc files + SBWG_status byte[0]=1, and (unless "nomosuppl") the
REAL SBWG_moSuppl, built from the four AI/motion_data/*_table_moai.bin exactly as the launcher builds it
(see mosuppl_bytes). An existing mapping too small for its payload is reported, never overrun. A fault repeating at
one address (a frame loop) is shown twice and then only counted; the end prints the top counts.
arg=X appends X to the target's command line (repeatable). The debug channel goes to _dbg_<prog>.txt.
"""
import bisect
import csv
import ctypes
import ctypes.wintypes as w
import os
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.abspath(os.environ["WCCF_GAME"]) if os.environ.get("WCCF_GAME") else ""   # play.py sets WCCF_GAME: the game's "extracted" folder
GAMEID = "SBWG"
MOAI = [
    ("game_motion_data.moai",       os.path.join(GAME, "AI", "motion_data", "game_motion_data.moai")),
    ("management_motion_data.moai", os.path.join(GAME, "data", "motion", "launcherMotion", "management_motion_data.moai")),
    ("scene_motion_data.moai",      os.path.join(GAME, "data", "motion", "launcherMotion", "scene_motion_data.moai")),
]
PROGRAMS = {"client": "client_Release.exe", "control": "control_Release.exe", "match": "match_Release.exe"}
INDEXED = {"client_release.exe": "client", "control_release.exe": "control", "match_release.exe": "match",
           "launcher1011.exe": "launcher"}

# ---- the game's window: closing it ends the game (2026-10-08) ------------------------------------------------------
# The arcade program never quits when its window is closed: the window goes, the program runs on without it (seen
# 2026-10-08: seat 4's client_Release.exe ran on windowless, so its launcher - this - and the whole run with it
# stayed).  So for a client (a cabinet or the projector) this launcher ends the program once its window, up for
# WINDOW_SETTLE s, has been gone for two looks in a row; PLAY.exe's watcher then stops the rest of the run.  The
# panel (wccfpanel.dll) asks once before a close during a card session.  Never for control: its windows are hidden.
WINDOW_SETTLE = 5.0
_u = ctypes.windll.user32
_ENUM_PROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
_u.EnumWindows.argtypes = [_ENUM_PROC, w.LPARAM]
_u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
_u.IsWindowVisible.argtypes = [w.HWND]


def has_window(pid):
    """True if the process has a visible top-level window"""
    found = []

    def cb(h, _lp):
        owner = w.DWORD()
        _u.GetWindowThreadProcessId(h, ctypes.byref(owner))
        if owner.value == pid and _u.IsWindowVisible(h):
            found.append(h)
            return False                        # one is enough
        return True
    _u.EnumWindows(_ENUM_PROC(cb), 0)
    return bool(found)


# ---- shared-memory setup (same as _shm_provider.py) ----------------------
INVALID = w.HANDLE(-1).value
PAGE_READWRITE = 0x04
FILE_MAP_WRITE = 0x02
k = ctypes.windll.kernel32
k.CreateFileMappingW.restype = w.HANDLE
k.CreateFileMappingW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, w.DWORD, w.DWORD, w.LPCWSTR]
k.MapViewOfFile.restype = ctypes.c_void_p
k.MapViewOfFile.argtypes = [w.HANDLE, w.DWORD, w.DWORD, w.DWORD, ctypes.c_size_t]
k.UnmapViewOfFile.restype = w.BOOL
k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", w.DWORD),
                ("PartitionId", w.WORD), ("RegionSize", ctypes.c_size_t), ("State", w.DWORD), ("Protect", w.DWORD),
                ("Type", w.DWORD)]


k.VirtualQuery.argtypes = [ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
k.VirtualQuery.restype = ctypes.c_size_t
ERROR_ALREADY_EXISTS = 183

# SBWG_moSuppl, the motion-supplement tables (2026-10-04): Launcher1011.exe FUN_00401490 reads these four
# AI/motion_data files in THIS order (pointer table 0x0043c13c), and lays them out as four dword offsets
# (from the start of the block) followed by each file, padded to a multiple of 4. No size prefix.
# The minimal stand-in used before (four empty tables) booted the client, but every match engine crashed
# at the GAME phase in MotionActionTestStand's constructor (an empty table -> a null motion object).
MOSUPPL = ["game_motion_table_moai.bin", "game_actionsetup_table_moai.bin",
           "game_movepack_table_moai.bin", "game_request_table_moai.bin"]


def mosuppl_bytes():
    """SBWG_moSuppl exactly as the launcher builds it."""
    header, body, off = [], [], 16
    for name in MOSUPPL:
        data = open(os.path.join(GAME, "AI", "motion_data", name), "rb").read()
        pad = b"\x00" * ((-len(data)) & 3)
        header.append(off)
        body.append(data + pad)
        off += len(data) + len(pad)
    return struct.pack("<4I", *header) + b"".join(body)


def make(full, payload, total_size):
    h = k.CreateFileMappingW(INVALID, None, PAGE_READWRITE, 0, total_size, full)
    existed = ctypes.GetLastError() == ERROR_ALREADY_EXISTS
    if not h:
        print("  FAIL create %s err=%d" % (full, ctypes.GetLastError()))
        return None
    view = k.MapViewOfFile(h, FILE_MAP_WRITE, 0, 0, 0)
    if view and payload:
        mbi = MEMORY_BASIC_INFORMATION()
        k.VirtualQuery(view, ctypes.byref(mbi), ctypes.sizeof(mbi))
        if len(payload) > mbi.RegionSize:      # an older, smaller copy is still held by another process
            print("  !! %s already exists and is only %d bytes (need %d): NOT written - stop whatever holds it"
                  % (full, mbi.RegionSize, len(payload)))
            k.UnmapViewOfFile(view)
            return h
        ctypes.memmove(view, payload, len(payload))
    if view:
        k.UnmapViewOfFile(view)
    print("  %s %-34s size=%d" % ("opened" if existed else "made  ", full, total_size))
    return h


def make_all(with_mosuppl):
    handles = []
    for name, path in MOAI:
        data = open(path, "rb").read()
        handles.append(make("%s_%s" % (GAMEID, name), struct.pack("<I", len(data)) + data, len(data) + 4))
    handles.append(make("%s_status" % GAMEID, b"\x01", 64))
    if with_mosuppl:
        body = mosuppl_bytes()
        handles.append(make("%s_moSuppl" % GAMEID, body, len(body)))
    return handles


# ---- Win32 debug-loop structures (64-bit debugger, 32-bit debuggee) ------
DWORD, c_void_p, Structure, Union = w.DWORD, ctypes.c_void_p, ctypes.Structure, ctypes.Union


class EXCEPTION_RECORD(Structure):
    _fields_ = [("ExceptionCode", DWORD), ("ExceptionFlags", DWORD),
                ("ExceptionRecord", c_void_p), ("ExceptionAddress", c_void_p),
                ("NumberParameters", DWORD), ("ExceptionInformation", c_void_p * 15)]


class EXCEPTION_DEBUG_INFO(Structure):
    _fields_ = [("ExceptionRecord", EXCEPTION_RECORD), ("dwFirstChance", DWORD)]


class CREATE_THREAD_DEBUG_INFO(Structure):
    _fields_ = [("hThread", c_void_p), ("lpThreadLocalBase", c_void_p), ("lpStartAddress", c_void_p)]


class CREATE_PROCESS_DEBUG_INFO(Structure):
    _fields_ = [("hFile", c_void_p), ("hProcess", c_void_p), ("hThread", c_void_p),
                ("lpBaseOfImage", c_void_p), ("dwDebugInfoFileOffset", DWORD),
                ("nDebugInfoSize", DWORD), ("lpThreadLocalBase", c_void_p),
                ("lpStartAddress", c_void_p), ("lpImageName", c_void_p), ("fUnicode", ctypes.c_ushort)]


class EXIT_CODE_INFO(Structure):          # EXIT_THREAD_DEBUG_INFO and EXIT_PROCESS_DEBUG_INFO
    _fields_ = [("dwExitCode", DWORD)]


class LOAD_DLL_DEBUG_INFO(Structure):
    _fields_ = [("hFile", c_void_p), ("lpBaseOfDll", c_void_p),
                ("dwDebugInfoFileOffset", DWORD), ("nDebugInfoSize", DWORD), ("lpImageName", c_void_p),
                ("fUnicode", ctypes.c_ushort)]


class OUTPUT_DEBUG_STRING_INFO(Structure):
    _fields_ = [("lpDebugStringData", c_void_p), ("fUnicode", ctypes.c_ushort), ("nDebugStringLength", ctypes.c_ushort)]


class DEBUG_U(Union):
    _fields_ = [("Exception", EXCEPTION_DEBUG_INFO),
                ("CreateThread", CREATE_THREAD_DEBUG_INFO),
                ("CreateProcessInfo", CREATE_PROCESS_DEBUG_INFO),
                ("Exit", EXIT_CODE_INFO),
                ("LoadDll", LOAD_DLL_DEBUG_INFO),
                ("DebugString", OUTPUT_DEBUG_STRING_INFO),
                ("pad", ctypes.c_byte * 184)]


class DEBUG_EVENT(Structure):
    _fields_ = [("dwDebugEventCode", DWORD), ("dwProcessId", DWORD), ("dwThreadId", DWORD), ("u", DEBUG_U)]


class WOW64_FLOATING_SAVE_AREA(Structure):
    _fields_ = [("ControlWord", DWORD), ("StatusWord", DWORD), ("TagWord", DWORD), ("ErrorOffset", DWORD),
                ("ErrorSelector", DWORD), ("DataOffset", DWORD), ("DataSelector", DWORD),
                ("RegisterArea", ctypes.c_byte * 80), ("Cr0NpxState", DWORD)]


class WOW64_CONTEXT(Structure):
    _fields_ = [("ContextFlags", DWORD), ("Dr0", DWORD), ("Dr1", DWORD), ("Dr2", DWORD), ("Dr3", DWORD),
                ("Dr6", DWORD), ("Dr7", DWORD), ("FloatSave", WOW64_FLOATING_SAVE_AREA),
                ("SegGs", DWORD), ("SegFs", DWORD), ("SegEs", DWORD), ("SegDs", DWORD),
                ("Edi", DWORD), ("Esi", DWORD), ("Ebx", DWORD), ("Edx", DWORD), ("Ecx", DWORD), ("Eax", DWORD),
                ("Ebp", DWORD), ("Eip", DWORD), ("SegCs", DWORD), ("EFlags", DWORD), ("Esp", DWORD), ("SegSs", DWORD),
                ("ExtendedRegisters", ctypes.c_byte * 512)]


assert ctypes.sizeof(WOW64_CONTEXT) == 716, ctypes.sizeof(WOW64_CONTEXT)


class PROCESSENTRY32W(Structure):
    _fields_ = [("dwSize", DWORD), ("cntUsage", DWORD), ("th32ProcessID", DWORD), ("th32DefaultHeapID", c_void_p),
                ("th32ModuleID", DWORD), ("cntThreads", DWORD), ("th32ParentProcessID", DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", DWORD), ("szExeFile", ctypes.c_wchar * 260)]


EXCEPTION_DEBUG_EVENT, CREATE_THREAD_DEBUG_EVENT, CREATE_PROCESS_DEBUG_EVENT = 1, 2, 3
EXIT_THREAD_DEBUG_EVENT, EXIT_PROCESS_DEBUG_EVENT, LOAD_DLL_DEBUG_EVENT, OUTPUT_DEBUG_STRING_EVENT = 4, 5, 6, 8
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_ACCESS_VIOLATION = 0xC0000005
BREAKPOINTS = (0x80000003, 0x4000001F)          # native and WOW64 initial breakpoints
QUIET_CODES = (0x406D1388,)                      # MSVC thread naming
DEBUG_PROCESS, DEBUG_ONLY_THIS_PROCESS = 0x00000001, 0x00000002
WOW64_CONTEXT_FULL = 0x00010007

# ---- control's message-reassembly crash guard (2026-10-08) --------------------------------------------------------
# control_Release crashes while reassembling a per-connection message in FUN_00412860: it trusts a length/offset that
# came from the wire and was not bounds-checked, so a malformed / awkwardly-split message makes that function touch
# memory far outside its buffer and the one-thread server dies, taking every cabinet and the projector with it
# (Error 3000).  Seen four times on 2026-10-08: twice the READ `movq xmm0,[ecx+esi]` at control+0x129C2 (02:08, 03:17),
# and once a WRITE inside msvcr90 memcpy (~1 GB count) called from control+0x12A3D (14:30) - SAME root bug, different
# instruction.  So we do NOT guard one instruction (that was the 05:04 fix and it missed the memcpy path).  Instead,
# on ANY first-chance access violation we look for FUN_00412860's own return-into-its-caller on the stack
# (control+0x1226A, the instruction after the one call to FUN_00412860 in FUN_00412140) - if it is there, the fault
# happened while FUN_00412860 was running (directly or in a memcpy/CRT call it made), so we UNWIND the whole function:
# restore the four callee-saved regs it pushed, zero the remaining length (*param_1) and offset (*param_3) so control
# abandons the bad chunk, and resume at the caller with eax=1 (the "message consumed" return).  ASLR is off in control
# (ImageBase 0x400000).  Only this signature in control is ever touched; every other fault is left exactly as before.
# Off with WCCF_MSGGUARD=0.  Analysis: .work\research\control_crash\ANALYSIS.md.
MSGPARSE_RET_OFF = 0x1226A          # control+0x1226A: FUN_00412140's instruction right after it calls FUN_00412860
if os.environ.get("WCCF_MSGGUARD_RET"):  # TESTS ONLY (research\control_crash): a stand-in exe's own return offset
    MSGPARSE_RET_OFF = int(os.environ["WCCF_MSGGUARD_RET"], 16)
MSGPARSE_GUARD_ON = os.environ.get("WCCF_MSGGUARD", "1") != "0"
MSGPARSE_STACK_SCAN = 0x120         # bytes of stack to scan up from ESP for the return address
MSGPARSE_FRAME_SPAN = 0x90000       # FUN_00412140's frame holds a ~512 KB (0x80000) recv buffer: its &len/&off live here


def plan_412860_recovery(esp, read_fn, mod_base, mod_end, ret_off=MSGPARSE_RET_OFF):
    """Pure (no side effects): did this access violation happen while control's FUN_00412860 was on the stack, and if so
    how do we make that function return cleanly (drop the bad message)?  read_fn(addr, n) -> bytes|None reads the
    faulting process's memory.  Returns {regs, zero, retaddr, p_len, p_off, at} or None.  We scan the stack up from ESP
    for FUN_00412860's return-into-caller (mod_base+ret_off, default 0x1226A); at the slot A that holds it, FUN_00412860's
    prologue (push ebx/ebp/esi/edi) put the caller's saved regs just below - ebx=[A-4] ebp=[A-8] esi=[A-12] edi=[A-16] -
    and its 3 args just above - &len=[A+4] buf=[A+8] &off=[A+0xc].  A clean `ret 0xc` restores those regs, pops to the
    return address and drops the 3 args (esp -> A+0x10).  The arg pointers must point into the caller's frame (above A)
    or it is a stale value, not the live frame.  (ret_off is overridable only so the off-line test can point it at its
    own victim's return address.)"""
    ret140 = (mod_base + ret_off) & 0xFFFFFFFF
    stack = read_fn(esp, MSGPARSE_STACK_SCAN)
    if not stack or len(stack) < MSGPARSE_STACK_SCAN:
        return None
    for off in range(0x10, len(stack) - 0x10, 4):          # >=0x10: room for the 4 saved regs below the return slot
        if struct.unpack_from("<I", stack, off)[0] != ret140:
            continue
        a = (esp + off) & 0xFFFFFFFF                        # absolute address of the return-address slot
        edi, esi, ebp, ebx = struct.unpack_from("<4I", stack, off - 0x10)
        p_len, _buf, p_off = struct.unpack_from("<3I", stack, off + 4)
        if not (a < p_len <= a + MSGPARSE_FRAME_SPAN and a < p_off <= a + MSGPARSE_FRAME_SPAN):
            continue                                        # not the live frame's args - keep scanning
        return {"regs": {"Edi": edi, "Esi": esi, "Ebp": ebp, "Ebx": ebx, "Eip": ret140,
                         "Esp": (a + 0x10) & 0xFFFFFFFF, "Eax": 1},
                "zero": [p_len, p_off], "retaddr": ret140, "p_len": p_len, "p_off": p_off, "at": off}
    return None

k.WaitForDebugEvent.argtypes = [ctypes.c_void_p, DWORD]
k.WaitForDebugEvent.restype = w.BOOL
k.ContinueDebugEvent.argtypes = [DWORD, DWORD, DWORD]
k.ContinueDebugEvent.restype = w.BOOL
k.ReadProcessMemory.argtypes = [w.HANDLE, c_void_p, c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.ReadProcessMemory.restype = w.BOOL
k.Wow64GetThreadContext.argtypes = [w.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k.Wow64GetThreadContext.restype = w.BOOL
k.Wow64SetThreadContext.argtypes = [w.HANDLE, ctypes.POINTER(WOW64_CONTEXT)]
k.Wow64SetThreadContext.restype = w.BOOL
k.WriteProcessMemory.argtypes = [w.HANDLE, c_void_p, c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k.WriteProcessMemory.restype = w.BOOL
k.FlushInstructionCache.argtypes = [w.HANDLE, c_void_p, ctypes.c_size_t]
k.FlushInstructionCache.restype = w.BOOL
k.SetProcessInformation.argtypes = [w.HANDLE, ctypes.c_int, c_void_p, DWORD]
k.SetProcessInformation.restype = w.BOOL
k.GetCurrentProcess.restype = w.HANDLE
k.SetPriorityClass.argtypes = [w.HANDLE, DWORD]
k.SetPriorityClass.restype = w.BOOL
PROCESS_POWER_THROTTLING, THROTTLE_SPEED, THROTTLE_TIMER = 4, 0x1, 0x4
HIGH_PRIORITY_CLASS = 0x80
EVENT_NAMES = {1: "exception", 2: "thread start", 3: "process start", 4: "thread end", 5: "process end",
               6: "DLL load", 7: "DLL unload", 8: "debug text", 9: "RIP"}


class POWER_THROTTLING(Structure):
    _fields_ = [("Version", DWORD), ("ControlMask", DWORD), ("StateMask", DWORD)]


def full_speed(hproc):
    """Opt the process out of Windows' throttling (see the docstring); returns what was switched off, or None."""
    for mask, what in ((THROTTLE_SPEED | THROTTLE_TIMER, "timer and speed"), (THROTTLE_TIMER, "timer"),
                       (THROTTLE_SPEED, "speed only (this Windows has no timer opt-out)")):
        s = POWER_THROTTLING(1, mask, 0)
        if hproc and k.SetProcessInformation(hproc, PROCESS_POWER_THROTTLING, ctypes.byref(s), ctypes.sizeof(s)):
            return what
    return None
k.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, DWORD, DWORD]
k.GetFinalPathNameByHandleW.restype = DWORD
k.CloseHandle.argtypes = [w.HANDLE]
k.CreateToolhelp32Snapshot.argtypes = [DWORD, DWORD]
k.CreateToolhelp32Snapshot.restype = w.HANDLE
k.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]

class PROCESS_BASIC_INFORMATION(Structure):
    _fields_ = [("ExitStatus", ctypes.c_long), ("PebBaseAddress", c_void_p), ("AffinityMask", c_void_p),
                ("BasePriority", ctypes.c_long), ("UniqueProcessId", c_void_p), ("InheritedFromUniqueProcessId", c_void_p)]


ntdll = ctypes.windll.ntdll
ntdll.NtQueryInformationProcess.argtypes = [w.HANDLE, ctypes.c_ulong, c_void_p, ctypes.c_ulong,
                                            ctypes.POINTER(ctypes.c_ulong)]
ntdll.NtQueryInformationProcess.restype = ctypes.c_long

_INDEX_CACHE = {}


def load_index(prog):
    """Ghidra function index for one program: sorted starts, names, body sizes (cached)."""
    if prog in _INDEX_CACHE:
        return _INDEX_CACHE[prog]
    path = os.path.join(HERE, "ghidra_out_1011_classes", prog, "_index.csv")
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append((int(r["addr"], 16), r["full_name"], int(r["body_bytes"] or 0)))
    except OSError:
        print("  (no Ghidra index at %s - addresses will be unnamed)" % path)
    rows.sort()
    _INDEX_CACHE[prog] = ([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
    return _INDEX_CACHE[prog]


def children_of(pid):
    """{child pid: exe name} for processes whose parent is pid."""
    out = {}
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == INVALID:
        return out
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    ok = k.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        if pe.th32ParentProcessID == pid:
            out[pe.th32ProcessID] = pe.szExeFile
        ok = k.Process32NextW(snap, ctypes.byref(pe))
    k.CloseHandle(snap)
    return out


def path_of(handle):
    buf = ctypes.create_unicode_buffer(520)
    if handle and k.GetFinalPathNameByHandleW(handle, buf, 520, 0):
        return os.path.basename(buf.value)
    return None


def esc(b):
    """bytes -> ASCII for the log (it is not UTF-8): printable characters as they are, any other byte as \\xNN"""
    return "".join(chr(c) if 32 <= c < 127 and c != 92 else "\\x%02x" % c for c in b)


class Proc:
    """One debugged process: its memory handle, image, threads, DLLs and Ghidra index."""

    def __init__(self, pid, hproc, base, name):
        self.pid, self.hproc, self.base, self.name = pid, hproc, base, name
        self.end = base + 0x1000
        self.threads = {}          # tid -> (hThread, start address)
        self.dlls = []             # (base, end, name)
        self.watson = None         # (address, original byte) of MSVCR90!_invoke_watson while its breakpoint is armed
        prog = INDEXED.get(name.lower())
        self.index = load_index(prog) if prog else ([], [], [])

    def rd(self, addr, n):
        if not self.hproc or addr <= 0:
            return None
        buf = (ctypes.c_char * n)()
        got = ctypes.c_size_t()
        if k.ReadProcessMemory(self.hproc, ctypes.c_void_p(addr), buf, n, ctypes.byref(got)) and got.value:
            return buf.raw[:got.value]
        return None

    def wr(self, addr, data):
        got = ctypes.c_size_t()
        ok = k.WriteProcessMemory(self.hproc, ctypes.c_void_p(addr), data, len(data), ctypes.byref(got))
        k.FlushInstructionCache(self.hproc, ctypes.c_void_p(addr), len(data))
        return bool(ok) and got.value == len(data)

    def try_recover_412860(self, tid):
        """If thread tid faulted while control's FUN_00412860 was on the stack (the message reassembler - read OR a
        memcpy it makes), make that function return cleanly (drop the bad message) and return a short note; else None.
        Only for control_Release, and only when WCCF_MSGGUARD is on.  Every time it steps aside it says why in
        self.why (2026-10-08: it stepped aside twice on the live server and nothing said why)."""
        self.why = ""
        if not MSGPARSE_GUARD_ON or self.name.lower() != "control_release.exe":
            return None
        h = self.threads.get(tid, (None, 0))[0]
        if not h:
            self.why = "no handle for thread %d" % tid
            return None
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL
        if not k.Wow64GetThreadContext(h, ctypes.byref(ctx)):
            self.why = "could not read the thread's registers (err %d)" % ctypes.GetLastError()
            return None
        fault_eip = ctx.Eip
        plan = plan_412860_recovery(ctx.Esp, self.rd, self.base, self.end)
        if not plan:
            stack = self.rd(ctx.Esp, MSGPARSE_STACK_SCAN) or b""
            ret = (self.base + MSGPARSE_RET_OFF) & 0xFFFFFFFF
            dw = [struct.unpack_from("<I", stack, o)[0] for o in range(0, len(stack) - 3, 4)]
            hits = [i * 4 for i, v in enumerate(dw) if v == ret]
            self.why = "no plan: %d stack bytes at ESP 0x%08X; return 0x%08X at %s; stack: %s" % (
                len(stack), ctx.Esp, ret, ", ".join(
                    "+0x%X (then %s)" % (o, " ".join("%08X" % v for v in dw[o // 4 + 1:o // 4 + 4])) for o in hits[:3])
                or "nowhere", " ".join("%08X" % v for v in dw[:16]))
            return None
        for addr in plan["zero"]:                    # remaining length and offset -> 0: abandon the bad chunk
            if not self.wr(addr, b"\x00\x00\x00\x00"):
                self.why = "could not write 0x%08X (err %d)" % (addr, ctypes.GetLastError())
                return None
        for field, val in plan["regs"].items():
            setattr(ctx, field, val)
        if not k.Wow64SetThreadContext(h, ctypes.byref(ctx)):
            self.why = "could not set the thread's registers (err %d)" % ctypes.GetLastError()
            return None
        return "fault at 0x%08X (%s, frame +0x%X); len@0x%08X=0 off@0x%08X=0 -> return 1 to 0x%08X" % (
            fault_eip, self.name_of(fault_eip), plan["at"], plan["p_len"], plan["p_off"], plan["retaddr"])

    def export_va(self, base, want):
        """Address of the export called want in the 32-bit DLL at base, read from its memory (names are sorted, so a
        binary search); None if absent or unreadable."""
        hdr = self.rd(base, 0x400)
        if not hdr or hdr[:2] != b"MZ":
            return None
        lfa = struct.unpack_from("<I", hdr, 0x3C)[0]
        if lfa + 0x80 > len(hdr):
            return None
        ed = self.rd(base + struct.unpack_from("<I", hdr, lfa + 0x78)[0], 40)
        if not ed or len(ed) < 40:
            return None
        count, funcs, names, ords = struct.unpack_from("<IIII", ed, 0x18)
        key, lo, hi = want.encode(), 0, count - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            ptr = self.rd(base + names + 4 * mid, 4)
            name = self.rd(base + struct.unpack("<I", ptr)[0], 128) if ptr else None
            if not name:
                return None
            name = name.split(b"\0", 1)[0]
            if name == key:
                o = self.rd(base + ords + 2 * mid, 2)
                f = self.rd(base + funcs + 4 * struct.unpack("<H", o)[0], 4) if o else None
                return base + struct.unpack("<I", f)[0] if f else None
            lo, hi = (mid + 1, hi) if name < key else (lo, mid - 1)
        return None

    def arm_watson(self, base):
        """Breakpoint on MSVCR90!_invoke_watson. Returns a line for the log."""
        va = self.export_va(base, "_invoke_watson")
        old = self.rd(va, 1) if va else None
        if not old or not self.wr(va, b"\xcc"):
            return "NOT armed (_invoke_watson %s, error %d)" % ("at 0x%08X" % va if va else "not found",
                                                              ctypes.GetLastError())
        self.watson = (va, old)
        return "armed at 0x%08X" % va

    def unarm_watson(self, tid):
        """Original byte back, and the thread's EIP back onto it: _invoke_watson then runs as if never stopped."""
        va, old = self.watson
        self.watson = None
        self.wr(va, old)
        h = self.threads.get(tid, (None, 0))[0]
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL
        if h and k.Wow64GetThreadContext(h, ctypes.byref(ctx)) and ctx.Eip == va + 1:
            ctx.Eip = va
            k.Wow64SetThreadContext(h, ctypes.byref(ctx))

    def command_line(self):
        """The process's command line, from its native (64-bit) PEB; None if unreadable.
        At process creation the parameters may not be normalized yet: then Buffer is an offset."""
        pbi = PROCESS_BASIC_INFORMATION()
        got = ctypes.c_ulong()
        if ntdll.NtQueryInformationProcess(self.hproc, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(got)):
            return None
        raw = self.rd((pbi.PebBaseAddress or 0) + 0x20, 8)
        if not raw:
            return None
        pp = struct.unpack("<Q", raw)[0]
        flags = self.rd(pp + 0x08, 4)
        us = self.rd(pp + 0x70, 16)
        if not flags or not us:
            return None
        length, buf = struct.unpack_from("<H", us, 0)[0], struct.unpack_from("<Q", us, 8)[0]
        if not (struct.unpack("<I", flags)[0] & 1) and buf < pp:
            buf += pp
        data = self.rd(buf, length) if length else b""
        return data.decode("utf-16-le", "replace") if data is not None else None

    def image_end(self, base):
        hdr = self.rd(base, 0x400)
        if not hdr or hdr[:2] != b"MZ":
            return base + 0x1000
        lfa = struct.unpack_from("<I", hdr, 0x3C)[0]
        if lfa + 0x54 > len(hdr):
            return base + 0x1000
        return base + struct.unpack_from("<I", hdr, lfa + 0x50)[0]

    def name_of(self, va):
        starts, names, sizes = self.index
        if self.base <= va < self.end:
            i = bisect.bisect_right(starts, va) - 1
            if i >= 0:
                off = va - starts[i]
                return "%s+0x%X%s" % (names[i], off, "" if off < sizes[i] else " (?)")
            return "%s+0x%X" % (self.name, va - self.base)
        for base, end, nm in self.dlls:
            if base <= va < end:
                return "%s+0x%X" % (nm, va - base)
        return "?"

    def looks_like_return(self, va):
        """True if the bytes just before va are a CALL instruction."""
        b = self.rd(va - 7, 7)
        if not b or len(b) < 7:
            return False
        return (b[2] == 0xE8                                            # call rel32
                or (b[1] == 0xFF and (b[2] == 0x15 or (b[2] & 0xF8) == 0x90))   # call [abs] / [reg+disp32]
                or (b[3] == 0xFF and b[4] == 0x54)                      # call [esp+disp8]
                or (b[4] == 0xFF and (b[5] & 0xF8) == 0x50)             # call [reg+disp8]
                or (b[5] == 0xFF and ((b[6] & 0xF8) == 0xD0 or (b[6] & 0xF8) == 0x10)))  # call reg / [reg]

    def dump_thread(self, tid):
        h = self.threads.get(tid, (None, 0))
        if not h[0]:
            print("    (no handle for thread %d)" % tid)
            return
        print("    thread %d, started at 0x%08X = %s" % (tid, h[1], self.name_of(h[1])))
        ctx = WOW64_CONTEXT()
        ctx.ContextFlags = WOW64_CONTEXT_FULL
        if not k.Wow64GetThreadContext(h[0], ctypes.byref(ctx)):
            print("    (Wow64GetThreadContext failed err=%d)" % ctypes.GetLastError())
            return
        print("    EIP=%08X  %s" % (ctx.Eip, self.name_of(ctx.Eip)))
        print("    EAX=%08X EBX=%08X ECX=%08X EDX=%08X ESI=%08X EDI=%08X EBP=%08X ESP=%08X" % (
            ctx.Eax, ctx.Ebx, ctx.Ecx, ctx.Edx, ctx.Esi, ctx.Edi, ctx.Ebp, ctx.Esp))
        code = self.rd(ctx.Eip, 16)
        if code:
            print("    code at EIP: %s" % code.hex(" "))
        stack = self.rd_upto(ctx.Esp, 0x2000)
        shown = 0
        print("    return addresses on the stack (ESP+offset: address = function; a raw scan, so leftovers of earlier "
              "calls show too):")
        for off in range(0, len(stack) - 3, 4):
            v = struct.unpack_from("<I", stack, off)[0]
            if self.name_of(v) != "?" and self.looks_like_return(v):
                print("      +%03X: %08X = %s" % (off, v, self.name_of(v)))
                shown += 1
                if shown >= 80:
                    break
        try:
            self.dump_texts(stack, ctx)
        except Exception as ex:                          # the extra report must never stop the debugger
            print("    (text report failed: %r)" % (ex,))

    def rd_upto(self, addr, n):
        """Up to n bytes from addr, page by page, stopping at the first page that cannot be read (the stack's top):
        one read of the whole range would fail entirely there."""
        out = b""
        while len(out) < n:
            a = addr + len(out)
            want = min(n - len(out), 0x1000 - (a & 0xFFF))
            b = self.rd(a, want)
            if not b:
                break
            out += b
            if len(b) < want:
                break
        return out

    def text_at(self, va, n=200):
        """The NUL-ended text at va, or None when it does not look like text: under 3 bytes, a control character
        other than tab / CR / LF, or not valid Shift-JIS (cp932)."""
        if va < 0x10000:
            return None
        s = self.rd_upto(va, n).split(b"\0", 1)[0]
        if len(s) < 3 or any(c < 32 and c not in (9, 10, 13) for c in s):
            return None
        try:
            s.decode("cp932")
        except UnicodeDecodeError:
            return None
        return s

    def dump_texts(self, stack, ctx):
        """The texts the stack points to - in a stop inside vsprintf_s the format being parsed is one of them, marked *
        when it holds a % - and the bytes around EBX, which is the printf engine's read position in msvcr90
        9.0.30729 (seat 1's stops of 2026-10-05: the game's text drawer FUN_0040e170 uses each text AS A FORMAT)."""
        print("    texts the stack points to (ESP+offset: address -> text; * = it holds a %):")
        seen, shown = set(), 0
        for off in range(0, len(stack) - 3, 4):
            v = struct.unpack_from("<I", stack, off)[0]
            if v in seen:
                continue
            seen.add(v)
            s = self.text_at(v)
            if s:
                print("      +%03X: %08X -> %s\"%s\"" % (off, v, "*" if b"%" in s else " ", esc(s[:160])))
                shown += 1
                if shown >= 40:
                    break
        before, after = self.rd_upto(ctx.Ebx - 64, 64), self.rd_upto(ctx.Ebx, 48)
        if before or after:
            print("    bytes around EBX %08X: \"%s\" <EBX> \"%s\"" % (ctx.Ebx, esc(before), esc(after)))


def main(argv):
    if not GAME or not os.path.isfile(os.path.join(GAME, "client_Release.exe")):
        print("WCCF_GAME must be the game's extracted folder (play.py sets it)")
        return 2
    lower = [a.lower() for a in argv]
    timeout_s = int(argv[0]) if argv and argv[0].isdigit() else 60
    prog = next((p for p in PROGRAMS if p in lower), "client")
    exe = PROGRAMS[prog]
    extra = [a[4:] for a in argv if a.lower().startswith("arg=")]
    dirs = [a[4:] for a in argv if a.lower().startswith("dir=")]
    run_dir = os.path.abspath(os.path.join(HERE, dirs[-1])) if dirs else GAME
    if not os.path.isfile(os.path.join(run_dir, exe)):
        print("no %s in %s" % (exe, run_dir))
        return 2
    tag = "" if run_dir == GAME else "_" + os.path.basename(run_dir)
    follow = "follow" in lower
    with_mosuppl = "nomosuppl" not in lower      # the client crashes without one (2026-10-03); control does not read it
    with_maps = "nomaps" not in lower            # tests only: a running stack's shared memory is left alone
    env = dict(os.environ)
    if "debugheap" not in lower:
        env["_NO_DEBUG_HEAP"] = "1"
    print("%s; target=%s %s; debug heap %s; children %s:" % (
        "creating mappings (moSuppl=%s)" % with_mosuppl if with_maps else "NO mappings (nomaps)", exe, " ".join(extra),
        "ON" if "debugheap" in lower else "off", "DEBUGGED (follow)" if follow else "watched only"))
    handles = make_all(with_mosuppl) if with_maps else []
    me = k.GetCurrentProcess()                   # every event freezes the game until we answer: answer fast
    print("  this debugger: high priority %s, Windows' throttling off: %s" % (
        "yes" if k.SetPriorityClass(me, HIGH_PRIORITY_CLASS) else "NO", full_speed(me) or "NO"))

    si = None
    if "hide" in lower:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0                       # SW_HIDE
    p = subprocess.Popen([os.path.join(run_dir, exe)] + extra, cwd=run_dir, env=env,
                         creationflags=DEBUG_PROCESS if follow else DEBUG_ONLY_THIS_PROCESS, startupinfo=si)
    print("launched %s pid %d under debugger from %s; watching up to %ds%s" % (
        exe, p.pid, run_dir, timeout_s, "; its windows hidden" if si else ""))

    procs = {}             # pid -> Proc
    ended = []             # (name, pid, how) for processes that ended
    de = DEBUG_EVENT()
    t0 = time.time()
    seen_codes = {}
    seen_at = {}           # (process name, code, address) -> count
    dbg_path = os.path.join(os.environ.get("WCCF_LOGS") or HERE, "_dbg_%s%s.txt" % (prog, tag))
    # the server (control): one line, one write, so the file's time is control's last word (2026-10-07: through the
    # 8 KB buffer - about 25 minutes of control's output - a quiet file was misread as a frozen server).  The cabinets
    # keep the buffer: every debug event holds the game until it is answered.
    dbg_file = open(dbg_path, "w", encoding="utf-8", buffering=1 if prog == "control" else -1)
    dbg_lines = dbg_shown = 0
    kids = {}
    next_kid_check = 0.0
    fatal = False
    stops = 0              # invalid-parameter stops caught
    guarded = 0           # control message-reassembly OOB reads caught and recovered (MSGPARSE guard)
    ev_time = {}           # event kind -> [count, total ms, max ms]: how long each kind held the game
    watch_window = prog == "client"
    next_win_check, win_since, win_gone = 0.0, None, 0
    while time.time() - t0 < timeout_s:
        now = time.time() - t0
        if watch_window and now >= next_win_check:       # its window closed: the game ends (see has_window)
            next_win_check = now + 1.0
            if has_window(p.pid):
                win_since = now if win_since is None else win_since
                win_gone = 0
            elif win_since is not None and now - win_since >= WINDOW_SETTLE:
                win_gone += 1
                if win_gone >= 2:
                    print("  t+%5.1fs its window was closed - ending %s (the program never quits by itself)" % (
                        now, exe), flush=True)
                    break
            else:
                win_since = None                        # a window replaced while it starts: not a close
        if not follow and now >= next_kid_check:
            next_kid_check = now + 1.0
            cur = children_of(p.pid)
            for cpid, cname in cur.items():
                if cpid not in kids:
                    print("  t+%5.1fs child started: %s pid %d" % (now, cname, cpid))
            for cpid, cname in kids.items():
                if cpid not in cur:
                    print("  t+%5.1fs child gone: %s pid %d" % (now, cname, cpid))
            kids = cur
        if not k.WaitForDebugEvent(ctypes.byref(de), 250):
            continue
        t_ev = time.perf_counter()
        now = time.time() - t0
        code = de.dwDebugEventCode
        pid, tid = de.dwProcessId, de.dwThreadId
        pr = procs.get(pid)
        status = DBG_CONTINUE
        if code == CREATE_PROCESS_DEBUG_EVENT:
            ci = de.u.CreateProcessInfo
            name = path_of(ci.hFile) or ("pid%d" % pid)
            if ci.hFile:
                k.CloseHandle(ci.hFile)
            pr = procs[pid] = Proc(pid, ci.hProcess, ci.lpBaseOfImage or 0, name)
            pr.end = pr.image_end(pr.base)
            pr.threads[tid] = (ci.hThread, ci.lpStartAddress or 0)
            fast = full_speed(ci.hProcess)
            if pid == p.pid or not fast:
                print("  t+%5.1fs %sWindows' throttling off: %s" % (
                    now, "" if pid == p.pid else "[%s %d] " % (name, pid), fast or "FAILED (error %d)" %
                    ctypes.GetLastError()))
            if pid == p.pid:
                print("  image base = 0x%08X (to 0x%08X)" % (pr.base, pr.end))
                if pr.name.lower() == "control_release.exe":
                    mapped = pr.rd((pr.base + MSGPARSE_RET_OFF) & 0xFFFFFFFF, 1) is not None
                    print("  MSGPARSE guard: %s (any fault while FUN_00412860 is on the stack -> drop the message; "
                          "caller return 0x%08X; off with WCCF_MSGGUARD=0)" % (
                              ("ON" if MSGPARSE_GUARD_ON else "off (WCCF_MSGGUARD=0)") if mapped else
                              "NOT armed - control+0x%X is not mapped (different build?)" % MSGPARSE_RET_OFF,
                              (pr.base + MSGPARSE_RET_OFF) & 0xFFFFFFFF))
            else:
                print("  t+%5.1fs process started: %s pid %d (debugged)  command line: %s" % (
                    now, name, pid, pr.command_line()))
        elif pr is None:
            pass                                       # an event for a process we never saw start
        elif code == CREATE_THREAD_DEBUG_EVENT:
            pr.threads[tid] = (de.u.CreateThread.hThread, de.u.CreateThread.lpStartAddress or 0)
        elif code == EXIT_THREAD_DEBUG_EVENT:
            pr.threads.pop(tid, None)
        elif code == LOAD_DLL_DEBUG_EVENT:
            li = de.u.LoadDll
            base = li.lpBaseOfDll or 0
            nm = path_of(li.hFile) or ("dll@%08X" % base)
            if li.hFile:
                k.CloseHandle(li.hFile)
            pr.dlls.append((base, pr.image_end(base), nm))
            if nm.lower() == "msvcr90.dll":
                how = pr.arm_watson(base)
                if pid == p.pid or not pr.watson:
                    print("  t+%5.1fs %sinvalid-parameter catch (msvcr90.dll _invoke_watson) %s" % (
                        now, "" if pid == p.pid else "[%s %d] " % (pr.name, pid), how))
        elif code == OUTPUT_DEBUG_STRING_EVENT:
            ds = de.u.DebugString
            raw = pr.rd(ds.lpDebugStringData or 0, min(ds.nDebugStringLength, 1024)) or b""
            txt = raw.decode("utf-16-le" if ds.fUnicode else "cp932", "replace").rstrip("\x00\r\n")
            who = "" if pid == p.pid else "[%s %d] " % (pr.name, pid)
            dbg_file.write("t+%6.2fs %s%s\n" % (now, who, txt))
            dbg_lines += 1
            if not txt.startswith("inst(") and dbg_shown < 60:     # inst(0) = one team name each, hundreds
                print("  t+%5.1fs dbg> %s%s" % (now, who, txt))
                dbg_shown += 1
        elif code == EXCEPTION_DEBUG_EVENT:
            er = de.u.Exception.ExceptionRecord
            ec = er.ExceptionCode & 0xFFFFFFFF
            first = de.u.Exception.dwFirstChance
            addr = er.ExceptionAddress or 0
            if ec in BREAKPOINTS and pr.watson and addr in (pr.watson[0], pr.watson[0] + 1):
                stops += 1
                print("  t+%5.1fs %sSTOP: invalid parameter (msvcr90.dll _invoke_watson) - the program is ending itself "
                      "with 0xC0000417; the callers below passed the bad value  [thread %d]" % (
                          now, "" if pid == p.pid else "[%s %d] " % (pr.name, pid), tid))
                pr.dump_thread(tid)
                pr.unarm_watson(tid)
                status = DBG_CONTINUE
            elif ec in BREAKPOINTS and first:
                status = DBG_CONTINUE
            elif ec in QUIET_CODES:
                status = DBG_EXCEPTION_NOT_HANDLED
            elif ec == EXCEPTION_ACCESS_VIOLATION and first and pr.try_recover_412860(tid):
                # the known control message-reassembly OOB read: recovered (bad message dropped), control lives on
                guarded += 1
                status = DBG_CONTINUE
                note = "len/off zeroed, FUN_00412860 returns 1"
                if guarded <= 5 or guarded % 50 == 0:
                    print("  t+%5.1fs GUARD: control OOB message read at 0x%08X caught & dropped (#%d)  [thread %d]" % (
                        now, addr, guarded, tid))
                dbg_file.write("t+%6.2fs GUARD #%d recovered 0x%08X: %s\n" % (now, guarded, addr, note))
            else:
                status = DBG_EXCEPTION_NOT_HANDLED
                n = seen_codes.get(ec, 0) + 1
                seen_codes[ec] = n
                key = (pr.name, ec, addr)
                at_n = seen_at.get(key, 0) + 1          # the same fault in a loop: show twice, then count
                seen_at[key] = at_n
                if not first or (at_n <= 2 and (ec == EXCEPTION_ACCESS_VIOLATION or n <= 3)):
                    detail = ""
                    if ec == EXCEPTION_ACCESS_VIOLATION:
                        acc = er.ExceptionInformation[0] or 0
                        tgt = (er.ExceptionInformation[1] or 0) & 0xFFFFFFFF
                        detail = "  (%s of 0x%08X)" % ({0: "read", 1: "write", 8: "execute"}.get(acc, "access"), tgt)
                    print("  t+%5.1fs %s%s exception 0x%08X at 0x%08X = %s%s  [thread %d]" % (
                        now, "" if pid == p.pid else "[%s %d] " % (pr.name, pid),
                        "FIRST-chance" if first else "SECOND-chance / FATAL", ec, addr, pr.name_of(addr),
                        detail, tid))
                    if ec == EXCEPTION_ACCESS_VIOLATION or not first:
                        pr.dump_thread(tid)
                if ec == EXCEPTION_ACCESS_VIOLATION and first and getattr(pr, "why", ""):
                    print("  t+%5.1fs MSGPARSE guard stepped aside: %s" % (now, pr.why))
                    dbg_file.write("t+%6.2fs MSGPARSE guard stepped aside: %s\n" % (now, pr.why))
                if not first and pid == p.pid:
                    fatal = True
                    k.ContinueDebugEvent(pid, tid, status)
                    break
        elif code == EXIT_PROCESS_DEBUG_EVENT:
            how = "exit code 0x%08X" % (de.u.Exit.dwExitCode & 0xFFFFFFFF)
            if pid == p.pid:
                print("  t+%5.1fs process exited, %s" % (now, how))
                k.ContinueDebugEvent(pid, tid, status)
                break
            print("  t+%5.1fs process ended: %s pid %d, %s" % (now, pr.name, pid, how))
            ended.append((pr.name, pid, how))
            procs.pop(pid, None)
        held = (time.perf_counter() - t_ev) * 1000.0
        st = ev_time.setdefault(code, [0, 0.0, 0.0])
        st[0], st[1], st[2] = st[0] + 1, st[1] + held, max(st[2], held)
        if held > 50.0:
            print("  t+%5.1fs SLOW: a %s event held %s for %.0f ms" % (
                now, EVENT_NAMES.get(code, str(code)), pr.name if pr else "pid %d" % pid, held))
        k.ContinueDebugEvent(pid, tid, status)
    else:
        print("  timed out after %ds (no fatal crash); still running" % timeout_s)
    dbg_file.close()
    print("  debug channel: %d lines, all in %s" % (dbg_lines, dbg_path))
    if stops:
        print("  invalid-parameter stops caught: %d (callers printed above)" % stops)
    if guarded:
        print("  MSGPARSE guard: %d control OOB message read(s) caught & dropped - control kept running" % guarded)
    if ev_time:
        print("  time the game was held per debug event: " + ", ".join(
            "%s %d x mean %.2f ms max %.1f ms" % (EVENT_NAMES.get(c, str(c)), n, tot / n, mx)
            for c, (n, tot, mx) in sorted(ev_time.items())))
    if seen_codes:
        print("  exception counts: " + ", ".join("0x%08X x%d" % (c, n) for c, n in sorted(seen_codes.items())))
        for (nm, c, a), n in sorted(seen_at.items(), key=lambda kv: -kv[1])[:10]:
            owner = next((q for q in procs.values() if q.name == nm), None)
            print("    %s: 0x%08X at 0x%08X = %s  x%d" % (nm, c, a, owner.name_of(a) if owner else "?", n))
    if follow:
        print("  debugged children that ended: %s" % (", ".join("%s %d (%s)" % e for e in ended) or "none"))
        print("  still running at the end: %s" % (", ".join("%s %d" % (q.name, q.pid) for q in procs.values()
                                                         if q.pid != p.pid) or "none"))
    else:
        print("  children at the end: %s" % (", ".join("%s %d" % (v, c) for c, v in children_of(p.pid).items()) or "none"))
    try:
        p.kill()
    except Exception:
        pass
    _ = handles
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
