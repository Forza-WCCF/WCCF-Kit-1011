# -*- coding: utf-8 -*-
"""test_english_pictures.py - English writing in the game's pictures (check.ps1 runs it; no game, nothing live): a
scratch archive with one picture gets the English added at its end and its entry pointed at it; "on" twice gives the
same file; "off" gives back Sega's archive byte for byte, also after an "on" stopped before the entries were written.
    python source\\test_english_pictures.py"""
import io
import os
import shutil
import struct
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import english as E  # noqa: E402
import kit_common as K  # noqa: E402
from PIL import Image  # noqa: E402

scratch = tempfile.mkdtemp(prefix="wccf_pictures_")
E.BACK = os.path.join(scratch, "english_backup")             # never the kit's own data\english_backup
E.XAF_STATE = os.path.join(E.BACK, "wccf_data.xaf.json")
game = os.path.join(scratch, "game")
os.makedirs(os.path.join(game, "data"))
xaf = os.path.join(game, "data", "wccf_data.xaf")

pic = Image.new("RGBA", (16, 16), (0, 0, 0, 0))     # small: the picture fits in one sector
pic.paste((255, 255, 255, 255), (2, 2, 14, 14))               # "Sega's writing": a white block
sega_dds = E.dds_argb(pic)
entry = bytearray(E.ENTRY)                                    # one file, uncompressed, in sector 1
entry[:7] = b"pic.dds"
entry[0x80] = 1
struct.pack_into("<i", entry, 0x84, -1)
struct.pack_into("<III", entry, 0x94, len(sega_dds), len(sega_dds), 0)
struct.pack_into("<I", entry, 0xA0, 1)
hdr = bytearray(E.TOC_AT)
struct.pack_into("<4s3I", hdr, 0, b"xaf0", 2, E.SECTOR, 1)
struct.pack_into("<3Q", hdr, 0x18, 2, 1, 1)
sega = bytes(hdr + entry).ljust(E.SECTOR, b"\0") + sega_dds.ljust(E.SECTOR, b"\0")
with open(xaf, "wb") as f:
    f.write(sega)


def archive():
    with open(xaf, "rb") as f:
        return f.read()


E.sheet = lambda name: [{"sega_sha256": E.sha(sega_dds), "style": "white", "labels": "0,0,15,15=OK",
                         "files": "pic.dds"}]
pics, note = E.build_pictures(game)
assert pics, note
E.pictures_on(game, pics)
on = archive()
assert len(on) == 3 * E.SECTOR and on[:E.SECTOR * 2] != sega[:E.SECTOR * 2], "the picture is added at the end"
assert on[E.SECTOR:E.SECTOR * 2] == sega[E.SECTOR:E.SECTOR * 2], "Sega's picture is never written over"
assert struct.unpack_from("<Q", on, 0x18)[0] == 3, "the header's sector count grows"
e = on[E.TOC_AT:E.TOC_AT + E.ENTRY]
assert e[0x81] == 0 and struct.unpack_from("<I", e, 0xA0)[0] == 2, "the entry points at the added picture"
new = Image.open(io.BytesIO(on[2 * E.SECTOR:2 * E.SECTOR + len(sega_dds)])).convert("RGBA")
assert new.size == (16, 16) and new.tobytes() != pic.tobytes(), "Sega's writing is replaced"
assert new.getchannel("A").getbbox() is not None, "the English is drawn"

E.pictures_on(game, E.build_pictures(game)[0])                 # "on" again builds from Sega's picture, not stacked
assert archive() == on, "on twice gives the same archive"

assert E.pictures_off(game) == 1 and archive() == sega, "off gives back Sega's archive byte for byte"
assert not os.path.exists(E.XAF_STATE)

E.pictures_on(game, pics)                                     # stopped half way: state saved, entries not written
with open(xaf, "r+b") as f:
    f.seek(E.TOC_AT)
    f.write(entry)
    f.seek(0x18)
    f.write(struct.pack("<Q", 2))
assert E.pictures_off(game) == 1 and archive() == sega, "off after an interrupted on gives back Sega's archive"

# --- the "memory" pictures (2026-10-15): redrawn into a folder for the hook; the archive is never touched ---------
assert E.fnv64(b"") == 0xCBF29CE484222325 and E.fnv64(b"a") == 0xAF63DC4C8601EC8C, \
    "the fingerprint is FNV-1a 64 (its published values - test_pictures.c checks the hook's against the same)"


def dxt5_header(w, h):
    return struct.pack("<4s7I44x8I5I", b"DDS ", 124, 0x81007, h, w, w * h, 0, 0, 32, 0x4,
                       int.from_bytes(b"DXT5", "little"), 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)


