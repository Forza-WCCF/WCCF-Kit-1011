# -*- coding: utf-8 -*-
"""test_setup_kit_english.py - SETUP on a game that another copy of the kit made English (2026-10-16, a player's
report: "not Rev D" for his English game, run from a new kit folder): setup.kit_language_in finds the kit's English
or Italian in client_Release.exe - english.py's words at exe_text.tsv's places - and nothing in a file without them
(check.ps1 runs it; scratch files, no game).
    python source\\test_setup_kit_english.py"""
import csv
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import setup  # noqa: E402

with open(os.path.join(KIT, "languages", "english", "exe_text.tsv"), encoding="utf-8", newline="") as f:
    rows = [r for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE) if r["program"] == "client"]
row = next(r for r in rows if r["english"] and r.get("italiano"))      # a place with both words ("Next match: ")
at = int(row["offset"], 16)
size = max(int(r["offset"], 16) + int(r["length"]) for r in rows) + 64

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


t = tempfile.mkdtemp(prefix="wccf-kit-english-")
try:
    def exe(name, text):
        d = bytearray(b"\xAA" * size)                    # never zeros: an empty text must not count as a match
        if text is not None:
            d[at:at + len(text) + 1] = text.encode("ascii") + b"\0"
        p = os.path.join(t, name)
        with open(p, "wb") as f:
            f.write(d)
        return p

    check(setup.kit_language_in(exe("en.exe", row["english"])) == "English", "the kit's English is found")
    check(setup.kit_language_in(exe("it.exe", row["italiano"])) == "Italian", "the kit's Italian is found")
    check(setup.kit_language_in(exe("other.exe", None)) is None, "a file without the kit's words: nothing")
    check(setup.kit_language_in(exe("cut.exe", row["english"][:-1])) is None, "a word cut short: nothing")
    check(setup.kit_language_in(os.path.join(t, "missing.exe")) is None, "a missing file: nothing, no error")
    with open(os.path.join(t, "short.exe"), "wb") as f:
        f.write(b"MZ" + b"\0" * 98)
    check(setup.kit_language_in(os.path.join(t, "short.exe")) is None, "a short file: nothing, no error")
    n = 6
    print("setup kit english: %d of %d checks passed" % (n - len(fails), n))
finally:
    shutil.rmtree(t, ignore_errors=True)

sys.exit(1 if fails else 0)
