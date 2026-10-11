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
    overlay = os.path.join(t, "overlay")
    for d in (game, seat, overlay):
        os.makedirs(d)
    open(os.path.join(seat, ".wccf-kit"), "w").close()        # the "set up" marker

    K.find_game = lambda cfg: game                            # a set-up game
    K.seat_dir = lambda g: seat
    K.load_settings = lambda: {"game": game}
    K.OVERLAY = overlay

    # no catalogue.tsv: the start must still go (only a note)
    check(play.setup_state() == (game, seat), "a missing catalogue does NOT stop the start")

    # with the catalogue present: also fine
    open(os.path.join(overlay, "catalogue.tsv"), "w").close()
    check(play.setup_state() == (game, seat), "a built catalogue is fine too")

    # a game that is not set up (no .wccf-kit) still stops, clearly
    os.remove(os.path.join(seat, ".wccf-kit"))
    check(play.setup_state() == (None, None), "a game that is not set up still stops")

    # no game at all
    K.find_game = lambda cfg: None
    check(play.setup_state() == (None, None), "no game found still stops")

    n = 4
    print("setup_state: %d of %d checks passed" % (n - len(fails), n))
finally:
    import shutil
    shutil.rmtree(t, ignore_errors=True)

sys.exit(1 if fails else 0)
