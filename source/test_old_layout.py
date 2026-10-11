# -*- coding: utf-8 -*-
"""test_old_layout.py - a kit updated from before kit 6 (scripts\\ english\\ bin\\ overlay\\) is tidied by setup: the catalogue
and card pictures move to data\\cache\\, the old kit's own files go, a player's own file stays (check.ps1 runs it;
a scratch folder, no game).
    python source\\test_old_layout.py"""
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import kit_common as K  # noqa: E402
import setup  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


def touch(*parts):
    p = os.path.join(t, *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()


t = tempfile.mkdtemp(prefix="wccf-oldlayout-")
try:
    K.KIT, K.SCRIPTS, K.CACHE = t, os.path.join(t, "code"), os.path.join(t, "data", "cache")
    touch("code", "play.py")
    touch("scripts", "play.py")                      # the old copy of code\play.py
    touch("scripts", "__pycache__", "play.cpython-313.pyc")
    touch("scripts", "_jvs_seat1_input.txt")         # written beside the old scripts while the kit ran
    touch("scripts", "_dbg_control.txt")
    touch("languages", "english", "screen_text.tsv")
    touch("english", "screen_text.tsv")              # the old copy of languages\\english\\screen_text.tsv
    touch("bin", "winmm.dll")                        # the old fake hook (what Defender flagged)
    touch("overlay", "wccfpanel.dll")
    touch("overlay", "skin.tex")
    touch("overlay", "catalogue.tsv")
    touch("overlay", "cards", "1.png")
    touch("overlay", "mine.txt")                     # not the kit's: must stay

    setup.tidy_old_layout()
    check(not os.path.exists(os.path.join(t, "scripts")), "scripts\\ (old copies + __pycache__) removed")
    check(not os.path.exists(os.path.join(t, "bin")), "bin\\ with the old winmm.dll removed")
    check(not os.path.exists(os.path.join(t, "english")), "english\\ (now languages\\english\\) removed")
    check(os.path.isfile(os.path.join(K.CACHE, "catalogue.tsv")), "the catalogue moved to data\\cache\\")
    check(os.path.isfile(os.path.join(K.CACHE, "cards", "1.png")), "the card pictures moved to data\\cache\\")
    check(os.listdir(os.path.join(t, "overlay")) == ["mine.txt"], "overlay\\ keeps only the player's own file")
    check(os.path.isfile(os.path.join(t, "code", "play.py")), "code\\ untouched")

    setup.tidy_old_layout()                          # a second run: nothing to do, nothing raised
    check(os.listdir(os.path.join(t, "overlay")) == ["mine.txt"], "a second run changes nothing")
finally:
    shutil.rmtree(t, ignore_errors=True)

n = 8
print("old_layout: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
