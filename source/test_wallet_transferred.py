# -*- coding: utf-8 -*-
"""test_wallet_transferred.py - after a manager transfer the old card is used up (counter low byte 0): the CLUB CARD
panel lists it as transferred with no PLAY THIS CLUB, a switch to it is refused, and an ended contract says so
(check.ps1 runs it; cards made here in a scratch folder - no game, no real card).
    python source\\test_wallet_transferred.py"""
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import club_view as V  # noqa: E402
import club_wallet as W  # noqa: E402
import edit_club_card as E  # noqa: E402

BLOCKS = [bytearray(16) for _ in range(256)]
BLOCKS[4][8:12] = bytes([0x95, 0x71, 0x66, 0x40])                 # the reader signature (as edit_club_card's self-test)
BLOCKS[6][12:16] = bytes([0x00, 0x98, 0x96, 0x81])                # the serial


def card(path, counter, term=50):
    """a card file the game accepts, with this use counter and contract"""
    copy = bytearray(E.D.COPY_BYTES)
    key, row, bit = E.resolve("Coach.COACH_LAST_TERM")
    E.write_bits(copy, bit, row[3] * row[4], term)
    header = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x18, counter & 0xFF, counter >> 8]) + bytes(9)
    with open(path, "wb") as f:
        f.write(E.stamp_copy(header, BLOCKS, copy))


tmp = tempfile.mkdtemp(prefix="wccf_wallet_")
try:
    cards = os.path.join(tmp, "cards")
    os.makedirs(cards)
    slot, dead, other = os.path.join(tmp, "seat1_club.bin"), os.path.join(cards, "OLD - transferred.bin"), \
        os.path.join(cards, "OTHER.bin")
    card(slot, 0xFFF0)
    card(dead, 0x0000, term=0)
    card(other, 0xFF01, term=0)                                    # contract ended, not transferred yet: still playable
    assert W.used_up(dead) and not W.used_up(other) and not W.used_up(slot)
    labels = {f: s for f, _n, s in W.wallet(cards)}
    assert labels["OLD - transferred.bin"].startswith("transferred"), labels
    assert not labels["OTHER.bin"].startswith("transferred"), labels
    view = V.build(card=slot, catalogue=os.path.join(tmp, "none.tsv"), backups=os.path.join(tmp, "none"),
                   running=os.path.join(tmp, "none.json"), cards=cards)
    wal = {ln.split("|")[1]: ln for ln in view if ln.startswith("wallet|")}
    assert wal["OLD - transferred.bin"].endswith("|transferred"), wal
    assert not wal["OTHER.bin"].endswith("|transferred"), wal
    done, what = W.switch("OLD - transferred.bin", slot=slot, folder=cards)
    assert not done and "transferred" in what and os.path.exists(dead) and os.path.exists(slot), what
    for path, want in ((other, "ended - put the card in"), (dead, "transferred - the game will not play"),
                       (slot, "50 matches left")):
        rows = [ln for ln in V.build(card=path, catalogue=os.path.join(tmp, "none.tsv"),
                                     backups=os.path.join(tmp, "none"), running=os.path.join(tmp, "none.json"),
                                     cards=cards) if ln.startswith("row|CONTRACT|")]
        assert rows and want in rows[0], (os.path.basename(path), rows)
    done, what = W.switch("OTHER.bin", slot=slot, folder=cards)   # an ended contract still switches: it can transfer
    assert done, what
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("wallet transferred: 10 checks passed")
