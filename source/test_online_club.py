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

# play.py's rule for going online (the owner, 2026-10-14: only the online club online; your own cards on this PC)
check("not signed in: not online", play.online_club(lambda: None, lambda t: online) == (None, "no wccf.online sign-in"))
check("signed in but the online club not ready: not online",
      play.online_club(lambda: "t", lambda t: None) == (None, "your online club is not ready"))
check("signed in with the online club: online", play.online_club(lambda: "t", lambda t: online) == (online, None))

# SETTINGS' SIGN OUT: done at the next start, then taken out of the file; RESTART NOW then makes it a full start
play.PANEL = os.path.join(TMP, "panel.txt")
with open(play.PANEL, "w") as f:
    f.write("play_on=online\nserver=1.2.3.4\naccount=signout\n")
calls = []
A.signout = lambda: calls.append(1) or "tester signed out"
_r, said = run(play.apply_account_request)
with open(play.PANEL) as f:
    left = f.read()
check("SIGN OUT asked: done at the start, the request then taken out", calls == [1] and "account=" not in left and
      "server=1.2.3.4" in left and "signed out" in said, (calls, left, said))
run(play.apply_account_request)
check("... once", calls == [1], calls)
play.write_running({123: "seat 1 launcher"}, "local", None)
with open(play.PANEL, "w") as f:
    f.write("play_on=this_pc\n")
fits = play.cabinet_restart_fits()
with open(play.PANEL, "w") as f:
    f.write("play_on=this_pc\naccount=signout\n")
check("RESTART NOW with a SIGN OUT waiting is a full start (the seat lease holds the old sign-in)",
      fits and not play.cabinet_restart_fits())

# the club card kept on wccf.online (2c/2d): upload, the start-time sync, the contract-end swap, the helper's sends
import base64  # noqa: E402
import hashlib  # noqa: E402
import time  # noqa: E402

posts = []


def fake_post(action, fields):
    posts.append((action, dict(fields)))
    got = answer[action]
    return got(fields) if callable(got) else got


A.post = fake_post
CL = os.path.join(TMP, "clubs")


def card_of(counter, fill=1):
    b = bytearray([fill]) * C.CARD_BYTES
    b[5], b[6] = counter & 0xFF, counter >> 8
    return bytes(b)


