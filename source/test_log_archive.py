# -*- coding: utf-8 -*-
"""test_log_archive.py - the run before last is zipped into data\\logs\\archive, never just deleted, and the archive
keeps to its size (check.ps1 runs it; scratch folders only, nothing live).
    python source\\test_log_archive.py"""
import os
import sys
import tempfile
import zipfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import play  # noqa: E402


def run_folder(root, name, stamp, size):
    """a fake run's log folder: one log of `size` random-ish bytes (they do not compress) and a hook log"""
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "hook"))
    for rel, data in (("run_seat1.txt", os.urandom(size)), (os.path.join("hook", "mxhook_1.log"), b"hook")):
        with open(os.path.join(d, rel), "wb") as f:
            f.write(data)
        os.utime(os.path.join(d, rel), (stamp, stamp))
    return d


def main():
    bad = []
    with tempfile.TemporaryDirectory() as t:
        arc = os.path.join(t, "archive")
        base = 1791500000                                       # 2026-10-09 (local time decides the name)
        for i in range(4):                                      # four runs of ~40 kB each, a 100 kB archive
            play.archive_run(run_folder(t, "run%d" % i, base + 60 * i, 40000), arc, limit=100000)
        zips = sorted(os.listdir(arc))
        if len(zips) != 2:
            bad.append("the archive should keep the 2 newest runs that fit in 100 kB, has %r" % zips)
        with zipfile.ZipFile(os.path.join(arc, zips[-1])) as z:
            names = sorted(n.replace("\\", "/") for n in z.namelist())
        if names != ["hook/mxhook_1.log", "run_seat1.txt"]:
            bad.append("a zip holds the run's files with their folders, has %r" % names)
        if any(n.endswith(".tmp") for n in os.listdir(arc)):
            bad.append("a .tmp zip was left behind")
        big = run_folder(t, "big", base + 600, 300000)          # the newest stays even past the limit
        play.archive_run(big, arc, limit=100000)
        if len(os.listdir(arc)) != 1:
            bad.append("past the limit only the newest (big) run should stay, has %r" % os.listdir(arc))
        if play.archive_run(os.path.join(t, "empty-none"), arc) or len(os.listdir(arc)) != 1:
            bad.append("an empty or missing folder makes no zip")
    for b in bad:
        print("FAIL " + b)
    print("log archive: %s" % ("FAILED" if bad else "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
