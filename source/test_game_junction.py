# -*- coding: utf-8 -*-
"""test_game_junction.py - a game folder reached through a junction: PLAY still finds the game's running programs
(2026-11-27: Windows names a running program by its real path, so PLAY counted 0 match engines and stopped at 1/6 on
a game that ran).  A scratch folder, a junction to it and Windows' ping.exe copied in as match_Release.exe (it pings
127.0.0.1 for a few seconds, nothing else).
    python source\\test_game_junction.py"""
import _winapi
import os
import shutil
import subprocess
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import kit_common as K  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


t = tempfile.mkdtemp(prefix="wccf_junction_")
p = None
try:
    real = os.path.join(t, "real", "extracted")
    os.makedirs(real)
    for n in ("client_Release.exe", "control_Release.exe"):
        open(os.path.join(real, n), "w").close()
    shutil.copy(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE"),
                os.path.join(real, "match_Release.exe"))
    _winapi.CreateJunction(os.path.join(t, "real"), os.path.join(t, "link"))
    game = K.find_game(os.path.join(t, "link"))
    check(game is not None, "the game is found through the junction")
    check(game and os.path.normcase(game) == os.path.normcase(K.find_game(real)),
          "through the junction the game folder is its real path")
    p = subprocess.Popen([os.path.join(t, "link", "extracted", "match_Release.exe"), "-n", "6", "127.0.0.1"],
                         stdout=subprocess.DEVNULL)
    time.sleep(1.0)
    seen = [x[0] for x in K.game_processes(game)] if game else []
    check(p.pid in seen, "a match engine started through the junction is one of the game's programs")
finally:
    if p is not None:
        p.kill()
        p.wait()
    shutil.rmtree(t, ignore_errors=True)

n = 3
print("game_junction: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
