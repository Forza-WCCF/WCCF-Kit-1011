# -*- coding: utf-8 -*-
"""test_online_club.py - the online club (online\\club.py, 2026-10-14): the owned cards from the website make the
CATALOGUE (only those, each once, the header first); the list kept for when the website is down; refused, unknown or
empty answers play with the slot card; a new club's cards laid out on the table, owned by no board; the online club's
board found by formation.py; play.py's run record and environment carry it (check.ps1 runs it; no network - the
website's answers are given to account.post here).
    python source\\test_online_club.py"""
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

TMP = tempfile.mkdtemp(prefix="wccf-club-")
os.environ["WCCF_ACCOUNT_FILE"] = os.path.join(TMP, "account.json")      # before the imports: account reads it then
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from online import account as A  # noqa: E402
from online import club as C  # noqa: E402
from cards import formation as F  # noqa: E402
import play  # noqa: E402

SAVE, SEAT = os.path.join(TMP, "save"), os.path.join(TMP, "seat1")
os.makedirs(SEAT)
C.SAVE, C.ONLINE = SAVE, os.path.join(SAVE, "online")
C.CATALOGUE, C.OWNED_CATALOGUE = os.path.join(TMP, "catalogue.tsv"), os.path.join(TMP, "catalogue_online.tsv")
HEAD = "card_no\tset_no\tposition_name\tname\r\n"
ROWS = {25: "DF", 31: "GK", 40: "MF", 41: "MF", 52: "FW", 60: "DF", 77: "FW", 90: "MF"}
with open(C.CATALOGUE, "w", encoding="utf-8", newline="") as f:
    f.write(HEAD + "".join("%d\t1\t%s\tPLAYER %d\r\n" % (no, pos, no) for no, pos in ROWS.items()))
answer = {}
A.post = lambda action, fields: answer[action]
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print("%s  %s%s" % ("ok  " if ok else "FAIL", name, "  (%s)" % detail if detail and not ok else ""))


def run(fn, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        got = fn(*args)
    return got, out.getvalue()


A.save({"token": "t" * 64, "username": "tester", "website": A.WEBSITE, "linked": "x"})
answer["wccf_owned"] = (200, {"uid": 7, "username": "tester", "cards": [52, 31, 25, 25, 40, 999], "starter_given_now": True})
got, said = run(C.prepare, "t" * 64)
check("signed in: the online club's card is the account's own", got and got["card"] == os.path.join(SAVE, "online", "u7", "club.bin"),
      got)
with open(C.OWNED_CATALOGUE, encoding="utf-8", newline="") as f:
    owned = f.read()
check("the CATALOGUE lists only the owned cards, each once, header first, lines as they were",
      owned == HEAD + "".join("%d\t1\t%s\tPLAYER %d\r\n" % (no, ROWS[no], no) for no in (25, 31, 40, 52)), repr(owned))
check("a card the catalogue does not know (999) is left out, and said cards counted", "4 cards" in said, said)
kept = C.read_owned(7)
check("the owned list is kept beside the card", kept and kept["cards"] == [52, 31, 25, 25, 40, 999], kept)
check("the account file learns its uid (for when the website is down)", (A.load() or {}).get("uid") == 7, A.load())
check("the token is in nothing said", "t" * 16 not in said, said)

answer["wccf_owned"] = (0, {"error": "connection refused"})
got, said = run(C.prepare, "t" * 64)
check("the website down: the kept list plays", got and got["uid"] == 7 and "as they were" in said, said)
answer["wccf_owned"] = (503, {"error": "the card list is not loaded on the website yet"})
got, said = run(C.prepare, "t" * 64)
check("the website not ready (503): the kept list plays too", got is not None and "as they were" in said, said)
answer["wccf_owned"] = (0, {"error": "connection refused"})
shutil.rmtree(os.path.join(SAVE, "online", "u7"))
got, said = run(C.prepare, "t" * 64)
check("the website down and nothing kept: the slot card plays (None)", got is None and "slot" in said, said)

answer["wccf_owned"] = (401, {"error": "unknown or revoked sign-in"})
got, said = run(C.prepare, "t" * 64)
check("a refused sign-in: the slot card plays (None)", got is None and "refused" in said, said)
answer["wccf_owned"] = (200, {"username": "tester", "cards": [25]})
got, said = run(C.prepare, "t" * 64)
check("an answer without the account's number (an older website): not used", got is None, said)
answer["wccf_owned"] = (200, {"uid": 7, "username": "tester", "cards": [998, 999]})
got, said = run(C.prepare, "t" * 64)
check("no owned card in this kit's catalogue: the slot card plays (None)", got is None, said)

answer["wccf_owned"] = (200, {"uid": 7, "username": "tester", "cards": sorted(ROWS) * 3})
online, _said = run(C.prepare, "t" * 64)
squad = C.squad_of(online["catalogue"])
check("the squad by line (GK DF MF FW), each card once",
      squad == [(31, "GK"), (25, "DF"), (60, "DF"), (40, "MF"), (41, "MF"), (90, "MF"), (52, "FW"), (77, "FW")], squad)
said, _out = run(C.table, SEAT, online)
table = F.table(SEAT)
check("no club yet: every owned card laid out on the table", sorted(c[1] for c in table) == sorted(ROWS), table)
check("... the goalkeeper in goal", any(c[1] == 31 and c[3] > 0.8 for c in table), table)
check("... owned by no board (the club the game makes takes it)", F.owner(SEAT) is None, F.owner(SEAT))
check("... and said how to make the club", any("press START" in s for s in said), said)
board = os.path.join(SAVE, "online", "u7", "club.board")
os.makedirs(board)
with open(os.path.join(board, "id.txt"), "w") as f:
    f.write("abc123\n")
check("formation finds the online club's board", F.all_boards(SAVE).get("abc123") == board, F.all_boards(SAVE))

env = play.kit_env("G:\\game", online)
check("play.py: the run's programs get the online card and its CATALOGUE",
      env.get("WCCF_CLUB_CARD") == online["card"] and env.get("WCCF_CATALOGUE") == online["catalogue"], env)
check("play.py: without one, the slot (no WCCF_CLUB_CARD)", "WCCF_CLUB_CARD" not in play.kit_env("G:\\game"))
play.RUNNING = os.path.join(TMP, "running.json")
play.write_running({123: "seat 1 launcher"}, "remote", "1.2.3.4", 2, online)
info = play.running_info()
check("play.py: the run record keeps the online club", play.online_of(info) == online, info)
play.write_running({}, "local", None)
check("play.py: a run without one records none", play.online_of(play.running_info()) is None, play.running_info())
with open(play.RUNNING, "w") as f:
    json.dump({"online": "junk"}, f)
check("play.py: a broken record means the slot", play.online_of(play.running_info()) is None)

shutil.rmtree(TMP, ignore_errors=True)
print("online club: %s" % ("all %d checks passed" % len(results) if all(results) else
                           "%d of %d FAILED" % (results.count(False), len(results))))
sys.exit(0 if all(results) else 1)
