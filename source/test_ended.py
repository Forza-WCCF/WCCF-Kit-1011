# -*- coding: utf-8 -*-
"""test_ended.py - play.py's choice when a game window's launcher ends (check.ps1 runs it; nothing live, no game):
a closed window stops the rest, a crash stops nothing while another game window runs (the projector keeps running).
    python source\\test_ended.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import play  # noqa: E402

CLOSED = "  t+ 42.0s %s - ending client_Release.exe\n" % play.WINDOW_CLOSED
roles = {10: "scene service", 11: "server launcher", 12: "projector launcher", 13: "seat 1 launcher", 14: "key driver"}
win = play.window_launchers(roles)
assert win == {12: "run_projector.txt", 13: "run_seat1.txt"}, win
assert play.window_launchers({20: "seat 2 launcher", 21: "seat  launcher"}) == {20: "run_seat1.txt"}


def logs(**text):
    return lambda name: text.get(name.replace(".txt", ""), "")


assert play.crashed_logs(win, {12}, logs(run_seat1=CLOSED)) is None, "seat closed: the rest stops"
assert play.crashed_logs(win, {12}, logs(run_seat1="  FATAL 0xC0000005\n")) == ["run_seat1.txt"], "seat crashed"
assert play.crashed_logs(win, {13}, logs()) == ["run_projector.txt"], "projector crashed: seat 1 plays on"
assert play.crashed_logs(win, set(), logs()) is None, "no game window left: the rest stops"
assert play.crashed_logs(win, {12, 13}, logs()) == [], "nothing ended (a hand-run ended): nothing stops"
assert play.crashed_logs({}, set(), logs()) is None, "no running.json: the rest stops, as before"

with open(os.path.join(KIT, "code", "hardware", "debugger.py"), encoding="utf-8") as f:
    dbg = f.read()
assert play.WINDOW_CLOSED in dbg, "debugger.py no longer prints the line play.py looks for"

# a run that went wrong (the automatic report, 2026-10-11): a crash, or the server link lost
seat = ["run_seat1.txt"]
assert play.went_wrong(seat, logs(run_seat1=CLOSED)) == [], "closed by the player, link fine: nothing to report"
assert play.went_wrong(seat, logs(run_seat1="  t+ 9.0s process exited\n"))[0].startswith(
    "run_seat1.txt: the game window went by itself"), "gone without a close: reported"
why = play.went_wrong(seat, logs(run_seat1=CLOSED + "  SECOND-chance / FATAL exception 0xC0000005\n"))
assert why == ["run_seat1.txt: a crash recorded (SECOND-chance / FATAL)"], why
why = play.went_wrong(seat, logs(run_seat1=CLOSED, server_link="2026-10-11 20:01:02 UP 1.2.3.4\n"
                                 "2026-10-11 20:09:40 LOST (it was up 518 s)\n"))
assert why == ["server_link.txt: 2026-10-11 20:09:40 LOST (it was up 518 s)"], why
assert play.went_wrong(seat, logs(run_seat1=CLOSED, run_server="  STOP: invalid parameter\n")) == [
    "run_server.txt: a crash recorded (STOP: invalid parameter)"], "a crash of the server on this PC counts too"
for sign in play.CRASH_SIGNS:                                    # the words must stay the launcher's own
    assert sign in dbg, "debugger.py no longer prints %r" % sign
with open(os.path.join(KIT, "source", "panel", "wccfpanel.c"), encoding="utf-8") as f:
    assert " LOST (it was up " in f.read(), "wccfpanel.c no longer writes the LOST line play.py looks for"
print("ended: 16 checks passed")
