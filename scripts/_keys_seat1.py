# -*- coding: utf-8 -*-
"""Drive seat 1 (the 2010-11 player cabinet) from the keyboard.

    python .work/_keys_seat1.py              run it; keep its window open, close the window to stop
    python .work/_keys_seat1.py --selftest   check the key logic on a scratch file (touches nothing live)

Keys count only while a game window (client_Release.exe) is the one in front, so typing anywhere else
sends nothing.  Every change is written to .work/_jvs_seat1_input.txt, which the I/O board stand-in
(_jvs_board.py) re-reads at once.  The bits are the ones in .work/input_mapping.md (the game's switch
table at 0x00ad0a30).  Only one copy can run at a time.

Which key does what comes from keys.txt (keys_path(): the kit's data folder), written by the KEYS panel in seat 1's
window (wccfpanel.dll); missing = the defaults in ACTIONS.  The file is read again whenever it changes, so a key
changed in the panel works at once.

Controllers (2026-10-06): each action can also have one control on a game controller - a USB encoder under a real
cabinet's buttons, an arcade stick, a PC pad - read with Windows' standard joystick calls (CONTROLLERS below).
keys.txt lines "PAD START=B3"; the KEYS panel catches the control pressed.  Controllers are looked for only once
keys.txt has such a line, and like the keys they count only while a game window is in front.

Free play (FREE_PLAY below, the player 2026-10-04): every START press first puts in a coin, and START itself reaches
the game a moment later, so the credit is counted before START is seen.  This is the driver paying for you,
not the game's own FREE PLAY setting (not found yet): the screen still shows CREDIT(S).
"""
import ctypes
import ctypes.wintypes as w
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "_jvs_seat1_input.txt")

# THE KEYS (2026-10-05: the KEYS panel in seat 1's window can change them).  Every action: its name in keys.txt, the
# default key (virtual-key code), the cabinet input it holds - (line, byte, bit), or None for CARD and COIN, which are
# edges - and what it is.  The names are the on-screen buttons' (wccfpanel.dll): the player tried X = PRESS, S = DATA and
# B = KEEPER in the game; D = KEY PLAYER is still a guess.  2010-11 wiring (game button table DAT_009fbd30): the
# cabinet's extra buttons are on the 2ND JVS player; p1 byte 1 0x80 is a card-dispenser sensor and 0x20 is never read.
ACTIONS = [
    ("START", 0x0D, ("p1", 0, 0x80), "START"),
    ("PRESS", 0x58, ("p1", 0, 0x02), "PRESS (decide)"),
    ("SHOOT", 0x43, ("p1", 0, 0x01), "SHOOT"),
    ("KEEPER", 0x42, ("p2", 0, 0x02), "KEEPER (game button 8)"),
    ("DATA", 0x53, ("p2", 1, 0x80), "DATA (game button 5)"),
    ("KEYPLAYER", 0x44, ("p2", 1, 0x40), "KEY PLAYER - a guess (game button 9)"),
    ("UP", 0x26, ("p1", 0, 0x20), "tactics: CENTRAL (up)"),
    ("DOWN", 0x28, ("p1", 0, 0x10), "tactics: COUNTER (down)"),
    ("LEFT", 0x25, ("p1", 0, 0x08), "tactics: L-SIDE (left)"),
    ("RIGHT", 0x27, ("p1", 0, 0x04), "tactics: R-SIDE (right)"),
    ("CARD", 0x49, None, "club card in / out of the slot"),     # p2 byte 0 0x20 (bit 29), held while the card is in
    ("COIN", 0x35, None, "one coin"),
    ("TEST", 0x70, ("sys", 0, 0x80), "TEST (operator menu)"),
    ("SERVICE", 0x71, ("p1", 0, 0x40), "SERVICE"),
    ("SENSOR2", 0x38, ("p2", 0, 0x10), "Sega's service switch SW1 (bit 28) - CAREFUL: on Sega's club-card recovery "
                                       "screen SW1 = 'overwrite the card with the backup'; not needed to play"),
    ("SENSOR3", 0x39, ("p2", 0, 0x08), "Sega's service switch SW2 (bit 27) - 'back' on Sega's service screens; "
                                       "not needed to play"),
]
DEFAULTS = {a[0]: a[1] for a in ACTIONS}
# keys an action may have: letters, digits, the number pad, F1-F9 and F12-F24, arrows and the keys around them,
# Enter Space Tab Backspace Shift Ctrl Pause and the punctuation keys.  Never Esc (it closes the panels), F10
# (Windows' menu key - it froze the game window, the player 2026-10-04), F11 (the window's size), Alt, the Windows keys,
# the lock keys or a mouse button.
ALLOWED_VKS = frozenset([0x08, 0x09, 0x0D, 0x10, 0x11, 0x13, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,
                         0x2D, 0x2E, 0xE2] + list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)) +
                        list(range(0x60, 0x70)) + list(range(0x70, 0x79)) + list(range(0x7B, 0x88)) +
                        list(range(0xBA, 0xC1)) + list(range(0xDB, 0xE0)))

# CONTROLLERS (the player, 2026-10-06: "users can map their joystick without an issue" - a player's group runs real cabinet
# button panels on a USB encoder).  An action's controller control, read with Windows' standard joystick calls (winmm
# joyGetPosEx, Pads below).  All controllers count as one: B3 is button 3 on any of them.  A control is a number above
# every key code, so keys and controls share one set: 0x100 + n = button n (1-32); 0x200 + 2 * axis + (1 for +) = a
# stick or axis direction (axes X Y Z R U V - the stick is X and Y, up is Y-); 0x300 + n = the hat, a pad's d-pad
# (up right down left).  The KEYS panel (wccfpanel.dll) reads controllers the same way to catch the one pressed: keep
# these numbers, the words below and PadDevice's rest rule equal in both.
PAD_BUTTON, PAD_AXIS, PAD_HAT = 0x100, 0x200, 0x300
AXES = "XYZRUV"
HATS = ("UP", "RIGHT", "DOWN", "LEFT")
PAD_ON, PAD_OFF = 0.5, 0.3      # an axis direction is pressed past half way, let go back inside 0.3 (no flicker)


def pad_token(code):
    """a control's word in keys.txt ("B3", "X+", "HAT UP"), or None"""
    if PAD_BUTTON < code <= PAD_BUTTON + 32:
        return "B%d" % (code - PAD_BUTTON)
    if PAD_AXIS <= code < PAD_AXIS + 2 * len(AXES):
        axis, plus = divmod(code - PAD_AXIS, 2)
        return AXES[axis] + ("+" if plus else "-")
    if PAD_HAT <= code < PAD_HAT + len(HATS):
        return "HAT " + HATS[code - PAD_HAT]
    return None


