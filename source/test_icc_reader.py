# -*- coding: utf-8 -*-
"""test_icc_reader.py - the club-card reader's saving and recovery (check.ps1 runs it; scratch files only, no game,
no pipe). Covers the two player-safety fixes:
  A2 - a save that cannot reach the disk never writes the card in place; the card on disk stays the last good one and
       the newest is kept in memory and retried.
  A1 - an unreadable (wrong-size) card file does not lock the player out: it is kept as .bad and a NEW card is served.
    python source\\test_icc_reader.py"""
import os
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import _icc_reader as R  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


t = tempfile.mkdtemp(prefix="wccf-icc-")
try:
    path = os.path.join(t, "club.bin")

    # 1. a NEW card saves atomically: exactly CARD_BYTES, loads back equal, no .tmp left
    c = R.Card()
    c.path = path
    c.blocks[7][0] = 0x55
    c.save()
    check(os.path.getsize(path) == R.CARD_BYTES, "a saved card is exactly %d bytes" % R.CARD_BYTES)
    check(not os.path.exists(path + ".tmp"), "no .tmp left after a save")
    check(R.Card(path).blocks[7][0] == 0x55, "the saved card loads back equal")

    # 2. a new session backs the card up first; backups are kept
    c.last_save = 0.0                                 # force "a new session"
    c.blocks[7][0] = 0x56
    c.save()
    baks = os.listdir(os.path.join(t, "backup"))
    check(len(baks) == 1 and baks[0].endswith(".bak"), "a new session makes one backup")

    # 3. A2: a forced save failure NEVER writes in place - the on-disk card stays the last good one, newest kept
    good = open(path, "rb").read()
    real_replace = os.replace
    os.replace = lambda *a, **k: (_ for _ in ()).throw(PermissionError("busy"))   # the card file stays busy
    try:
        c.blocks[7][0] = 0x99
        c.save()
        check(c.pending is not None, "a failed save keeps the newest card in memory")
        check(open(path, "rb").read() == good, "a failed save leaves the on-disk card UNCHANGED (never in place)")
        check(os.path.getsize(path) == R.CARD_BYTES, "the on-disk card is never a short file during a failed save")
    finally:
        os.replace = real_replace
    c._flush()                                        # the file is free again
    check(c.pending is None, "the kept card is written once the file is free")
    check(R.Card(path).blocks[7][0] == 0x99, "the retried save holds the newest card")

    # 4. A1: a wrong-size card file does not lock out - it is kept as .bad and a NEW card is served
    with open(path, "wb") as f:
        f.write(b"\x01" * 100)                        # the wrong size
    bad_bytes = open(path, "rb").read()
    msgs = []
    card = R.open_card(path, msgs.append)
    check(card.counter == 0xFFFF, "a refused card file gives a NEW (playable) card, not a lock-out")
    check(card.path == path, "the NEW card saves to the real card path")
    bad = [f for f in os.listdir(t) if f.endswith(".bad")]
    check(len(bad) == 1 and open(os.path.join(t, bad[0]), "rb").read() == bad_bytes,
          "the unreadable file is kept intact as .bad")
    card.log = msgs.append
    card.save()
    check(os.path.getsize(path) == R.CARD_BYTES, "the NEW card then saves a valid card over the bad one")

    # 5. a good card file still loads untouched (no false refusal)
    card2 = R.open_card(path, msgs.append)
    check(card2.counter == 0xFFFF and not any("REFUSED" in m for m in msgs[-3:]),
          "a good card file loads without a refusal")

    n = 14
    print("icc_reader: %d of %d checks passed" % (n - len(fails), n))
finally:
    os.replace = real_replace if "real_replace" in dir() else os.replace
    import shutil
    shutil.rmtree(t, ignore_errors=True)

sys.exit(1 if fails else 0)
