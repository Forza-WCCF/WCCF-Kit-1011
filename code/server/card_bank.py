# -*- coding: utf-8 -*-
r"""card_bank.py - this server's own card bank (2026-10-23): the accounts, the cards each one owns and its club card,
kept on the server itself, so hosting needs no website (the owner: "make sure my server or the files they need for the
server, or my website are never a blocker for anyone").  It answers the kit exactly as wccf.online's game link does
(docs\website\wccfgame.php: the same requests, the same answers, the same rules), so the kit's own code talks to either
one: the seat desk tells each player's PC where this server's players sign in (server\seat_desk.py, BANK).

    python code\server\card_bank.py SECONDS LOGFILE     play.py server starts it, unless data\card_bank.txt names a
                                                        website (TCP 20060; WCCF_BANK_PORT for the tests)
    python code\server\card_bank.py accounts            the accounts, their cards and matches
    python code\server\card_bank.py ban NAME            NAME is refused from now on (unban NAME: let in again)
    python code\server\card_bank.py password NAME NEW   a forgotten password replaced

Kept in data\bank\ (never sent with SEND LOGS, never in git):
    bank.sqlite3        the accounts (a name and a salted password hash), the sign-in codes and tokens (only their
                        SHA-256), the cards each account owns, every saved version of each club card, what this server
                        saw at each match's start and end
    server_name.txt     this server's name and secret for its own witness (server\witness.py tells the bank about each
    server_secret.txt   match with them) - made by identity() at the first start
The card list: data\cache\catalogue.tsv, which SETUP makes from the host's own game (real cards only).
The rules (RULES): the website's - a new account's 11 white cards (1 GK, 4 DF, 4 MF, 2 FW); a card for each finished
match: better than black 5% + 0.25% for each match card since the account's last one, of the rest 70% white and 30%
black; never a card the account owns while its group has another.  A host changes them in data\card_rules.json (kept
across kit updates), e.g. {"better": 800, "luck": 0, "starter": {"GK": 2, "DF": 4, "MF": 4, "FW": 3}}.

The requests (POST, form fields, JSON back - wccfgame.php's list): /xmlhttp.php?action=wccf_link_start, wccf_link_poll,
wccf_whoami, wccf_signout, wccf_owned, wccf_witness, wccf_club, wccf_club_save, wccf_formation.  The page /link: a
name and a password - log in, or make an account - and the game's code approved in the same step.
This is plain HTTP: a password typed on the page crosses the network unencrypted, so the page asks for one that is
used nowhere else.
"""
import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # code\, when run on its own
from cards import decode as D  # noqa: E402

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ.get("WCCF_BANK_DATA") or os.path.join(KIT, "data")
BANK = os.path.join(DATA, "bank")
CATALOGUE = os.environ.get("WCCF_BANK_CATALOGUE") or os.path.join(DATA, "cache", "catalogue.tsv")
PORT = int(os.environ.get("WCCF_BANK_PORT", "20060"))

RULES = {
    "starter": {"GK": 1, "DF": 4, "MF": 4, "FW": 2},   # a new account's cards: white, a playable shape
    "better": 500,          # per 10000: a match card better than black (RARE, LEGEND, ALL TIME LEGEND)
    "luck": 25,             # per 10000 more for each match card since the account's last better one
    "white": 700,           # per 1000 of the rest: white (REGULAR); the others black (SPECIAL)
    "no_twice": True,       # never a card the account owns while its group has another
    "card_gap": 240,        # seconds: at most one card per account in that time (a match takes longer)
}
CODE_LIFE = 600             # seconds a sign-in code can be approved in
COLLECT_LIFE = 600          # seconds after approval the kit can still collect its token
STARTS_PER_IP = 10          # codes one address may ask for within CODE_LIFE
TRIES_PER_IP = 10           # wrong passwords one address may type within CODE_LIFE
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I to misread
SAVES_PER_MINUTE = 30       # club card saves one account may send in a minute
TABLE_MAX = 20              # cards on a table the kit's card reader takes
BODY_MAX = 64 * 1024        # bytes one request may send (a club card is 5.5 KB as base64)
NAME = re.compile(r"^[A-Za-z0-9_\-. ]{3,20}$")
LINES = ("GK", "DF", "MF", "FW")


def positions(name):
    """[(first bit, width)] of every value of a field in a club's data - every instance, every repeat, in card order -
    from the kit's decoder (cards\\decode.py LAYOUT), which wccf.online's WCCFGAME_* tables were generated from"""
    out = [(b + k * r[4], r[4]) for _g, _i, r, b in D.LAYOUT if r[1] == name for k in range(r[3])]
    if not out:
        raise KeyError(name)
    return out


# The chain check (wccfgame.php, 2026-10-14): between a match's end and the next start nothing the club is worth may
# grow and no loss may shrink; START changes only the open mark, the new players' marks and, after a cut, the bad
# endings
CARD_ID = positions("SYSTEM_CARD_ID")[0]            # another id = another card (a manager transfer)
BAD_ENDINGS = positions("USER_INJUSTICE_NUM")[0]    # + 1 at the start after a cut
OPEN_MARK = positions("USER_INJUSTICE_FLAG")[0][0]  # set at START and when playing on
PLAYER_CARD = positions("PLAYER_CARD_NO")           # the 16 registered cards
GROW = ("COACH_SALARY", "COACH_SUCCESSION_SALARY", "COACH_LEVEL", "COACH_TOTAL_WIN_NUM", "COACH_TOTAL_DRAW_NUM",
        "COACH_TOTAL_CHAMPIONSHIP_NUM", "COACH_TOTAL_RL_NUM", "COACH_MAX_OFFICIAL_SERIES_WIN", "CLUB_TRADE_RIGHT_NUM",
        "CLUB_TRADE_REMAINDER_NUM", "CLUB_GET_PRIZE", "CLUB_FINANCIAL_POITN", "CLUB_RECORD_WIN", "CLUB_RECORD_DRAW",
        "CLUB_RECORD_MAX_SERIES_WIN", "CLUB_RECORD_MAX_OFFICIAL_SERIES_WIN", "CLUB_OFFICIAL_TOTAL_POINT", "CLUB_RL_WIN",
        "CLUB_RL_DRAW", "CLUB_RL_GET_GOAL", "TITLE_TOTAL_WIN_NUM", "TITLE_TOTAL_CHAMPIONSHIP_NUM", "CLUB_WT_POINT",
        "CLUB_WT_POINT_MAX")
