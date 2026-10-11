# -*- coding: utf-8 -*-
r"""hook.py - rename the game's import of Windows' winmm.dll to the kit's own hook name, so the kit's
hook DLL is loaded under an HONEST name instead of sitting beside the game as a fake "winmm.dll". A file with a
Windows system name, placed next to a program so the program loads it instead of Windows' own and passing the calls
on, is exactly the DLL side-loading pattern Windows Defender flagged (Trojan:Win32/Posilod); an own-named DLL is not.

The game imports only three winmm functions (timeBeginPeriod/timeEndPeriod/timeGetTime), all by name, and "winmm"
appears exactly once in each exe - the import-table name string. So the whole change is a 9-byte overwrite of that
one string. The exes have no bound-import table and are unsigned, and Windows does not verify a user exe's PE
checksum, so nothing else needs touching (verified in .work\research\mxrename\DESIGN.md) - which also keeps the
change a PURE, perfectly reversible swap: rename wccfk.dll back to winmm.dll gives the exact original bytes, so SETUP
can re-run and fingerprint the exe either way.

Used by setup.py. Pure bytes in, bytes out - no files touched here, so it is easy to test.
"""
import struct

HOOK_DLL = b"wccfk.dll"          # the kit's hook under its own name (<= 9 chars: it replaces the import in place)
SYS_DLL = b"WINMM.dll"           # exactly as Sega's Rev D exes import it (uppercase WINMM) - so renaming back is
                                 # byte-exact. Detection is case-insensitive anyway (_import_name_offset).


class PatchError(Exception):
    pass


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
    """return `data` with its import of `frm` renamed to `to` (in place, same length or shorter). A pure byte swap: no
    other field changes, so renaming back is exact. Raises PatchError if `frm` is not imported, or `to` is longer."""
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
    return bytes(data)


def normalized(data):
    """`data` with the hook import renamed back to winmm.dll if it was renamed (else unchanged) - the Sega-original
    bytes, so a fingerprint is the same whether or not SETUP has applied the rename yet (idempotency)."""
    return rename_import(data, frm=HOOK_DLL, to=SYS_DLL) if imports_hook(data) else bytes(data)


def imports_hook(data):
    """True if `data` imports the kit's hook (already renamed)."""
    return _import_name_offset(data, HOOK_DLL) >= 0
