# -*- coding: utf-8 -*-
"""test_defender.py - setup's Windows Defender step (code\\helpers\\defender.py, 2026-11-18): the game's own folders
(extracted\\, seat1\\, misc\\ - never one above them) left out of Defender's scans with the player's Yes, remembered,
asked again after a No, nothing asked where Defender is not the antivirus or PowerShell does not run (Wine), and undo
puts them back.  A stand-in answers for PowerShell: nothing real is asked of Windows (check.ps1 runs it; scratch
folders only).
    python source\\test_defender.py"""
import base64
import os
import re
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from helpers import defender as D  # noqa: E402

fails, checks = [], [0]


def check(cond, what, got=""):
    checks[0] += 1
    if not cond:
        fails.append(what)
        print("FAILED: %s%s" % (what, (" - %r" % (got,)) if got != "" else ""))


class Windows:
    """answers like PowerShell: Defender on/off/absent, the prompt's answer; keeps what it was asked"""
    def __init__(self, status="on", answer=0):
        self.status, self.answer, self.asked = status, answer, []

    def __call__(self, command, timeout=30):
        self.asked.append(command)
        if "Get-MpComputerStatus" in command:
            return (None, "no powershell") if self.status is None else (0, self.status)
        return self.answer, ""


def inner(command):
    """the command that would run as administrator, decoded from -EncodedCommand"""
    m = re.search(r"'-EncodedCommand','([A-Za-z0-9+/=]+)'", command)
    return base64.b64decode(m.group(1)).decode("utf-16-le") if m else ""


lines = []
ok = lambda m: lines.append("ok " + m)          # noqa: E731
note = lambda m: lines.append("note " + m)      # noqa: E731

tmp = tempfile.mkdtemp(prefix="wccf-defender-")
try:
    D.STATE = os.path.join(tmp, "data", "defender.json")
    sbwg = os.path.join(tmp, "Bob's games", "sbwg")              # an apostrophe: PowerShell's quote
    game = os.path.join(sbwg, "extracted")
    os.makedirs(game)
    os.makedirs(os.path.join(sbwg, "misc"))
    want = [game, os.path.join(sbwg, "seat1"), os.path.join(sbwg, "misc")]
    check(D.folders(game) == want, "the folders: extracted\\, seat1\\ (even before setup made it), misc\\", D.folders(game))
    check(sbwg not in D.folders(game) and os.path.dirname(sbwg) not in D.folders(game), "never a folder above them")

    for status in ("off", "none", None):
        W = D.runner = Windows(status=status)
        got = D.ensure(game, ok, note)
        check(got == "none" and len(W.asked) == 1 and not os.path.exists(D.STATE),
              "Defender %s: nothing asked, nothing written" % ("not running" if status is None else status), (got, W.asked))

    W = D.runner = Windows(answer=D.DECLINED)
    got = D.ensure(game, ok, note)
    check(got == "declined" and not os.path.exists(D.STATE) and "Run setup again" in lines[-1],
          "No answered: setup goes on, says how to be asked again, remembers nothing", (got, lines[-1:]))
    W = D.runner = Windows(answer=1)
    check(D.ensure(game, ok, note) == "failed" and not os.path.exists(D.STATE), "Windows refused: said, nothing kept")

    W = D.runner = Windows(answer=0)
    got = D.ensure(game, ok, note)
    cmd = W.asked[-1]
    run = inner(cmd)
    check(got == "done" and sorted(D.load().get("excluded", [])) == sorted(want), "Yes: the three folders kept", D.load())
    check("-Verb RunAs" in cmd and "Add-MpPreference -ExclusionPath" in run, "it asks Windows' prompt (RunAs) to add them", run)
    check(all(("'%s'" % p.replace("'", "''")) in run for p in want), "each folder quoted for PowerShell (Bob''s)", run)
    check(not any(p in cmd for p in want) and "Bob" not in cmd, "no path on the command line itself (base64 only)")
    check(run.startswith("$ErrorActionPreference = 'Stop'"), "a failure inside ends with an error exit, not 0", run)
    W = D.runner = Windows(answer=0)
    check(D.ensure(game, ok, note) == "had" and W.asked == [], "set up again: not asked again", W.asked)
    os.makedirs(os.path.join(sbwg, "misc2"))
    check(D.ensure(game, ok, note) == "had", "a new unrelated folder changes nothing")

    other = os.path.join(tmp, "another", "extracted")      # a scratch game, as test_setup_state undoes one
    os.makedirs(other)
    W = D.runner = Windows(answer=0)
    check(D.undo(other, ok, note) == "none" and W.asked == [] and sorted(D.load()["excluded"]) == sorted(want),
          "undo of ANOTHER game: nothing asked, this game's folders kept", (W.asked, D.load()))
    W = D.runner = Windows(answer=D.DECLINED)
    got = D.undo(game, ok, note)
    check(got == "declined" and D.load().get("excluded") and "Exclusions removes them by hand" in lines[-1],
          "undo, No answered: kept, says how to remove them by hand", (got, lines[-1:]))
    W = D.runner = Windows(answer=0)
    got = D.undo(game, ok, note)
    run = inner(W.asked[-1])
    check(got == "done" and "Remove-MpPreference -ExclusionPath" in run and not D.load().get("excluded")
          and all(("'%s'" % p.replace("'", "''")) in run for p in want), "undo, Yes: its three folders removed, forgotten",
          (got, run))
    W = D.runner = Windows(answer=0)
    check(D.undo(game, ok, note) == "none" and W.asked == [], "undo with nothing left out: nothing asked")

    with open(D.STATE, "w") as f:
        f.write("not json {")
    W = D.runner = Windows(status="none")
    check(D.ensure(game, ok, note) == "none", "a broken defender.json: read as empty, no error")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("defender: %s" % ("all %d checks passed" % checks[0] if not fails else "%d of %d FAILED" % (len(fails), checks[0])))
sys.exit(1 if fails else 0)
