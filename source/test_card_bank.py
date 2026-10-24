# -*- coding: utf-8 -*-
"""test_card_bank.py - a server's own card bank (2026-10-23, server\\card_bank.py), driven by the kit's own code: the real
bank on 127.0.0.1 with a scratch data folder and a made-up card list; account.py signs in through its page, club.py
gets the starter 11 and saves the club card, witness.py tells it about a finished match, and the card drawn follows the
rules (bad-luck count, never a card twice).  Then the chain check, a cut match, the rules file, the host's commands,
the field positions against the website's own tables (source\\website\\wccfgame.php) and hostile requests.  No game, no
real website, nothing outside the scratch folder (check.ps1 runs it).
    python source\\test_card_bank.py"""
import base64
import json
import os
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = free_port()
TMP = tempfile.mkdtemp(prefix="wccf-card-bank-")
SITE = "http://127.0.0.1:%d" % PORT
os.environ.update({"WCCF_BANK_DATA": TMP, "WCCF_BANK_PORT": str(PORT), "WCCF_WEBSITE": SITE,
                   "WCCF_ACCOUNT_FILE": os.path.join(TMP, "account.json"), "WCCF_NO_POPUP": "1"})
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))

# a made-up card list: 5 white cards per line, 10 black, 10 better (no Sega data)
CARDS = [(n, 1, ("GK", "DF", "MF", "FW")[(n - 1) // 5], "White %d" % n) for n in range(1, 21)] + \
        [(n, 2, "MF", "Black %d" % n) for n in range(21, 31)] + [(n, 3 + n % 3, "FW", "Rare %d" % n) for n in range(31, 41)]
os.makedirs(os.path.join(TMP, "cache"))
with open(os.path.join(TMP, "cache", "catalogue.tsv"), "w", encoding="utf-8", newline="\n") as f:
    f.write("card_no\tis_placeholder\trarity\tposition_name\tname_full_latin\n")
    f.writelines("%d\t0\t%d\t%s\t%s\n" % c for c in CARDS)
    f.write("99\t1\t1\tGK\tPlaceholder\n")

from cards import decode as D  # noqa: E402
from hardware import card_reader  # noqa: E402
from online import account, club  # noqa: E402
from server import card_bank as B  # noqa: E402
from server import witness as W  # noqa: E402

fails, checks = [], [0]


def check(cond, what, got=""):
    checks[0] += 1
    if not cond:
        fails.append(what)
        print("FAILED: %s %s" % (what, got))


class Clock:
    """account.py's clock in the test: a sign-in that is never approved runs out at once, not in 10 real minutes"""
    t = 1e9

    def time(self):
        return self.t

    def strftime(self, *a):
        return time.strftime(*a)


clock = Clock()
account.time = clock


def http(path, fields=None, method="POST", raw=None):
    data = raw if raw is not None else urllib.parse.urlencode(fields or {}).encode() if method == "POST" else None
    req = urllib.request.Request(SITE + path, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode("utf-8")


def set_bits(buf, at, v):
    start, width = at
    for k in range(width):
        i = start + k
        bit = (v >> (width - 1 - k)) & 1
        buf[i >> 3] = (buf[i >> 3] & ~(0x80 >> (i & 7))) | (bit << (7 - (i & 7)))


def club_data(serial, players, wins=0):
    d = bytearray(D.PAYLOAD_BYTES)
    set_bits(d, B.CARD_ID, serial)
    for i, no in enumerate(players):
        set_bits(d, B.PLAYER_CARD[i], no)
    set_bits(d, B.positions("COACH_TOTAL_WIN_NUM")[0], wins)
    return bytes(d)


def card_file(data, base=None, counter=0xFFF0):
    """a played club card holding data in both copies (the game's checksum), on base's id or a new one"""
    c = card_reader.Card.blank(None)
    if base:
        c.uid, c.blocks[0][:], c.blocks[6][:] = base[:4], base[16:32], base[112:128]
    c.counter = counter
    c.blocks[7][:] = c.blocks[0]
    copy = data + struct.pack("<I", (B.dword_sum(data) + 1) & 0xFFFFFFFF)
    both = copy + copy
    for i in range(210):
        c.blocks[8 + i][:] = both[16 * i:16 * i + 16]
    return c.image()


def serial_of(raw):
    return struct.unpack(">I", raw[124:128])[0]          # block 6, bytes 12-15


def rslt(data):
    return struct.pack("<I", len(data)) + data


def entry(data):
    return bytes(0x38) + struct.pack("<H", len(data)) + data


threading.Thread(target=B.serve, args=(3600, PORT, "127.0.0.1"), daemon=True).start()
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
        break
    except OSError:
        time.sleep(0.1)
IDENT = B.identity()


def witness(kind, body, uid, secret=None):
    return account.post("wccf_witness", {"server": IDENT[0], "secret": secret or IDENT[1], "uid": uid, "kind": kind,
                                         "body": base64.b64encode(body).decode()})


# ---- sign in with the kit's own account.py, through the bank's page ----
codes = []
account.show_code = codes.append


def approve(name, pw, do):
    def sleep(s):
        clock.t += s
        if codes and not getattr(sleep, "done", False):
            sleep.done = True
            http("/link", {"code": codes[-1], "name": name, "pw": pw, "do": do})
    return sleep


got = account.sign_in(open_browser=False, sleep=approve("Tester", "secret-1", "register"))
check(got and got.get("username") == "Tester", "sign-in: a new account made on the page, the code approved", got)
token = (got or {}).get("token", "")
check(account.check(token) == ("ok", "Tester"), "who-am-I knows the token", account.check(token))
codes.clear()
again = account.sign_in(open_browser=False, sleep=approve("Tester", "wrong-pw", "login"))
check(again is None, "a wrong password approves nothing (the code runs out)", again)
st, page = http("/link", {"code": "ABCD-EFGH", "name": "x", "pw": "y", "do": "login"})
check(st == 200 and "not valid" in page, "an unknown code is refused on the page", page[-200:])

# ---- the starter 11 (club.py's fetch) ----
state, own = club.fetch(token)
uid = own.get("uid") if isinstance(own, dict) else None
cards = own.get("cards", []) if isinstance(own, dict) else []
lines = [B.cards[c][1] for c in cards] if cards else []
check(state == "ok" and len(cards) == 11 and all(B.cards[c][0] == 1 for c in cards), "11 white starter cards", own)
check(sorted(lines) == sorted(["GK"] + ["DF"] * 4 + ["MF"] * 4 + ["FW"] * 2), "the starter's shape 1-4-4-2", lines)
state2, own2 = club.fetch(token)
check(own2.get("cards") == cards, "asked again: the same 11, nothing more", own2)
check(99 not in B.cards and len(B.cards) == 40, "the catalogue's placeholder is not a card", len(B.cards))

# ---- a finished match through the real witness.py ----
WD = os.path.join(TMP, "witness")
os.makedirs(WD)
with open(os.path.join(TMP, "leases.json"), "w") as f:
    json.dump({"1": {"ip": "10.0.0.5", "uid": uid, "username": "Tester"}}, f)
seats = W.Seats(os.path.join(TMP, "leases.json"))
seats.look(time.time())
blank = card_reader.Card.blank(None).image()
SERIAL = serial_of(blank)
d0 = club_data(SERIAL, cards)
for name, body in (("20261023-120000-1-entry-10.0.0.5_1.bin", entry(d0)), ("20261023-121000-2-rslt-10.0.0.5_1.bin", rslt(d0))):
    with open(os.path.join(WD, name), "wb") as f:
        f.write(body)
said = [W.handle(os.path.join(WD, n), W.server_id(os.path.join(TMP, "bank")), seats) for n in sorted(os.listdir(WD))]
check(said[0][0] and "kept, no card" in said[0][1], "witness: the session's start kept, no card", said[0])
check(said[1][0] and re.search(r"card \d+", said[1][1]), "witness: the finished match earns a card", said[1])
state, own = club.fetch(token)
won = own["cards"][11:] if state == "ok" else []
check(len(own.get("cards", [])) == 12 and won and won[0] not in cards, "the 12th card is owned, and not one already held",
      own)
st, b = witness("rslt", rslt(d0), uid)
check(st == 200 and b.get("why") == "seen before", "the same end again: nothing more", b)
st, b = witness("rslt", rslt(club_data(SERIAL, cards, wins=1)), uid, secret="0" * 64)
check(st == 403, "a wrong server secret is refused", (st, b))

# ---- the club card save (club.py's upload, the website's checks) ----
CARD = os.path.join(TMP, "online", "club.bin")
os.makedirs(os.path.dirname(CARD))
good = card_file(d0, blank)
with open(CARD, "wb") as f:
    f.write(good)
check(club.upload(token, CARD, os.path.dirname(CARD))[0] == "kept", "a save equal to what the server saw is kept")
check(club.upload(token, CARD, os.path.dirname(CARD))[0] == "same", "the same save again: nothing new")
bad = card_file(club_data(SERIAL, cards[:10] + [40]), blank, 0xFFEF)
st, b = account.post("wccf_club_save", {"token": token, "base": club.synced(os.path.dirname(CARD))["sha256"],
                                        "card": base64.b64encode(bad).decode()})
check(st == 422 and "does not match" in b.get("error", ""), "a save the server never saw is refused", b)
st, b = account.post("wccf_club_save", {"token": token, "base": "", "card": base64.b64encode(bad).decode()})
check(st == 409, "a save built on an older version: newer one here", (st, b))
st, b = account.post("wccf_club_save", {"token": token, "base": "x", "card": "%%%"})
check(st == 422 and "base64" in b.get("error", ""), "junk instead of a card is refused", b)

# ---- the chain: a start that grew since the last end does not count; then a cut match makes the next version ----
st, b = witness("entry", entry(club_data(SERIAL, cards, wins=5)), uid)
check(st == 200 and "out of line" in b.get("why", "") and "COACH_TOTAL_WIN_NUM" in b["why"], "a start with more wins "
      "than the last end is out of line", b)
st, b = witness("rslt", rslt(club_data(SERIAL, cards, wins=6)), uid)
check(st == 200 and b.get("card_no") == 0 and "does not count" in b.get("why", ""), "its end earns no card", b)
with B.LOCK:
    B.db.execute("DELETE FROM witness WHERE broken!=''")          # back to the honest chain: the end of d0
d1 = bytearray(club_data(SERIAL, cards))
d1[B.OPEN_MARK >> 3] |= 0x80 >> (B.OPEN_MARK & 7)                 # START marked the card open
d1 = bytes(d1)
st, b = witness("entry", entry(d1), uid)
check(st == 200 and "out of line" not in b.get("why", ""), "a fair start after the end is in line", b)
st, b = account.post("wccf_club", {"token": token})
cut = B.card_read(base64.b64decode(b.get("card", ""))) if st == 200 else "no answer"
check(st == 200 and b.get("seq") == 2 and not isinstance(cut, str) and cut["data"] == d1,
      "a start with no end (a cut): the next start gets the cut card, version 2",
      (st, b.get("seq"), cut if isinstance(cut, str) else ""))

# ---- the draw: bad-luck count and never a card twice ----
rules = dict(B.RULES)
with B.LOCK:
    B.db.execute("INSERT INTO owned (uid, card_no, source, created) VALUES " + ",".join(["(?, 21, 'match', 0)"] * 40),
                 [uid] * 40)
    m = B.misses(uid)
    better = sum(B.cards[B.draw(uid, rules)][0] >= 3 for _ in range(4000)) / 4000.0
check(m >= 40, "40 more black match cards: the bad-luck count is at least 40", m)
check(0.12 < better < 0.19 + 0.0025 * (m - 40), "after %d misses about %.1f%% better than black" % (m, 5 + m * 0.25),
      better)
with B.LOCK:
    B.db.execute("INSERT INTO owned (uid, card_no, source, created) VALUES (?, 31, 'match', 0)", (uid,))
    m2 = B.misses(uid)
    have = {r[0] for r in B.db.execute("SELECT card_no FROM owned WHERE uid=?", (uid,))}
    whites_left = [n for n, c in B.cards.items() if c[0] == 1 and n not in have]
    for n in whites_left[1:]:
        B.db.execute("INSERT INTO owned (uid, card_no, source, created) VALUES (?, ?, 'starter', 0)", (uid, n))
    drawn = {B.draw(uid, dict(rules, better=0, luck=0, white=1000)) for _ in range(200)}
check(m2 == 0, "a better card resets the count", m2)
check(drawn == set(whites_left[:1]), "every white card but one owned: each white draw is that one", (drawn, whites_left[:1]))
with B.LOCK:
    drawn = {B.draw(uid, dict(rules, better=0, luck=0, white=1000, no_twice=False)) for _ in range(300)}
check(len(drawn) > 5, "no_twice off: owned cards come again", len(drawn))

# ---- the rules file ----
rf = os.path.join(TMP, "card_rules.json")
with open(rf, "w") as f:
    json.dump({"better": 800, "luck": -1, "white": "x", "no_twice": False, "starter": {"GK": 2, "DF": 4, "MF": 4, "FW": 3},
               "nonsense": 1}, f)
r, said = B.load_rules(rf)
check(r["better"] == 800 and r["luck"] == 25 and r["white"] == 700 and r["no_twice"] is False
      and r["starter"] == {"GK": 2, "DF": 4, "MF": 4, "FW": 3}, "the rules file: good values taken", r)
check(len(said) == 3, "the rules file: each bad value said and left out", said)
with open(rf, "w") as f:
    f.write("{not json")
check(B.load_rules(rf)[0] == B.RULES, "a broken rules file: the usual rules")

# ---- the field positions are the website's own (source\website\wccfgame.php) ----
with open(os.path.join(KIT, "source", "website", "wccfgame.php"), encoding="utf-8") as f:
    php = f.read()
table = {m.group(1): tuple(map(int, m.group(2).split(","))) for m in re.finditer(r"'(\w+)' => \[([\d, ]+)\]", php)}
bad = []
for name in B.GROW + B.SHRINK:
    bit, width, count, stride = table[name]
    if B.positions(name) != [(bit + stride * k, width) for k in range(count)]:
        bad.append(name)
for name in B.PLAYER_GROW:
    off, width = table[name]
    if any(B.positions(name)[i] != (B.PLAYER_CARD[i][0] + off, width) for i in range(16)):
        bad.append(name)
check(not bad and len(table) >= 45, "every chain field sits where the website reads it", bad)
check(B.PLAYER_CARD[0][0] == int(re.search(r"WCCFGAME_PLAYER_BIT = (\d+)", php).group(1)) and
      B.CARD_ID == tuple(map(int, re.search(r"WCCFGAME_CARD_ID = \[(\d+), (\d+)\]", php).groups())),
      "the player cards and the card id where the website reads them")

# ---- hostile requests, and the host's commands ----
check(http("/xmlhttp.php?action=wccf_whoami", method="GET")[0] == 405, "GET on the requests: refused")
check(http("/xmlhttp.php?action=nope", {})[0] == 404, "an unknown action")
check(http("/xmlhttp.php?action=wccf_whoami", {"token": "z" * 64})[0] == 401, "an unknown token")
try:            # the bank answers 413 without reading it all: the sender may see the connection closed instead
    too_big = http("/xmlhttp.php?action=wccf_owned", raw=b"x" * (B.BODY_MAX + 1))[0]
except OSError:
    too_big = 413
check(too_big == 413 and http("/xmlhttp.php?action=wccf_whoami", {"token": token})[0] == 200,
      "a body too big: refused, and the bank answers the next one", too_big)
st, b = account.post("wccf_formation", {"token": token, "cards": json.dumps([[cards[0], 0.1, 2.5]])})
check(st == 422, "a table card off the board", b)
st, b = account.post("wccf_formation", {"token": token, "cards": json.dumps([[40, 0, 0]] * 3)})
check(st == 422 and "does not own" in b.get("error", ""), "a table card the account does not own", b)
st, b = account.post("wccf_formation", {"token": token, "cards": json.dumps([[cards[0], 0.1, -0.5]])})
check(st == 200 and b.get("kept") == 1, "a fair table is kept", b)
st, b = witness("rslt", b"x" * 0x2001, uid)
check(st == 422, "a witness message far too big", b)
codes.clear()
evil = account.sign_in(open_browser=False, sleep=approve("<script>x</script>", "secret-2", "register"))
check(evil is None, "a name with < > is refused")
st, page = http("/link?code=%3Cb%3E", method="GET")
check(st == 200 and "<b>" not in page.split("<form", 1)[1], "the page never echoes markup")
st, page = http("/xmlhttp.php?action=wccf_link_start", {"kit": "t"})
code = json.loads(page).get("code", "")
for _ in range(B.TRIES_PER_IP):
    http("/link", {"code": code, "name": "Tester", "pw": "nope", "do": "login"})
st, page = http("/link", {"code": code, "name": "Tester", "pw": "secret-1", "do": "login"})
check("Too many wrong passwords" in page, "too many wrong passwords from one address: refused for a while")
B.tries.clear()
check(B.admin(["ban", "Tester"]) == 0, "the host bans an account")
check(account.check(token)[0] == "refused", "a banned account's token is refused", account.check(token))
check(B.admin(["unban", "Tester"]) == 0 and account.check(token)[0] == "ok", "let in again")
check(B.admin(["password", "Tester", "new-pass-1"]) == 0, "the host replaces a forgotten password")
codes.clear()
got = account.sign_in(open_browser=False, sleep=approve("tester", "new-pass-1", "login"))
check(got and got.get("username") == "Tester", "log in with the new password (the name's case does not matter)", got)
check(account.post("wccf_signout", {"token": token})[1].get("signed_out") is True and
      account.check(token)[0] == "refused", "SIGN OUT: the token is refused from then on")
check(B.admin(["password", "Nobody", "abcdef"]) == 1 and B.admin(["nonsense"]) == 2, "the host's commands: wrong ones said")

print("card bank: %s" % ("all %d checks passed" % checks[0] if not fails else "%d of %d FAILED" % (len(fails), checks[0])))
sys.exit(1 if fails else 0)
