# -*- coding: utf-8 -*-
"""test_free_mode.py - FREE online (2026-10-15): the start's choices for it, in scratch files (check.ps1 runs it; nothing
starts, nothing is sent). A plain start with the SETTINGS panel's FREE, and "remote ADDRESS free", go online FREE; a
FREE run's programs get WCCF_FREE_MODE=1; its seat request carries no sign-in, even on a signed-in PC; RESTART NOW
restarts only the cabinet when FREE stays FREE, and starts everything again when FREE and ONLINE change places.
    python source\\test_free_mode.py"""
import json
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="wccf-free-")
os.environ["WCCF_ACCOUNT_FILE"] = os.path.join(T, "account.json")      # never the real sign-in
os.environ.pop("WCCF_FREE_MODE", None)
sys.path.insert(0, os.path.join(KIT, "code"))
import play  # noqa: E402
from online import seat  # noqa: E402

fails, n = [], 0


def check(cond, what):
    global n
    n += 1
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


def write(path, text):
    with open(path, "w", encoding="ascii") as f:
        f.write(text)


try:
    play.PANEL, play.RUNNING = os.path.join(T, "panel.txt"), os.path.join(T, "running.json")

    # a FREE run's programs are told so; any other run's are not
    check(play.kit_env("G", None, True).get("WCCF_FREE_MODE") == "1", "a FREE run: WCCF_FREE_MODE=1")
    check("WCCF_FREE_MODE" not in play.kit_env("G"), "an ONLINE or THIS PC run: no WCCF_FREE_MODE")
    os.environ["WCCF_FREE_MODE"] = "1"                                  # an earlier run's value never leaks in
    check("WCCF_FREE_MODE" not in play.kit_env("G"), "... not even when the shell still holds one")
    del os.environ["WCCF_FREE_MODE"]

    # the seat request: no sign-in in FREE, even on a signed-in PC (its matches earn no card, save nothing online)
    write(os.environ["WCCF_ACCOUNT_FILE"], json.dumps({"token": "ab12" * 8, "username": "Ali"}))
    check(seat.signed() == b" TOKEN " + b"ab12" * 8, "signed in, ONLINE: the token goes with the seat request")
    os.environ["WCCF_FREE_MODE"] = "1"
    check(seat.signed() == b"", "signed in, FREE: no token")
    del os.environ["WCCF_FREE_MODE"]

    # running.json says FREE only for a FREE run
    play.write_running({}, "remote", "1.2.3.4", 2, None, True)
    check(json.load(open(play.RUNNING)).get("free") is True, "a FREE run is written as one")
    play.write_running({}, "remote", "1.2.3.4", 2, None)
    check("free" not in json.load(open(play.RUNNING)), "an ONLINE run is not")

    # RESTART NOW: the cabinet alone while FREE stays FREE (or ONLINE stays ONLINE); a full start when they swap
    def fits(run_free, panel):
        write(play.RUNNING, json.dumps(dict({"mode": "remote", "server": "1.2.3.4", "seat": 2,
                                             "processes": {"4242": "seat 2 launcher"}}, **({"free": True} if run_free else {}))))
        write(play.PANEL, panel)
        return play.cabinet_restart_fits()
    on, free = "play_on=online\nserver=1.2.3.4\n", "play_on=online\nonline_mode=free\nserver=1.2.3.4\n"
    check(fits(True, free) is True, "FREE run, FREE chosen: the cabinet alone")
    check(fits(False, on) is True, "ONLINE run, ONLINE chosen: the cabinet alone")
    check(fits(True, on) is False, "FREE run, ONLINE chosen: everything again (the sign-in comes back)")
    check(fits(False, free) is False, "ONLINE run, FREE chosen: everything again (the sign-in goes)")

    # the starts: what play_online would be asked (nothing starts here)
    asked = []
    play.play_online = lambda debug, ip, seat_no=None, free=False: asked.append((ip, seat_no, free)) or 0
    play.server_answers = lambda ip, port=play.CONTROL_PORT, seconds=5: True
    play.K.load_settings = lambda: {}
    play.K.save_settings = lambda s: None
    write(play.PANEL, free)
    play.main([])
    check(asked[-1:] == [("1.2.3.4", None, True)], "a plain start with the panel's FREE: online, FREE")
    write(play.PANEL, on)
    play.main([])
    check(asked[-1:] == [("1.2.3.4", None, False)], "a plain start with the panel's ONLINE: online, not FREE")
    play.main(["remote", "5.6.7.8", "free"])
    check(asked[-1:] == [("5.6.7.8", None, True)], "remote ADDRESS free")
    play.main(["remote", "5.6.7.8", "seat", "3", "free"])
    check(asked[-1:] == [("5.6.7.8", 3, True)], "remote ADDRESS seat N free")
    play.main(["remote", "5.6.7.8"])
    check(asked[-1:] == [("5.6.7.8", None, False)], "remote ADDRESS: not FREE")
finally:
    shutil.rmtree(T, ignore_errors=True)

print("free mode: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
