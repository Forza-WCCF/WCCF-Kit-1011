# -*- coding: utf-8 -*-
"""test_setup_state.py - a missing card CATALOGUE (a panel-only extra) must NOT stop a start (A10); a game that is
not set up still does (check.ps1 runs it; scratch folders, no game).
    python source\\test_setup_state.py"""
import os
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import kit_common as K  # noqa: E402
import play  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


t = tempfile.mkdtemp(prefix="wccf-setup-")
try:
    game = os.path.join(t, "game")
    seat = os.path.join(t, "seat")
    cache = os.path.join(t, "cache")
    for d in (game, seat, cache):
        os.makedirs(d)
    open(os.path.join(seat, ".wccf-kit"), "w").close()        # the "set up" marker

    K.find_game = lambda cfg: game                            # a set-up game
    K.seat_dir = lambda g: seat
    K.load_settings = lambda: {"game": game}
    K.CACHE = cache

    # no catalogue.tsv: the start must still go (only a note)
    check(play.setup_state() == (game, seat), "a missing catalogue does NOT stop the start")

    # with the catalogue present: also fine
    open(os.path.join(cache, "catalogue.tsv"), "w").close()
    check(play.setup_state() == (game, seat), "a built catalogue is fine too")

    # a game that is not set up (no .wccf-kit) still stops, clearly
    os.remove(os.path.join(seat, ".wccf-kit"))
    check(play.setup_state() == (None, None), "a game that is not set up still stops")

    # no game at all
    K.find_game = lambda cfg: None
    check(play.setup_state() == (None, None), "no game found still stops")

    # ensure_hook: a game an older kit set up (no wccfk.dll) is set up once by the start, not refused or started old
    def put(path, data):
        with open(path, "wb") as f:
            f.write(data)
    K.PROGRAMS = os.path.join(t, "programs")
    os.makedirs(K.PROGRAMS)
    put(os.path.join(K.PROGRAMS, "wccfk.dll"), b"this kit's hook")
    calls = []
    play.subprocess.call = lambda args: calls.append(args) or answer[0]
    answer = [0]
    put(os.path.join(game, "wccfk.dll"), b"this kit's hook")
    check(play.ensure_hook(game, seat) is True and len(calls) == 1, "no wccfk.dll in seat1\\: setup is run")
    calls.clear()
    put(os.path.join(seat, "wccfk.dll"), b"this kit's hook")
    check(play.ensure_hook(game, seat) is True and calls == [], "set up for this kit: no setup run")
    put(os.path.join(seat, "wccfk.dll"), b"an older kit's hook")     # a newer kit unzipped over by hand
    check(play.ensure_hook(game, seat) is True and len(calls) == 1, "an older wccfk.dll in seat1\\: setup is run")
    calls.clear()
    put(os.path.join(seat, "wccfk.dll"), b"this kit's hook")
    os.remove(os.path.join(game, "wccfk.dll"))
    check(play.ensure_hook(game, seat) is True and len(calls) == 1 and calls[0][-1] == game
          and calls[0][-2].endswith("setup.py"), "no wccfk.dll: setup.py GAME is run, and the start goes on")
    answer[0] = 1
    check(play.ensure_hook(game, seat) is False, "setup failing: the start stops, saying SETUP.exe")

    n = 9
    print("setup_state: %d of %d checks passed" % (n - len(fails), n))
finally:
    import shutil
    shutil.rmtree(t, ignore_errors=True)

sys.exit(1 if fails else 0)
