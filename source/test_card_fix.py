# -*- coding: utf-8 -*-
"""test_card_fix.py - a missing club-card helper file never stops a start (check.ps1 runs it; nothing live, no game,
no real card): decode_club_card.py and edit_club_card.py raise ImportError instead of exiting, and play.py's
apply_card_fix then says so, takes the card_fix request out of panel.txt and lets the start go on.
    python source\\test_card_fix.py"""
import contextlib
import io
import os
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import play  # noqa: E402

CARD_MODULES = ("club_card_schema", "decode_club_card", "edit_club_card")


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


e = load_without("club_card_schema", "decode_club_card")
assert isinstance(e, ImportError) and "club_card_schema.py" in str(e), repr(e)
e = load_without("decode_club_card", "edit_club_card")
assert isinstance(e, ImportError) and "decode_club_card.py" in str(e), repr(e)

scratch = tempfile.mkdtemp(prefix="wccf_cardfix_")
play.PANEL = os.path.join(scratch, "panel.txt")
play.CARD = os.path.join(scratch, "no_card.bin")         # never the real card
with open(play.PANEL, "w", encoding="ascii") as f:
    f.write("play_on=this_pc\ncard_fix=bad_endings\n")
sys.modules["edit_club_card"] = None
out = io.StringIO()
try:
    with contextlib.redirect_stdout(out):
        play.apply_card_fix()                        # must come back: an exit here would stop the start, every start
finally:
    sys.modules.pop("edit_club_card", None)
assert "were not cleared" in out.getvalue(), out.getvalue()
assert play.read_panel(play.PANEL) == {"play_on": "this_pc"}, "the card_fix request must leave panel.txt"
os.remove(play.PANEL)
os.rmdir(scratch)
print("card fix: 4 checks passed")
