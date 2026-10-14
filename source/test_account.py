# -*- coding: utf-8 -*-
"""test_account.py - the wccf.online sign-in (online\\account.py, 2026-10-14) against a fake website on loopback: a
code, the approval, the token saved and never printed; a saved sign-in reused, a refused one replaced; the website
down or out of reach; a code that runs out; junk in the file; seat.py's TOKEN suffix (check.ps1 runs it; loopback
only - no real website, no browser, no Windows box).
    python source\\test_account.py"""
import io
import json
import os
import socket
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
TMP = tempfile.mkdtemp(prefix="wccf-account-")
os.environ["WCCF_WEBSITE"] = "http://127.0.0.1:%d" % PORT          # before the imports: both read these at import
os.environ["WCCF_ACCOUNT_FILE"] = os.path.join(TMP, "account.json")
os.environ["WCCF_NO_POPUP"] = "1"

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from online import account as A  # noqa: E402
from online import seat as S  # noqa: E402

fails = []
site = {"starts": 0, "polls": 0, "mode": "approve", "issued": [], "good": set()}


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


class Site(BaseHTTPRequestHandler):
    """the three actions of the website's game link, as WCCFOnline\\mybb\\plugins\\wccfgame.php answers them"""

    def log_message(self, *args):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        action = parse_qs(urlparse(self.path).query).get("action", [""])[0]
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()).items()}
        if site["mode"] == "down":
            return self.answer(503, {"error": "down for a test"})
        if action == "wccf_link_start":
            site["starts"] += 1
            site["polls"] = 0
            return self.answer(200, {"code": "ABCD-EFGH", "poll": "poll%d" % site["starts"], "interval": 1,
                                     "expires_in": 600, "url": "http://x/misc.php?action=wccf_link&code=ABCD-EFGH"})
        if action == "wccf_link_poll":
            site["polls"] += 1
            if site["mode"] == "expire":
                return self.answer(200, {"status": "expired"})
            if site["polls"] < 2:
                return self.answer(200, {"status": "waiting"})
            token = "%064x" % (len(site["issued"]) + 0xA11)
            site["issued"].append(token)
            site["good"].add(token)
            return self.answer(200, {"status": "approved", "token": token, "username": "Tester"})
        if action == "wccf_whoami":
            if form.get("token") in site["good"]:
                return self.answer(200, {"uid": 7, "username": "Tester"})
            return self.answer(401, {"error": "unknown or revoked sign-in"})
        return self.answer(404, {"error": "unknown action"})


srv = HTTPServer(("127.0.0.1", PORT), Site)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def run(fn, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        got = fn(*args)
    return got, out.getvalue()


def no_wait(_seconds):
    pass


# 1. not signed in: a code, "waiting", then approved -> saved with the name; the code shown, the token never printed
tok, out = run(A.ensure, False, no_wait)
check(site["issued"] and tok == site["issued"][0], "a first sign-in returns the token the website issued")
saved = A.load()
check(saved and saved.get("username") == "Tester" and saved.get("token") == tok, "it is saved, with the name")
check("ABCD-EFGH" in out and tok not in out, "the code is shown; the token is never printed")
check(site["starts"] == 1, "one code asked for")

# 2. a saved sign-in the website still knows: kept, no new code
tok2, out = run(A.ensure, False, no_wait)
check(tok2 == tok and site["starts"] == 1, "a saved good sign-in is used again without a new code")
check("plays as Tester" in out, "the start says who this PC plays as")

# 3. the website refuses it (revoked or banned): forgotten, and a new sign-in
site["good"].discard(tok)
tok3, out = run(A.ensure, False, no_wait)
check(site["starts"] == 2 and tok3 and tok3 != tok, "a refused sign-in is replaced by a new one")
check(A.load() and A.load()["token"] == tok3, "and the new one is saved")

# 4. the website down: the saved token is used as it is (the server decides)
site["mode"] = "down"
tok4, out = run(A.ensure, False, no_wait)
check(tok4 == tok3 and "could not be reached" in out, "the website down: the saved sign-in is used as it is")

# 5. down, and nothing saved: None at once, nothing written
A.forget()
tok5, out = run(A.ensure, False, no_wait)
check(tok5 is None and A.load() is None, "down with no sign-in saved: none, nothing written")

# 6. nothing listening at all: post() says so instead of raising
A.WEBSITE, keep = "http://127.0.0.1:1", A.WEBSITE
status, body = A.post("wccf_whoami", {"token": "x"})
check(status == 0 and body.get("error"), "an unreachable website is an answer, not an exception")
A.WEBSITE = keep

# 7. the code runs out before anyone approves: None, nothing saved
site["mode"] = "expire"
tok7, out = run(A.ensure, False, no_wait)
check(tok7 is None and A.load() is None and "not approved" in out, "a code that runs out: none, nothing saved")
site["mode"] = "approve"

# 8. junk in account.json counts as not signed in
with open(A.ACCOUNT, "w", encoding="utf-8") as f:
    f.write("not json at all")
check(A.load() is None, "junk in account.json = not signed in")

# 9. seat.py adds the token to its seat requests - plain hex only
with open(A.ACCOUNT, "w", encoding="utf-8") as f:
    json.dump({"token": "ab" * 32}, f)
check(S.signed() == b" TOKEN " + b"ab" * 32, "seat.py: WANT ... TOKEN <the saved token>")
with open(A.ACCOUNT, "w", encoding="utf-8") as f:
    json.dump({"token": "not hex; and spaces"}, f)
check(S.signed() == b"", "seat.py: a token that is not plain hex is not sent")
A.forget()
check(S.signed() == b"", "seat.py: not signed in -> nothing added")

srv.shutdown()
print("account: %d failed" % len(fails) if fails else "account: all 16 checks passed")
sys.exit(1 if fails else 0)