SHRINK = ("COACH_TOTAL_LOSE_NUM", "CLUB_RECORD_LOSE", "CLUB_RL_LOSE", "CLUB_RL_LOSE_GOAL",
          "CLUB_OFFICIAL_TOTAL_LOST_POINT", "TITLE_TOTAL_LOSE_NUM", "USER_WAN_INJUSTICE_NUM")
PLAYER_GROW = ("PLAYER_OFFICIAL_GOAL", "PLAYER_OFFICIAL_ASSIST", "PLAYER_PARTICIPATE_NUM", "PLAYER_MASTERY",
               "PLAYER_MASTERY_OFFENCE_NUM", "PLAYER_MASTERY_DEFENCE_NUM", "PLAYER_MASTERY_TECHNIQUE_NUM",
               "PLAYER_MASTERY_POWER_NUM", "PLAYER_MASTERY_SPEED_NUM", "PLAYER_MASTERY_STAMINA_NUM",
               "PLAYER_ABILITY_UP_1", "PLAYER_ABILITY_UP_2", "PLAYER_ABILITY_UP_3", "PLAYER_KEYPLAYER_EXP")

db = None                   # the one connection (sqlite3), used under LOCK only
LOCK = threading.Lock()
cards = {}                  # card number -> (rarity, position, full name), from the catalogue
tries = {}                  # address -> times of wrong passwords (kept in memory: a restart forgets them)
log_file = None


class Answer(Exception):
    """a request's answer, raised to end it early (wccfgame_json's exit)"""

    def __init__(self, status, body):
        super().__init__(status)
        self.status, self.body = status, body


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ---- the rules, the card list, the store ----------------------------------------------------------------------------

def load_rules(path=None):
    """RULES with data\\card_rules.json's changes - each value checked; a bad file or value is said and left out (never a
    reason not to start) -> (rules, what was said)"""
    rules, said = json.loads(json.dumps(RULES)), []
    path = path or os.path.join(DATA, "card_rules.json")
    try:
        with open(path, encoding="utf-8") as f:
            got = json.load(f)
    except FileNotFoundError:
        return rules, said
    except (OSError, ValueError) as ex:
        return rules, ["%s could not be read (%s) - the usual rules" % (path, ex)]
    if not isinstance(got, dict):
        return rules, ["%s is not a list of rules - the usual rules" % path]
    limits = {"better": 10000, "luck": 10000, "white": 1000, "card_gap": 86400}
    for k, v in got.items():
        if k in limits and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= limits[k]:
            rules[k] = v
        elif k == "no_twice" and isinstance(v, bool):
            rules[k] = v
        elif k == "starter" and isinstance(v, dict) and set(v) <= set(LINES) and all(
                isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 11 for n in v.values()) and sum(v.values()):
            rules[k] = {p: v.get(p, 0) for p in LINES}
        else:
            said.append("%s: %r for %r left out - not a value it takes" % (os.path.basename(path), v, k))
    return rules, said