src = Image.new("RGBA", (16, 8), (0, 0, 0, 0))                # writing: one colour, every strength of alpha
for x in range(16):
    for y in range(8):
        src.putpixel((x, y), (216, 225, 216, (x * 16 + y * 3) % 256))
enc = E.dxt5(src, dxt5_header(16, 8))
back = Image.open(io.BytesIO(enc)).convert("RGBA")
assert len(enc) == 128 + 16 * 8 and back.size == (16, 8), "DXT5: one byte a pixel after the 128-byte header"
assert max(abs(a - b) for a, b in zip(src.getchannel("A").getdata(), back.getchannel("A").getdata())) <= 20, \
    "DXT5: every pixel's strength within one of the block's 8 steps"
assert all(abs(c - d) <= 8 for p, q in zip(src.getdata(), back.getdata()) if p[3] for c, d in zip(p[:3], q[:3])), \
    "DXT5: the writing keeps its colour"

wait = Image.new("RGBA", (32, 32), (0, 0, 0, 0))              # "Sega's" wait picture: two lines of writing
wait.paste((216, 225, 216, 255), (1, 1, 20, 6))
wait.paste((216, 225, 216, 255), (1, 9, 20, 14))
sega_wait = E.dxt5(wait, dxt5_header(32, 32))
entry2 = bytearray(entry)
entry2[:8] = b"wait.dds"
struct.pack_into("<III", entry2, 0x94, len(sega_wait), len(sega_wait), 0)
struct.pack_into("<I", entry2, 0xA0, 2)
hdr2 = bytearray(hdr)
struct.pack_into("<I", hdr2, 12, 2)                            # two files now
struct.pack_into("<3Q", hdr2, 0x18, 3, 1, 2)
sega2 = bytes(hdr2 + entry + entry2).ljust(E.SECTOR, b"\0") + sega_dds.ljust(E.SECTOR, b"\0") + \
    sega_wait.ljust(E.SECTOR, b"\0")
with open(xaf, "wb") as f:
    f.write(sega2)
E.sheet = lambda name: [{"sega_sha256": E.sha(sega_dds), "style": "white", "labels": "0,0,15,15=OK",
                         "files": "pic.dds", "how": "archive"},
                        {"sega_sha256": E.sha(sega_wait), "style": "wait", "labels": "1,1,30,6=Please;1,9,30,14=wait",
                         "files": "wait.dds", "italiano": "Attendi;ancora", "how": "memory"}]
mem, note = E.build_memory_pictures(game)
assert list(mem) == [E.memory_name(sega_wait)] == ["%d-%016X.dds" % (len(sega_wait), E.fnv64(sega_wait))], \
    "only the memory row, named by Sega's picture's size and fingerprint"
blob = mem[E.memory_name(sega_wait)]
assert len(blob) == len(sega_wait) and blob[:128] == sega_wait[:128] and blob != sega_wait, \
    "the same kind and size of picture as Sega's (its own header), the writing redrawn"
eng = Image.open(io.BytesIO(blob)).convert("RGBA")
assert eng.getchannel("A").crop((0, 15 + E.REFLECT_GAP, 32, 32)).getbbox(), "the last line mirrored below it"
assert archive() == sega2, "the archive is never touched for a memory picture"
it = E.build_memory_pictures(game, "it")[0][E.memory_name(sega_wait)]
assert it != blob, "Italian: its own words in the same picture"

E.PIC_DIR = os.path.join(scratch, "english_pictures")      # never the kit's own data\english_pictures
E.memory_pictures_on(mem)
assert os.listdir(E.PIC_DIR) == list(mem), "on: the folder holds the picture"
with open(os.path.join(E.PIC_DIR, E.memory_name(sega_wait)), "rb") as f:
    assert f.read() == blob, "... byte for byte"
E.memory_pictures_on({})                                     # a language with no memory pictures: none left behind
assert not os.path.exists(E.PIC_DIR), "on with none: the folder goes"
E.memory_pictures_on(mem)
assert E.memory_pictures_off() == 1 and not os.path.exists(E.PIC_DIR), "off: the pictures and the folder go"
assert E.memory_pictures_off() == 0, "off again: nothing to do"
assert os.path.basename(K.ENGLISH_PICTURES) == "english_pictures", "the folder play.py names to the hook"

shutil.rmtree(scratch)
# off by default: with the redrawn pictures in the archive the game did not read a club card (2026-10-11, a real start)
assert E.PICTURES == (os.environ.get("WCCF_PICTURES") == "1"), "the pictures must stay off unless WCCF_PICTURES=1"
print("english pictures: 27 checks passed")
