# -*- coding: utf-8 -*-
"""test_patch_hook_import.py - renaming the game's winmm import to the kit's hook name (the Defender fix). Built on a
tiny synthetic PE (Sega's programs do not ship, so a real one cannot be in CI); the real programs are proved
separately on Ali's PC. check.ps1 runs it.
    python source\\test_patch_hook_import.py"""
import os
import struct
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import patch_hook_import as P  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


def make_pe(dll=b"WINMM.dll"):                          # Sega's Rev D exes import it as uppercase WINMM
    """a minimal PE32 that imports `dll` (one import descriptor), for the patcher to work on."""
    b = bytearray(0x300)
    b[0:2] = b"MZ"
    pe = 0x80
    struct.pack_into("<I", b, 0x3C, pe)
    b[pe:pe + 4] = b"PE\0\0"
    struct.pack_into("<H", b, pe + 4, 0x014C)          # Machine = i386
    struct.pack_into("<H", b, pe + 6, 1)               # NumberOfSections
    struct.pack_into("<H", b, pe + 20, 0xE0)           # SizeOfOptionalHeader (PE32)
    opt = pe + 24
    struct.pack_into("<H", b, opt, 0x10B)              # Magic = PE32
    struct.pack_into("<I", b, opt + 92, 16)            # NumberOfRvaAndSizes
    struct.pack_into("<I", b, opt + 104, 0x1000)       # DataDirectory[1] (import) VirtualAddress
    struct.pack_into("<I", b, opt + 108, 40)           # its Size
    sec = opt + 0xE0
    b[sec:sec + 8] = b".idata\0\0"
    struct.pack_into("<I", b, sec + 8, 0x200)          # VirtualSize
    struct.pack_into("<I", b, sec + 12, 0x1000)        # VirtualAddress
    struct.pack_into("<I", b, sec + 16, 0x100)         # SizeOfRawData
    struct.pack_into("<I", b, sec + 20, 0x200)         # PointerToRawData
    struct.pack_into("<I", b, 0x200 + 12, 0x1000 + 40)  # descriptor[0].Name = RVA of the string
    name_off = 0x200 + 40
    b[name_off:name_off + len(dll)] = dll
    return bytes(b)


orig = make_pe(b"WINMM.dll")

# rename WINMM.dll -> wccfk.dll (a pure byte swap, same length)
patched = P.rename_import(orig)
check(len(patched) == len(orig), "the rename does not change the file length")
check(P._import_name_offset(patched, b"winmm.dll") < 0, "winmm is gone after the rename")
check(P._import_name_offset(patched, b"wccfk.dll") >= 0, "wccfk is the import now")
check(P.imports_hook(patched), "imports_hook sees the renamed import")
check(b"winmm" not in patched.lower(), "the bytes 'winmm' appear nowhere after the rename")
# only the 9 name bytes changed, nothing else
check(sum(a != b for a, b in zip(orig, patched)) <= 9, "at most the 9 name bytes changed")

# renaming back gives the EXACT original (a pure swap is perfectly reversible)
check(P.rename_import(patched, frm=b"wccfk.dll", to=b"WINMM.dll") == orig, "renaming back restores the exact original")

# normalized(): the Sega bytes whether or not the rename was applied (idempotency for SETUP's fingerprints)
check(P.normalized(orig) == orig, "normalized leaves an un-renamed file alone")
check(P.normalized(patched) == orig, "normalized un-renames a patched file back to the original")

# errors
for bad, why in [(lambda: P.rename_import(orig, to=b"toolongname.dll"), "a too-long name must raise"),
                 (lambda: P.rename_import(make_pe(b"other.dll")), "a program not importing winmm must raise"),
                 (lambda: P.rename_import(patched), "an already-renamed program must raise")]:
    try:
        bad()
        check(False, why)
    except P.PatchError:
        pass

n = 12
print("patch_hook_import: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