def pad_code(word):
    """keys.txt's word -> the control, 0 if it is none (case and spaces do not matter: "hat up" = "HATUP")"""
    t = "".join((word or "").split()).upper()
    if t.startswith("HAT") and t[3:] in HATS:
        return PAD_HAT + HATS.index(t[3:])
    if len(t) == 2 and t[0] in AXES and t[1] in "+-":
        return PAD_AXIS + 2 * AXES.index(t[0]) + (t[1] == "+")
    n = t[1:]
    if t[:1] == "B" and n.isascii() and n.isdigit() and len(n) <= 4 and 1 <= int(n) <= 32:
        return PAD_BUTTON + int(n)
    return 0


def pad_label(code):
    """a control's name on screen and in this window"""
    if not code:
        return "(none)"
    if PAD_BUTTON < code <= PAD_BUTTON + 32:
        return "Button %d" % (code - PAD_BUTTON)
    if PAD_AXIS <= code < PAD_AXIS + 2 * len(AXES):
        axis, plus = divmod(code - PAD_AXIS, 2)
        if axis < 2:
            return "Stick " + (("Left", "Right"), ("Up", "Down"))[axis][plus]
        return "Axis %s%s" % (AXES[axis], "+" if plus else "-")
    if PAD_HAT <= code < PAD_HAT + len(HATS):
        return "D-pad " + HATS[code - PAD_HAT].capitalize()
    return "0x%X" % code


def keys_path():
    """keys.txt: WCCF_KEYS if set; in the kit, data\\keys.txt beside scripts\\ (the overlay finds the same file from
    overlay\\); otherwise beside this script"""
    env = os.environ.get("WCCF_KEYS")
    if env:
        return env
    data = os.path.join(os.path.dirname(HERE), "data")
    return os.path.join(data, "keys.txt") if os.path.isdir(data) else os.path.join(HERE, "keys.txt")


def load_keys(path):
    """-> ({action: vk}, [notes]).  A missing file = the defaults.  Lines "NAME=0x58"; a bad, unknown or forbidden
    line is skipped (that action keeps its default); a key given twice stays with the first action, and the later one
    goes back to its default if that is free, else it has no key (0).  Never raises: the file may be mid-swap."""
    keys, notes = dict(DEFAULTS), []
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return keys, notes
    given = []
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        name, _, val = ln.partition("=")
        name = name.strip().upper()
        if name.split()[:1] == ["PAD"]:                  # a controller line: load_pads() reads those
            continue
        if name not in DEFAULTS:
            notes.append("unknown action %r" % name)
            continue
        try:
            vk = int(val.strip(), 0)
        except ValueError:
            notes.append("%s: not a key code: %r" % (name, val.strip()))
            continue
        if vk not in ALLOWED_VKS:
            notes.append("%s: key 0x%02X cannot be used" % (name, vk))
            continue
        keys[name] = vk
        if name not in given:
            given.append(name)
    order = given + [a[0] for a in ACTIONS if a[0] not in given]    # the file's own lines win a clash first
    owner = {}                                                      # key -> the action that has it
    for i, name in enumerate(order):
        vk = keys[name]
        if vk and vk in owner:
            d, later = DEFAULTS[name], {keys[n] for n in order[i + 1:]}
            keys[name] = d if d not in owner and d not in later else 0
            notes.append("%s: key 0x%02X is %s's - %s" % (name, vk, owner[vk],
                                                          "back to its default" if keys[name] else "left with no key"))
        if keys[name]:
            owner[keys[name]] = name
    return keys, notes


def load_pads(path):
    """-> ({action: control}, [notes]) from keys.txt's "PAD NAME=WORD" lines.  No file and no line = no controls (the
    default: nothing on a controller does anything until it is given).  "PAD NAME=" or "=-" = none.  A bad action or
    word is skipped; the same action twice: the last line counts; a control given to two actions stays with the one
    whose line came first, the other gets none.  Never raises: the file may be mid-swap."""
    pads, notes = {}, []
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return pads, notes
    given, order = {}, []
    for ln in lines:
        name, eq, val = ln.split("#", 1)[0].strip().partition("=")
        words = name.split()
        if not eq or len(words) != 2 or words[0].upper() != "PAD":
            continue
        act, val = words[1].upper(), val.strip()
        if act not in DEFAULTS:
            notes.append("PAD: unknown action %r" % act)
            continue
        code = pad_code(val) if val not in ("", "-") else 0
        if val not in ("", "-") and not code:
            notes.append("PAD %s: not a controller control: %r" % (act, val))
            continue
        given[act] = code
        if act not in order:
            order.append(act)
    owner = {}                                           # control -> the action that has it
    for act in order:
        code = given[act]
        if not code:
            continue
        if code in owner:
            notes.append("PAD %s: %s is %s's - left with none" % (act, pad_label(code), owner[code]))
            continue
        owner[code] = act
        pads[act] = code
    return pads, notes


def apply_keys(keys, pads=None):
    """the module's tables from {action: key} and {action: controller control} (none if not given) - render(), step()
    and the main loop read these"""
    global KEYS, PADS, INPUTS, ALL_VKS, CARD_VK, COIN_VK, START_VK
    KEYS = dict(keys)
    PADS = {n: c for n, c in (pads or {}).items() if c and n in KEYS}
    INPUTS = {n: frozenset(x for x in (KEYS[n], PADS.get(n, 0)) if x) for n in KEYS}   # what holds each action
    CARD_VK, COIN_VK, START_VK = KEYS["CARD"], KEYS["COIN"], KEYS["START"]
    ALL_VKS = [KEYS[n] for n, _d, _b, _w in ACTIONS if KEYS[n]]


def held_actions(down):
    """the actions held by these inputs: key codes and controller controls (controls are above 0xFF: never a key)"""
    return {n for n, ins in INPUTS.items() if ins & down}


