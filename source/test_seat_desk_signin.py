# -*- coding: utf-8 -*-
"""test_seat_desk_signin.py - the seat desk and the wccf.online sign-in (2026-10-14): the real desk on loopback, a fake
website's who-am-I beside it. Without data\\require_signin.txt a PC that is not signed in still gets a seat; with it,
"ERR sign in: ..."; a good token gets a seat and the log names the account; a refused token gets "ERR sign in
again"; the website down lets a token in unchecked; the token is never in the desk's log; and the real seat.py, signed
in, holds a seat as its account.  The club card word (2026-10-15): the lease keeps the card a signed-in seat plays,
seat.py says it, and a desk from before it is asked again without it, the sign-in kept (check.ps1 runs it; loopback
only, no game, no real website).
    python source\\test_seat_desk_signin.py"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


DESK, SITE = free_port(), free_port()
TMP = tempfile.mkdtemp(prefix="wccf-desk-signin-")
REQUIRE = os.path.join(TMP, "require_signin.txt")
LOG = os.path.join(TMP, "seat_broker.txt")
os.environ.update({"WCCF_BROKER_PORT": str(DESK), "WCCF_WEBSITE": "http://127.0.0.1:%d" % SITE,
                   "WCCF_REQUIRE_FILE": REQUIRE, "WCCF_CONTROL_LOG": os.path.join(TMP, "_dbg_control.txt"),
                   "WCCF_HOLD_FILE": os.path.join(TMP, "no_hold.txt"), "WCCF_ACCOUNT_FILE": os.path.join(TMP, "account.json"),
                   "WCCF_LEASE_PING": "0.3", "WCCF_LEASES_FILE": os.path.join(TMP, "leases.json")})

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from server import seat_desk as D  # noqa: E402
from online import seat as S  # noqa: E402

fails, checks = [], [0]
GOOD = {"a1" * 32: (7, "Tester"), "b2" * 32: (8, "Second"), "c3" * 32: (9, "Third"), "d4" * 32: (10, "Fourth")}
REVOKED = "e5" * 32
UNCHECKED = "f6" * 32
site = {"down": False}


def check(cond, what):
    checks[0] += 1
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


class Site(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()).items()}
        token = form.get("token", "")
        if site["down"]:
            code, body = 503, {"error": "down for a test"}
        elif token in GOOD:
            code, body = 200, {"uid": GOOD[token][0], "username": GOOD[token][1]}
        else:
            code, body = 401, {"error": "unknown or revoked sign-in"}
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


web = HTTPServer(("127.0.0.1", SITE), Site)
threading.Thread(target=web.serve_forever, daemon=True).start()
threading.Thread(target=D.main, args=(["60", LOG],), daemon=True).start()
for _ in range(50):                                      # the desk listening
    try:
        socket.create_connection(("127.0.0.1", DESK), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)


def ask(line):
    """one claim; returns (the reply line, the open connection - close it to free the seat)"""
    c = socket.create_connection(("127.0.0.1", DESK), timeout=5)
    c.sendall(line.encode() + b"\n")
    buf = b""
    while b"\n" not in buf:
        data = c.recv(256)
        if not data:
            break
        buf += data
    return buf.split(b"\n", 1)[0].decode(), c


def log_text():
    time.sleep(0.2)
    with open(LOG, encoding="utf-8") as f:
        return f.read()


# sign-in not needed (no require_signin.txt): a PC that is not signed in gets a seat, as kit 6's do
reply, c = ask("WANT")
check(reply == "SEAT 1 PROJECTOR 0", "not needed: a plain WANT gets a seat (%r)" % reply)
check("seat 1 is not signed in" in log_text(), "the log says the seat is not signed in")
c.close()

# a signed-in PC: a seat, and the log names the account
good = "a1" * 32
reply, c = ask("WANT TOKEN " + good)
check(reply.startswith("SEAT "), "a good token gets a seat (%r)" % reply)
check("signed in as Tester (uid 7)" in log_text(), "the log names the account")
with open(os.environ["WCCF_LEASES_FILE"], encoding="utf-8") as f:     # for server\witness.py (2026-10-14)
    leased = f.read()
check(json.loads(leased).get(reply.split()[1]) == {"ip": "127.0.0.1", "uid": 7, "username": "Tester"} and
      good not in leased, "leases.json: the seat, its address and account - never the token (%r)" % leased)
c.close()
time.sleep(0.5)
with open(os.environ["WCCF_LEASES_FILE"], encoding="utf-8") as f:
    check(reply.split()[1] not in json.load(f), "leases.json: the seat gone once it is free")

# WANT SEAT n with a token
reply, c = ask("WANT SEAT 5 TOKEN " + "b2" * 32)
check(reply == "SEAT 5 PROJECTOR 0", "WANT SEAT 5 + a good token gets seat 5 (%r)" % reply)
c.close()

# the club card word (2026-10-15): a signed-in seat's lease keeps the card it plays (leases.json, for the witness)
reply, c = ask("WANT CARD 26548962 TOKEN " + good)
check(reply.startswith("SEAT "), "WANT CARD c + a good token gets a seat (%r)" % reply)
with open(os.environ["WCCF_LEASES_FILE"], encoding="utf-8") as f:
    lease = json.load(f).get(reply.split()[1] if reply.startswith("SEAT ") else "", {})
check(lease.get("card") == 26548962 and lease.get("uid") == 7, "leases.json: the seat's club card (%r)" % lease)
check("club card 26548962" in log_text(), "the desk's log names the club card")
c.close()
reply, c = ask("WANT SEAT 6 CARD 26548962")
check(reply == "SEAT 6 PROJECTOR 0", "a card word without a sign-in: a seat as before (%r)" % reply)
c.close()

# a token the website refuses: no seat
reply, c = ask("WANT TOKEN " + REVOKED)
check(reply.startswith("ERR sign in again"), "a refused token: ERR sign in again (%r)" % reply)
c.close()

# sign-in needed (require_signin.txt exists - looked at on every claim, no restart)
open(REQUIRE, "w").close()
reply, c = ask("WANT")
check(reply.startswith("ERR sign in:"), "needed: a plain WANT is refused (%r)" % reply)
c.close()
reply, c = ask("WANT TOKEN " + "c3" * 32)
check(reply.startswith("SEAT "), "needed: a good token still gets a seat (%r)" % reply)
c.close()

# the website down: a token is let in unchecked (never everyone locked out because the website is down)
site["down"] = True
reply, c = ask("WANT TOKEN " + UNCHECKED)
check(reply.startswith("SEAT "), "the website down: a token is let in (%r)" % reply)
check("let in unchecked" in log_text(), "the log says it was let in unchecked")
c.close()
site["down"] = False

# the real seat.py, signed in: it holds a seat, and the desk knows who it is - and which club card it plays
with open(os.environ["WCCF_ACCOUNT_FILE"], "w", encoding="utf-8") as f:
    json.dump({"token": "d4" * 32, "username": "Fourth"}, f)
CARDFILE = os.path.join(TMP, "club.bin")
card_raw = bytearray(4112)
card_raw[124:128] = (22481763).to_bytes(4, "big")              # block 6, bytes 12-15: the card's serial
with open(CARDFILE, "wb") as f:
    f.write(card_raw)
os.environ["WCCF_CLUB_CARD"] = CARDFILE
out = os.path.join(TMP, "lease.json")
threading.Thread(target=S.main, args=(["127.0.0.1", out, "3"],), daemon=True).start()
for _ in range(50):
    if os.path.exists(out):
        break
    time.sleep(0.1)
try:
    with open(out, encoding="utf-8") as f:
        got = json.load(f)
except (OSError, ValueError):
    got = {}
check("seat" in got, "seat.py, signed in, holds a seat (%r)" % got)
check("signed in as Fourth (uid 10), club card 22481763" in log_text(), "the desk knows seat.py's account and club card")
del os.environ["WCCF_CLUB_CARD"]

# seat.py when the desk refuses the sign-in: the answer play.py turns into "play on this PC"
with open(os.environ["WCCF_ACCOUNT_FILE"], "w", encoding="utf-8") as f:
    json.dump({"token": REVOKED}, f)
out2 = os.path.join(TMP, "lease2.json")
S.main(["127.0.0.1", out2, "3"])
with open(out2, encoding="utf-8") as f:
    got2 = json.load(f)
check(got2.get("error") == "signin" and "again" in got2.get("detail", ""), "seat.py writes 'signin' for play.py (%r)" % got2)

# an older server's seat desk (kit 6 and before) does not know TOKEN: seat.py asks again without it - a signed-in
# kit 7 must still join a host who has not updated
OLD = free_port()
old_lines, kept = [], []


def old_desk():
    srv = socket.socket()
    srv.bind(("127.0.0.1", OLD))
    srv.listen(4)
    srv.settimeout(10)
    for _ in range(2):
        try:
            c, _addr = srv.accept()
        except OSError:
            return
        line = c.recv(256).decode("ascii", "replace").strip()
        old_lines.append(line)
        if "TOKEN" in line:
            c.sendall(b"ERR say WANT or WANT SEAT n\n")                 # kit 6's answer to anything it does not know
            c.close()
        else:
            c.sendall(b"SEAT 2 PROJECTOR 0\n")
            kept.append(c)


threading.Thread(target=old_desk, daemon=True).start()
with open(os.environ["WCCF_ACCOUNT_FILE"], "w", encoding="utf-8") as f:
    json.dump({"token": "d4" * 32}, f)
S.PORT, desk_port = OLD, S.PORT
out3 = os.path.join(TMP, "lease3.json")
threading.Thread(target=S.main, args=(["127.0.0.1", out3, "2"],), daemon=True).start()
for _ in range(50):
    if os.path.exists(out3):
        break
    time.sleep(0.1)
S.PORT = desk_port
try:
    with open(out3, encoding="utf-8") as f:
        got3 = json.load(f)
except (OSError, ValueError):
    got3 = {}
check(got3.get("seat") == 2, "an older seat desk: seat.py still gets a seat (%r)" % got3)
check(len(old_lines) == 2 and "TOKEN" in old_lines[0] and old_lines[1] == "WANT",
      "it asked once with the token, then again without it (%r)" % [ln[:12] for ln in old_lines])

# a seat desk from before the club card word (kit 7 test builds before 2026-10-15) knows TOKEN, not CARD: seat.py asks
# again without the card - and keeps its sign-in
MID = free_port()
mid_lines, mid_kept = [], []


def mid_desk():
    srv = socket.socket()
    srv.bind(("127.0.0.1", MID))
    srv.listen(4)
    srv.settimeout(10)
    for _ in range(2):
        try:
            c, _addr = srv.accept()
        except OSError:
            return
        line = c.recv(256).decode("ascii", "replace").strip()
        mid_lines.append(line)
        if "CARD" in line:
            c.sendall(b"ERR say WANT or WANT SEAT n\n")
            c.close()
        else:
            c.sendall(b"SEAT 3 PROJECTOR 0\n")
            mid_kept.append(c)


threading.Thread(target=mid_desk, daemon=True).start()
os.environ["WCCF_CLUB_CARD"] = CARDFILE
S.PORT, desk_port = MID, S.PORT
out4 = os.path.join(TMP, "lease4.json")
threading.Thread(target=S.main, args=(["127.0.0.1", out4, "2"],), daemon=True).start()
for _ in range(50):
    if os.path.exists(out4):
        break
    time.sleep(0.1)
S.PORT = desk_port
del os.environ["WCCF_CLUB_CARD"]
try:
    with open(out4, encoding="utf-8") as f:
        got4 = json.load(f)
except (OSError, ValueError):
    got4 = {}
check(got4.get("seat") == 3, "a seat desk without the card word: seat.py still gets a seat (%r)" % got4)
check(len(mid_lines) == 2 and "CARD 22481763" in mid_lines[0] and "TOKEN" in mid_lines[0] and "CARD" not in mid_lines[1]
      and "TOKEN" in mid_lines[1], "it asked with the card, then again without it - the sign-in kept (%r)" %
      [ln[:24] for ln in mid_lines])

# never a token in the desk's log
text = log_text()
check(not any(t in text for t in list(GOOD) + [REVOKED, UNCHECKED]), "no token is ever written to the desk's log")

web.shutdown()
print("seat desk sign-in: %d of %d failed" % (len(fails), checks[0]) if fails else
      "seat desk sign-in: all %d checks passed" % checks[0])
sys.exit(1 if fails else 0)
