# -*- coding: utf-8 -*-
"""test_ended.py - play.py's choice when a game window's launcher ends (check.ps1 runs it; nothing live, no game):
a closed window stops the rest, a crash stops nothing while another game window runs (the projector keeps running).
    python source\\test_ended.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
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

with open(os.path.join(KIT, "scripts", "_debug_launch.py"), encoding="utf-8") as f:
    assert play.WINDOW_CLOSED in f.read(), "_debug_launch.py no longer prints the line play.py looks for"
print("ended: 9 checks passed")