def key_label(vk):
    """a key's name for the console: letters and digits as they are, else the common names"""
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return "F%d" % (vk - 0x6F)
    if 0x60 <= vk <= 0x69:
        return "Num%d" % (vk - 0x60)
    return {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift", 0x11: "Ctrl", 0x13: "Pause", 0x20: "Space",
            0x21: "PgUp", 0x22: "PgDn", 0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right",
            0x28: "Down", 0x2D: "Insert", 0x2E: "Delete", 0x6A: "Num*", 0x6B: "Num+", 0x6C: "NumSep", 0x6D: "Num-",
            0x6E: "Num.", 0x6F: "Num/", 0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
            0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'", 0xDF: "OEM8", 0xE2: "<>", 0: "(none)"}.get(vk, "0x%02X" % vk)


apply_keys(DEFAULTS)
# The card comes out by itself when the game lets it go (the player, 2026-10-04: no loop after a timeout). Nothing
# can push a card out here, so after "card ejected" the sensor stayed on and the game read the card again. The
# board stand-in writes the game's JVS outputs to OUTPUTS; output byte 1 bit 0x08 is on only while the game
# waits for a card (start screen, and ~5.6 s after each eject; off while a card is in use - _jvs_seat1_log.txt).
# Seen on WITH our card in = the game has let it go -> take it out. Margins: not in the first EJECT_GRACE s
# after an insert, and the signal must hold EJECT_HOLD s (the game re-reads a held card ~0.7 s later).
OUTPUTS = os.path.join(HERE, "_jvs_seat1_outputs.txt")
AUTO_EJECT = True
EJECT_BYTE, EJECT_BIT = 1, 0x08
EJECT_GRACE, EJECT_HOLD = 2.5, 0.25
FREE_PLAY = True        # every START press puts a coin in first
START_DELAY = 0.15      # s between that coin and START reaching the game
START_MIN = 0.35        # s after the press until which START stays held even if the key was only tapped


def read_outputs(path=OUTPUTS):
    """the game's latest JVS output bytes as a list, or None (missing, being swapped, garbled - never fatal)"""
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            lines = f.read().splitlines()
        return [int(x, 16) for x in lines[1].split()]
    except (OSError, IndexError, ValueError):
        return None


def should_eject(now, card, card_in_since, outs, waiting_since):
    """-> (take the card out?, new waiting_since).  waiting_since = when the 'waiting for a card' bit came on"""
    waiting = outs is not None and len(outs) > EJECT_BYTE and bool(outs[EJECT_BYTE] & EJECT_BIT)
    if not waiting:
        return False, None
    since = waiting_since if waiting_since is not None else now
    ok = (card and card_in_since is not None and now - card_in_since >= EJECT_GRACE
          and now - since >= EJECT_HOLD)
    return ok, since


def start_held(now, enter_down, armed):
    """free play: is START held at time `now`?  armed = (from, until) set when Enter went down, or None"""
    if not armed or now < armed[0]:
        return False
    return enter_down or now < armed[1]


def render(down, card, coin, start=None):
    """the input file's text for these held inputs (keys and controller controls), card state and coin count.
    start: None = START as its inputs say; True / False = held or not, whatever they say (free play's timing)"""
    acts = held_actions(down)
    if start is not None:
        acts.discard("START")
        if start:
            acts.add("START")
    f = {"sys": [0], "p1": [0, 0], "p2": [0, 0]}
    for name, _d, bits, _what in ACTIONS:
        if bits and name in acts:
            line, byte, bit = bits
            f[line][byte] |= bit
    if card:
        f["p2"][0] |= 0x20
    return ("# JVS inputs for the player cabinet - written by _keys_seat1.py; read by _jvs_board.py\n"
            "sys=0x%02X\np1=0x%02X 0x%02X\np2=0x%02X 0x%02X\ncoin1=%d\ncoin2=0\n"
            % (f["sys"][0], f["p1"][0], f["p1"][1], f["p2"][0], f["p2"][1], coin))


def step(down, prev, card, coin):
    """one poll: an action's first moment held (by its key or its controller control) toggles the card / adds a
    coin.  Returns (card, coin, events)."""
    events = []
    now_a, was_a = held_actions(down), held_actions(prev)
    edges = now_a - was_a
    if "CARD" in edges:
        card = not card
        events.append("card IN the slot" if card else "card OUT of the slot")
    if "COIN" in edges:
        coin += 1
        events.append("coin inserted (counter %d)" % coin)
    if FREE_PLAY and "START" in edges:
        coin += 1
        events.append("coin put in for you - free play (counter %d)" % coin)
    events += ["%s down" % what for name, _d, bits, what in ACTIONS if bits and name in edges]
    events += ["%s up" % what for name, _d, bits, what in ACTIONS if bits and name in was_a - now_a]
    return card, coin, events


def read_start(path):
    """card state and coin counter from the file as it is now (missing / garbled -> out, 0)"""
    card, coin = False, 0
    try:
        for line in open(path, encoding="ascii", errors="replace"):
            key, _, val = line.strip().partition("=")
            nums = val.split()
            try:
                if key == "p2" and nums:
                    card = bool(int(nums[0], 0) & 0x20)
                elif key == "coin1" and nums:
                    coin = max(0, int(nums[0], 0))
            except ValueError:
                pass
    except OSError:
        pass
    return card, coin


def file_stamp(path):
    """(write time, size) of a file, or None if it is not there - a change means: read it again"""
    try:
        st = os.stat(path)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def write(path, text):
    """replace the file whole, so the stand-in never reads half of it; retry if it has it open"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii", newline="\n") as f:
        f.write(text)
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.005)
    with open(path, "w", encoding="ascii", newline="\n") as f:   # last resort: write in place
        f.write(text)


# ---- reading the controllers (CONTROLLERS above)
def pad_axis_value(v, lo, hi):
    """an axis reading as -1 .. +1, the middle 0 (a range that is no range: 0)"""
    if hi <= lo:
        return 0.0
    return max(-1.0, min(1.0, 2.0 * (v - lo) / (hi - lo) - 1.0))


def pad_hat_dirs(pov):
    """the hat's directions held, 0-3 = up right down left; pov in hundredths of a degree, centred = 0xFFFF (anything
    above 35999).  A diagonal holds both of its directions."""
    if pov > 35999:
        return set()
    out = set()
    for i, centre in enumerate((0, 9000, 18000, 27000)):
        d = abs(pov - centre) % 36000
        if min(d, 36000 - d) <= 4500:
            out.add(i)
    return out


class PadDevice:
    """one controller: what it rested on when first seen, and its controls pressed at the last read.  The REST RULE
    (the same in the KEYS panel): an axis direction the controller rests on when first seen - a trigger resting at one
    end, a throttle, an axis it does not use - is never a press while it stays plugged in; a button or hat direction
    held when first seen counts once it has been let go."""

    def __init__(self, buttons, axes, pov):
        self.rest = [0 if v is None else -1 if v < -PAD_ON else 1 if v > PAD_ON else 0 for v in axes]
        self.held0, self.hat0, self.act = buttons, pad_hat_dirs(pov), set()
        self.read(buttons, axes, pov)

    def read(self, buttons, axes, pov):
        """the controls pressed now (control numbers), from one reading: buttons (a bit each), axes (-1 .. 1, or None
        where the controller has none, X Y Z R U V), the hat (pov)"""
        self.held0 &= buttons
        now = {PAD_BUTTON + i + 1 for i in range(32) if (buttons & ~self.held0) >> i & 1}
        for axis, v in enumerate(axes):
            if v is None:
                continue
            for plus, side in ((0, -1), (1, 1)):
                code = PAD_AXIS + 2 * axis + plus
                if side != self.rest[axis] and v * side > (PAD_OFF if code in self.act else PAD_ON):
                    now.add(code)
        dirs = pad_hat_dirs(pov)
        self.hat0 &= dirs
        now |= {PAD_HAT + d for d in dirs - self.hat0}
        self.act = now
        return now


class JOYCAPSW(ctypes.Structure):                       # mmsystem.h (728 bytes - checked 2026-10-06)
    _fields_ = [("wMid", w.WORD), ("wPid", w.WORD), ("szPname", w.WCHAR * 32)] + \
               [(n, w.UINT) for n in ("wXmin", "wXmax", "wYmin", "wYmax", "wZmin", "wZmax", "wNumButtons",
                                      "wPeriodMin", "wPeriodMax", "wRmin", "wRmax", "wUmin", "wUmax", "wVmin",
                                      "wVmax", "wCaps", "wMaxAxes", "wNumAxes", "wMaxButtons")] + \
               [("szRegKey", w.WCHAR * 32), ("szOEMVxD", w.WCHAR * 260)]


class JOYINFOEX(ctypes.Structure):                      # mmsystem.h (52 bytes)
    _fields_ = [(n, w.DWORD) for n in ("dwSize", "dwFlags", "dwXpos", "dwYpos", "dwZpos", "dwRpos", "dwUpos",
                                       "dwVpos", "dwButtons", "dwButtonNumber", "dwPOV", "dwReserved1",
                                       "dwReserved2")]


JOY_RETURNALL, JOY_RETURNPOVCTS = 0xFF, 0x200
JOYCAPS_HASZ, JOYCAPS_HASR, JOYCAPS_HASU, JOYCAPS_HASV, JOYCAPS_HASPOV = 0x1, 0x2, 0x4, 0x8, 0x10


class Winmm:
    """Windows' standard joystick calls (winmm.dll): caps() and pos() answer None for an empty slot"""

    def __init__(self):
        mm = ctypes.WinDLL("winmm")
        mm.joyGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(JOYCAPSW), w.UINT]
        mm.joyGetDevCapsW.restype = w.UINT
        mm.joyGetPosEx.argtypes = [w.UINT, ctypes.POINTER(JOYINFOEX)]
        mm.joyGetPosEx.restype = w.UINT
        mm.joyConfigChanged.argtypes = [w.DWORD]
        mm.joyConfigChanged.restype = w.UINT
        self.mm = mm

    def caps(self, jid):
        c = JOYCAPSW()
        return None if self.mm.joyGetDevCapsW(jid, ctypes.byref(c), ctypes.sizeof(c)) else c

    def pos(self, jid):
        i = JOYINFOEX(dwSize=ctypes.sizeof(JOYINFOEX), dwFlags=JOY_RETURNALL | JOY_RETURNPOVCTS)
        return None if self.mm.joyGetPosEx(jid, ctypes.byref(i)) else i

    def config_changed(self):
        """Windows reads its controller list again (finds one plugged in after the start: 1-4 ms here, 2026-10-06)"""
        self.mm.joyConfigChanged(0)


