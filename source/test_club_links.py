# -*- coding: utf-8 -*-
"""test_club_links.py - the club card's links in the CLUB CARD view (data\\club_view.txt), for the FORMATION board's
lines: a pair is listed with its two card numbers once its value is 151 or more (thin white; 201 thick white, 255
gold), never below, never with an empty slot; the pair order is the game's (0,1) (0,2) ... (14,15) (WCCF research
AFFINITY-2010-11.md 3.1).  check.ps1 runs it; the card is made here in a scratch folder - no game, no real card.
    python source\\test_club_links.py"""
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from cards import view as V  # noqa: E402
from cards import edit as E  # noqa: E402

BLOCKS = [bytearray(16) for _ in range(256)]
BLOCKS[4][8:12] = bytes([0x95, 0x71, 0x66, 0x40])                 # the reader signature (as edit_club_card's self-test)
BLOCKS[6][12:16] = bytes([0x00, 0x98, 0x96, 0x81])                # the serial
CARDS = {0: 101, 1: 202, 2: 303, 3: 404, 15: 1616}                 # slot -> card number; the other slots empty
VALUES = {(0, 1): 255, (0, 2): 201, (1, 2): 151, (2, 3): 150, (0, 5): 255, (3, 15): 200, (14, 15): 254}


def index(lo, hi):
    """the research's pair index, worked out apart from view.py's own loop"""
    return sum(15 - k for k in range(lo)) + (hi - lo - 1)


tmp = tempfile.mkdtemp(prefix="wccf_links_")
try:
    copy = bytearray(E.D.COPY_BYTES)
    for slot, no in CARDS.items():
        _k, row, bit = E.resolve("Player%d.PLAYER_CARD_NO" % slot)
        E.write_bits(copy, bit, row[4], no)
    _k, row, bit = E.resolve("Club.CLUB_PLAYER_COOPERATION_INFO")
    assert (row[3], row[4]) == (120, 8), row
    for (lo, hi), v in VALUES.items():
        E.write_bits(copy, bit + index(lo, hi) * 8, 8, v)
    card = os.path.join(tmp, "seat1_club.bin")
    header = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x18, 0xF0, 0xFF]) + bytes(9)
    with open(card, "wb") as f:
        f.write(E.stamp_copy(header, BLOCKS, copy))
    view = V.build(card=card, catalogue=os.path.join(tmp, "none.tsv"), backups=os.path.join(tmp, "none"),
                   running=os.path.join(tmp, "none.json"), cards=os.path.join(tmp, "cards"))
    assert view[0] == "state|ok", view[:3]
    got = [ln for ln in view if ln.startswith("link|")]
    want = ["link|101|202|255", "link|101|303|201", "link|202|303|151", "link|404|1616|200"]
    assert got == want, got                       # 150 and an empty slot left out; (14,15) has no card in slot 14
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("club links: 3 checks passed")
