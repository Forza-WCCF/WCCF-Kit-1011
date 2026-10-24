# -*- coding: utf-8 -*-
"""test_handoffs.py - every folder of the kit's source has a HANDOFF.md, and each one names every file in its folder
(Ali, 2026-10-11: "a HANDOFF in every folder").  A file added or renamed without its line here fails the checks, so
the HANDOFFs never quietly go stale.  check.ps1 runs it; the HANDOFFs are not in the players' ZIP (.gitattributes),
so in an unzipped kit there is nothing to check.
    python source\\test_handoffs.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDERS = ["art", "code", "code/cards", "code/hardware", "code/helpers", "code/online", "code/server", "docs",
           "languages", "languages/english", "languages/italian", "python", "source", "source/card_table", "source/hook",
           "source/launcher", "source/panel", "source/website"]
WHOLE = {"python"}                          # Python itself: its HANDOFF names what matters, not each of its files
SKIP = {"HANDOFF.md"}

if not os.path.isfile(os.path.join(KIT, "HANDOFF.md")):
    print("handoffs: not a checkout of the kit's source (no HANDOFF.md) - nothing to check")
    sys.exit(0)

fails = []
for rel in FOLDERS:
    folder = os.path.join(KIT, *rel.split("/"))
    path = os.path.join(folder, "HANDOFF.md")
    if not os.path.isfile(path):
        fails.append("%s\\ has no HANDOFF.md" % rel.replace("/", "\\"))
        continue
    if rel in WHOLE:
        continue
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for name in sorted(os.listdir(folder)):
        if name in SKIP or not os.path.isfile(os.path.join(folder, name)) or name.endswith(".pyc"):
            continue
        if name not in text:
            fails.append("%s\\HANDOFF.md does not name %s" % (rel.replace("/", "\\"), name))
for f in fails:
    print("FAILED: " + f)
print("handoffs: %d folders, %d problems" % (len(FOLDERS), len(fails)))
sys.exit(1 if fails else 0)
