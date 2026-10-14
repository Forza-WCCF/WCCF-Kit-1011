# -*- coding: utf-8 -*-
r"""club.py - your online club on this PC (2026-10-14, kit 7: one account for wccf.online and the online game).

Signed in, a PC plays online with the account's own club, not with the club card in the slot: its card file is
data\save\online\u<account>\club.bin (the slot card and YOUR CARDS stay as they are, for play on this PC). Its cards
are the ones the account owns on wccf.online - a new account is given 11 white cards there (1 GK, 4 DF, 4 MF, 2 FW) -
and the CATALOGUE lists only those: data\cache\catalogue_online.tsv, which play.py gives the panel as WCCF_CATALOGUE.
A card with no club on it yet goes through the game's own Club Make, with the owned cards laid out on the table.
The owned list is kept beside the card (owned.json): when the website cannot be reached, the one from the last time
is used; none kept -> prepare() says so and returns None, and play.py plays with the slot card as before (never
locked out).
    python code\online\club.py         what this PC holds for the signed-in account (read-only)
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # code\, when run on its own
import kit_common as K  # noqa: E402
from online import account  # noqa: E402

SAVE = K.SAVE
ONLINE = os.path.join(SAVE, "online")
CATALOGUE = os.path.join(K.CACHE, "catalogue.tsv")
OWNED_CATALOGUE = os.path.join(K.CACHE, "catalogue_online.tsv")
LINES = ("GK", "DF", "MF", "FW")
TABLE_MAX = 16                    # cards on the table: 11 on the pitch + 5 on the bench (formation.py, the board)


def say(msg):
    print(msg, flush=True)


def folder_of(uid):
    return os.path.join(ONLINE, "u%d" % uid)


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def fetch(token):
    """("ok", {"uid", "username", "cards"}) / ("refused", why) / ("unreachable", why) - the owned cards from the
    website (a new account's first ask gives it the starter 11)"""
    status, body = account.post("wccf_owned", {"token": token})
    cards = body.get("cards")
    if status == 200 and isinstance(cards, list) and isinstance(body.get("uid"), int) and body["uid"] > 0:
        return "ok", {"uid": body["uid"], "username": str(body.get("username", "")),
                      "cards": [c for c in cards if isinstance(c, int) and c > 0]}
    if status in (401, 403):
        return "refused", body.get("error") or "refused"
    return "unreachable", body.get("error") or "HTTP %s" % status


def read_owned(uid):
    """the owned list kept from the last time: {"uid", "username", "cards", "at"}, or None"""
    try:
        with open(os.path.join(folder_of(uid), "owned.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    ok = isinstance(d, dict) and d.get("uid") == uid and isinstance(d.get("cards"), list)
    return d if ok else None


def owned_catalogue(cards, src=None, out=None):
    """the catalogue's lines of the owned cards, its header first and each card once -> out (OWNED_CATALOGUE);
    returns how many cards it lists"""
    keep = set(cards)
    with open(src or CATALOGUE, encoding="utf-8", newline="") as f:
        lines = f.readlines()
    if not lines or not lines[0].startswith("card_no\t"):
        raise ValueError("%s is not the kit's catalogue (run SETUP.exe)" % (src or CATALOGUE))
    mine = [ln for ln in lines[1:] if ln.split("\t", 1)[0].isdigit() and int(ln.split("\t", 1)[0]) in keep]
    write_atomic(out or OWNED_CATALOGUE, lines[0] + "".join(mine))
    return len(mine)


def prepare(token):
    """the signed-in account's online club, ready to play -> {"uid", "username", "card", "catalogue"} (what play.py
    keeps in data\\running.json), or None after saying why (play.py then plays with the slot card, as before)"""
    state, got = fetch(token)
    saved = account.load() or {}
    if state == "ok":
        got["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_atomic(os.path.join(folder_of(got["uid"]), "owned.json"), json.dumps(got) + "\n")
        if saved and saved.get("uid") != got["uid"]:
            saved["uid"] = got["uid"]                 # so the club is found when the website cannot be reached
            account.save(saved)
    elif state == "refused":
        say("  online club: wccf.online refused this PC's sign-in (%s) - playing with the club card in the slot" % got)
        return None
    else:
        kept = read_owned(saved.get("uid")) if isinstance(saved.get("uid"), int) else None
        if not kept:
            say("  online club: wccf.online could not be reached (%s) and this PC has no list of your cards yet - "
                "playing with the club card in the slot" % got)
            return None
        say("  online club: wccf.online could not be reached (%s) - your cards as they were at %s" % (got, kept.get("at")))
        got = kept
    n = owned_catalogue(got["cards"])
    if not n:
        say("  online club: none of your cards is in this kit's catalogue - playing with the club card in the slot")
        return None
    card = os.path.join(folder_of(got["uid"]), "club.bin")
    say("  online club: %s - %d cards (%s)" % (got.get("username") or "?", n, K.shown(card)))
    return {"uid": got["uid"], "username": got.get("username", ""), "card": card, "catalogue": OWNED_CATALOGUE}


def squad_of(catalogue):
    """[(card number, line)] of the cards a catalogue lists, by line (GK DF MF FW) then number, at most TABLE_MAX"""
    with open(catalogue, encoding="utf-8", newline="") as f:
        rows = [ln.rstrip("\r\n").split("\t") for ln in f]
    col = rows[0].index("position_name") if rows and "position_name" in rows[0] else None
    if col is None:
        raise ValueError("%s has no position_name column" % catalogue)
    cards = sorted((LINES.index(r[col]), int(r[0])) for r in rows[1:]
                   if len(r) > col and r[0].isdigit() and r[col] in LINES)
    return [(no, LINES[k]) for k, no in cards][:TABLE_MAX]


def table(seat, online):
    """the online club's cards on the table, before anything reads it (play.py) -> what it did, said.  A club made:
    its own board, as for any card (formation.sync).  No club yet: the owned cards laid out for Club Make, owned by
    no board - the club the game makes from them takes them at the next start"""
    from cards import formation
    said = formation.sync(seat, card=online["card"], save=SAVE)
    name, _why = formation.club_of(online["card"])
    if name is None:
        n = formation.lay_out(seat, "the online club of %s" % (online.get("username") or "?"), squad_of(online["catalogue"]))
        formation.set_owner(seat, None)
        said.append("your online club has no club yet: your %d cards are on the table - put the card in (I) and "
                    "press START, and the game makes your club" % n)
    return said


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    saved = account.load()
    uid = saved.get("uid") if saved else None
    if not isinstance(uid, int):
        print("no online club on this PC yet (sign in, then play online once)")
        return 1
    kept = read_owned(uid)
    card = os.path.join(folder_of(uid), "club.bin")
    print("account %s (u%d): %s cards kept (at %s); club card %s" % (
        saved.get("username") or "?", uid, len(kept["cards"]) if kept else "no", kept.get("at") if kept else "-",
        "there" if os.path.exists(card) else "not made yet"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
