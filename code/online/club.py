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
import base64
import hashlib
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
CARD_BYTES = 4112                 # a club card file (hardware\card_reader.py)
SYNCED = "synced.json"            # beside the card: the version wccf.online has {"sha256", "seq"}


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
    try:
        for what in ready(token, card):
            say("  online club: %s" % what)
    except Exception as ex:                    # never a reason not to play: the card on this PC plays as it is
        say("  online club: the club card was not checked with wccf.online (%s) - it plays as it is" % ex)
        if not os.path.exists(card):           # else the card reader's own blank, with the id every kit card shares
            make_blank(card)
    return {"uid": got["uid"], "username": got.get("username", ""), "card": card, "catalogue": OWNED_CATALOGUE}


def ready(token, card):
    """the online club card ready for the card reader: a finished manager transfer put away (wallet.finish_transfer,
    as for the slot: the old card kept in transferred\\), then the card made the same as wccf.online's (sync)"""
    from cards import wallet
    _done, what = wallet.finish_transfer(card, os.path.splitext(card)[0] + ".new.bin",
                                         os.path.join(os.path.dirname(card), "transferred"))
    return ([what] if what else []) + sync(token, card)


def card_bytes(path):
    """a club card file's bytes, or None (none there, or not a card's size)"""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return data if len(data) == CARD_BYTES else None


def synced(folder):
    """the version of the club card wccf.online has, as this PC last knew it: {"sha256", "seq"} or {}"""
    try:
        with open(os.path.join(folder, SYNCED), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("sha256"), str) else {}
    except (OSError, ValueError):
        return {}


def set_synced(folder, sha, seq):
    write_atomic(os.path.join(folder, SYNCED), json.dumps({"sha256": sha, "seq": seq}) + "\n")


def upload(token, card, folder):
    """the card file as a new version on wccf.online, built on the one it had at the last sync -> (state, detail):
    "kept" (seq) / "same" (nothing new) / "newer" (another PC saved since - the next start takes the website's) /
    "refused" (why: the website's checks) / "unreachable" (why: try again later) / "used up" (not sent: a manager
    transfer left it, and the website keeps the new card instead - it refuses this one too)"""
    data = card_bytes(card)
    if data is None:
        return "refused", "no club card file of the right size"
    if data[5] == 0:                           # the use counter's low byte 0 (card_reader.py: transferred)
        return "used up", "its manager moved to a new card - that card goes up after its first save"
    base = synced(folder).get("sha256", "")
    sha = hashlib.sha256(data).hexdigest()
    if sha == base:
        return "same", synced(folder).get("seq")
    status, body = account.post("wccf_club_save", {"token": token, "base": base,
                                                   "card": base64.b64encode(data).decode("ascii")})
    if status == 200 and body.get("sha256") == sha and isinstance(body.get("seq"), int):
        set_synced(folder, sha, body["seq"])
        return "kept", body["seq"]
    if status == 409:
        return "newer", body.get("error") or "the website has a newer club card"
    if status in (401, 403, 422):
        return "refused", body.get("error") or "HTTP %s" % status
    return "unreachable", body.get("error") or "HTTP %s" % status


def send_formation(token, seat):
    """the cards on the table and where each stands (cards\\formation.py table: the board's fpr_table0.txt in the
    seat folder) -> wccf.online, for the account's profile (2026-10-16, the owner: "show the current formation the
    player is playing") -> (state, detail): "kept" (n) / "empty" (no card on the table: nothing sent, the profile keeps
    the last one) / "refused" (why) / "unreachable" (why)"""
    from cards import formation
    cards = [[no, x, y] for _slot, no, x, y in formation.table(seat)]
    if not cards:
        return "empty", 0
    status, body = account.post("wccf_formation", {"token": token, "cards": json.dumps(cards)})
    if status == 200:
        return "kept", body.get("kept")
    if status in (401, 403, 422):
        return "refused", body.get("error") or "HTTP %s" % status
    return "unreachable", body.get("error") or "HTTP %s" % status


def make_blank(card):
    """a blank club card with an id of its own (card_reader.Card.blank): every card older kits made shares one id, so
    an online club starts on its own card - the website refuses the shared one"""
    from hardware import card_reader
    write_atomic_bytes(card, card_reader.Card.blank(card).image())


def write_atomic_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)


