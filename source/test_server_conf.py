# -*- coding: utf-8 -*-
"""test_server_conf.py - the server's settings file (setup.py CONF_CONTROL, written to the game's
local\\ctrl_user_option.conf): kit 7's random-pairing line is there with a value (an empty one would likely crash control
at start), and an older kit's file - also with the WAIT_PROJECTOR line play.py adds on a server - is replaced without a
.before-kit copy, while a hand edit is still kept (check.ps1 runs it; scratch files, no game).
    python source\\test_server_conf.py"""
import contextlib
import io
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import setup as S  # noqa: E402

fails, n = [], 0


def check(cond, what):
    global n
    n += 1
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


lines = [x for x in S.CONF_CONTROL.split("\r\n") if x and not x.startswith("#")]
check(all("=" in x and x.split("=", 1)[1] != "" for x in lines), "every setting has a value (an empty one may crash control)")
fm1 = [x for x in lines if x.startswith("MATCHING_PARA_FM1=")]
fm1v = int(fm1[0].split("=", 1)[1]) if len(fm1) == 1 and fm1[0].split("=", 1)[1].isdigit() else None
# FREE online (2026-10-15): real clubs' values 2,004-6,054 (21 cards), the widest gap 4,050; a FREE club reports 16383
check(fm1v is not None and fm1v >= 4050, "MATCHING_PARA_FM1 once, at least the widest gap seen between two real clubs")
check(fm1v is not None and 16383 - fm1v > 6054 + 2000,
      "... and a FREE club's 16383 stays out of its reach from every real club seen, with room to grow")
check("MATCHING_HISTORY_CHECK" not in S.CONF_CONTROL, "MATCHING_HISTORY_CHECK left out (control never reads it)")

NEW = S.CONF_CONTROL.encode("ascii")
SERVER = b"WAIT_PROJECTOR=0\r\n"                      # what play.py server appends at each start
t = tempfile.mkdtemp(prefix="wccf-conf-")


def write(before):
    """the file after setup.py's write_text, and whether a .before-kit copy was made"""
    p = os.path.join(t, "ctrl_user_option.conf")
    for f in (p, p + ".before-kit"):
        if os.path.exists(f):
            os.remove(f)
    if before is not None:
        with open(p, "wb") as f:
            f.write(before)
    with contextlib.redirect_stdout(io.StringIO()):
        S.write_text(p, S.CONF_CONTROL, "server settings")
    with open(p, "rb") as f:
        after = f.read()
    kept = None
    if os.path.exists(p + ".before-kit"):
        with open(p + ".before-kit", "rb") as f:
            kept = f.read()
    return after, kept


try:
    first_kit = [c for c in S.EARLIER_KIT_CONFS if b"FIX_REST_ENTRY_TIME" not in c]
    old = S.CONF_CONTROL_BEFORE_KIT7.encode("ascii")
    check(write(None) == (NEW, None), "no file: written")
    check(write(old) == (NEW, None), "the file kits before 7 wrote: replaced, no copy kept")
    check(write(old + SERVER) == (NEW, None), "... on a server too (with play.py's WAIT_PROJECTOR line)")
    kit7 = S.CONF_CONTROL_KIT7.encode("ascii")
    check(write(kit7 + SERVER) == (NEW, None), "kit 7's file (FM1=20000) on a server: replaced, no copy kept")
    check(len(first_kit) == 1 and write(first_kit[0] + SERVER) == (NEW, None), "the first kit's file: replaced, no copy")
    hand = old + b"MATCHING_PARA_FM1=600\r\n"
    check(write(hand) == (NEW, hand), "a hand edit: replaced, and kept as .before-kit")
    check(write(NEW + SERVER) == (NEW + SERVER, None), "this kit's own file on a server: left as it is")
finally:
    shutil.rmtree(t, ignore_errors=True)

print("server settings: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
