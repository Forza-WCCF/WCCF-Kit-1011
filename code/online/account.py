# -*- coding: utf-8 -*-
r"""account.py - this PC's wccf.online sign-in (2026-10-14: the first step of linking the website and the online game).

Signing in works the way a TV does: the kit asks wccf.online for a code, opens the page in the browser and shows the
code (in the PLAY window and in a small Windows box), then waits while the player logs in - or registers - and
approves it there. The website then hands this PC a token, kept in data\account.json. Only this module reads that
file: the token is never printed, never written to a log, and SEND LOGS never packs it (send_logs.files() names
what it packs). seat.py sends the token to the server's seat desk, which checks it with the website.

Nothing here is fatal: if the website cannot be reached or the player does not approve, play.py goes on without a
sign-in, and the server decides (it lets players in without one until its owner switches sign-in on).

    python code\online\account.py signin      sign in now (a saved sign-in is checked first)
    python code\online\account.py status      who this PC is signed in as
    python code\online\account.py signout     forget the sign-in on this PC
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ACCOUNT = os.environ.get("WCCF_ACCOUNT_FILE") or os.path.join(KIT, "data", "account.json")
WEBSITE = os.environ.get("WCCF_WEBSITE", "https://wccf.online").rstrip("/")
TIMEOUT = 15                     # seconds for one request to the website


def say(msg):
    print(msg, flush=True)


def kit_version():
    try:
        with open(os.path.join(KIT, "version.txt"), encoding="utf-8") as f:
            return (f.read().split() or ["kit"])[0][:40]
    except OSError:
        return "kit"


def load():
    """the saved sign-in {"token", "username", "website", "linked"}, or None"""
    try:
        with open(ACCOUNT, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("token"), str) and d["token"] else None


def save(d):
    os.makedirs(os.path.dirname(ACCOUNT), exist_ok=True)
    with open(ACCOUNT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(ACCOUNT + ".tmp", ACCOUNT)


def forget():
    try:
        os.remove(ACCOUNT)
    except OSError:
        pass


def post(action, fields):
    """(HTTP status, JSON dict) from the website's xmlhttp.php?action=...; (0, {"error": why}) when it cannot be reached"""
    req = urllib.request.Request("%s/xmlhttp.php?action=%s" % (WEBSITE, action),
                                 data=urllib.parse.urlencode(fields).encode("ascii"),
                                 headers={"User-Agent": "WCCF-kit/" + kit_version()})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as ex:
        try:
            body = json.loads(ex.read().decode("utf-8", "replace") or "{}")
        except ValueError:
            body = {}
        return ex.code, body if isinstance(body, dict) else {}
    except (OSError, ValueError) as ex:
        return 0, {"error": str(ex)}


def check(token):
    """("ok", name) / ("refused", why) / ("unreachable", why)"""
    status, body = post("wccf_whoami", {"token": token})
    if status == 200 and body.get("username"):
        return "ok", body["username"]
    if status in (401, 403):
        return "refused", body.get("error") or "refused"
    return "unreachable", body.get("error") or ("HTTP %s" % status)


def show_code(code):
    """the code in a small Windows box as well - the PLAY window may be behind something; never waits for it"""
    if os.name != "nt" or os.environ.get("WCCF_NO_POPUP"):
        return

    def box():
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None, "Your game's sign-in code:\n\n        %s\n\nApprove it on wccf.online - the page has opened in your "
                      "browser (log in or register there).\nThe game carries on by itself once you approve." % code,
                "WCCF Online - sign in", 0x40 | 0x10000 | 0x40000)        # information icon, to the front, on top
        except Exception:
            pass
    threading.Thread(target=box, daemon=True).start()


def sign_in(open_browser=True, sleep=time.sleep):
    """the TV-style sign-in; returns the saved sign-in, or None after saying why"""
    status, start = post("wccf_link_start", {"kit": kit_version()})
    if status != 200 or not start.get("code") or not start.get("poll"):
        say("  sign-in: wccf.online did not give a code (%s) - going on without a sign-in" %
            (start.get("error") or "HTTP %s" % status))
        return None
    code, poll, url = start["code"], start["poll"], start.get("url") or WEBSITE
    say("  sign-in: your code is %s - approve it on wccf.online (log in or register there; the page opens now)" % code)
    say("           %s" % url)
    show_code(code)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    every = max(1, int(start.get("interval", 3)))
    end = time.time() + int(start.get("expires_in", 600)) + 30
    noted = time.time()
    while time.time() < end:
        sleep(every)
        status, got = post("wccf_link_poll", {"poll": poll})
        state = got.get("status")
        if status == 200 and state == "approved" and got.get("token"):
            d = {"token": got["token"], "username": got.get("username", ""), "website": WEBSITE,
                 "linked": time.strftime("%Y-%m-%d %H:%M:%S")}
            save(d)
            say("  sign-in: done - this PC plays as %s" % d["username"])
            return d
        if state in ("expired", "collected", "refused", "unknown") or status in (403, 404, 410):
            say("  sign-in: not approved (%s) - going on without a sign-in; the next start asks again" %
                (state or "HTTP %s" % status))
            return None
        if time.time() - noted >= 30:
            say("  sign-in: still waiting for the approval of %s ..." % code)
            noted = time.time()
    say("  sign-in: the code ran out - going on without a sign-in; the next start asks again")
    return None


def ensure(open_browser=True, sleep=time.sleep):
    """the token to play with, or None. A saved sign-in the website still knows: kept. Refused (revoked, banned): forgotten,
    and a new sign-in. The website unreachable: the saved token as it is (the server decides). None saved: sign in."""
    saved = load()
    if saved and saved.get("website", WEBSITE) == WEBSITE:
        state, detail = check(saved["token"])
        if state == "ok":
            say("  sign-in: this PC plays as %s" % detail)
            return saved["token"]
        if state == "unreachable":
            say("  sign-in: wccf.online could not be reached (%s) - using this PC's saved sign-in (%s)" %
                (detail, saved.get("username") or "?"))
            return saved["token"]
        say("  sign-in: the saved one was refused (%s) - signing in again" % detail)
        forget()
    got = sign_in(open_browser, sleep)
    return got["token"] if got else None


def main(argv):
    if argv[:1] == ["signin"]:
        return 0 if ensure() else 1
    if argv[:1] == ["status"]:
        saved = load()
        if not saved:
            say("This PC is not signed in to wccf.online.")
            return 1
        state, detail = check(saved["token"])
        say("This PC is signed in as %s (%s)." % (saved.get("username") or "?", {
            "ok": "the website knows it", "refused": "the website refused it: " + detail,
            "unreachable": "the website could not be reached: " + detail}[state]))
        return 0 if state != "refused" else 1
    if argv[:1] == ["signout"]:
        forget()
        say("This PC's sign-in is forgotten; the next online start asks again.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
