# -*- coding: utf-8 -*-
"""test_italian_tables.py - the Italian tables against the kit's English (check.ps1 runs it; no game): each key once,
every line in the game's font (cp932), and the kit's Italian with the same printf and colour codes as the kit's English
line of that key (a line of Sega's Italian that does not fit is left for the English by english.py) -
a stray "%" ("100% presto" is "% p" to printf) or a lost "%s" would show junk or stop the game.  english.py checks the
same against the game's own Japanese at "on"; this catches it before a release.
    python source\\test_italian_tables.py"""
import collections
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import english as E  # noqa: E402

english = {}
for name in ("sega_rstring.tsv", "screen_text.tsv"):              # the kit's own English wins, as in build_strings
    english.update({r["key"]: r["english"] for r in E.sheet(name) if (r.get("english") or "").strip()})
bad, n = [], 0
for name in ("screen_text.tsv", "sega_rstring.tsv"):
    rows = E.sheet(name, "italian")
    for k, c in collections.Counter(r["key"] for r in rows).items():
        if c > 1:
            bad.append("%s %s: %d times" % (name, k, c))
    for r in rows:
        k, it = r["key"], r["italiano"]
        n += 1
        try:
            it.encode("cp932")
        except UnicodeEncodeError:
            bad.append("%s %s: a letter the game's font cannot show" % (name, k))
        en = english.get(k)
        if name != "screen_text.tsv" or en is None or en.strip() == "<empty>":   # Sega's: english.py falls back
            continue
        if E.FMT.findall(it) != E.FMT.findall(en) or it.count("$c") != en.count("$c"):
            bad.append("%s %s: codes %s, the English has %s" % (name, k, E.FMT.findall(it), E.FMT.findall(en)))
assert not bad, "%d problem(s): %s" % (len(bad), "; ".join(bad[:5]))
print("italian tables: %d lines checked" % n)
