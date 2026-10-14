# -*- coding: utf-8 -*-
"""test_witness.py - server\\witness.py (2026-10-14, phase 3: a card per finished match): who sat where (the seat
desk's leases.json, a seat freed a moment ago, one address with two accounts), what goes to the website for each kind
of kept club data, refusals, a website out of reach (tried again later), files moved to done\\ and never sent twice,
the server's secret in no log line, no secret = not started (check.ps1 runs it; no network - the website's answers are
given to account.post here).
    python source\\test_witness.py"""
import base64
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from server import witness as W  # noqa: E402
from online import account as A  # noqa: E402

TMP = tempfile.mkdtemp(prefix="wccf-witness-")
FOLDER, LEASES = os.path.join(TMP, "witness"), os.path.join(TMP, "leases.json")
os.makedirs(FOLDER)
SECRET = "5" * 64
IDENT = ("this-pc-test", SECRET)
posts, answer = [], {"status": 200, "body": {"card_no": 1234, "why": "a finished match"}}
A.post = lambda action, fields: posts.append((action, dict(fields))) or (answer["status"], answer["body"])
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, "" if ok else "  (%s)" % (detail,)))


def leases(d):
    with open(LEASES, "w", encoding="utf-8") as f:
        json.dump(d, f)


def kept(name, body=b"R" * 0x1490):
    with open(os.path.join(FOLDER, name), "wb") as f:
        f.write(body)
    return os.path.join(FOLDER, name)


def run(fn, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        got = fn(*args)
    return got, out.getvalue()


seats = W.Seats(LEASES)
leases({"1": {"ip": "1.2.3.4", "uid": 7, "username": "tester"}, "2": {"ip": "5.6.7.8", "uid": None, "username": None}})
seats.look(1000.0)
check("the signed-in seat at an address", seats.at("1.2.3.4") == ("ok", {"seat": "1", "uid": 7, "username": "tester"}),
      seats.at("1.2.3.4"))
check("a seat not signed in: nobody", seats.at("5.6.7.8")[0] == "none")
check("an address with no seat: nobody", seats.at("9.9.9.9")[0] == "none")
leases({})
seats.look(1000.0 + W.RECENT - 1)
check("a seat freed a moment ago still counts (a quick quit after the locker room)", seats.at("1.2.3.4")[0] == "ok")
seats.look(1000.0 + W.RECENT + 1)
check("... not after RECENT seconds", seats.at("1.2.3.4")[0] == "none")
leases({"1": {"ip": "1.2.3.4", "uid": 7, "username": "a"}, "3": {"ip": "1.2.3.4", "uid": 8, "username": "b"}})
seats.look(2000.0)
check("two accounts at one address (one house): whose it was cannot be told", seats.at("1.2.3.4")[0] == "none" and
      "2 signed-in accounts" in seats.at("1.2.3.4")[1], seats.at("1.2.3.4"))

seats = W.Seats(LEASES)
leases({"1": {"ip": "127.0.0.1", "uid": 7, "username": "tester"}})
rslt = kept("20261014-120000-1-rslt-127.0.0.1_52046.bin", b"RSLT" * 100)
entry = kept("20261014-115000-2-entry-127.0.0.1_52046.bin", b"ENTR" * 100)
other = kept("20261014-120001-3-rslt-8.8.8.8_1000.bin")
odd = kept("something else.bin")
retry = {}
_r, out = run(W.tick, FOLDER, IDENT, seats, retry, 3000.0)
sent = {p[1]["kind"]: p[1] for p in posts}
check("a finished match goes to the website: this server, its secret, the account, the body", "rslt" in sent and
      sent["rslt"]["server"] == "this-pc-test" and sent["rslt"]["secret"] == SECRET and sent["rslt"]["uid"] == 7 and
      base64.b64decode(sent["rslt"]["body"]) == b"RSLT" * 100, sent.get("rslt", {}).get("uid"))
check("... and what came before a match too", "entry" in sent and sent["entry"]["uid"] == 7)
check("... and the card it earned is said", "card 1234" in out, out)
check("an address with nobody signed in: nothing sent, said why", len(posts) == 2 and "no signed-in seat at 8.8.8.8" in out,
      out)
check("a file the hook would not name: set aside", "not a name the hook gives" in out, out)
done = sorted(os.listdir(os.path.join(FOLDER, "done")))
check("every handled file moved to done\\ (kept)", len(done) == 4 and not [f for f in os.listdir(FOLDER) if f.endswith(".bin")],
      done)
check("the server's secret in no line said", SECRET not in out, out)
posts.clear()
run(W.tick, FOLDER, IDENT, seats, retry, 3001.0)
check("nothing sent twice", posts == [], posts)

answer.update(status=0, body={"error": "timed out"})
late = kept("20261014-121000-4-rslt-127.0.0.1_52046.bin")
_r, out = run(W.tick, FOLDER, IDENT, seats, retry, 3002.0)
check("the website out of reach: the file stays, said", os.path.exists(late) and "could not be reached" in out, out)
posts.clear()
run(W.tick, FOLDER, IDENT, seats, retry, 3002.0 + W.RETRY - 1)
check("... not tried again at once", posts == [], posts)
answer.update(status=200, body={"card_no": 0, "why": "a card less than 240 seconds ago"})
_r, out = run(W.tick, FOLDER, IDENT, seats, retry, 3002.0 + W.RETRY + 1)
check("... then tried again, and the website's answer said", len(posts) == 1 and not os.path.exists(late) and
      "kept, no card (a card less than 240 seconds ago)" in out, out)
answer.update(status=403, body={"error": "not one of our game servers"})
kept("20261014-122000-5-rslt-127.0.0.1_52046.bin")
_r, out = run(W.tick, FOLDER, IDENT, seats, retry, 4000.0)
check("refused by the website (a wrong secret): said, not tried again", "refused by wccf.online" in out and
      not [f for f in os.listdir(FOLDER) if f.endswith(".bin")], out)

data = os.path.join(TMP, "data")
os.makedirs(data)
check("no server name or secret: not one of wccf.online's", W.server_id(data) is None)
with open(os.path.join(data, "server_name.txt"), "w") as f:
    f.write("x\n")
with open(os.path.join(data, "server_secret.txt"), "w") as f:
    f.write("short\n")
check("a secret too short to be one: none", W.server_id(data) is None)
with open(os.path.join(data, "server_secret.txt"), "w") as f:
    f.write(SECRET + "\n")
check("name + secret: this server", W.server_id(data) == ("x", SECRET))
W.DATA = os.path.join(TMP, "nothing here")
rc, out = run(W.main, ["5", ""])
check("no secret: the witness does not start, and says so", rc == 2 and "earn no cards here" in out, out)

shutil.rmtree(TMP, ignore_errors=True)
print("witness: %s" % ("all %d checks passed" % len(results) if all(results) else
                       "%d of %d FAILED" % (results.count(False), len(results))))
sys.exit(0 if all(results) else 1)
