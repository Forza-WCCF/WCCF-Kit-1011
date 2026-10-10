# -*- coding: utf-8 -*-
"""test_hook.py - play.py puts the kit's winmm.dll back in the game folders before a start, and says so in plain
words when it cannot or when Windows Security blocked a file (check.ps1 runs it; scratch folders only, no game).
    python source\\test_hook.py"""
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import play  # noqa: E402

t = tempfile.mkdtemp(prefix="wccf-hook-")
try:
    bin_dir, game, seat = (os.path.join(t, n) for n in ("bin", "extracted", "seat1"))
    for d in (bin_dir, game, seat):
        os.makedirs(d)
    with open(os.path.join(bin_dir, "winmm.dll"), "wb") as f:
        f.write(b"the kit's hook")

    def failed(folders, bdir=bin_dir):
        try:
            play.ensure_hook(folders, bdir)
        except play.Failed as ex:
            return str(ex)
        return None

    assert play.ensure_hook((game, seat), bin_dir) == [game, seat], "both missing: both put back"
    assert play.ensure_hook((game, seat), bin_dir) == [], "run twice: nothing to do"
    with open(os.path.join(seat, "winmm.dll"), "wb") as f:
        f.write(b"Windows' own winmm.dll")
    assert play.ensure_hook((game, seat), bin_dir) == [seat], "a different file: replaced, the right one left alone"
    with open(os.path.join(seat, "winmm.dll"), "rb") as f:
        assert f.read() == b"the kit's hook"

    os.remove(os.path.join(seat, "winmm.dll"))
    os.makedirs(os.path.join(seat, "winmm.dll"))        # cannot be written over: a plain message, not a traceback
    msg = failed((seat,))
    assert msg and "could not put the kit's winmm.dll back" in msg and "SETUP.exe" in msg, msg

    assert "is missing" in failed((game,), os.path.join(t, "nowhere")), "the kit's own copy gone"
    os.remove(os.path.join(bin_dir, "winmm.dll"))
    os.makedirs(os.path.join(bin_dir, "winmm.dll"))     # there but unreadable, like a file Windows Security blocks
    assert "is blocked" in failed((game,)), "the kit's own copy blocked"

    play.K.LOGS = t                                      # wait_for reads the launcher's log from here
    with open(os.path.join(t, "run_seat1.txt"), "w", encoding="utf-8") as f:
        f.write("  t+ 36.5s process exited, exit code 0xC0000906\n")
    try:
        play.wait_for("seat 2's window", lambda: False, 0, None, "run_seat1.txt")
        raise AssertionError("wait_for did not fail")
    except play.Failed as ex:
        assert "Windows Security blocked" in str(ex) and "0xc0000906" in str(ex), ex
    with open(os.path.join(t, "run_seat1.txt"), "w", encoding="utf-8") as f:
        f.write("  t+  0.3s SECOND-chance / FATAL exception 0xC0000005\n")
    try:
        play.wait_for("seat 2's window", lambda: False, 0, None, "run_seat1.txt")
        raise AssertionError("wait_for did not fail")
    except play.Failed as ex:
        assert str(ex).endswith("see data\\logs\\run_seat1.txt"), ex
finally:
    shutil.rmtree(t, ignore_errors=True)
print("hook: 10 checks passed")