def pad_reading(caps, info):
    """(buttons, [axis -1..1, or None if the controller has no such axis] for X Y Z R U V, pov) from winmm's answers"""
    has = (caps.wNumAxes >= 1, caps.wNumAxes >= 2, caps.wCaps & JOYCAPS_HASZ, caps.wCaps & JOYCAPS_HASR,
           caps.wCaps & JOYCAPS_HASU, caps.wCaps & JOYCAPS_HASV)
    vals = ((caps.wXmin, caps.wXmax, info.dwXpos), (caps.wYmin, caps.wYmax, info.dwYpos),
            (caps.wZmin, caps.wZmax, info.dwZpos), (caps.wRmin, caps.wRmax, info.dwRpos),
            (caps.wUmin, caps.wUmax, info.dwUpos), (caps.wVmin, caps.wVmax, info.dwVpos))
    axes = [pad_axis_value(v, lo, hi) if h and hi > lo else None for h, (lo, hi, v) in zip(has, vals)]
    return info.dwButtons, axes, info.dwPOV if caps.wCaps & JOYCAPS_HASPOV else 0xFFFF


def pad_name(caps):
    """the controller's own name as Windows keeps it under its USB ids (2026-10-06 here: "DualSense Wireless
    Controller"), else the ids - winmm's own name is "Microsoft PC-joystick driver" for every one; ASCII (the font)"""
    import winreg
    key = ("System\\CurrentControlSet\\Control\\MediaProperties\\PrivateProperties\\Joystick\\OEM\\"
           "VID_%04X&PID_%04X" % (caps.wMid, caps.wPid))
    name = ""
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as k:
                name = str(winreg.QueryValueEx(k, "OEMName")[0]).strip()
        except OSError:
            continue
        if name:
            break
    name = name or "controller %04X:%04X" % (caps.wMid, caps.wPid)
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in name)


class Pads:
    """every controller plugged in, read through api (Winmm, or a stand-in for the selftest).  poll() asks only the
    controllers already found and answers the controls held now on any of them; looking for controllers runs on its
    own thread every RESCAN s - an empty slot answered in 0.01 ms here (2026-10-06) but is known to be slow on some
    PCs, so never inside the 10 ms key loop.  Windows' controller list is read again only while none is found, so a
    controller in use is never disturbed.  say(): one line per controller found or gone."""
    RESCAN = 2.0

    def __init__(self, api, say=None, name=pad_name, thread=True):
        self.api, self.say, self.name = api, say or (lambda m: None), name
        self.lock = threading.Lock()
        self.devs = {}                                   # slot -> (caps, PadDevice, name)
        self.stop = threading.Event()
        if thread:
            threading.Thread(target=self._loop, name="pads", daemon=True).start()

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.rescan()
            except Exception as ex:                      # a controller must never stop the driver
                self.say("controllers: could not look for them (%r)" % ex)
            self.stop.wait(self.RESCAN)

    def rescan(self):
        with self.lock:
            known = set(self.devs)
        if not known:
            self.api.config_changed()
        for jid in range(16):
            if jid in known:
                continue
            caps = self.api.caps(jid)
            info = self.api.pos(jid) if caps is not None else None
            if info is None:
                continue
            dev, name = PadDevice(*pad_reading(caps, info)), self.name(caps)
            with self.lock:
                self.devs[jid] = (caps, dev, name)
            self.say("controller found: %s (%d buttons)" % (name, caps.wNumButtons))

    def poll(self):
        """the controls held now on every controller found (a controller that stops answering is let go and said)"""
        with self.lock:
            devs = list(self.devs.items())
        held = set()
        for jid, (caps, dev, name) in devs:
            info = self.api.pos(jid)
            if info is None:
                with self.lock:
                    self.devs.pop(jid, None)
                self.say("controller gone: %s" % name)
                continue
            held |= dev.read(*pad_reading(caps, info))
        return held

    def names(self):
        with self.lock:
            return [n for _c, _d, n in self.devs.values()]


