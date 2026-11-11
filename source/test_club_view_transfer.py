# -*- coding: utf-8 -*-
"""test_club_view_transfer.py - after Sega's manager transfer, and before the next start swaps the two files
(wallet.finish_transfer), the CLUB CARD view and the FORMATION board's lines are the NEW club's (NAME.new.bin), not the
used-up card's still in the slot (2026-11-11: the board drew the old club's 21 lines over a new club that had none).
A blank new card beside an expired one (the transfer not done yet), no new card, or a stray one beside a card still
in play leave the view on the slot's card.  check.ps1 runs it; cards made here in a scratch folder - no game, no real card.
    python source\\test_club_view_transfer.py"""
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
sys.path.insert(0, os.path.join(KIT, "code", "helpers"))
from cards import edit as E  # noqa: E402
import panel  # noqa: E402

BLOCKS = [bytearray(16) for _ in range(256)]
BLOCKS[4][8:12] = bytes([0x95, 0x71, 0x66, 0x40])                 # the reader signature (as edit_club_card's self-test)
BLOCKS[6][12:16] = bytes([0x00, 0x98, 0x96, 0x81])                # the serial


def card(path, counter, term, link):
    """a card file the game accepts: this use counter and contract; cards 101 and 202 in slots 0 and 1, their link
    LINK (0 = none drawn)"""
    copy = bytearray(E.D.COPY_BYTES)
    _k, row, bit = E.resolve("Coach.COACH_LAST_TERM")
    E.write_bits(copy, bit, row[3] * row[4], term)
    for slot, no in ((0, 101), (1, 202)):
        _k, row, bit = E.resolve("Player%d.PLAYER_CARD_NO" % slot)
        E.write_bits(copy, bit, row[4], no)
    _k, row, bit = E.resolve("Club.CLUB_PLAYER_COOPERATION_INFO")
    E.write_bits(copy, bit, 8, link)                               # pair (0,1) is the first
    header = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x18, counter & 0xFF, counter >> 8]) + bytes(9)
    with open(path, "wb") as f:
        f.write(E.stamp_copy(header, BLOCKS, copy))


def view_of(data, online_card):
    """the view ClubView writes, as the helper's loop would: a first look, then again once it has held still"""
    v = panel.ClubView(data, online_card)
    v.tick(0.0)
    v.tick(2.0)
    with open(os.path.join(data, "club_view.txt"), encoding="ascii") as f:
        lines = f.read().splitlines()
    return v, lines


def summary(lines):
    contract = [ln for ln in lines if ln.startswith("row|CONTRACT|")]
    return (contract[0].split("|")[2] if contract else None), [ln for ln in lines if ln.startswith("link|")]


passed = 0
tmp = tempfile.mkdtemp(prefix="wccf_viewxfer_")
try:
    for online in (False, True):                                   # the slot offline, the account's club online
        data = os.path.join(tmp, "online" if online else "slot", "data")
        folder = os.path.join(data, "save", "online", "u1") if online else os.path.join(data, "save")
        os.makedirs(folder)
        slot = os.path.join(folder, "club.bin" if online else "seat1_club.bin")
        new = os.path.splitext(slot)[0] + ".new.bin"
        arg = slot if online else None

        card(slot, 0xFF20, 40, 255)                                # a card in play, a gold link; no new card
        _v, lines = view_of(data, arg)
        assert summary(lines) == ("40 matches left", ["link|101|202|255"]), summary(lines)
        passed += 1

        card(new, 0xFF63, 98, 0)                                   # a stray new card beside a card still in play
        _v, lines = view_of(data, arg)
        assert summary(lines)[0] == "40 matches left", summary(lines)
        passed += 1

        card(slot, 0xFF01, 0, 255)                                 # the contract ended: a blank new card beside it
        card(new, 0xFFFF, 0, 0)
        _v, lines = view_of(data, arg)
        assert summary(lines) == ("ended - put the card in: the game moves your manager to a new card",
                                  ["link|101|202|255"]), summary(lines)
        passed += 1

        card(slot, 0xFF00, 0, 255)                                 # the transfer done: the slot's card used up
        card(new, 0xFF63, 98, 0)                                   # the new club, no links yet
        v, lines = view_of(data, arg)
        assert summary(lines) == ("98 matches left", []), summary(lines)
        assert v.shown() == new, v.shown()
        passed += 1

        card(new, 0xFF62, 97, 201)                                 # a save to the new card alone is seen: the view
        v.tick(10.0)                                               # follows its first link (the same ClubView, so
        v.tick(12.0)                                               # only a changed signature makes it write again)
        with open(os.path.join(data, "club_view.txt"), encoding="ascii") as f:
            lines = f.read().splitlines()
        assert summary(lines) == ("97 matches left", ["link|101|202|201"]), summary(lines)
        passed += 1

        os.remove(new)                                             # the next start swapped them: the slot again
        os.rename(slot, os.path.join(folder, "old.bin"))
        card(slot, 0xFF61, 96, 201)
        _v, lines = view_of(data, arg)
        assert summary(lines) == ("96 matches left", ["link|101|202|201"]), summary(lines)
        passed += 1
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("club view after a transfer: %d checks passed" % passed)
