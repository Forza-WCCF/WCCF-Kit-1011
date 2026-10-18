# -*- coding: utf-8 -*-
"""test_graphics_env.py - SETTINGS > GRAPHICS' NEXT START rows reach the game's hook (check.ps1 runs it; a scratch
panel.txt, no game): play.py kit_env gives msaa= / shadows= / motion_blur= as WCCF_MSAA / WCCF_SHADOWS /
WCCF_MOTION_BLUR (wccfk.c "graphics"), valid values only - a missing or unknown one sets nothing, and an earlier
test kit's resolution= (dropped 2026-10-18) nothing at all.
    python source\\test_graphics_env.py"""
import os
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import play  # noqa: E402

VARS = ("WCCF_MSAA", "WCCF_RES", "WCCF_SHADOWS", "WCCF_MOTION_BLUR")   # WCCF_RES: must never come back
play.PANEL = os.path.join(tempfile.mkdtemp(prefix="wccf_gfx_"), "panel.txt")


def env_of(text):
    with open(play.PANEL, "w", encoding="ascii") as f:
        f.write(text)
    env = play.kit_env("g")
    return {k: env[k] for k in VARS if k in env}


n = 0
for text, want in [
        ("msaa=8\nshadows=low\nmotion_blur=off\n",
         {"WCCF_MSAA": "8", "WCCF_SHADOWS": "low", "WCCF_MOTION_BLUR": "off"}),
        ("msaa=OFF  # a note\nresolution=720\n", {"WCCF_MSAA": "off"}),
        ("msaa=2\n", {"WCCF_MSAA": "2"}),
        ("msaa=4\nresolution=1920\n", {"WCCF_MSAA": "4"}),
        ("msaa=3\nshadows=high\nmotion_blur=on\n", {}),
        ("play_on=this_pc\n", {}),
        ("", {})]:
    got = env_of(text)
    assert got == want, (text, got, want)
    n += 1
os.environ["WCCF_MSAA"] = "8"                      # an earlier run's value never leaks into this one
assert "WCCF_MSAA" not in env_of("play_on=this_pc\n")
n += 1
print("graphics: %d checks passed - panel.txt's GRAPHICS rows reach the hook, valid values only" % n)
