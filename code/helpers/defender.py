# -*- coding: utf-8 -*-
r"""defender.py - Windows Defender and the game's own folders (2026-11-18).

Defender's cloud machine learning quarantined seat 1's client_Release.exe on a player's PC as
"Trojan:Win32/Bearfoos.A!ml": to run on a PC the kit edits Sega's program (the 15 changes - some switch off the
arcade board's checks -, the hook's import, the English text), which looks like what trojans do, and the game no
longer started ("seat 1 did not come up").  The same bytes had run for weeks; the verdict changed, not the file.
So setup asks Windows, once, to leave the game's own folders out of Defender's scans - extracted\ (the game),
seat1\ and misc\ beside it, never a folder above them - with Windows' own "make changes?" prompt; undo asks to put
them back.  data\defender.json remembers what was left out.  Where Defender is not the antivirus, or does not exist
(another antivirus; the Linux server under Wine) nothing is asked.  Never raises: setup goes on whatever the answer.
    python code\helpers\defender.py GAME       the folders it would leave out, and whether Defender runs here
"""
import base64
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # code\, when run on its own
import kit_common as K  # noqa: E402

STATE = os.path.join(K.DATA, "defender.json")
WAIT = 300                  # seconds the player has to answer Windows' prompt
DECLINED = 3                # the exit code when the prompt was answered No (or could not be shown)


def run_ps(command, timeout=30):
    """(exit code, output) of a PowerShell command, with no window; (None, why) when PowerShell cannot run here"""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                           capture_output=True, text=True, errors="replace", timeout=timeout,
                           creationflags=0x08000000 if os.name == "nt" else 0)        # CREATE_NO_WINDOW
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired, ValueError) as ex:
        return None, str(ex)


runner = run_ps             # the tests put a stand-in here: nothing real is asked of Windows there


def folders(game):
    r"""the game's own folders: extracted\ (GAME), seat1\ (made by setup if not there yet) and misc\ when it exists"""
    game = os.path.abspath(game)
    misc = K.misc_dir(game)
    return [game, K.seat_dir(game)] + ([misc] if os.path.isdir(misc) else [])


def active():
    """Windows Defender is this PC's antivirus and is on"""
    code, out = runner("try { if ((Get-MpComputerStatus -ErrorAction Stop).AntivirusEnabled) { 'on' } else { 'off' } }"
                       " catch { 'none' }")
    return code == 0 and out.strip().splitlines()[-1:] == ["on"]


def ps_paths(paths):
    return ",".join("'%s'" % p.replace("'", "''") for p in paths)


def elevated(command):
    """run command as administrator through Windows' prompt -> 0 done, 1 it failed, DECLINED answered No, None no
    PowerShell.  The command travels base64-encoded, so no path is ever quoted on a command line."""
    inner = "$ErrorActionPreference = 'Stop'; " + command + "; exit 0"
    enc = base64.b64encode(inner.encode("utf-16-le")).decode("ascii")
    outer = ("try { $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList "
             "'-NoProfile','-NonInteractive','-EncodedCommand','%s' -ErrorAction Stop; exit $p.ExitCode } "
             "catch { exit %d }" % (enc, DECLINED))
    return runner(outer, timeout=WAIT)[0]


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except (OSError, ValueError):
        return {}


def save(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(STATE + ".tmp", STATE)


def ensure(game, ok, note):
    """setup's step -> "had" / "done" / "none" (no Defender here) / "declined" / "failed"; says one line"""
    want = folders(game)
    if all(p in load().get("excluded", []) for p in want):
        ok("Windows Defender leaves the game's folders alone (asked before: %s)" % ", ".join(want))
        return "had"
    if not active():
        ok("Windows Defender is not this PC's antivirus here - nothing to ask")
        return "none"
    print("  ...   Windows asks now \"Do you want to allow this app to make changes?\" - Yes keeps Windows Defender "
          "from deleting the game's program (it takes the kit's changes to Sega's game for a trojan) by leaving only "
          "these folders out of its scans: %s" % ", ".join(want), flush=True)
    code = elevated("Add-MpPreference -ExclusionPath " + ps_paths(want))
    if code == 0:
        s = load()
        s["excluded"] = sorted(set(s.get("excluded", [])) | set(want))
        save(s)
        ok("Windows Defender leaves the game's folders alone now")
        return "done"
    if code == DECLINED:
        note("No was answered - Windows Defender may delete the game's program and the game then does not start "
             "(\"seat 1 did not come up\"). Run setup again to be asked again.")
        return "declined"
    note("Windows Defender could not be told (%s) - the game still runs while Defender leaves it alone" %
         ("no PowerShell" if code is None else "exit %s" % code))
    return "failed"


def undo(game, ok, note):
    """undo's step: what setup left out of Defender's scans for THIS game goes back in (Windows' prompt again); any
    other folder it remembers stays as it is"""
    mine = set(folders(game)) | {os.path.abspath(game)}
    gone = [p for p in load().get("excluded", []) if p in mine]
    if not gone:
        return "none"
    print("  ...   Windows asks now \"Do you want to allow this app to make changes?\" - Yes lets Windows Defender "
          "scan the game's folders again", flush=True)
    code = elevated("Remove-MpPreference -ExclusionPath " + ps_paths(gone))
    if code == 0:
        s = load()
        s["excluded"] = [p for p in s.get("excluded", []) if p not in gone]
        save(s)
        ok("Windows Defender scans the game's folders again")
        return "done"
    note("the game's folders are still left out of Windows Defender's scans (%s): Windows Security > Virus & threat "
         "protection > Exclusions removes them by hand" % ", ".join(gone))
    return "declined" if code == DECLINED else "failed"


if __name__ == "__main__":
    game = K.find_game(sys.argv[1]) if len(sys.argv) > 1 else K.find_game(K.load_settings().get("game"))
    if not game:
        print("no game folder given or set up")
        sys.exit(2)
    print("Windows Defender %s here; the folders setup leaves out of its scans: %s; already: %s" % (
        "runs" if active() else "does not run", ", ".join(folders(game)), load().get("excluded", [])))
