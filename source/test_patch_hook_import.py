# -*- coding: utf-8 -*-
"""test_patch_hook_import.py - renaming the game's winmm import to the kit's hook name (the Defender fix). Built on a
tiny synthetic PE (Sega's programs do not ship, so a real one cannot be in CI); the real programs are proved
separately on Ali's PC. check.ps1 runs it.
    python source\\test_patch_hook_import.py"""
import os
import struct
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import patch_hook_import as P  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


def make_pe(dll=b"winmm.dll"):
    """a minimal valid-enough PE32 that imports `dll` (one import descriptor), for the patcher to work on."""
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
    sec = opt + 0xE0                                   # the one section header
    b[sec:sec + 8] = b".idata\0\0"
    struct.pack_into("<I", b, sec + 8, 0x200)          # VirtualSize
    struct.pack_into("<I", b, sec + 12, 0x1000)        # VirtualAddress
    struct.pack_into("<I", b, sec + 16, 0x100)         # SizeOfRawData
    struct.pack_into("<I", b, sec + 20, 0x200)         # PointerToRawData
    # the import descriptors live at RVA 0x1000 = file 0x200; the dll name string just after them
    struct.pack_into("<I", b, 0x200 + 12, 0x1000 + 40)  # descriptor[0].Name = RVA of the string
    name_off = 0x200 + 40
    b[name_off:name_off + len(dll)] = dll
    # a fresh checksum so the "unchanged" round-trip is exact
    struct.pack_into("<I", b, opt + 64, P.pe_checksum(b))
    return bytes(b)


orig = make_pe(b"winmm.dll")

# the checksum we wrote reads back correct
struct_csum = struct.unpack_from("<I", orig, 0x80 + 24 + 64)[0]
check(P.pe_checksum(orig) == struct_csum, "pe_checksum is stable for an unchanged file")

# rename winmm.dll -> wccfk.dll
patched = P.rename_import(orig)
check(P._import_name_offset(patched, b"winmm.dll") < 0, "winmm is gone after the rename")
check(P._import_name_offset(patched, b"wccfk.dll") >= 0, "wccfk is the import now")
check(P.imports_hook(patched), "imports_hook sees the renamed import")
check(b"winmm" not in patched.lower(), "the bytes 'winmm' appear nowhere after the rename")
pc = struct.unpack_from("<I", patched, 0x80 + 24 + 64)[0]
check(P.pe_checksum(patched) == pc, "the checksum is correct after the rename")

# undo: wccfk.dll -> winmm.dll gives back the exact original (both names are 9 bytes)
back = P.rename_import(patched, frm=b"wccfk.dll", to=b"winmm.dll")
check(back == orig, "renaming back restores the exact original bytes")

# errors
try:
    P.rename_import(orig, to=b"toolongname.dll")
    check(False, "a too-long name must raise")
except P.PatchError:
    pass
try:
    P.rename_import(make_pe(b"other.dll"))
    check(False, "a program that does not import winmm must raise")
except P.PatchError:
    pass
try:
    P.rename_import(patched)                            # already renamed
    check(False, "an already-renamed program must raise")
except P.PatchError:
    pass

n = 11
print("patch_hook_import: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
