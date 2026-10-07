# -*- coding: utf-8 -*-
r"""sound_defaults.py - the game's starting volumes (the player, 2026-10-06: "the projector starts muted, and the normal game
starts with very low volume just like if i lowered it in volume mixer on windows ... but as a default").

Windows keeps a volume for each program that plays sound - the Volume Mixer's sliders.  _kit_helper.py calls apply()
for the projector and seat 1 once each, when each has first opened its sound after a start: the projector muted,
seat 1 at GAME_VOLUME.  Nothing is set again afterwards, so a change made in the Volume Mixer while playing stays.
Only these two programs are touched, found by their full path (the game folder's extracted\ and seat1\).

    python sound_defaults.py --list      every program's sound on this PC: process, volume, muted (changes nothing)

Windows' Core Audio calls (IMMDeviceEnumerator -> each active playback device -> IAudioSessionManager2 -> its sessions:
IAudioSessionControl2 for the process, ISimpleAudioVolume for the level and mute), through ctypes.
"""
import ctypes
import ctypes.wintypes as w
import os
import sys

GAME_VOLUME = 0.04              # seat 1 starts at 4%: "very low" - the player's own Volume Mixer had it at 4% (2026-10-06)
PROJECTOR_MUTED = True          # the projector starts muted (two windows of one game play the same sounds), at the
                                # same 4%, so unmuting it in the Volume Mixer is never a blast

_ole = ctypes.WinDLL("ole32")
_ole.CoInitializeEx.argtypes = [ctypes.c_void_p, w.DWORD]
_ole.CoInitializeEx.restype = ctypes.HRESULT
_ole.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]
_ole.CoCreateInstance.restype = ctypes.HRESULT
_ole.CLSIDFromString.argtypes = [w.LPCWSTR, ctypes.c_void_p]
_ole.CLSIDFromString.restype = ctypes.HRESULT


class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    g = GUID()
    _ole.CLSIDFromString(text, ctypes.byref(g))
    return g


CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioSessionManager2 = _guid("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
IID_IAudioSessionControl2 = _guid("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
IID_ISimpleAudioVolume = _guid("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")
CLSCTX_ALL, E_RENDER, DEVICE_STATE_ACTIVE = 23, 0, 1


def _method(obj, slot, *argtypes, restype=ctypes.HRESULT):
    """a COM object's method by its place in the object's table (a failing HRESULT raises OSError)"""
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[slot])


def _release(obj):
    if obj:
        _method(obj, 2, restype=ctypes.c_ulong)(obj)


def _query(obj, iid):
    out = ctypes.c_void_p()
    _method(obj, 0, ctypes.c_void_p, ctypes.c_void_p)(obj, ctypes.byref(iid), ctypes.byref(out))
    return out


def _each_session():
    """(process id, ISimpleAudioVolume) of every sound session on every active playback device; the caller releases
    each volume object.  COM is started on this thread if it is not yet."""
    try:
        _ole.CoInitializeEx(None, 0)                  # COINIT_MULTITHREADED; already started is fine
    except OSError:
        pass
    found, held = [], []
    enum = ctypes.c_void_p()
    _ole.CoCreateInstance(ctypes.byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                          ctypes.byref(IID_IMMDeviceEnumerator), ctypes.byref(enum))
    held.append(enum)
    try:
        devices = ctypes.c_void_p()
        _method(enum, 3, ctypes.c_int, w.DWORD, ctypes.c_void_p)(enum, E_RENDER, DEVICE_STATE_ACTIVE,
                                                                ctypes.byref(devices))   # EnumAudioEndpoints
        held.append(devices)
        n = w.UINT()
        _method(devices, 3, ctypes.c_void_p)(devices, ctypes.byref(n))                   # GetCount
        for i in range(n.value):
            dev, mgr, sessions = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
            _method(devices, 4, w.UINT, ctypes.c_void_p)(devices, i, ctypes.byref(dev))   # Item
            held.append(dev)
            _method(dev, 3, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.c_void_p)(
                dev, ctypes.byref(IID_IAudioSessionManager2), CLSCTX_ALL, None, ctypes.byref(mgr))   # Activate
            held.append(mgr)
            _method(mgr, 5, ctypes.c_void_p)(mgr, ctypes.byref(sessions))                # GetSessionEnumerator
            held.append(sessions)
            count = ctypes.c_int()
            _method(sessions, 3, ctypes.c_void_p)(sessions, ctypes.byref(count))         # GetCount
            for j in range(count.value):
                ctl = ctypes.c_void_p()
                try:                                  # one odd session is skipped, never the whole list
                    _method(sessions, 4, ctypes.c_int, ctypes.c_void_p)(sessions, j, ctypes.byref(ctl))   # GetSession
                    held.append(ctl)
                    ctl2 = _query(ctl, IID_IAudioSessionControl2)
                    held.append(ctl2)
                    pid = w.DWORD()
                    _method(ctl2, 14, ctypes.c_void_p)(ctl2, ctypes.byref(pid))          # GetProcessId
                    found.append((pid.value, _query(ctl, IID_ISimpleAudioVolume)))
                except OSError:
                    continue
    except BaseException:
        for _pid, vol in found:
            _release(vol)
        raise
    finally:
        for obj in reversed(held):
            _release(obj)
    return found


_k = ctypes.WinDLL("kernel32", use_last_error=True)
_k.OpenProcess.restype = w.HANDLE
_k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
_k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
_k.CloseHandle.argtypes = [w.HANDLE]


def exe_path(pid):
    """a process's program, full path ("" if it cannot be read)"""
    h = _k.OpenProcess(0x1000, False, pid) if pid else None          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(1024), w.DWORD(1024)
        return buf.value if _k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        _k.CloseHandle(h)


def sessions():
    """[(process id, its program's full path, volume 0-1, muted)] of every sound session on this PC - read only"""
    out = []
    for pid, vol in _each_session():
        try:
            level, muted = ctypes.c_float(), w.BOOL()
            _method(vol, 4, ctypes.c_void_p)(vol, ctypes.byref(level))                    # GetMasterVolume
            _method(vol, 6, ctypes.c_void_p)(vol, ctypes.byref(muted))                    # GetMute
            out.append((pid, exe_path(pid), round(level.value, 3), bool(muted.value)))
        finally:
            _release(vol)
    return out


def apply(pid, volume=None, mute=None):
    """every sound session of process pid: its volume (0-1) and / or mute set, as the Volume Mixer sets them.
    -> how many sessions were set (0: the process has no sound open yet)"""
    done = 0
    for p, vol in _each_session():
        try:
            if p == pid:
                if volume is not None:
                    _method(vol, 3, ctypes.c_float, ctypes.c_void_p)(vol, max(0.0, min(1.0, volume)), None)
                if mute is not None:
                    _method(vol, 5, w.BOOL, ctypes.c_void_p)(vol, bool(mute), None)
                done += 1
        finally:
            _release(vol)
    return done


def main(argv):
    if argv != ["--list"]:
        print(__doc__)
        return 2
    for pid, path, level, muted in sessions():
        print("  pid %-6d %3d%%%s  %s" % (pid, round(level * 100), "  MUTED" if muted else "",
                                          path or ("(system sounds)" if pid == 0 else "?")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