def put(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def kept_answer(fields):
    data = base64.b64decode(fields["card"])
    return 200, {"seq": 5, "sha256": sha(data)}


one = os.path.join(CL, "a", "club.bin")
put(one, card_of(0xFFFE, 7))
answer["wccf_club_save"] = kept_answer
posts.clear()
check("upload: a new save kept, built on no version yet", C.upload("t", one, os.path.dirname(one)) == ("kept", 5) and
      posts[-1][1]["base"] == "" and base64.b64decode(posts[-1][1]["card"]) == card_of(0xFFFE, 7), posts)
check("... and the version is remembered beside the card", C.synced(os.path.dirname(one)) == {"sha256": sha(card_of(0xFFFE, 7)), "seq": 5})
posts.clear()
check("upload: the same save again is not sent", C.upload("t", one, os.path.dirname(one)) == ("same", 5) and not posts, posts)
put(one, card_of(0xFFFD, 7))
answer["wccf_club_save"] = (409, {"error": "the website has a newer club card"})
check("upload: another PC saved since -> newer", C.upload("t", one, os.path.dirname(one))[0] == "newer" and
      posts[-1][1]["base"] == sha(card_of(0xFFFE, 7)), posts[-1:])
answer["wccf_club_save"] = (422, {"error": "card 5 is not owned"})
check("upload: refused, and why", C.upload("t", one, os.path.dirname(one)) == ("refused", "card 5 is not owned"))
answer["wccf_club_save"] = (0, {"error": "timed out"})
check("upload: the website out of reach", C.upload("t", one, os.path.dirname(one)) == ("unreachable", "timed out"))
check("upload: no card file", C.upload("t", os.path.join(CL, "none", "club.bin"), CL)[0] == "refused")
used = os.path.join(CL, "used", "club.bin")
put(used, card_of(0x0000, 7))
posts.clear()
check("upload: a used-up card (a manager transfer left it) is not sent - the website keeps the new card instead",
      C.upload("t", used, os.path.dirname(used))[0] == "used up" and not posts, posts)

two = os.path.join(CL, "b", "club.bin")
answer["wccf_club"] = (200, {"seq": 0})
said = C.sync("t", two)
blank = C.card_bytes(two)
check("sync, nothing anywhere: a new blank card with an id of its own", blank is not None and blank[5:7] == b"\xff\xff"
      and blank[:4] != b"\xde\xad\xbe\xef" and "a new card" in " ".join(said), (said, blank[:8] if blank else None))
posts.clear()
check("sync, nothing on the website and a blank here: nothing to do", C.sync("t", two) == [] and
      [p for p in posts if p[0] == "wccf_club_save"] == [], posts)
put(two, card_of(0xFFFE, 2))
answer["wccf_club_save"] = kept_answer
said = C.sync("t", two)
check("sync, nothing on the website, this PC's club: it goes up", "kept on wccf.online now" in " ".join(said) and
      C.synced(os.path.dirname(two)).get("sha256") == sha(card_of(0xFFFE, 2)), said)
site_card = card_of(0xFFFC, 3)
answer["wccf_club"] = (200, {"seq": 9, "sha256": sha(site_card), "card": base64.b64encode(site_card).decode()})
put(two, site_card)
check("sync, the same card on both: nothing said", C.sync("t", two) == [] and
      C.synced(os.path.dirname(two)) == {"sha256": sha(site_card), "seq": 9})
put(two, card_of(0xFFFB, 3))
said = C.sync("t", two)
check("sync, a save here after the website's version: it goes up now", "went to wccf.online now" in " ".join(said) and
      posts[-1][1]["base"] == sha(site_card) and C.card_bytes(two) == card_of(0xFFFB, 3), said)
C.set_synced(os.path.dirname(two), sha(site_card), 9)
put(two, card_of(0xFFFA, 3))
answer["wccf_club_save"] = (422, {"error": "an older save than the one kept"})
said = C.sync("t", two)
aside = [f for f in os.listdir(os.path.join(os.path.dirname(two), "backup")) if ".replaced-" in f]
check("sync, the website refuses this PC's save: the website's card plays, this PC's kept in backup\\",
      C.card_bytes(two) == site_card and len(aside) == 1 and "did not take" in " ".join(said), (said, aside))
C.set_synced(os.path.dirname(two), "an older version", 8)
put(two, card_of(0xFFF9, 3))
posts.clear()
said = C.sync("t", two)
check("sync, the website's is newer (another PC): it wins, nothing sent, this PC's kept",
      C.card_bytes(two) == site_card and not [p for p in posts if p[0] == "wccf_club_save"] and
      len([f for f in os.listdir(os.path.join(os.path.dirname(two), "backup")) if ".replaced-" in f]) == 2, said)
answer["wccf_club"] = (0, {"error": "no network"})
put(two, card_of(0xFFF8, 3))
said = C.sync("t", two)
check("sync, the website out of reach: this PC's card plays", C.card_bytes(two) == card_of(0xFFF8, 3) and
      "could not be read" in " ".join(said), said)
three = os.path.join(CL, "c", "club.bin")
C.sync("t", three)
check("sync, out of reach with no card here: a blank to make the club on", (C.card_bytes(three) or b"")[5:7] == b"\xff\xff")
answer["wccf_club"] = (200, {"seq": 2, "sha256": "x", "card": base64.b64encode(b"short").decode()})
said = C.sync("t", two)
check("sync, the website's card is not a card file: this PC's plays", C.card_bytes(two) == card_of(0xFFF8, 3) and
      "not a card file" in " ".join(said), said)

from cards import wallet  # noqa: E402
got_args = []
keep_ft = wallet.finish_transfer
wallet.finish_transfer = lambda *a: got_args.append(a) or (True, "manager transfer finished")
answer["wccf_club"] = (200, {"seq": 0})
said = C.ready("t", two)
wallet.finish_transfer = keep_ft
check("a finished manager transfer of the online card is put away first (wallet.finish_transfer)",
      got_args == [(two, os.path.join(os.path.dirname(two), "club.new.bin"), os.path.join(os.path.dirname(two), "transferred"))]
      and said[0] == "manager transfer finished", (got_args, said))

from helpers import panel as H  # noqa: E402
import kit_common as K  # noqa: E402
sent = []
keep_upload, keep_session = C.upload, K.card_session
C.upload = lambda token, card, folder: sent.append(card) or ("kept", len(sent))
session = ["open"]
K.card_session = lambda card, since=None: (session[0], 0)
four = os.path.join(CL, "d", "club.bin")
put(four, card_of(0xFFFE, 4))
A.save({"token": "t" * 64, "username": "tester", "website": A.WEBSITE, "linked": "x"})
keep_checks, H.ClubSync.CHECKS = H.ClubSync.CHECKS, ()     # the sends alone first; the card looks below
sync = H.ClubSync(four)
now = time.time()


def ticks(*at):
    for t in at:
        sync.tick(now + t)
        if sync.busy:
            sync.busy.join(5)


ticks(0, 1, 3)
check("the helper: nothing sent while a match is on (the session open)", sent == [], sent)
session[0] = "closed"
ticks(4)
check("the helper: the locker-room save goes up once the card holds still", sent == [four], sent)
ticks(5, 9)
check("... once", sent == [four], sent)
put(four, card_of(0xFFFD, 4))
ticks(10, 11, 13)
check("... and the next save after the next match", sent == [four, four], sent)
C.upload = lambda token, card, folder: sent.append("x") or ("unreachable", "no network")
put(four, card_of(0xFFFC, 4))
ticks(20, 23)
n = len(sent)
ticks(40, 60)
check("the helper: the website out of reach - not again within the minute", len(sent) == n, sent)
ticks(84)
check("... then tried again", len(sent) == n + 1, sent)
H.ClubSync(None).tick(now)
check("the helper offline (no online club): nothing", True)
check("the helper watches the online card and the new card a manager transfer puts beside it (its first save shows "
      "the match's card; 2026-10-15 the real transfer showed none)",
      [s.card for s in H.club_syncs(four, TMP)] == [four, os.path.join(os.path.dirname(four), "club.new.bin")] and
      [s.card for s in H.club_syncs(None, TMP)] == [None, None])

# phase 3: the card a finished match earned - found after the save, into the CATALOGUE and dealt.txt for the panel
looks, found = [], [[], [77]]
H.ClubSync.CHECKS = keep_checks
keep_new = C.new_cards
C.new_cards = lambda token, data: looks.append(now) or found.pop(0)
sync = H.ClubSync(four, TMP)
sync.done = None
C.upload = lambda token, card, folder: ("kept", 9)
put(four, card_of(0xFFFB, 4))
ticks(100, 103)
check("after a save, the helper asks for the match's card a few seconds later", sync.checks and looks == [], sync.checks)
ticks(108)
check("... first look: nothing yet", len(looks) == 1, looks)
ticks(118)
check("... next look: the card - no more looks after it", len(looks) == 2 and sync.checks == [], (looks, sync.checks))
ticks(140, 170)
check("... none after that", len(looks) == 2, looks)
C.new_cards = keep_new
C.upload, K.card_session = keep_upload, keep_session

data = os.path.join(TMP, "data7")
os.makedirs(data)
with open(C.OWNED_CATALOGUE, "w", encoding="utf-8", newline="") as f:
    f.write(HEAD + "25\t1\tDF\tPLAYER 25\r\n31\t1\tGK\tPLAYER 31\r\n")
put(os.path.join(C.ONLINE, "u7", "owned.json"), json.dumps({"uid": 7, "username": "tester", "cards": [25, 31]}).encode())
answer["wccf_owned"] = (200, {"uid": 7, "username": "tester", "cards": [25, 31, 40]})
got = C.new_cards("t", data)
with open(C.OWNED_CATALOGUE, encoding="utf-8", newline="") as f:
    listed = f.read()
with open(os.path.join(data, "dealt.txt")) as f:
    dealt = f.read()
check("a card the match earned: found, into the CATALOGUE once, named for the panel", got == [40] and
      listed.count("40\t1\tMF") == 1 and dealt == "1 40\n", (got, listed, dealt))
check("... and remembered as owned", C.read_owned(7)["cards"] == [25, 31, 40])
check("asked again: nothing new, nothing named again", C.new_cards("t", data) == [] and
      open(os.path.join(data, "dealt.txt")).read() == "1 40\n")
answer["wccf_owned"] = (200, {"uid": 7, "username": "tester", "cards": [25, 31, 40, 40]})
got = C.new_cards("t", data)
with open(C.OWNED_CATALOGUE, encoding="utf-8", newline="") as f:
    listed = f.read()
check("a second copy of a card: shown (\"2 40\"), the CATALOGUE not listing it twice", got == [40] and
      listed.count("40\t1\tMF") == 1 and open(os.path.join(data, "dealt.txt")).read() == "2 40\n", (got, listed))
answer["wccf_owned"] = (0, {"error": "no network"})
check("the website out of reach: nothing", C.new_cards("t", data) == [])

other = "Q:\\elsewhere\\club.bin" if not K.KIT.upper().startswith("Q:") else "R:\\elsewhere\\club.bin"
check("a card on another drive is shown whole (CI's temp folder: relpath raised, 2026-10-14)", K.shown(other) == other)
check("a card in the kit is shown from the kit's folder",
      K.shown(os.path.join(K.KIT, "data", "save", "x.bin")) == os.path.join("data", "save", "x.bin"))

shutil.rmtree(TMP, ignore_errors=True)
print("online club: %s" % ("all %d checks passed" % len(results) if all(results) else
                           "%d of %d FAILED" % (results.count(False), len(results))))
sys.exit(0 if all(results) else 1)
