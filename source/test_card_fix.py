# -*- coding: utf-8 -*-
"""test_card_fix.py - a missing club-card helper file never stops a start (check.ps1 runs it; nothing live, no game,
no real card): decode.py and edit.py raise ImportError instead of exiting, and play.py's
apply_card_fix then says so, takes the card_fix request out of panel.txt and lets the start go on.
    python source\\test_card_fix.py"""
import contextlib
import io
import os
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import play  # noqa: E402

CARD_MODULES = ("cards.schema", "cards.decode", "cards.edit")


def load_without(missing, module):
    """what importing module raises while missing cannot be imported (None if it loads)"""
    saved = {k: sys.modules.pop(k) for k in CARD_MODULES if k in sys.modules}
    sys.modules[missing] = None                      # Python's own way to make an import fail
    try:
        __import__(module)
        return None
    except BaseException as e:                       # SystemExit too: that is the fault this test is for
        return e
    finally:
        for k in CARD_MODULES:
            sys.modules.pop(k, None)
        sys.modules.update(saved)


e = load_without("cards.schema", "cards.decode")
assert isinstance(e, ImportError) and "schema.py" in str(e), repr(e)
e = load_without("cards.decode", "cards.edit")
assert isinstance(e, ImportError) and "decode.py" in str(e), repr(e)

scratch = tempfile.mkdtemp(prefix="wccf_cardfix_")
play.PANEL = os.path.join(scratch, "panel.txt")
play.CARD = os.path.join(scratch, "no_card.bin")         # never the real card
with open(play.PANEL, "w", encoding="ascii") as f:
    f.write("play_on=this_pc\ncard_fix=bad_endings\n")
import cards  # noqa: E402
cards.__dict__.pop("edit", None)                     # a submodule already loaded would be found on the package
sys.modules["cards.edit"] = None
out = io.StringIO()
try:
    with contextlib.redirect_stdout(out):
        play.apply_card_fix()                        # must come back: an exit here would stop the start, every start
finally:
    sys.modules.pop("cards.edit", None)
assert "were not cleared" in out.getvalue(), out.getvalue()
assert play.read_panel(play.PANEL) == {"play_on": "this_pc"}, "the card_fix request must leave panel.txt"
os.remove(play.PANEL)
os.rmdir(scratch)
print("card fix: 4 checks passed")
