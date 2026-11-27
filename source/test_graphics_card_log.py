# -*- coding: utf-8 -*-
"""test_graphics_card_log.py - the run log's graphics line can always be written (2026-11-27: debugger.py prints the
PC's graphics cards before it starts the game; a card name outside the PC's ANSI code page would raise on the run log
and stop the start).  Windows' list of displays is made up here, the line printed to a strict cp1252 stream.
    python source\\test_graphics_card_log.py"""
import ctypes
import io
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code", "hardware"))
import debugger  # noqa: E402

NAME = "Radeon\u2122 \u30b0\u30e9\u30d5\u30a3\u30c3\u30af\u30b9"   # the Japanese is not in cp1252


def fake_enum(_device, i, pd, _flags):
    if i:
        return 0
    pd._obj.DeviceString, pd._obj.StateFlags = NAME, 0x4
    return 1


fails = []
user32 = ctypes.windll.user32
real = user32.EnumDisplayDevicesW
user32.EnumDisplayDevicesW = fake_enum
try:
    line = debugger.graphics_cards()
finally:
    user32.EnumDisplayDevicesW = real
out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
try:
    print("  graphics: %s" % line, file=out, flush=True)
except UnicodeEncodeError as e:
    fails.append("the graphics line raises on a cp1252 run log: %s" % e)
if "(primary)" not in line or not line.startswith("Radeon"):
    fails.append("the card is still named: %r" % line)
for f in fails:
    print("FAILED: " + f)
print("graphics card log: %d of 2 checks passed" % (2 - len(fails)))
sys.exit(1 if fails else 0)