def selftest():
    ok = bad = 0

    def check(what, got, want):
        nonlocal ok, bad
        if got == want:
            ok += 1
        else:
            bad += 1
            print("FAIL %s: got %r want %r" % (what, got, want))
    x, cardk, five, f1, enter, s_key = 0x58, CARD_VK, COIN_VK, 0x70, 0x0D, 0x53
    check("idle", render(set(), False, 0).splitlines()[1:4], ["sys=0x00", "p1=0x00 0x00", "p2=0x00 0x00"])
    check("decide", render({x}, False, 0).splitlines()[2], "p1=0x02 0x00")
    check("start+decide", render({x, enter}, False, 0).splitlines()[2], "p1=0x82 0x00")
    check("goalie on the 2nd JVS player", render({s_key}, False, 0).splitlines()[3], "p2=0x00 0x80")
    check("goalie leaves the 1st player alone", render({s_key}, False, 0).splitlines()[2], "p1=0x00 0x00")
    check("card + goalie share the 2nd player line", render({s_key}, True, 0).splitlines()[3], "p2=0x20 0x80")
    check("D = 2nd player byte 1 0x40", render({0x44}, False, 0).splitlines()[3], "p2=0x00 0x40")
    check("B = 2nd player byte 0 0x02", render({0x42}, False, 0).splitlines()[3], "p2=0x02 0x00")
    check("test", render({f1}, False, 0).splitlines()[1], "sys=0x80")
    check("card held", render(set(), True, 0).splitlines()[3], "p2=0x20 0x00")
    check("card + sensor 2", render({0x38}, True, 0).splitlines()[3], "p2=0x30 0x00")
    card, coin, ev = step({cardk}, set(), False, 0)
    check("card key edge -> in", (card, ev), (True, ["card IN the slot"]))
    card, coin, ev = step({cardk}, {cardk}, card, coin)
    check("card key still held -> no change", (card, ev), (True, []))
    card, coin, ev = step({cardk}, set(), card, coin)
    check("card key again -> out", card, False)
    check("card key is not F10", CARD_VK != 0x79, True)
    card, coin, _ = step({five}, set(), card, coin)
    card, coin, _ = step({five}, {five}, card, coin)
    card, coin, _ = step({five}, set(), card, coin)
    check("two presses of 5 -> 2 coins", coin, 2)
    check("free play: START press adds a coin", step({enter}, set(), False, 4)[1], 5 if FREE_PLAY else 4)
    check("free play: holding START adds no more", step({enter}, {enter}, False, 5)[1], 5)
    armed = (0.15, 0.35)                           # Enter went down at t = 0
    check("START not yet at 0.10 s", start_held(0.10, True, armed), False)
    check("START at 0.20 s after a tap", start_held(0.20, False, armed), True)
    check("START let go at 0.40 s after a tap", start_held(0.40, False, armed), False)
    check("START still held at 0.90 s while the key is down", start_held(0.90, True, armed), True)
    check("nothing armed -> no START", start_held(5.0, True, None), False)
    wait_on, wait_off = [0x00, 0x08, 0x60], [0x00, 0x00, 0x80]
    check("eject: card in 3 s, waiting 0.3 s -> out", should_eject(10.0, True, 7.0, wait_on, 9.7)[0], True)
    check("eject: just inserted (grace) -> stays", should_eject(10.0, True, 8.5, wait_on, 9.0)[0], False)
    check("eject: waiting only 0.1 s -> stays", should_eject(10.0, True, 5.0, wait_on, 9.9)[0], False)
    check("eject: first sight starts the clock", should_eject(10.0, True, 5.0, wait_on, None), (False, 10.0))
    check("eject: card in use (bit off) -> stays, clock reset", should_eject(10.0, True, 5.0, wait_off, 9.0), (False, None))
    check("eject: card already out -> nothing", should_eject(10.0, False, None, wait_on, 9.0)[0], False)
    check("eject: no outputs file -> nothing", should_eject(10.0, True, 5.0, None, 9.0), (False, None))
    check("outputs: missing file -> None", read_outputs(os.path.join(tempfile.mkdtemp(), "none.txt")), None)
    op = os.path.join(tempfile.mkdtemp(), "o.txt")
    with open(op, "w") as f:
        f.write("# the game's JVS outputs\n00 08 60\n")
    check("outputs: parsed", read_outputs(op), [0x00, 0x08, 0x60])
    with open(op, "w") as f:
        f.write("# garbled\nzz 08\n")
    check("outputs: garbled -> None", read_outputs(op), None)
    check("button events", step({x}, set(), False, 0)[2], ["PRESS (decide) down"])
    check("release events", step(set(), {x}, False, 0)[2], ["PRESS (decide) up"])
    # ---- keys.txt (the KEYS panel's file)
    kd = tempfile.mkdtemp()
    kp = os.path.join(kd, "keys.txt")
    check("keys: no file -> the defaults", load_keys(kp), (dict(DEFAULTS), []))
    with open(kp, "w") as f:
        f.write("# test\nSTART=0x20\nshoot = 0x56\n\nPRESS=V\nCOIN=0x1B\nKEEPER=0x79\nNOPE=0x41\nTEST=0x7a\n")
    k2, notes = load_keys(kp)
    check("keys: START -> Space, SHOOT -> V (names any case, spaces)", (k2["START"], k2["SHOOT"]), (0x20, 0x56))
    check("keys: a bad value, Esc, F10, F11, an unknown name - each skipped with a note",
          (k2["PRESS"], k2["COIN"], k2["KEEPER"], k2["TEST"], len(notes)), (0x58, 0x35, 0x42, 0x70, 5))
    with open(kp, "w") as f:
        f.write("SHOOT=0x58\n")                     # X is PRESS's by default
    k3, notes = load_keys(kp)
    check("keys: a clash - the file's line wins, PRESS has no free default -> no key",
          (k3["SHOOT"], k3["PRESS"]), (0x58, 0))
    with open(kp, "w") as f:
        f.write("SHOOT=0x58\nPRESS=0x43\n")         # a swap, as the panel writes it
    k4, notes = load_keys(kp)
    check("keys: a swap is no clash", (k4["SHOOT"], k4["PRESS"], notes), (0x58, 0x43, []))
    with open(kp, "w") as f:
        f.write("START=0x0D\nSTART=0x20\n")
    check("keys: the same action twice - the last line counts, no clash with itself", load_keys(kp)[0]["START"], 0x20)
    with open(kp, "wb") as f:
        f.write(b"\xff\xfe garbage \x00\nSTART")
    check("keys: a garbled file -> the defaults, no exception", load_keys(kp)[0], dict(DEFAULTS))
    vks = [vk for vk in load_keys(kp)[0].values() if vk]
    check("keys: the defaults use every key once", len(vks), len(set(vks)))
    check("keys: no default is forbidden", all(v in ALLOWED_VKS for v in DEFAULTS.values()), True)
    try:
        apply_keys(k2)                              # START = Space, SHOOT = V
        check("rebound: Space holds START", render({0x20}, False, 0).splitlines()[2], "p1=0x80 0x00")
        check("rebound: V holds SHOOT, C does nothing now", (render({0x56}, False, 0).splitlines()[2],
                                                            render({0x43}, False, 0).splitlines()[2]),
              ("p1=0x01 0x00", "p1=0x00 0x00"))
        check("rebound: Enter is no longer START", render({0x0D}, False, 0).splitlines()[2], "p1=0x00 0x00")
        check("rebound: free play follows START to Space", step({0x20}, set(), False, 0)[1], 1 if FREE_PLAY else 0)
        check("rebound: the keys polled", sorted(ALL_VKS), sorted(v for n, v in k2.items() if v))
        apply_keys(k3)                              # PRESS has no key
        check("no key: PRESS is not polled and holds nothing", (0 in ALL_VKS, render({0}, False, 0).splitlines()[2]),
              (False, "p1=0x00 0x00"))
    finally:
        apply_keys(DEFAULTS)
    check("defaults back: Enter is START", render({0x0D}, False, 0).splitlines()[2], "p1=0x80 0x00")
    check("key names", [key_label(v) for v in (0x0D, 0x20, 0x41, 0x35, 0x70, 0x87, 0x26, 0x60, 0xBD, 0)],
          ["Enter", "Space", "A", "5", "F1", "F24", "Up", "Num0", "-", "(none)"])
    d = tempfile.mkdtemp()
    p = os.path.join(d, "in.txt")
    check("missing file -> out, 0", read_start(p), (False, 0))
    write(p, render(set(), True, 3))
    check("round trip", read_start(p), (True, 3))
    with open(p, "w") as f:
        f.write("p2=zz\ncoin1=-4\njunk\n")
    check("garbled file -> out, 0", read_start(p), (False, 0))
    write(p, render({x}, False, 1))
    check("write leaves no .tmp", os.path.exists(p + ".tmp"), False)
    # ---- controllers: keys.txt's PAD lines, the rest rule, Pads on a stand-in for winmm (nothing real is asked)
    every = [PAD_BUTTON + n for n in range(1, 33)] + [PAD_AXIS + i for i in range(12)] + [PAD_HAT + i for i in range(4)]
    check("pad words <-> controls, every control both ways", all(pad_code(pad_token(c)) == c for c in every), True)
    check("pad words: case and spaces do not matter",
          [pad_code(t) for t in ("b3", " B 12 ", "hat up", "HATLEFT", "y-", "Z+")],
          [PAD_BUTTON + 3, PAD_BUTTON + 12, PAD_HAT, PAD_HAT + 3, PAD_AXIS + 2, PAD_AXIS + 5])
    check("pad words refused", [pad_code(t) for t in ("B0", "B33", "B", "B-1", "Q+", "X", "HAT", "HAT NORTH", "",
                                                      None, "0x0D", "B³", "B99999")], [0] * 13)
    check("pad names", [pad_label(c) for c in (PAD_BUTTON + 3, PAD_AXIS + 2, PAD_AXIS + 3, PAD_AXIS, PAD_AXIS + 1,
                                               PAD_AXIS + 5, PAD_HAT + 1, 0)],
          ["Button 3", "Stick Up", "Stick Down", "Stick Left", "Stick Right", "Axis Z+", "D-pad Right", "(none)"])
    kp2 = os.path.join(kd, "keys_pad.txt")
    check("pads: no file -> none", load_pads(kp2), ({}, []))
    with open(kp2, "w") as f:
        f.write("START=0x0D\nPAD START=B10\npad shoot = b2\nPAD UP=Y-\nPAD LEFT = hat left\nPAD NOPE=B1\n"
                "PAD DATA=B99\nPAD KEEPER=B2\nPAD COIN=B5\nPAD COIN=\nPAD TEST\nPAD  SERVICE  X  =B7\n")
    pm, pn = load_pads(kp2)
    check("pads: read in any case and spacing; COIN's last line (none) counts",
          pm, {"START": PAD_BUTTON + 10, "SHOOT": PAD_BUTTON + 2, "UP": PAD_AXIS + 2, "LEFT": PAD_HAT + 3})
    check("pads: an unknown action, a bad word, a control given twice - one note each", len(pn), 3)
    check("keys: PAD lines are left to load_pads - no note, the keys as given", load_keys(kp2), (dict(DEFAULTS), []))
    with open(kp2, "w") as f:
        f.write("PAD START=B1\nPAD SHOOT=B1\nPAD START=B4\n")
    check("pads: the same action twice - its last line counts (so SHOOT keeps B1, no clash)",
          load_pads(kp2), ({"START": PAD_BUTTON + 4, "SHOOT": PAD_BUTTON + 1}, []))
    with open(kp2, "wb") as f:
        f.write(b"\xff\xfe PAD START=B3 \x00\nPAD")
    check("pads: a garbled file -> no exception", isinstance(load_pads(kp2)[0], dict), True)
    still = [0.0, 0.0, None, None, None, None]                # a stick at rest, no other axes
    d = PadDevice(0, still, 0xFFFF)
    check("pad: nothing held -> nothing", d.read(0, still, 0xFFFF), set())
    check("pad: button 3 and the stick up", d.read(0b100, [0.0, -1.0, None, None, None, None], 0xFFFF),
          {PAD_BUTTON + 3, PAD_AXIS + 2})
    check("pad: a diagonal on the hat holds both its directions (45 and 315 degrees)",
          (d.read(0, still, 4500), d.read(0, still, 31500)), ({PAD_HAT, PAD_HAT + 1}, {PAD_HAT, PAD_HAT + 3}))
    check("pad: an axis is pressed past 0.5, still held at 0.4, let go at 0.25 (no flicker)",
          [bool(d.read(0, [v, 0.0] + [None] * 4, 0xFFFF)) for v in (0.45, 0.6, 0.4, 0.25, 0.45)],
          [False, True, True, False, False])
    trig = [0.0, 0.0, None, None, -1.0, -1.0]                 # a PlayStation pad: its triggers rest at one end of U, V
    d = PadDevice(0, trig, 0xFFFF)
    check("rest: triggers resting at one end are no press", d.read(0, trig, 0xFFFF), set())
    check("rest: a trigger pulled all the way is", d.read(0, [0.0, 0.0, None, None, 1.0, -1.0], 0xFFFF),
          {PAD_AXIS + 9})
    check("rest: back to rest after a half pull - still no press",
          [d.read(0, [0.0, 0.0, None, None, u, -1.0], 0xFFFF) for u in (0.0, -1.0)], [set(), set()])
    d = PadDevice(0b1, still, 0)                              # button 1 and the hat's up held when first seen
    check("held when first seen: no press while still held", d.read(0b1, still, 0), set())
    d.read(0, still, 0xFFFF)
    check("... let go, then pressed again: a press", d.read(0b1, still, 0), {PAD_BUTTON + 1, PAD_HAT})
    d = PadDevice(0, [-1.0, 0.0] + [None] * 4, 0xFFFF)        # a stick held left when first seen
    check("a stick held left when first seen: left never a press while plugged in, right still is",
          [d.read(0, [v, 0.0] + [None] * 4, 0xFFFF) for v in (0.0, -1.0, 1.0)], [set(), set(), {PAD_AXIS + 1}])

    class Caps:                                               # what winmm's JOYCAPSW answers, as far as used
        def __init__(self, axes=2, caps=0x10, pid=0x0006):
            self.wNumButtons, self.wNumAxes, self.wCaps, self.wMid, self.wPid = 12, axes, caps, 0x0079, pid
            self.szPname = "Microsoft PC-joystick driver"
            for a in AXES:
                setattr(self, "w%smin" % a, 0)
                setattr(self, "w%smax" % a, 65535)

    class Info:                                               # what winmm's JOYINFOEX answers
        def __init__(self, buttons=0, x=32767, y=32767, z=32767, r=32767, u=32767, v=32767, pov=0xFFFF):
            self.dwButtons, self.dwXpos, self.dwYpos, self.dwZpos = buttons, x, y, z
            self.dwRpos, self.dwUpos, self.dwVpos, self.dwPOV = r, u, v, pov

    class Api:                                                # a stand-in for Winmm: slot -> (Caps, Info)
        def __init__(self):
            self.devs, self.changed = {}, 0

        def caps(self, jid):
            return self.devs[jid][0] if jid in self.devs else None

        def pos(self, jid):
            return self.devs[jid][1] if jid in self.devs else None

        def config_changed(self):
            self.changed += 1
    api, said = Api(), []
    pads = Pads(api, say=said.append, name=lambda c: "pad %04X" % c.wPid, thread=False)
    pads.rescan()
    check("Pads: none plugged in -> Windows' list read again, nothing found", (api.changed, pads.poll(), said),
          (1, set(), []))
    api.devs[2] = (Caps(), Info())
    pads.rescan()
    check("Pads: one plugged in -> found and said", (pads.names(), said),
          (["pad 0006"], ["controller found: pad 0006 (12 buttons)"]))
    n0 = api.changed
    pads.rescan()
    check("Pads: Windows' list is not read again while a controller is found", api.changed, n0)
    api.devs[2] = (Caps(), Info(buttons=0b100, y=0))
    check("Pads: button 3 and the stick up", pads.poll(), {PAD_BUTTON + 3, PAD_AXIS + 2})
    api.devs[5] = (Caps(axes=4, caps=0x1F, pid=0x0CE6), Info(u=0, v=0))   # a second one: triggers at rest on U, V
    pads.rescan()
    api.devs[5] = (Caps(axes=4, caps=0x1F, pid=0x0CE6), Info(buttons=0b1, u=0, v=0))
    check("Pads: two controllers count as one; the second's resting triggers are no press", pads.poll(),
          {PAD_BUTTON + 1, PAD_BUTTON + 3, PAD_AXIS + 2})
    del api.devs[2]
    check("Pads: one unplugged -> let go and said, the other still read", (pads.poll(), said[-1]),
          ({PAD_BUTTON + 1}, "controller gone: pad 0006"))
    api.devs[2] = (Caps(), Info(buttons=0b100))
    pads.rescan()
    check("Pads: plugged in again with button 3 held -> no press until let go", pads.poll(), {PAD_BUTTON + 1})
    try:
        apply_keys(DEFAULTS, {"START": PAD_BUTTON + 10, "PRESS": PAD_BUTTON + 1, "UP": PAD_AXIS + 2})
        check("controls: button 1 holds PRESS as X does", render({PAD_BUTTON + 1}, False, 0).splitlines()[2],
              "p1=0x02 0x00")
        check("controls: the stick up holds CENTRAL", render({PAD_AXIS + 2}, False, 0).splitlines()[2], "p1=0x20 0x00")
        check("controls: START's key and control at once - one press, one coin",
              step({0x0D, PAD_BUTTON + 10}, set(), False, 0)[1], 1 if FREE_PLAY else 0)
        check("controls: the control pressed while the key is held - no second coin",
              step({0x0D, PAD_BUTTON + 10}, {0x0D}, False, 1)[1], 1)
        check("controls: free play follows START to its control", step({PAD_BUTTON + 10}, set(), False, 0)[1],
              1 if FREE_PLAY else 0)
        check("controls: a control with no job does nothing", render({PAD_BUTTON + 7}, False, 0).splitlines()[1:4],
              ["sys=0x00", "p1=0x00 0x00", "p2=0x00 0x00"])
        apply_keys(dict(DEFAULTS, PRESS=0), {"PRESS": PAD_BUTTON + 1})
        check("controls: an action with no key still works by its control",
              render({PAD_BUTTON + 1}, False, 0).splitlines()[2], "p1=0x02 0x00")
        check("controls: events name the action", step({PAD_BUTTON + 1}, set(), False, 0)[2], ["PRESS (decide) down"])
        check("free play's timing holds START whatever its inputs say", render(set(), False, 0, start=True).splitlines()[2],
              "p1=0x80 0x00")
    finally:
        apply_keys(DEFAULTS)
    check("apply_keys(DEFAULTS) leaves no control", (PADS, render({PAD_BUTTON + 1}, False, 0).splitlines()[2]),
          ({}, "p1=0x00 0x00"))
    print("selftest: %d passed, %d failed" % (ok, bad))
    return 0 if bad == 0 else 1


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    if argv:
        print("usage: python _keys_seat1.py   (or --selftest)")
        return 2
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u.GetForegroundWindow.restype = w.HWND
    u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    k.OpenProcess.restype = w.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    k.CreateMutexW.restype = w.HANDLE
    k.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    # A click inside this window would put its console in text-selection mode and FREEZE this program (no keys
    # until Esc) - the same thing that froze the control server on 2026-10-04. Switch click-to-select off.
    k.GetStdHandle.restype = w.HANDLE
    k.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k.SetConsoleMode.argtypes = [w.HANDLE, w.DWORD]
    cin, cmode = k.GetStdHandle(0xFFFFFFF6), w.DWORD()     # STD_INPUT_HANDLE
    if cin and k.GetConsoleMode(cin, ctypes.byref(cmode)):
        k.SetConsoleMode(cin, (cmode.value & ~0x0040) | 0x0080)   # QuickEdit off, extended flags on
    k.CreateMutexW(None, False, "Local\\wccf_keys_seat1")
    if ctypes.get_last_error() == 183:            # ERROR_ALREADY_EXISTS
        print("_keys_seat1.py is already running in another window - use that one")
        time.sleep(4)
        return 1
    u.GetPropW.argtypes = [w.HWND, w.LPCWSTR]
    u.GetPropW.restype = w.HANDLE
    cache = {}

    def is_game(hwnd):
        if hwnd not in cache:
            pid = w.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            name = ""
            h = k.OpenProcess(0x1000, False, pid.value)
            if h:
                buf = ctypes.create_unicode_buffer(520)
                n = w.DWORD(520)
                if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    name = os.path.basename(buf.value).lower()
                k.CloseHandle(h)
            if len(cache) > 64:
                cache.clear()
            cache[hwnd] = (name == "client_release.exe")
        return cache[hwnd]

    u.WindowFromPoint.argtypes = [w.POINT]
    u.WindowFromPoint.restype = w.HWND

    def game_in_front():
        """a game window in front - or the combined window of fpr_panel.py (it marks itself WCCF_GAME_HOST),
        unless its card search box has the keyboard (it sets WCCF_TYPING) and the mouse is not over the game:
        typing a player's name presses no buttons.  The in-game card browser (wccfpanel.dll) sets WCCF_TYPING on
        the GAME window itself while it is open - no buttons then either."""
        fg = u.GetForegroundWindow()
        if not fg:
            return False
        if is_game(fg):
            return not u.GetPropW(fg, "WCCF_TYPING")
        if not u.GetPropW(fg, "WCCF_GAME_HOST"):
            return False
        pt = w.POINT()
        if u.GetCursorPos(ctypes.byref(pt)):
            under = u.WindowFromPoint(pt)
            if under and is_game(under):
                return True
        return not u.GetPropW(fg, "WCCF_TYPING")

    def stamped(msg):
        print(time.strftime("%H:%M:%S"), " ", msg, flush=True)

    def start_pads():
        """the controllers' reader, the first time keys.txt gives a controller a job (False: none on this PC)"""
        try:
            p = Pads(Winmm(), say=stamped)
        except (OSError, AttributeError) as ex:          # no winmm or no joystick calls: the keys still work
            stamped("controllers cannot be read on this PC (%r) - the keys still work" % ex)
            return False
        stamped("controllers: looking for them (keys.txt gives one a job)")
        return p

    card, coin = read_start(LIVE)
    kpath = keys_path()
    keys, notes = load_keys(kpath)
    pmap, pnotes = load_pads(kpath)
    apply_keys(keys, pmap)
    pads = None                                          # the controllers' reader once needed (start_pads)
    kstamp, next_keys_check = file_stamp(kpath), 0.0
    print("WCCF 2010-11 seat 1 - keyboard and controller (both count only while a game window is in front)")
    for name, _d, _bits, what in ACTIONS:
        print("  %-9s %-12s %s" % (key_label(KEYS[name]), pad_label(PADS[name]) if name in PADS else "", what))
    print("keys from %s%s" % (kpath, "" if os.path.exists(kpath) else " (not there yet: the defaults)"))
    for n in notes + pnotes:
        print("  keys.txt: " + n)
    print("now: card %s, coin counter %d.  Close this window to stop." % ("IN" if card else "OUT", coin))
    if FREE_PLAY:
        print("FREE PLAY: every Enter (START) puts a coin in for you first - no need for 5.")
    if AUTO_EJECT:
        print("CARD: when the game ejects the card it comes out by itself - press I to put it back in.")
    prev, last, armed = set(), None, None
    card_in_since = time.time() if card else None
    waiting_since, next_out_check = None, 0.0
    try:
        while True:
            now = time.time()
            if now >= next_keys_check:               # the KEYS panel saved new keys: use them at once
                next_keys_check = now + 0.5
                st = file_stamp(kpath)
                if st != kstamp:
                    kstamp = st
                    keys, notes = load_keys(kpath)
                    pmap, pnotes = load_pads(kpath)
                    changed = [n for n, _d, _b, _w in ACTIONS if keys[n] != KEYS[n]]
                    pchanged = [n for n, _d, _b, _w in ACTIONS if pmap.get(n, 0) != PADS.get(n, 0)]
                    if changed or pchanged:
                        apply_keys(keys, pmap)
                    if changed:
                        print(time.strftime("%H:%M:%S"), "  keys: " +
                              ", ".join("%s = %s" % (n, key_label(keys[n])) for n in changed))
                    if pchanged:
                        print(time.strftime("%H:%M:%S"), "  controller: " +
                              ", ".join("%s = %s" % (n, pad_label(pmap.get(n, 0))) for n in pchanged))
                    for n in notes + pnotes:
                        print(time.strftime("%H:%M:%S"), "  keys.txt: " + n)
            if PADS and pads is None:
                pads = start_pads()
            front = game_in_front()
            down = {vk for vk in ALL_VKS if front and (u.GetAsyncKeyState(vk) & 0x8000)}
            if front and pads and PADS:
                down |= pads.poll()                      # controller controls: numbers above every key code
            was_in = card
            card, coin, events = step(down, prev, card, coin)
            if card and not was_in:
                card_in_since = now
            if AUTO_EJECT and now >= next_out_check:
                next_out_check = now + 0.1
                eject, waiting_since = should_eject(now, card, card_in_since, read_outputs(), waiting_since)
                if eject:
                    card, card_in_since, waiting_since = False, None, None
                    events.append("the game ejected the card - taken out (press I to put it back in)")
            start = None
            if FREE_PLAY:                                # START by its key or its controller control
                acts = held_actions(down)
                if "START" in acts - held_actions(prev):
                    armed = (now + START_DELAY, now + START_MIN)
                start = start_held(now, "START" in acts, armed)
            text = render(down, card, coin, start)
            if text != last:
                write(LIVE, text)
                last = text
            for e in events:
                print(time.strftime("%H:%M:%S"), " ", e)
            prev = down
            time.sleep(0.01)
    except KeyboardInterrupt:
        write(LIVE, render(set(), card, coin))     # let go of every button, keep card and coins
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