def load_cards(path=None):
    """{card number: (rarity, position, full name)} of the real cards in the kit's catalogue ({} when there is none)"""
    import csv
    out = {}
    try:
        with open(path or CATALOGUE, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                if r.get("is_placeholder") == "0" and (r.get("card_no") or "").isdigit() and \
                        r.get("rarity") in ("1", "2", "3", "4", "5") and r.get("position_name") in LINES:
                    out[int(r["card_no"])] = (int(r["rarity"]), r["position_name"], (r.get("name_full_latin") or "").strip())
    except OSError:
        pass
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw TEXT NOT NULL, created INTEGER NOT NULL, banned INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS link (lid INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, poll_hash TEXT NOT NULL,
    ip TEXT NOT NULL, kit TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL,
    uid INTEGER NOT NULL DEFAULT 0, approved INTEGER NOT NULL DEFAULT 0, collected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tokens (tid INTEGER PRIMARY KEY, uid INTEGER NOT NULL, token_hash TEXT NOT NULL UNIQUE,
    kit TEXT NOT NULL, created INTEGER NOT NULL, last_used INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS accounts (uid INTEGER PRIMARY KEY, starter_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS owned (oid INTEGER PRIMARY KEY, uid INTEGER NOT NULL, card_no INTEGER NOT NULL,
    source TEXT NOT NULL, created INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS owned_uid ON owned (uid);
CREATE TABLE IF NOT EXISTS club_versions (vid INTEGER PRIMARY KEY, uid INTEGER NOT NULL, seq INTEGER NOT NULL,
    sha256 TEXT NOT NULL, base TEXT NOT NULL, card TEXT NOT NULL, card_uid TEXT NOT NULL, serial INTEGER NOT NULL,
    counter INTEGER NOT NULL, created INTEGER NOT NULL, ip TEXT NOT NULL, UNIQUE (uid, seq));
CREATE TABLE IF NOT EXISTS witness (wid INTEGER PRIMARY KEY, uid INTEGER NOT NULL, server TEXT NOT NULL,
    kind TEXT NOT NULL, sha256 TEXT NOT NULL, body TEXT NOT NULL, card_no INTEGER NOT NULL DEFAULT 0,
    created INTEGER NOT NULL, broken TEXT NOT NULL DEFAULT '', UNIQUE (uid, sha256));
CREATE TABLE IF NOT EXISTS formations (uid INTEGER PRIMARY KEY, cards TEXT NOT NULL, updated INTEGER NOT NULL);
"""


def open_store(path=None):
    """the bank's database (made the first time) -> the connection"""
    os.makedirs(BANK, exist_ok=True)
    conn = sqlite3.connect(path or os.path.join(BANK, "bank.sqlite3"), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def one(sql, args=()):
    row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


def value(sql, args=()):
    row = db.execute(sql, args).fetchone()
    return row[0] if row else None


def identity():
    """(name, secret) this server's witness tells the bank about each match with - made the first time, in data\\bank"""
    os.makedirs(BANK, exist_ok=True)
    name_file, secret_file = os.path.join(BANK, "server_name.txt"), os.path.join(BANK, "server_secret.txt")
    if not (os.path.isfile(name_file) and os.path.isfile(secret_file)):
        with open(name_file, "w", encoding="ascii") as f:
            f.write("this-server\n")
        with open(secret_file + ".tmp", "w", encoding="ascii") as f:
            f.write(secrets.token_hex(32) + "\n")
        os.replace(secret_file + ".tmp", secret_file)
    with open(name_file, encoding="ascii") as f:
        name = f.read().strip()
    with open(secret_file, encoding="ascii") as f:
        return name, f.read().strip()


# ---- passwords ----------------------------------------------------------------------------------------------------

def pw_hash(password, salt=None, rounds=200000):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return "pbkdf2_sha256$%d$%s$%s" % (rounds, salt, h)


def pw_ok(password, stored):
    try:
        _kind, rounds, salt, _h = stored.split("$")
        return hmac.compare_digest(pw_hash(password, salt, int(rounds)), stored)
    except (ValueError, AttributeError):
        return False


# ---- the cards ----------------------------------------------------------------------------------------------------

def starter(uid, rules):
    """the starter 11 for an account that has none yet: white cards in the rules' shape, never two cards of one
    footballer - given once (the accounts row claimed first) -> "granted", "had" or "no cards"""
    pool = [(no, pos, name.lower()) for no, (rarity, pos, name) in cards.items() if rarity == 1]
    secrets.SystemRandom().shuffle(pool)
    need, names, pick = dict(rules["starter"]), set(), []
    for no, pos, name in pool:
        if need.get(pos, 0) < 1 or name in names:
            continue
        need[pos] -= 1
        names.add(name)
        pick.append(no)
    if len(pick) != sum(rules["starter"].values()):
        return "no cards"
    if db.execute("INSERT OR IGNORE INTO accounts (uid, starter_at) VALUES (?, ?)", (uid, int(time.time()))).rowcount != 1:
        return "had"
    db.executemany("INSERT INTO owned (uid, card_no, source, created) VALUES (?, ?, 'starter', ?)",
                   [(uid, no, int(time.time())) for no in pick])
    return "granted"


def misses(uid):
    """match cards the account got since its last one better than black (starter cards not counted)"""
    last = 0
    for oid, no in db.execute("SELECT oid, card_no FROM owned WHERE uid=? AND source='match'", (uid,)):
        if cards.get(no, (0,))[0] >= 3:
            last = max(last, oid)
    return value("SELECT COUNT(*) FROM owned WHERE uid=? AND source='match' AND oid>?", (uid, last))


def draw(uid, rules):
    """one card drawn for the account by the rules - better than black growing with each miss, uniform within its
    group, never one it owns while its group has another -> its number, or 0 (no cards)"""
    if secrets.randbelow(10000) < rules["better"] + rules["luck"] * misses(uid):
        group = [no for no, c in cards.items() if c[0] >= 3]
    else:
        rarity = 1 if secrets.randbelow(1000) < rules["white"] else 2
        group = [no for no, c in cards.items() if c[0] == rarity]
    have = {r[0] for r in db.execute("SELECT card_no FROM owned WHERE uid=?", (uid,))} if rules["no_twice"] else set()
    for pool in ([no for no in group if no not in have], group):    # every card of the group owned: a copy
        if pool:
            return secrets.choice(pool)
    return 0


def award(uid, rules):
    """the card a finished match earns: drawn and owned -> its number; 0 when the account had one less than card_gap
    seconds ago (nobody earns two by sending the end twice)"""
    last = value("SELECT MAX(created) FROM owned WHERE uid=? AND source='match'", (uid,)) or 0
    if last > time.time() - rules["card_gap"]:
        return 0
    no = draw(uid, rules)
    if no:
        db.execute("INSERT INTO owned (uid, card_no, source, created) VALUES (?, ?, 'match', ?)", (uid, no, int(time.time())))
    return no


def owned_count(uid):
    out = {}
    for (no,) in db.execute("SELECT card_no FROM owned WHERE uid=?", (uid,)):
        out[no] = out.get(no, 0) + 1
    return out


# ---- a club card and the club data our server saw (wccfgame.php's rules, the kit's decoder) ---------------------------

def bits(buf, at):
    return D.bits_at(buf, at[0], at[1])


def card_read(raw):
    """a club card file as the game reads it -> {"uid", "serial", "counter", "players", "data"} - or why the game would
    refuse it (a new card with no club yet, and a used-up one, are refused here too)"""
    if len(raw) != D.CARD_BYTES:
        return "it is %d bytes, a club card file is %d" % (len(raw), D.CARD_BYTES)
    blocks = [raw[16 + 16 * i:32 + 16 * i] for i in range(256)]
    counter = raw[5] | raw[6] << 8
    if counter == 0xFFFF:
        return "a new card - no club made on it yet"
    if counter & 0xFF == 0:
        return "a used-up card (its manager moved to a new card)"
    if raw[4] == 0x20:
        return "its status byte is 0x20"
    if struct.unpack_from("<I", blocks[4], 8)[0] & 0xF0FFFFFF != 0x40667195:
        return "its block 4 signature is wrong"
    serial = struct.unpack(">I", blocks[6][12:16])[0]
    if serial < 10000000:
        return "its serial is below 10,000,000"
    if blocks[7] != blocks[0]:
        return "block 7 is not block 0 (a copied card)"
    version = struct.unpack(">I", blocks[8][:4])[0]
    if 1 <= version <= 4:
        return "SYSTEM_VERSION %d is refused by the game" % version
    a, b = D.copy_check(D.copy_of(blocks, "A")), D.copy_check(D.copy_of(blocks, "B"))
    if a["all_zero"] or b["all_zero"]:
        return "a copy of its data is all zeros"
    if not (a["good"] or b["good"]):
        return "both copies of its data fail their checksum"
    copy = D.copy_of(blocks, "A" if a["good"] else "B")
    return {"uid": raw[0:4].hex(), "serial": serial, "counter": counter,
            "players": [bits(copy, at) for at in PLAYER_CARD], "data": copy[:D.PAYLOAD_BYTES]}


def msg_data(kind, body):
    """the club data in a message the server kept: TEAM DATA RSLT +0 its size (u32), +4 the data; ENTRY SVR and TEAM
    DATA +0x38 its size (u16), +0x3a the data - b"" when it is too short"""
    if kind == "rslt":
        return body[4:4 + struct.unpack_from("<I", body)[0]] if len(body) >= 4 else b""
    return body[0x3a:0x3a + struct.unpack_from("<H", body, 0x38)[0]] if len(body) >= 0x3a else b""


def open_mark(data):
    """a club's data with the game's open mark set - what the card holds once the game leaves the locker room to play on"""
    if len(data) != D.PAYLOAD_BYTES:
        return data
    out = bytearray(data)
    out[OPEN_MARK >> 3] |= 0x80 >> (OPEN_MARK & 7)
    return bytes(out)


def rows(uid, limit=10):
    """the account's messages in the chain, the newest first: [{"kind", "data"}]"""
    return [{"kind": k, "data": msg_data(k, base64.b64decode(b))} for k, b in db.execute(
        "SELECT kind, body FROM witness WHERE uid=? AND broken='' ORDER BY wid DESC LIMIT ?", (uid, limit))]


def card_state(rs, i):
    """what the club card holds after the message at i of rs (the newest first): a session's start - its data; a
    match's end - its data (with the open mark when a match was played on from it); None when the list runs out"""
    played_on = False
    for r in rs[i:]:
        if r["kind"] == "team":
            played_on = True
            continue
        if r["kind"] == "entry":
            return r["data"]
        return open_mark(r["data"]) if played_on else r["data"]
    return None


def seen(uid):
    """the club data this server last saw for the account - what a save must equal: the end of its last match (also
    with the open mark) and each session's start after it; [] when the server has not seen the account play"""
    out = []
    for r in rows(uid):
        if r["kind"] == "entry":
            out.append(r["data"])
        elif r["kind"] == "rslt":
            out += [r["data"], open_mark(r["data"])]
            break
    return out


def values(data, names):
    out = {}
    for name in names:
        ps = positions(name)
        for n, at in enumerate(ps):
            out[name if len(ps) == 1 else "%s[%d]" % (name, n)] = bits(data, at)
    return out


def chain(prev, nxt, cut):
    """may nxt, the club data a match starts with, follow prev, what the server saw last ('' = yes, else why)?  A cut
    must show at the next start (bad endings + 1); nothing the club is worth may grow, no loss may shrink"""
    n = D.PAYLOAD_BYTES
    if len(prev) != n or len(nxt) != n:
        return "" if len(nxt) == n else "not a club's data"
    if bits(prev, CARD_ID) != bits(nxt, CARD_ID):
        return ""                                   # another card: a manager transfer, or a new club
    why = []
    was, now = bits(prev, BAD_ENDINGS), bits(nxt, BAD_ENDINGS)
    if now < was + (1 if cut else 0):
        why.append("bad endings %d -> %d%s" % (was, now, " after a cut match" if cut else ""))
    for names, up in ((GROW, 1), (SHRINK, -1)):
        before = values(prev, names)
        for k, v in values(nxt, names).items():
            if (v - before[k]) * up > 0:
                why.append("%s %d -> %d" % (k, before[k], v))
    for i, at in enumerate(PLAYER_CARD):
        if bits(prev, at) != bits(nxt, at):
            continue                                # another card in this place: registered anew
        for name in PLAYER_GROW:
            pos = positions(name)[i]
            a, z = bits(prev, pos), bits(nxt, pos)
            if z > a:
                why.append("Player[%d].%s %d -> %d" % (i, name, a, z))
    return (", ".join(why[:4]) + (" ..." if len(why) > 4 else ""))[:255]


def verdict(uid, kind, body):
    """the chain verdict for a message, before it is kept: a start checked against what the card held after the last
    message (a session's start after a start with no end = after a cut); an end takes its start's"""
    if kind == "rslt":
        last = one("SELECT kind, broken FROM witness WHERE uid=? ORDER BY wid DESC LIMIT 1", (uid,))
        return ("its start: " + last["broken"])[:255] if last and last["kind"] != "rslt" and last["broken"] else ""
    rs = rows(uid)
    prev = card_state(rs, 0) if rs else None
    return "" if prev is None else chain(prev, msg_data(kind, body), kind == "entry" and rs[0]["kind"] != "rslt")


def latest(uid):
    return one("SELECT * FROM club_versions WHERE uid=? ORDER BY seq DESC LIMIT 1", (uid,))


def dword_sum(buf):
    return sum(struct.unpack("<%dI" % (len(buf) // 4), buf)) & 0xFFFFFFFF


def cut_version(uid, last):
    """a match the server saw start and never end (a cut) leaves the card as it was at that start: when the latest kept
    version is the club that session or match began from, the cut card is that version's file with the cut data in
    both copies and the game's checksum, kept as the next version -> that row; None when there is no cut to keep"""
    rs = rows(uid) if last else []
    if not rs or rs[0]["kind"] == "rslt":
        return None
    first = 0
    while first < len(rs) and rs[first]["kind"] == "team":
        first += 1
    if first == len(rs):
        return None
    cut = card_state(rs, 0)
    began = card_state(rs, first + 1) if rs[first]["kind"] == "entry" else rs[first]["data"]
    raw = base64.b64decode(last["card"])
    card = card_read(raw)
    if cut is None or len(cut) != D.PAYLOAD_BYTES or isinstance(card, str) or card["data"] != began \
            or card["data"] == cut:
        return None
    if bits(cut, CARD_ID) != bits(began, CARD_ID):
        return None                                 # a manager transfer's new club, cut: its card is not here
    copy = cut + struct.pack("<I", (dword_sum(cut) + 1) & 0xFFFFFFFF)
    at = 16 + 16 * 8
    new = raw[:at] + copy + copy + raw[at + 2 * D.COPY_BYTES:]
    cur = db.execute("INSERT OR IGNORE INTO club_versions (uid, seq, sha256, base, card, card_uid, serial, counter, "
                     "created, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'cut match')",
                     (uid, last["seq"] + 1, hashlib.sha256(new).hexdigest(), last["sha256"],
                      base64.b64encode(new).decode("ascii"), last["card_uid"], last["serial"], last["counter"],
                      int(time.time())))
    return latest(uid) if cur.rowcount == 1 else None


# ---- the requests ---------------------------------------------------------------------------------------------------

def shown(code):
    return code[:4] + "-" + code[4:]


def token_user(f):
    """the account a POSTed token belongs to - or a 401 / 403 answer"""
    row = one("SELECT * FROM tokens WHERE token_hash=? AND revoked=0", (hashlib.sha256(f.get("token", "").encode()).hexdigest(),))
    user = one("SELECT * FROM users WHERE uid=?", (row["uid"],)) if row else None
    if not user:
        raise Answer(401, {"error": "unknown or revoked sign-in - sign in again from the game"})
    if user["banned"]:
        raise Answer(403, {"error": "this account is banned"})
    if row["last_used"] < time.time() - 60:
        db.execute("UPDATE tokens SET last_used=? WHERE tid=?", (int(time.time()), row["tid"]))
    return user


def b64(s):
    """strict base64 -> bytes, or None"""
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        return None


def request(action, f, ip, host, rules, ident):
    """one of the kit's requests -> (status, JSON body).  Under LOCK."""
    now = int(time.time())

    if action == "wccf_link_start":
        if value("SELECT COUNT(*) FROM link WHERE ip=? AND created>?", (ip, now - CODE_LIFE)) >= STARTS_PER_IP:
            return 429, {"error": "too many sign-in codes from this address - wait a few minutes"}
        db.execute("DELETE FROM link WHERE expires<?", (now - 86400,))
        kit = re.sub(r"[^A-Za-z0-9 ._:+-]", "", f.get("kit", ""))[:40]
        code = ""
        for _try in range(5):
            c = "".join(secrets.choice(ALPHABET) for _ in range(8))
            if not value("SELECT lid FROM link WHERE code=?", (c,)):
                code = c
                break
        if not code:
            return 503, {"error": "no free code - try again"}
        poll = secrets.token_hex(32)
        db.execute("INSERT INTO link (code, poll_hash, ip, kit, created, expires) VALUES (?, ?, ?, ?, ?, ?)",
                   (code, hashlib.sha256(poll.encode()).hexdigest(), ip, kit, now, now + CODE_LIFE))
        return 200, {"code": shown(code), "poll": poll, "url": "http://%s/link?code=%s" % (host, shown(code)),
                     "expires_in": CODE_LIFE, "interval": 3}

    if action == "wccf_link_poll":
        row = one("SELECT * FROM link WHERE poll_hash=?", (hashlib.sha256(f.get("poll", "").encode()).hexdigest(),))
        if not row:
            return 404, {"status": "unknown"}
        if row["collected"]:
            return 410, {"status": "collected"}
        if not row["uid"]:
            return 200, {"status": "expired" if row["expires"] < now else "waiting"}
        if row["approved"] + COLLECT_LIFE < now:
            return 200, {"status": "expired"}
        user = one("SELECT * FROM users WHERE uid=?", (row["uid"],))
        if not user or user["banned"]:
            return 403, {"status": "refused"}
        if db.execute("UPDATE link SET collected=? WHERE lid=? AND collected=0", (now, row["lid"])).rowcount != 1:
            return 410, {"status": "collected"}
        token = secrets.token_hex(32)
        db.execute("INSERT INTO tokens (uid, token_hash, kit, created, last_used) VALUES (?, ?, ?, ?, ?)",
                   (user["uid"], hashlib.sha256(token.encode()).hexdigest(), row["kit"], now, now))
        return 200, {"status": "approved", "token": token, "username": user["username"]}

    if action == "wccf_signout":
        cur = db.execute("UPDATE tokens SET revoked=1 WHERE token_hash=? AND revoked=0",
                         (hashlib.sha256(f.get("token", "").encode()).hexdigest(),))
        return 200, {"signed_out": cur.rowcount == 1}

    if action == "wccf_whoami":
        user = token_user(f)
        return 200, {"uid": user["uid"], "username": user["username"]}

    if action == "wccf_owned":
        user = token_user(f)
        uid, state = user["uid"], "had"
        if not value("SELECT uid FROM accounts WHERE uid=?", (uid,)):
            state = starter(uid, rules)
            if state == "no cards":
                return 503, {"error": "this server's card list is not ready - its host runs SETUP.exe"}
        mine = [r[0] for r in db.execute("SELECT card_no FROM owned WHERE uid=? ORDER BY oid", (uid,))]
        return 200, {"uid": uid, "username": user["username"], "cards": mine, "starter_given_now": state == "granted"}

    if action == "wccf_witness":
        # a game server saw an account's club: a session's start ("entry"), a match's start ("team") or a match's end
        # ("rslt": one card).  Only this server's witness: its secret, never a token
        if not ident or f.get("server", "") != ident[0] or not hmac.compare_digest(
                hashlib.sha256(f.get("secret", "").encode()).digest(), hashlib.sha256(ident[1].encode()).digest()):
            return 403, {"error": "not this server's witness"}
        try:
            uid = int(f.get("uid") or 0)
        except ValueError:
            uid = 0
        user = one("SELECT * FROM users WHERE uid=?", (uid,)) if uid > 0 else None
        if not user or user["banned"]:
            return 404, {"error": "no such account"}
        kind, body = f.get("kind", ""), b64(f.get("body", ""))
        if kind not in ("entry", "team", "rslt") or not body or len(body) > 0x2000:
            return 422, {"error": "not a message the game sends"}
        sha = hashlib.sha256(body).hexdigest()
        broken = verdict(uid, kind, body)
        if db.execute("INSERT OR IGNORE INTO witness (uid, server, kind, sha256, body, created, broken) VALUES "
                      "(?, ?, ?, ?, ?, ?, ?)", (uid, ident[0], kind, sha, base64.b64encode(body).decode("ascii"), now,
                                                broken)).rowcount != 1:
            return 200, {"card_no": 0, "why": "seen before"}
        card = award(uid, rules) if kind == "rslt" and not broken else 0
        if card:
            db.execute("UPDATE witness SET card_no=? WHERE uid=? AND sha256=?", (card, uid, sha))
        why = "before a match" if kind != "rslt" else "a finished match" if card else \
            "a card less than %d seconds ago" % rules["card_gap"] if not broken else "a match that does not count"
        return 200, {"card_no": card, "why": why if not broken else "%s - out of line: %s" % (why, broken)}

    if action == "wccf_club":
        user = token_user(f)
        row = latest(user["uid"])
        row = cut_version(user["uid"], row) or row
        return 200, ({"seq": row["seq"], "sha256": row["sha256"], "card": row["card"]} if row else {"seq": 0})

    if action == "wccf_club_save":
        user = token_user(f)
        uid = user["uid"]
        raw = b64(f.get("card", ""))
        card = "it is not base64" if raw is None else card_read(raw)
        if isinstance(card, str):
            return 422, {"error": "the club card was refused: " + card}
        sha = hashlib.sha256(raw).hexdigest()
        last = latest(uid)
        if last and last["sha256"] == sha:                      # sent again (a retry): kept already
            return 200, {"seq": last["seq"], "sha256": sha}
        if f.get("base", "") != (last["sha256"] if last else ""):
            return 409, {"error": "the server has a newer club card - the next start takes it",
                         "seq": last["seq"] if last else 0}
        same = False
        if last:
            same = card["uid"] == last["card_uid"] and card["serial"] == last["serial"]
            if same and card["counter"] > last["counter"]:
                return 422, {"error": "the club card was refused: an older save than the one kept"}
            if not same and last["counter"] & 0xFF > 1:
                return 422, {"error": "the club card was refused: another card - a club moves to a new card only when "
                                      "its contract has ended"}
        elif card["uid"] == "deadbeef" and card["serial"] == 10000001:
            return 422, {"error": "the club card was refused: it carries the id every older kit card shares - start "
                                  "your online club with kit 7 or newer"}
        if not last or same:                                    # what the server saw (a manager transfer: let by)
            saw = seen(uid)
            if not saw:
                return 422, {"error": "the club card was refused: this server has not seen this account play yet"}
            if card["data"] not in saw:
                return 422, {"error": "the club card was refused: it does not match what this server saw at the end of "
                                      "your last match"}
        have = owned_count(uid)
        for no in card["players"]:
            if no and have.get(no, 0) < 1:
                return 422, {"error": "the club card was refused: card %d is registered on it, and your account does "
                                      "not own it" % no}
            if no:
                have[no] -= 1
        if value("SELECT COUNT(*) FROM club_versions WHERE uid=? AND created>?", (uid, now - 60)) >= SAVES_PER_MINUTE:
            return 429, {"error": "too many club card saves in a minute - wait a moment"}
        seq = (last["seq"] if last else 0) + 1
        if db.execute("INSERT OR IGNORE INTO club_versions (uid, seq, sha256, base, card, card_uid, serial, counter, "
                      "created, ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (uid, seq, sha, last["sha256"] if last else "", base64.b64encode(raw).decode("ascii"), card["uid"],
                       card["serial"], card["counter"], now, ip)).rowcount != 1:
            return 409, {"error": "the server has a newer club card - the next start takes it", "seq": seq}
        return 200, {"seq": seq, "sha256": sha}

    if action == "wccf_formation":
        user = token_user(f)
        try:
            table = json.loads(f.get("cards", ""))
        except ValueError:
            table = None
        if not isinstance(table, list) or len(table) > TABLE_MAX:
            return 422, {"error": "the table was refused: not a list of at most %d cards" % TABLE_MAX}
        have, kept = owned_count(user["uid"]), []

        def num(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) <= 1.5
        for c in table:
            if not (isinstance(c, list) and len(c) == 3 and isinstance(c[0], int) and not isinstance(c[0], bool)
                    and num(c[1]) and num(c[2])):
                return 422, {"error": "the table was refused: each card is [card number, x, y] on the board"}
            if have.get(c[0], 0) < 1:
                return 422, {"error": "the table was refused: card %d is on it, and your account does not own it" % c[0]}
            have[c[0]] -= 1
            kept.append([c[0], round(float(c[1]), 3), round(float(c[2]), 3)])
        db.execute("INSERT OR REPLACE INTO formations (uid, cards, updated) VALUES (?, ?, ?)",
                   (user["uid"], json.dumps(kept), now))
        return 200, {"kept": len(kept)}

    return 404, {"error": "unknown action"}


# ---- the page the player approves the code on ----------------------------------------------------------------------

STYLE = ("body{margin:0;background:#0b1a2e;color:#e8eef6;font:16px/1.5 Segoe UI,Arial,sans-serif}"
         "main{max-width:440px;margin:8vh auto;padding:28px 32px;background:#13294a;border:1px solid #2c4a75;"
         "border-radius:10px;box-shadow:0 10px 40px #0008}h1{margin:0 0 4px;font-size:22px;color:#ffd84d}"
         ".sub{margin:0 0 20px;color:#9fb3cc;font-size:14px}label{display:block;margin:14px 0 4px;font-size:14px;"
         "color:#c9d6e6}input[type=text],input[type=password]{width:100%;box-sizing:border-box;padding:10px 12px;"
         "border:1px solid #2c4a75;border-radius:6px;background:#0b1a2e;color:#fff;font-size:16px}"
         ".code{letter-spacing:.15em;font-weight:700;text-transform:uppercase}.row{display:flex;gap:10px;"
         "margin-top:22px}button{flex:1;padding:11px;border:0;border-radius:6px;font-size:15px;font-weight:600;"
         "cursor:pointer}.go{background:#ffd84d;color:#13294a}.new{background:#2c4a75;color:#fff}"
         ".note{margin-top:18px;font-size:13px;color:#9fb3cc}.ok{color:#7dde92}.bad{color:#ff8a80}"
         "@media(max-width:480px){main{margin:16px 12px;padding:22px 20px}}")


def page(body, status=200):
    return status, ("<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
                    "content=\"width=device-width,initial-scale=1\"><title>Link your game - WCCF</title><style>%s"
                    "</style></head><body><main><h1>Link your game</h1><p class=sub>This server's own accounts - "
                    "not wccf.online's</p>%s</main></body></html>" % (STYLE, body))


def form(code="", name="", msg=""):
    e = html.escape
    return page(("<p class=bad>%s</p>" % e(msg) if msg else "") +
                "<form method=post action=/link><label for=code>The code your game shows</label>"
                "<input type=text class=code id=code name=code maxlength=9 value=\"%s\" autocomplete=off required>"
                "<label for=name>Your name on this server</label><input type=text id=name name=name maxlength=20 "
                "value=\"%s\" autocomplete=username required><label for=pw>Password</label><input type=password id=pw "
                "name=pw maxlength=100 autocomplete=current-password required><div class=row><button class=go name=do "
                "value=login>Log in and approve</button><button class=new name=do value=register>New account and "
                "approve</button></div></form><p class=note>Only approve a code that is on your game's screen right now."
                " This page is not encrypted: use a password you use nowhere else.</p>" % (e(code), e(name)))


def link_page(method, f, ip):
    """the page: GET - the form; POST - log in or make an account, then the code approved -> (status, HTML)"""
    code = re.sub(r"[^A-Z0-9]", "", f.get("code", "").upper())[:8]
    if method != "POST":
        return form(shown(code) if len(code) == 8 else "")
    name, pw, want = f.get("name", "").strip(), f.get("pw", ""), f.get("do", "")
    now = time.time()
    with LOCK:
        tries[ip] = [t for t in tries.get(ip, []) if t > now - CODE_LIFE]
        if len(tries[ip]) >= TRIES_PER_IP:
            return form(code, name, "Too many wrong passwords from this address - wait a few minutes.")
        row = one("SELECT * FROM link WHERE code=?", (code,)) if len(code) == 8 else None
        user = one("SELECT * FROM users WHERE username=?", (name,))
    if not row or row["uid"] or row["expires"] < now:
        return form("", name, "That code is not valid, or it ran out (they last 10 minutes) - start again from your "
                              "game: it shows a new code.")
    if want == "register":
        if not NAME.match(name):
            return form(code, name, "A name is 3-20 letters, digits, spaces, dots, - or _.")
        if not 6 <= len(pw) <= 100:
            return form(code, name, "A password is 6-100 characters.")
        stored = pw_hash(pw)                                 # slow on purpose: outside the lock
        with LOCK:
            try:
                db.execute("INSERT INTO users (username, pw, created) VALUES (?, ?, ?)", (name, stored, int(now)))
            except sqlite3.IntegrityError:
                return form(code, name, "That name is taken - choose another, or log in.")
            user = one("SELECT * FROM users WHERE username=?", (name,))
        log("%s: a new account, %s (uid %d)" % (ip, user["username"], user["uid"]))
    elif not user or not pw_ok(pw, user["pw"]):
        with LOCK:
            tries.setdefault(ip, []).append(now)
        return form(code, name, "That name and password do not match an account here.")
    if user["banned"]:
        return form("", "", "This account is banned on this server.")
    with LOCK:
        done = db.execute("UPDATE link SET uid=?, approved=? WHERE lid=? AND uid=0 AND expires>=?",
                          (user["uid"], int(now), row["lid"], int(now))).rowcount == 1
    if not done:
        return form("", name, "That code could not be approved - start again from your game.")
    log("%s: code %s approved for %s" % (ip, shown(code), user["username"]))
    return page("<p class=ok>Done. Your game is linked to <b>%s</b> - go back to it; it carries on by itself.</p>"
                % html.escape(user["username"]))


# ---- the server -----------------------------------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    rules, ident = RULES, None
    server_version = "WCCF-card-bank"

    def log_message(self, *args):
        pass

    def send(self, status, body, kind="application/json; charset=utf-8"):
        data = (json.dumps(body) if isinstance(body, dict) else body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def fields(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > BODY_MAX:
            raise Answer(413, {"error": "too big"})
        got = parse_qs(self.rfile.read(n).decode("utf-8", "replace") if n else "", keep_blank_values=True)
        return {k: v[0] for k, v in got.items()}

    def host(self):
        h = self.headers.get("Host") or ""
        return h if re.match(r"^[A-Za-z0-9.\-]{1,64}(:\d{1,5})?$", h) else "127.0.0.1:%d" % PORT

    def route(self, method):
        url = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        ip = self.client_address[0]
        try:
            if url.path == "/xmlhttp.php":
                if method != "POST":
                    raise Answer(405, {"error": "POST only"})
                f = self.fields()
                with LOCK:
                    try:
                        db.execute("BEGIN IMMEDIATE")
                        status, body = request(query.get("action", ""), f, ip, self.host(), self.rules, self.ident)
                        db.execute("COMMIT")
                    except BaseException:
                        db.execute("ROLLBACK")
                        raise
                self.send(status, body)
            elif url.path == "/link":
                f = dict(query, **(self.fields() if method == "POST" else {}))
                status, body = link_page(method, f, ip)
                self.send(status, body, "text/html; charset=utf-8")
            elif url.path == "/" and method == "GET":
                self.send(*page("<p>This is the card bank of a WCCF 2010-11 server. Your game opens the sign-in page "
                                "by itself when you play here online.</p><p><a style=color:#ffd84d href=/link>Type a "
                                "code by hand</a></p>"), "text/html; charset=utf-8")
            else:
                self.send(404, {"error": "not found"})
        except Answer as a:
            self.send(a.status, a.body)
        except Exception as ex:                      # never a stack trace to the network: said in the log
            log("%s %s from %s: %s: %s" % (method, url.path, ip, type(ex).__name__, ex))
            self.send(500, {"error": "the card bank failed on this request"})

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")


def serve(life, port=None, host="0.0.0.0"):
    """the bank on TCP port for life seconds (the tests: host 127.0.0.1, no firewall question)"""
    global db, cards
    db = open_store()
    cards = load_cards()
    rules, said = load_rules()
    for line in said:
        log("card bank: " + line)
    Handler.rules, Handler.ident = rules, identity()
    srv = ThreadingHTTPServer((host, port or PORT), Handler)
    srv.daemon_threads = True
    log("card bank listening on TCP %d: %d cards (%s), %d accounts; rules %s" % (
        port or PORT, len(cards), "the catalogue" if cards else "NONE - the host runs SETUP.exe",
        value("SELECT COUNT(*) FROM users"), json.dumps(rules, sort_keys=True)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    end = time.time() + life
    while time.time() < end:
        time.sleep(1.0)
    srv.shutdown()
    log("card bank: its time is up - stopping")


def admin(argv):
    """the host's commands: accounts, ban NAME, unban NAME, password NAME NEW -> exit code"""
    global db, cards
    db, cards = open_store(), load_cards()
    if argv == ["accounts"]:
        for u in db.execute("SELECT uid, username, banned FROM users ORDER BY uid"):
            n = value("SELECT COUNT(*) FROM owned WHERE uid=?", (u["uid"],))
            m = value("SELECT COUNT(*) FROM owned WHERE uid=? AND source='match'", (u["uid"],))
            print("%5d  %-20s %3d cards, %3d from matches%s" % (u["uid"], u["username"], n, m,
                                                                 "  BANNED" if u["banned"] else ""))
        return 0
    if len(argv) == 2 and argv[0] in ("ban", "unban"):
        cur = db.execute("UPDATE users SET banned=? WHERE username=?", (int(argv[0] == "ban"), argv[1]))
        print("%s %s" % (argv[1], ("banned" if argv[0] == "ban" else "let in again") if cur.rowcount else "- no such account"))
        return 0 if cur.rowcount else 1
    if len(argv) == 3 and argv[0] == "password":
        if not 6 <= len(argv[2]) <= 100:
            print("a password is 6-100 characters")
            return 1
        cur = db.execute("UPDATE users SET pw=? WHERE username=?", (pw_hash(argv[2]), argv[1]))
        print("%s: %s" % (argv[1], "password replaced" if cur.rowcount else "no such account"))
        return 0 if cur.rowcount else 1
    print(__doc__)
    return 2


def main(argv):
    global log_file
    if argv and not argv[0].replace(".", "", 1).isdigit():
        return admin(argv)
    life = float(argv[0]) if argv else 12 * 3600
    log_file = argv[1] if len(argv) > 1 else None
    try:
        serve(life)
    except OSError as ex:
        log("card bank: cannot listen on TCP %d (%s) - is one already running?" % (PORT, ex))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
