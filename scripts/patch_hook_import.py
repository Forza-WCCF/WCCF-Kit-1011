# -*- coding: utf-8 -*-
r"""patch_hook_import.py - rename the game's import of Windows' winmm.dll to the kit's own hook name, so the kit's
hook DLL is loaded under an HONEST name instead of sitting beside the game as a fake "winmm.dll". A file with a
Windows system name, placed next to a program so the program loads it instead of Windows' own and passing the calls
on, is exactly the DLL side-loading pattern Windows Defender flagged (Trojan:Win32/Posilod); an own-named DLL is not.

The game imports only three winmm functions (timeBeginPeriod/timeEndPeriod/timeGetTime), all by name, and "winmm"
appears exactly once in each exe - the import-table name string. So the whole change is a 9-byte overwrite of that
string, plus recomputing the PE checksum. The exes have no bound-import table and are unsigned, so nothing else
breaks (verified in .work\research\mxrename\DESIGN.md). Reversible: rename wccfk.dll back to winmm.dll.

Used by setup.py. Pure bytes in, bytes out - no files touched here, so it is easy to test.
"""
import struct

HOOK_DLL = b"wccfk.dll"          # the kit's hook under its own name (<= 9 chars: it replaces "winmm.dll" in place)
SYS_DLL = b"winmm.dll"


class PatchError(Exception):
    pass


def pe_checksum(data):
    """the PE OptionalHeader checksum of `data` (with the checksum field itself counted as 0), the standard algorithm:
    sum of 16-bit words folded to 16 bits, plus the file length."""
    if data[:2] != b"MZ":
        raise PatchError("not a PE file (no MZ)")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise PatchError("not a PE file (no PE signature)")
    csum = pe + 24 + 64             # OptionalHeader + 64 = the 4-byte CheckSum field
    total, n, i = 0, len(data), 0
    while i + 1 < n:
        if i == csum or i == csum + 2:          # the checksum field counts as 0
            i += 2
            continue
        total += data[i] | (data[i + 1] << 8)
        i += 2
    if n & 1:
        total += data[n - 1]
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (total + n) & 0xFFFFFFFF


def _import_name_offset(data, dll):
    """file offset of the import-descriptor name string equal to `dll` (case-insensitive), or -1."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    opt = pe + 24
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    sec0 = opt + struct.unpack_from("<H", data, pe + 20)[0]
    imp_rva = struct.unpack_from("<I", data, opt + 104)[0]      # data directory 1 = import table
    secs = [struct.unpack_from("<8sIIII", data, sec0 + 40 * i) for i in range(nsec)]

    def off(rva):
        for _, vsize, va, rsize, raw in secs:
            if va <= rva < va + max(vsize, rsize):
                return rva - va + raw
        return -1

    d = off(imp_rva)
    if d < 0:
        return -1
    while True:
        name_rva = struct.unpack_from("<I", data, d + 12)[0]
        if struct.unpack_from("<I", data, d)[0] == 0 and name_rva == 0:
            break
        if name_rva:
            s = off(name_rva)
            if s >= 0:
                end = data.index(b"\0", s)
                if data[s:end].lower() == dll.lower():
                    return s
        d += 20
    return -1


def rename_import(data, frm=SYS_DLL, to=HOOK_DLL):
    """return `data` with its import of `frm` renamed to `to` (in place, same length or shorter) and the PE checksum
    recomputed. Raises PatchError if `frm` is not imported, or `to` is longer than `frm`."""
    data = bytearray(data)
    if len(to) > len(frm):
        raise PatchError("the new name %r is longer than %r - cannot overwrite in place" % (to, frm))
    s = _import_name_offset(data, frm)
    if s < 0:
        if _import_name_offset(data, to) >= 0:
            raise PatchError("already renamed to %r" % to.decode())
        raise PatchError("this program does not import %r" % frm.decode())
    end = data.index(b"\0", s)
    data[s:end] = to + b"\0" * (len(frm) - len(to))     # overwrite the name, pad with NULs to the old length
    # recompute the checksum: zero the field, compute, write it back
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    csum = pe + 24 + 64
    struct.pack_into("<I", data, csum, 0)
    struct.pack_into("<I", data, csum, pe_checksum(data))
    return bytes(data)


def imports_hook(data):
    """True if `data` imports the kit's hook (already renamed)."""
    return _import_name_offset(data, HOOK_DLL) >= 0