def keep_aside(card, why):
    """this PC's copy of the card into its backup folder (never deleted) -> the name it got"""
    folder = os.path.join(os.path.dirname(card), "backup")
    os.makedirs(folder, exist_ok=True)
    name = os.path.join(folder, "%s.%s-%s" % (os.path.basename(card), why, time.strftime("%Y%m%d-%H%M%S")))
    dst, n = name + ".bak", 2
    while os.path.exists(dst):                 # two in one second: never one over the other
        dst, n = "%s (%d).bak" % (name, n), n + 1
    os.replace(card, dst)
    return os.path.basename(dst)


def sync(token, card):
    """before the card reader starts (prepare): this PC's online club card made the same as wccf.online's -> what it
    did, to say.  Nothing there yet: this PC's club goes up, or a new blank card is made.  This PC saved after the
    website's version: that save goes up now.  The website's is newer (another PC): it wins, this PC's copy kept in
    backup\\.  The website out of reach: this PC's card plays, and goes up after the next match."""
    folder = os.path.dirname(card)
    status, body = account.post("wccf_club", {"token": token})
    local = card_bytes(card)
    if status != 200 or not isinstance(body.get("seq"), int):
        if local is None:
            make_blank(card)
        return ["wccf.online's copy of your club card could not be read (%s) - playing with this PC's; it goes up "
                "after the next match" % (body.get("error") or "HTTP %s" % status)]
    if body["seq"] == 0:                                    # nothing kept on the website yet
        if local is None:
            make_blank(card)
            return ["a new card for your online club (its own id) - put it in (I) and press START, and the game "
                    "makes your club"]
        if local[5:7] == b"\xff\xff":                      # a blank card: no club on it yet
            return []
        state, detail = upload(token, card, folder)
        return ["your club card %s" % {"kept": "is kept on wccf.online now (version %s)" % detail,
                                       "same": "is on wccf.online"}.get(state, "did not go to wccf.online: %s - "
                                                                               "it plays from this PC" % detail)]
    remote = base64.b64decode(body.get("card") or "")
    if local == remote:
        if synced(folder).get("sha256") != body.get("sha256"):
            set_synced(folder, body.get("sha256"), body["seq"])
        return []
    if local is not None and synced(folder).get("sha256") == body.get("sha256"):    # saved here after the website's
        state, detail = upload(token, card, folder)
        if state in ("kept", "same"):
            return ["your club card's last save went to wccf.online now (version %s)" % detail]
        if state == "unreachable":
            return ["your club card's last save could not go to wccf.online (%s) - it plays from this PC" % detail]
        said = ["wccf.online did not take this PC's last save (%s)" % detail]
    else:
        said = []
    if len(remote) != CARD_BYTES:
        return said + ["wccf.online's copy of your club card is not a card file - playing with this PC's"]
    if local is not None:
        said.append("this PC's copy kept as backup\\%s" % keep_aside(card, "replaced"))
    write_atomic_bytes(card, remote)
    set_synced(folder, body.get("sha256"), body["seq"])
    return said + ["your club card from wccf.online (version %s)" % body["seq"]]


def new_cards(token, data):
    """after a match (the panel helper): the account's cards again from wccf.online - one it did not have before (a
    finished match earns one, phase 3; a second copy counts too) goes into this run's CATALOGUE (OWNED_CATALOGUE, read
    again by the panel when it changes) and is named in data\\dealt.txt ("N CARDNO", N counting up) for the panel's
    NEW CARD window -> the new card numbers ([] when none, or the website out of reach)"""
    from collections import Counter
    state, got = fetch(token)
    if state != "ok":
        return []
    before = Counter((read_owned(got["uid"]) or {}).get("cards", []))
    new = list((Counter(got["cards"]) - before).elements())
    got["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    write_atomic(os.path.join(folder_of(got["uid"]), "owned.json"), json.dumps(got) + "\n")
    if not new:
        return []
    try:
        with open(OWNED_CATALOGUE, encoding="utf-8", newline="") as f:
            listed = {ln.split("\t", 1)[0] for ln in f}
        with open(CATALOGUE, encoding="utf-8", newline="") as f:
            add = [ln for ln in f if ln.split("\t", 1)[0].isdigit() and int(ln.split("\t", 1)[0]) in set(new)
                   and ln.split("\t", 1)[0] not in listed]
        if add:
            with open(OWNED_CATALOGUE, "a", encoding="utf-8", newline="") as f:
                f.writelines(add)
    except OSError:
        pass                                    # the card is owned all the same: the next start lists it
    dealt = os.path.join(data, "dealt.txt")
    try:
        with open(dealt, encoding="ascii") as f:
            n = int(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        n = 0
    write_atomic(dealt, "%d %d\n" % (n + 1, new[-1]))
    return new


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
