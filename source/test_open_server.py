# -*- coding: utf-8 -*-
"""test_open_server.py - hosting needs no wccf.online (2026-10-23): the real seat desk beside the real card bank on
127.0.0.1, and a player's PC as play.py runs it - it asks the desk where to sign in (BANK), signs in there through the
bank's page, and takes a seat that the desk checks with the bank.  This PC's wccf.online sign-in is never sent to that
server; an older desk (no BANK) means wccf.online as before; a cabinet restart keeps the same bank; the online club
lives in a folder of its own per bank; and play.py's choice of bank on a server (data\\card_bank.txt, the owner's
servers on wccf.online).  Scratch folders only, no game, no real website (check.ps1 runs it).
    python source\\test_open_server.py"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


BANK, DESK, OLD = free_port(), free_port(), free_port()
TMP = tempfile.mkdtemp(prefix="wccf-open-server-")
os.makedirs(os.path.join(TMP, "cache"))
os.makedirs(os.path.join(TMP, "logs"))
with open(os.path.join(TMP, "cache", "catalogue.tsv"), "w", encoding="utf-8", newline="\n") as f:
    f.write("card_no\tis_placeholder\trarity\tposition_name\tname_full_latin\n")
    f.writelines("%d\t0\t1\t%s\tWhite %d\n" % (n, ("GK", "DF", "MF", "FW")[(n - 1) // 5], n) for n in range(1, 21))
os.environ.update({"WCCF_BANK_DATA": TMP, "WCCF_BANK_PORT": str(BANK), "WCCF_BROKER_PORT": str(DESK),
                   "WCCF_WEBSITE": "http://127.0.0.1:%d" % BANK, "WCCF_NO_POPUP": "1",
                   "WCCF_ACCOUNT_FILE": os.path.join(TMP, "account.json"),
                   "WCCF_CONTROL_LOG": os.path.join(TMP, "_dbg_control.txt"), "WCCF_HOLD_FILE": os.path.join(TMP, "x"),
                   "WCCF_REQUIRE_FILE": os.path.join(TMP, "require_signin.txt"),
                   "WCCF_LEASES_FILE": os.path.join(TMP, "leases.json"), "WCCF_LEASE_PING": "0.3"})
KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import kit_common as K  # noqa: E402
import play  # noqa: E402
from online import account, club  # noqa: E402
from online import seat as S  # noqa: E402
from server import card_bank as B  # noqa: E402
from server import seat_desk as D  # noqa: E402

fails, checks = [], [0]


def check(cond, what, got=""):
    checks[0] += 1
    if not cond:
        fails.append(what)
        print("FAILED: %s %s" % (what, got))


class Clock:
    t = 1e9

    def time(self):
        return self.t

    def strftime(self, *a):
        return time.strftime(*a)


clock = Clock()
account.time = clock
codes = []
account.show_code = codes.append

threading.Thread(target=B.serve, args=(600, BANK, "127.0.0.1"), daemon=True).start()
threading.Thread(target=D.main, args=(["60", os.path.join(TMP, "logs", "seat_broker.txt")],), daemon=True).start()


def old_desk():                                  # a seat desk from before BANK: "ERR say ..." to anything new
    srv = socket.socket()
    srv.bind(("127.0.0.1", OLD))
    srv.listen(4)
    while True:
        c, _ = srv.accept()
        c.recv(256)
        c.sendall(b"ERR say WANT or WANT SEAT n\n")
        c.close()


threading.Thread(target=old_desk, daemon=True).start()
for port in (BANK, DESK, OLD):
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)

# ---- the desk says where to sign in ----
check(S.bank("127.0.0.1") == "http://127.0.0.1:%d" % BANK, "the desk names its own card bank", S.bank("127.0.0.1"))
del os.environ["WCCF_BANK_PORT"]
check(D.bank_answer() == ("BANK %s\n" % D.WEBSITE).encode(), "a desk with no bank of its own names its website")
os.environ["WCCF_BANK_PORT"] = str(BANK)
S.PORT = OLD
check(S.bank("127.0.0.1") is None, "a desk from before BANK: nothing (wccf.online, as before)")
S.PORT = free_port()
check(S.bank("127.0.0.1") is None, "no desk at all: nothing")
S.PORT = DESK

# ---- a player's PC: a wccf.online sign-in it already has is never sent to this server ----
with open(os.path.join(TMP, "account.json"), "w") as f:
    json.dump({"token": "ab" * 32, "username": "OnWccfOnline", "website": "https://wccf.online"}, f)
S.PORT = OLD
play.use_bank("127.0.0.1")
check(account.WEBSITE == "https://wccf.online" and account.ACCOUNT == os.path.join(TMP, "account.json"),
      "an older server: wccf.online and its sign-in file, as before", (account.WEBSITE, account.ACCOUNT))
S.PORT = DESK
play.use_bank("127.0.0.1")
key = "127.0.0.1_%d" % BANK
check(account.WEBSITE == "http://127.0.0.1:%d" % BANK and account.ACCOUNT == os.path.join(TMP, "accounts", key + ".json"),
      "this server: its bank and a sign-in file of its own", (account.WEBSITE, account.ACCOUNT))
check(os.environ["WCCF_WEBSITE"] == account.WEBSITE and os.environ["WCCF_ACCOUNT_FILE"] == account.ACCOUNT,
      "the run's programs get the same bank and file")
check(account.load() is None and S.signed() == b"", "the wccf.online token is not this server's: none sent")
check(account.site_name() == "the server's card bank (127.0.0.1:%d)" % BANK, "messages name the server's bank")


def approve(name, pw, do):
    def sleep(s):
        clock.t += s
        if codes and not getattr(sleep, "done", False):
            sleep.done = True
            urllib.request.urlopen(urllib.request.Request(
                "http://127.0.0.1:%d/link" % BANK, urllib.parse.urlencode({"code": codes[-1], "name": name, "pw": pw,
                                                                            "do": do}).encode()), timeout=10).read()
    return sleep


token = account.ensure(open_browser=False, sleep=approve("Host Friend", "pass-123", "register"))
check(token and account.load()["username"] == "Host Friend", "signed in on the server's own page", account.load())
with open(os.path.join(TMP, "account.json")) as f:
    check(json.load(f)["token"] == "ab" * 32, "the wccf.online sign-in file is untouched")

# ---- its seat: the desk checks the token with the bank ----
out = os.path.join(TMP, "lease.json")
threading.Thread(target=S.main, args=(["127.0.0.1", out, "3"],), daemon=True).start()
for _ in range(50):
    if os.path.exists(out):
        break
    time.sleep(0.1)
time.sleep(0.5)
got = json.load(open(out)) if os.path.exists(out) else {}
leases = json.load(open(os.path.join(TMP, "leases.json"))) if os.path.exists(os.path.join(TMP, "leases.json")) else {}
check("seat" in got, "a seat on this server", got)
check(any(v.get("username") == "Host Friend" for v in leases.values()), "the desk knows the account, from the bank", leases)

# ---- the online club: its own folder per bank, and a restart keeps the bank ----
check(club.folder_of(1) == os.path.join(club.ONLINE, key, "u1"), "the online club in a folder of its own", club.folder_of(1))
account.use("https://wccf.online")
check(club.folder_of(1) == os.path.join(club.ONLINE, "u1"), "wccf.online's online club where it always was")
env = play.kit_env(TMP, {"card": "c", "catalogue": "k", "username": "Host Friend",
                         "website": "http://127.0.0.1:%d" % BANK})
check(env.get("WCCF_WEBSITE") == "http://127.0.0.1:%d" % BANK and env.get("WCCF_ACCOUNT_FILE", "").endswith(key + ".json"),
      "a cabinet restart (running.json) plays on the same bank", (env.get("WCCF_WEBSITE"), env.get("WCCF_ACCOUNT_FILE")))

# ---- the server's choice (play.py bank_of): its own, unless the owner's or data\card_bank.txt says otherwise ----
K.DATA = TMP
for f in ("card_bank.txt", "server_name.txt", "server_secret.txt"):
    if os.path.exists(os.path.join(TMP, f)):
        os.remove(os.path.join(TMP, f))
check(play.bank_of() is None and play.witness_ready(), "any server: its own bank, and its matches earn cards")
for f in ("server_name.txt", "server_secret.txt"):
    with open(os.path.join(TMP, f), "w") as fh:
        fh.write("x\n")
check(play.bank_of() == "https://wccf.online" and play.witness_ready(), "the owner's servers: wccf.online, as now")
for text, want in (("own\n", None), ("https://example.org/ \n", "https://example.org"), ("rubbish", "https://wccf.online"),
                   ("", "https://wccf.online")):
    with open(os.path.join(TMP, "card_bank.txt"), "w") as fh:
        fh.write(text)
    check(play.bank_of() == want, "card_bank.txt %r -> %r" % (text, want), play.bank_of())
with open(os.path.join(TMP, "card_bank.txt"), "w") as fh:
    fh.write("own")
env = play.server_bank_env({})
check(env.get("WCCF_BANK_PORT") == str(play.BANK_PORT) and env.get("WCCF_SERVER_DATA") == os.path.join(TMP, "bank")
      and os.path.isfile(os.path.join(TMP, "bank", "server_secret.txt")), "its own bank: the desk and witness are told, "
      "and its witness has an identity", env)
os.remove(os.path.join(TMP, "card_bank.txt"))
check(play.server_bank_env({}).get("WCCF_WEBSITE") == "https://wccf.online", "the owner's server's programs: wccf.online")
check("card bank" in play.SERVER_ROLES, "the bank is part of the server (a player on the hosting PC is not refused)")

print("open server: %s" % ("all %d checks passed" % checks[0] if not fails else "%d of %d FAILED" % (len(fails), checks[0])))
sys.exit(1 if fails else 0)
