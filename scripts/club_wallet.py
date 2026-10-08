# -*- coding: utf-8 -*-
r"""club_wallet.py - your other club cards, and the card in the slot.  The slot is data\save\seat1_club.bin, the
card the card reader stand-in serves; your other cards wait in data\save\cards\, one file each.

Switching happens at a start, while nothing runs (the player chose "with a restart", 2026-10-06): the CLUB CARD panel
writes "card=FILE" (a file in cards\) or "card=new" into data\panel.txt and asks for RESTART NOW; play.py then
calls switch() before the card reader starts.

A switch is two renames inside data\save (each one step on the same disk): the card in the slot goes to cards\
under its club's name, then the chosen card goes into the slot.  play.py takes the request line out only after
both, so a switch stopped half way is finished at the next start.  No card is ever overwritten or deleted: a name
already taken gets " (2)", " (3)" ...  "new" leaves the slot empty: the card reader then serves a NEW card, and the
game makes a club when it goes in (as on the very first run).
"""
import os
import re

import kit_common as K

SLOT = os.path.join(K.SAVE, "seat1_club.bin")
WALLET = os.path.join(K.SAVE, "cards")


def club_label(card):
    """(the club's name as the panel draws it, or None; a short summary) of a card file - read-only"""
    import club_view as V                               # here, not at the top: club_view lists the wallet too
    D = V.D
    state, bad = K.card_session(card)
    if state == "none":
        return None, "no file"
    if state == "unreadable":
        return None, "cannot be read"
    if state == "new":
        return None, "a new card - no club yet"
    try:
        header, blocks = D.read_card(card)
        _a, _b, chosen, _v = D.game_choice(header, blocks)
        d = D.decode(D.copy_of(blocks, chosen))
        lg = D.league(d)
        name = V.ascii_name(D.text(d[("Club", 0, "CLUB_NAME")])) or None
        return name, "Div %d %s, W%d D%d L%d%s" % (lg["division"], V.ordinal(lg["position_computed"]), lg["win"],
                                                    lg["draw"], lg["lose"], ", %d bad" % bad if bad else "")
    except Exception as ex:                              # a card the decoder cannot take: say so, never raise
        return None, "cannot be read (%s)" % ex.__class__.__name__


def safe(name):
    """a club name as a file name: no characters Windows refuses, no dots or spaces at the ends, 40 at most"""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip(" .")[:40].strip(" .")
    return s or "club card"


def free_path(base, folder=None):
    """cards\\BASE.bin, or BASE (2).bin ... - a name nothing has yet"""
    folder = folder or WALLET
    p = os.path.join(folder, base + ".bin")
    n = 2
    while os.path.exists(p):
        p = os.path.join(folder, "%s (%d).bin" % (base, n))
        n += 1
    return p


def wallet(folder=None):
    """[(file name, club name or None, summary)] of the cards in cards\\, by file name"""
    folder = folder or WALLET
    try:
        files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".bin") and
                       os.path.isfile(os.path.join(folder, f)))
    except OSError:
        return []
    return [(f,) + club_label(os.path.join(folder, f)) for f in files]


def move_board(card_from, card_to):
    """a card's own table (boards.py, 2026-10-08) goes with it: NAME.board beside NAME.bin.  Moved BEFORE its card, so
    a switch stopped half way finishes the same at the next start; a folder already under the new name (a leftover)
    is kept aside as " (2)" ..., never written over"""
    src, dst = os.path.splitext(card_from)[0] + ".board", os.path.splitext(card_to)[0] + ".board"
    if not os.path.isdir(src):
        return
    if os.path.exists(dst):
        n = 2
        while os.path.exists("%s (%d)" % (dst, n)):
            n += 1
        os.rename(dst, "%s (%d)" % (dst, n))
    os.rename(src, dst)


def switch(request, slot=None, folder=None):
    """carry out "card=FILE" or "card=new" (nothing of the game may run: play.py calls it before the card reader
    starts) -> (done, what to say).  Never raises for a bad request: the slot is then left as it is."""
    slot, folder = slot or SLOT, folder or WALLET
    req = (request or "").strip()
    if req.lower() == "new":
        target = None
    else:
        if os.path.basename(req) != req or not req.lower().endswith(".bin"):
            return False, "\"%s\" is not one of your cards - the card in the slot stays" % req
        target = os.path.join(folder, req)
        if not os.path.isfile(target):
            return False, "%s is not in your cards (any more) - the card in the slot stays" % req
        if K.card_session(target)[0] in ("unreadable", "none"):
            return False, "%s cannot be read - it stays in your cards, the card in the slot stays" % req
    os.makedirs(folder, exist_ok=True)
    put_away = ""
    if os.path.isfile(slot):                             # 1: the card in the slot goes to your cards, by club name
        name, _summary = club_label(slot)
        dst = free_path(safe(name or "club card"), folder)
        move_board(slot, dst)                            # its cards on the table go with it (boards.py)
        os.rename(slot, dst)                             # rename: never over an existing file
        put_away = "%s went to your cards (%s)" % (name or "the old card", os.path.basename(dst))
    if target is None:
        return True, (put_away + "; " if put_away else "") + "a NEW card is in the slot - put it in, and the game " \
                                                              "makes a club"
    move_board(target, slot)
    os.rename(target, slot)                              # 2: the chosen card into the slot
    name, _summary = club_label(slot)
    return True, (put_away + "; " if put_away else "") + "%s is in the slot" % (name or req)
