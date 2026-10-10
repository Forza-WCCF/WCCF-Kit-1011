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
sys.path.insert(0, os.path.join(KIT, "scripts"))
import english as E  # noqa: E402
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

shutil.rmtree(scratch)
print("english pictures: 11 checks passed")
