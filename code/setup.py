# -*- coding: utf-8 -*-
r"""setup.py - make your own copy of WCCF 2010-11 (Rev D) run on this PC with the kit.
Run it once (SETUP.exe); running it again checks everything and repairs what is missing.

    python setup.py [GAME]     GAME = the game folder, the one that holds client_Release.exe (or the folder above
                               it); asked for if not given, then remembered in data\settings.json
    python setup.py undo       put the game folder back the way it was before setup

What it changes, and nothing else on the PC:
  in extracted\   + wccfk.dll (the kit's hook) and the game's import of WINMM.dll renamed to it, so the hook loads
                  under its own name (no system-named fake winmm.dll - what Windows Defender flagged); undo restores
                  Sega's WINMM import exactly.  logowin.exe stays Sega's: the hook keeps the server from starting it
                  (a kit before 2026-10-09 put a stand-in there, Sega's as logowin_sega.exe - Sega's goes back)
                  + local\client_user_option.conf (the projector) and local\ctrl_user_option.conf (the server)
  beside it       seat1\   the player cabinet: links to extracted\'s folders and files, its own patched
                           client_Release.exe (15 changes, checked byte for byte) and its own local\ settings
                  misc\FlatPanelReader_Emulator\exe\FPR_Emu.exe   the card-table helper the game starts
  in the kit      data\cache\catalogue.tsv, data\cache\cards\   the catalogue and card pictures, made from YOUR files
                  data\   settings, your club card (data\save), logs
                  an older kit's scripts\, english\, bin\ and overlay\ (before kit 6): its own files removed, its catalogue and
                  card pictures moved to data\cache\ (tidy_old_layout)
Exit: 0 done; 1 a step failed (the message says which); 2 no usable game folder.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys

from cards import catalogue
import kit_common as K
from helpers import hook as H

SEGA_CLIENT = "AEF9998D8A77B4DD7A0CFF3753A11FC8689A6700E133265D6681EF28D3E9CEA4"
PATCHED_CLIENT = "6243C394E9A57B33C23519326EF8A77B0992873A0033B5892A9155C5B827E20A"
SEGA_OTHERS = {"control_Release.exe": "23B9553096BB195FC991A1FC141D719DF3C8AE88460959A88CDFC18863A1376F",
               "match_Release.exe": "D6A1D05D9B0D7365F4260A38EC4D25A55D996AABB83F436B59BDE81CEDDACB38"}
SEGA_LOGOWIN = "0BFB857AF8627282BBEED9F3C977D6EC30F9E110A408E9683008F47637471326"
# seat 1's exe = Sega's + these 15 changes: (address, file offset, Sega's bytes, new bytes, what)
PATCHES = [
    (0x00401771, 0x000B71, "8d8140fcffff", "31c090909090", "picture layout: no left offset"),
    (0x0040178F, 0x000B8F, "c74644c0030000e936ffffff", "894e448b7e30e937ffffff90", "picture layout: full width"),
    (0x0045A56A, 0x05996A, "741a", "9090", "a main-board check jump (no effect found; kept: the tested exe)"),
    (0x004D91C9, 0x0D85C9, "01", "00", "I/O board in JVS mode 0 (COM4)"),
    (0x004E0AE0, 0x0DFEE0, "6aff68", "b001c3", "keychip check passes (error 0949)"),
    (0x004EE000, 0x0ED400, "558bec", "32c0c3", "camera firmware check passes (error 0xC05)"),
    (0x004EE080, 0x0ED480, "5333db", "32c0c3", "camera board check passes (error 5801)"),
    (0x004EE102, 0x0ED502, "38", "c3", "resolution check passes (error 0910)"),
    (0x00570C2A, 0x17002A, "c74604b7140000", "90909090909090", "main board error 5303 not raised"),
    (0x00570C61, 0x170061, "c7460419000000", "90909090909090", "main board error 0025 not raised"),
    (0x00570C98, 0x170098, "c746041a000000", "90909090909090", "main board error 0026 not raised"),
    (0x007A7066, 0x3A6466, "8b80fc000000", "33c090909090", "board error read as 0 (no effect found; kept)"),
    (0x00988668, 0x587668, "01000000", "02000000", "smooth texture scaling"),
    (0x009FBCE8, 0x5FACE8, "2003", "a005", "screen width 800 -> 1440"),
    (0x009FBCEC, 0x5FACEC, "5802", "8403", "screen height 600 -> 900"),
]
JUNCTIONS = ["AI", "data", "lighting", "Microsoft.VC90.CRT", "Microsoft.VC90.MFC", "prog_data", "script", "shader",
             "update"]
NO_LINK = re.compile(r"^(busram\d+\.bin|eeprom\d+\.bin|logowin_messages\.txt|client_release\.exe|wccfk\.dll|"
                     r"winmm\.dll|mxsram\.bin|.*\.log|.*\.bmp|.*\.tmp)$", re.I)
SEAT_DATA = re.compile(r"^(busram\d+\.bin|eeprom\d+\.bin|mxsram\.bin|fpr_table\d\.txt|fpr_panel_state\.json)$", re.I)
MARKER = ".wccf-kit"
WINMM = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "winmm.dll")
D3DX = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64", "d3dx9_40.dll")

CONF_HEAD = ("# WCCF 2010-11 - %s - written by the kit's setup.py.\r\n"
             "# DHCP=0 skips the network self-test; FPR_MODE=2 = the card-table helper; FULL_SCREEN_MODE=0 = a window.\r\n"
             "# SATELLITE_NO = the seat (0 projector, 1-8 player cabinets), set here because the game would otherwise\r\n"
             "# read it from its command line, which breaks on folder names with spaces.\r\n")
CLIENT_KEYS = ("IS_RINGEDGE=%d\r\nALLNET_AUTH=0\r\nDHCP=0\r\nCONTROL_IP=127.0.0.1\r\nCONTROL_PORT=20002\r\n"
               "MATCH_IP=127.0.0.1\r\nMATCH_PORT=20003\r\nFPR_MODE=2\r\nFULL_SCREEN_MODE=0\r\n%sSATELLITE_NO=%d\r\n")
CONF_PROJECTOR = CONF_HEAD % "the PROJECTOR (seat 0)" + CLIENT_KEYS % (0, "", 0)
CONF_SEAT1 = (CONF_HEAD % "the PLAYER CABINET (seat 1)" + CLIENT_KEYS % (1, "MANAGEMENT_0910=0\r\n", 1) +
              "TIMEOUT_P2P=%d\r\n" % K.MATCH_WAIT_LOCAL)
CONF_CONTROL_BEFORE_KIT7 = (
    "# WCCF 2010-11 - the SERVER (control) - written by the kit's setup.py: everything on this PC.\r\n"
    "# CLIENT_MAX must stay 9 (the game's own default): fewer made the server crash.\r\n"
    "# FIX_REST_ENTRY_TIME = seconds the entry window stays open each cycle (the game's own: 40). Longer, so\r\n"
    "# seat 1 can still enter the first match after starting and the projector does not wait a whole\r\n"
    "# 12-minute cycle on \"Now Synchronizing\".\r\n"
    "DHCP=0\r\nIS_RINGEDGE=0\r\nALLNET_AUTH=0\r\nACCEPT_ALL_IP=1\r\nCLIENT_MAX=9\r\nACCEPT_IP_0=127.0.0.1\r\n"
    "CONTROL_PORT=20002\r\nMATCH_PORT=20003\r\nGAME_SVR_IP=127.0.0.1\r\nFIX_REST_ENTRY_TIME=120\r\n")
# Kit 7 (2026-10-15, the owner: "anytime there is a chance of playing against each other it should be done"): random
# pairing in a free round no longer needs close club strengths (docs\research\ARRANGE-FIXTURE-2010-11.md section 9).
# Control reads the value with atoi and no limit; never write the key with an empty value (a likely crash at start).
CONF_CONTROL_KIT7 = CONF_CONTROL_BEFORE_KIT7 + (
    "# MATCHING_PARA_FM1 = the largest matching-value gap at which two free players are paired at random (the game's\r\n"
    "# own: 600; a club's value runs 0-16383). 20000 lets any two players in a free round play each other.\r\n"
    "MATCHING_PARA_FM1=20000\r\n")
# DREAM TEAM (2026-10-15, the owner: its players "cant be playing against people that are playing the game as it
# should be"; his choice: one server, friendlies only): a DREAM TEAM club reports the top value, 16383 (wccfpanel.c
# dream_team_install).  Real clubs: 2,004-6,054, gaps up to 4,050 (docs\PLAN-DREAM-TEAM.md on the PC).
CONF_CONTROL = CONF_CONTROL_BEFORE_KIT7 + (
    "# MATCHING_PARA_FM1 = the largest matching-value gap at which two free players are paired at random (the game's\r\n"
    "# own: 600; a club's value runs 0-16383, real ones 2000-6100). 6500: any two clubs as strong as those still play\r\n"
    "# each other; a DREAM TEAM club (it reports 16383) meets only clubs above 9883 - in practice only DREAM TEAM ones.\r\n"
    "MATCHING_PARA_FM1=6500\r\n")
EARLIER_KIT_CONFS = {   # byte for byte what an earlier kit wrote (play.py's own lines aside): replaced without keeping
    # a copy (any other text is a hand edit and is kept as .before-kit).  The first kit's, before FIX_REST_ENTRY_TIME:
    b"# WCCF 2010-11 - the SERVER (control) - written by the kit's setup.py: everything on this PC.\r\n"
    b"# CLIENT_MAX must stay 9 (the game's own default): fewer made the server crash.\r\n"
    b"DHCP=0\r\nIS_RINGEDGE=0\r\nALLNET_AUTH=0\r\nACCEPT_ALL_IP=1\r\nCLIENT_MAX=9\r\nACCEPT_IP_0=127.0.0.1\r\n"
    b"CONTROL_PORT=20002\r\nMATCH_PORT=20003\r\nGAME_SVR_IP=127.0.0.1\r\n",
    CONF_CONTROL_BEFORE_KIT7.encode("ascii"), CONF_CONTROL_KIT7.encode("ascii")}
ENGLISH_BACKUP = os.path.join(K.DATA, "english_backup")     # english.py keeps Sega's files here while English is on


class Failed(Exception):
    pass


def ok(msg):
    print("  ok    " + msg, flush=True)


def note(msg):
    print("  NOTE  " + msg, flush=True)


def put_file(data, path):
    """write bytes whole (temp file + swap): a crash never leaves half a file; replaces a link, never its target"""
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)


def copy_if_different(src, dst, what):
    if os.path.isfile(dst) and K.sha256(dst) == K.sha256(src):
        ok("%s already in place" % what)
        return
    put_file(open(src, "rb").read(), dst)
    if K.sha256(dst) != K.sha256(src):
        raise Failed("%s: the copy does not match" % what)
    ok("%s put in place" % what)


def norm_sha(path):
    """SHA-256 of a game program with its hook import renamed back to WINMM.dll (hook.normalized) - so a
    fingerprint is the same whether or not setup has already renamed the import to the kit's own wccfk.dll. Any file
    that is not a PE / does not import the hook hashes as-is."""
    try:
        return K.sha256(H.normalized(open(path, "rb").read()))
    except (OSError, H.PatchError):
        return K.sha256(path)


def rename_hook_import(path, what):
    """rename the game program's WINMM.dll import to the kit's own wccfk.dll, so it loads the hook by an honest name
    (no system-named side-loading DLL - what Windows Defender flagged). Idempotent: a program already renamed is left
    alone. Raises Failed only if the program does not import winmm at all (not Sega's exe)."""
    data = open(path, "rb").read()
    if H.imports_hook(data):
        return False
    try:
        put_file(H.rename_import(data), path)
    except H.PatchError as ex:
        raise Failed("%s: could not point it at the kit's hook (%s)" % (what, ex))
    ok("%s loads the kit's hook by its own name (wccfk.dll)" % what)
    return True


# the lines play.py sets at each start (the server's address, the seat, whether to wait for a projector, the
# projector's port - the server's projector relay, 2026-10-17): a file that differs from ours only there is ours, as
# play.py left it - not a hand edit (2026-10-06: online play changes them)
RUNTIME_LINES = re.compile(rb"(?m)^(CONTROL_IP|CONTROL_PORT|MATCH_IP|SATELLITE_NO|WAIT_PROJECTOR|TIMEOUT_P2P)=[^\r\n]*(\r?\n|$)")


def write_text(path, text, what):
    if os.path.isfile(path) and open(path, "rb").read() == text.encode("ascii"):
        ok("%s already in place" % what)
        return
    if os.path.isfile(path) and RUNTIME_LINES.sub(b"", open(path, "rb").read()) == RUNTIME_LINES.sub(b"", text.encode("ascii")):
        ok("%s already in place (with the server address / seat play.py set)" % what)
        return
    if os.path.isfile(path) and RUNTIME_LINES.sub(b"", open(path, "rb").read()) not in {
            RUNTIME_LINES.sub(b"", c) for c in EARLIER_KIT_CONFS}:      # a server's file also holds WAIT_PROJECTOR
        shutil.copyfile(path, path + ".before-kit")
        note("%s: the old one is kept as %s" % (what, os.path.basename(path) + ".before-kit"))
    put_file(text.encode("ascii"), path)
    ok("%s written" % what)


def junction_target(path):
    try:
        t = os.readlink(path)
    except OSError:
        return None
    return os.path.normcase(os.path.abspath(t[4:] if t.startswith("\\\\?\\") else t))


def make_junction(link, target):
    try:
        import _winapi
        _winapi.CreateJunction(target, link)
    except (ImportError, AttributeError, OSError):
        subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
    if junction_target(link) != os.path.normcase(os.path.abspath(target)):
        raise Failed("could not link %s to %s (is the drive NTFS?)" % (link, target))


def sega_client(game):
    """path of Sega's client exe: extracted\\'s own, or - while English is on - the copy in the backup"""
    p = os.path.join(game, "client_Release.exe")
    b = os.path.join(ENGLISH_BACKUP, "client_Release.exe")
    if norm_sha(p) != SEGA_CLIENT and os.path.isfile(b) and norm_sha(b) == SEGA_CLIENT:
        return b
    return p


def kit_language_in(path):
    """the kit's own words in a client_Release.exe that is not Sega's: "Italian" or "English" when english.py's
    build_exe wrote them at languages\\english\\exe_text.tsv's places (the text, then a zero byte), else None.  A game
    that another copy of the kit made English: this kit folder has no copy of Sega's original then (2026-10-16, a
    player unzipped the new kit into a new folder over a game his old kit had made English - SETUP said "not Rev D")"""
    try:
        with open(path, "rb") as f:
            d = f.read()
        with open(os.path.join(K.LANGUAGES, "english", "exe_text.tsv"), encoding="utf-8", newline="") as f:
            rows = [r for r in csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE) if r["program"] == "client"]
        for lang, col in (("Italian", "italiano"), ("English", "english")):
            for r in rows:
                t, o = (r.get(col) or "").encode("ascii", "replace"), int(r["offset"], 16)
                if t and d[o:o + len(t)] == t and d[o + len(t):o + len(t) + 1] == b"\0":
                    return lang
    except (OSError, ValueError, KeyError):
        pass
    return None


def english_copy(rel):
    """SHA-256 of the English file english.py put at rel (its manifest), or None when English is off"""
    try:
        with open(os.path.join(ENGLISH_BACKUP, "manifest.json"), encoding="utf-8") as f:
            return json.load(f).get(rel, {}).get("english")
    except (OSError, ValueError, AttributeError):
        return None


def patched_client(game):
    """Sega's client exe with the 15 changes, checked before and after (the base is normalized to WINMM.dll first, so
    an already-renamed Sega client still patches to the tested bytes)"""
    data = bytearray(H.normalized(open(sega_client(game), "rb").read()))
    for va, off, old, new, what in PATCHES:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        if catalogue.va_to_offset(data, va) != off or bytes(data[off:off + len(old)]) != old:
            raise Failed("client_Release.exe at 0x%08X is not Sega's Rev D bytes (%s)" % (va, what))
        data[off:off + len(new)] = new
    if K.sha256(data) != PATCHED_CLIENT:
        raise Failed("the patched exe does not come out as the tested one - not written")
    return bytes(data)


def check_game(game):
    if K.game_processes(game):
        raise Failed("the game is running - close its window first, then run setup again")
    h = norm_sha(sega_client(game))
    if sega_client(game) != os.path.join(game, "client_Release.exe"):
        ok("English is on (SETUP.exe's ENGLISH): Sega's client_Release.exe is checked in data\\english_backup")
    if h == PATCHED_CLIENT:
        raise Failed("the game folder's client_Release.exe is already PATCHED - setup needs the unchanged exe there "
                     "(only seat1\\ gets the patched copy). Put your own unchanged client_Release.exe back first.")
    if h != SEGA_CLIENT:
        lang = kit_language_in(sega_client(game))
        if lang:
            raise Failed("the game folder's client_Release.exe has the kit's %s in it - another copy of the kit put it "
                         "there, and THAT kit folder's data\\english_backup keeps Sega's originals (this one has none). "
                         "Open SETUP.exe in that kit folder and update it to this kit (UPDATE), or press JAPANESE there "
                         "first, then set up here. Without that folder: put your unchanged game files back." % lang)
        raise Failed("the game folder's client_Release.exe is not Rev D (SHA-256 %s...) - this kit is for Rev D only"
                     % h[:16])
    ok("client_Release.exe is Sega's Rev D")
    for n, want in SEGA_OTHERS.items():
        if norm_sha(os.path.join(game, n)) != want:
            note("%s is not the Rev D file this kit was tested with - it may not work" % n)
    if not os.path.isfile(WINMM):
        raise Failed("no %s - this needs 64-bit Windows 10 or 11" % WINMM)
    if not os.path.isfile(D3DX):
        note("DirectX 9 is missing (no d3dx9_40.dll): install Microsoft's \"DirectX End-User Runtime\" "
             "(June 2010) - the game cannot draw without it")
    for p, what in ((game, "the game folder"), (K.KIT, "the kit folder")):
        if any(ord(c) > 127 for c in p):
            note("%s's path has non-English letters - if the game fails, move it to a plain path like D:\\Games\\WCCF"
                 % what)


def setup_extracted(game):
    print("in %s:" % game)
    copy_if_different(os.path.join(K.PROGRAMS, "wccfk.dll"), os.path.join(game, "wccfk.dll"), "wccfk.dll (the kit's hook)")
    for n in ("client_Release.exe", "control_Release.exe", "match_Release.exe"):
        rename_hook_import(os.path.join(game, n), n)
    for old in ("winmm.dll", "winmm_orig.dll"):      # a kit before this one put a fake winmm.dll (a Windows name) here
        p = os.path.join(game, old)
        if os.path.isfile(p):
            os.remove(p)
            ok("removed the old %s - the hook now loads by its own name" % old)
    # logowin.exe (2026-10-09): the server starts it for its logo and error screens - a white window over the whole
    # screen.  The hook (wccfk.dll, above) now answers that start itself and runs nothing, so Sega's file stays.  A kit
    # before this one put a quiet stand-in there (the exe antivirus programs flagged) and kept Sega's as
    # logowin_sega.exe: Sega's goes back.  Seat 1's link to it follows (setup_seat links again what changed)
    lw, sega = os.path.join(game, "logowin.exe"), os.path.join(game, "logowin_sega.exe")
    if os.path.isfile(sega) and K.sha256(sega) == SEGA_LOGOWIN:
        if os.path.isfile(lw):
            os.remove(lw)
        os.replace(sega, lw)
        ok("Sega's logowin.exe back in place (the hook keeps the server from starting it)")
    elif os.path.isfile(lw) and K.sha256(lw) == SEGA_LOGOWIN:
        ok("logowin.exe: Sega's (the hook keeps the server from starting it)")
    else:
        note("logowin.exe is not Sega's - left alone (the hook keeps the server from starting it either way)")
    write_text(os.path.join(game, "local", "client_user_option.conf"), CONF_PROJECTOR, "projector settings")
    write_text(os.path.join(game, "local", "ctrl_user_option.conf"), CONF_CONTROL, "server settings")


def setup_seat(game):
    seat = K.seat_dir(game)
    print("in %s:" % seat)
    if os.path.isdir(seat) and not os.path.isfile(os.path.join(seat, MARKER)):
        raise Failed("there is already a folder %s that this kit did not make - move it away first" % seat)
    os.makedirs(os.path.join(seat, "local"), exist_ok=True)
    with open(os.path.join(seat, MARKER), "w", encoding="ascii") as f:
        f.write("made by the WCCF 2010-11 kit's setup.py; \"setup.py undo\" removes this folder\n")
    made = 0
    for n in JUNCTIONS:
        link, target = os.path.join(seat, n), os.path.join(game, n)
        if junction_target(link) == os.path.normcase(os.path.abspath(target)):
            continue
        if os.path.lexists(link):
            if not os.path.isjunction(link):
                raise Failed("%s is in the way (not a link)" % link)
            os.rmdir(link)                                   # an old link only
        make_junction(link, target)
        made += 1
    ok("%d folder links to extracted\\ (%d new)" % (len(JUNCTIONS), made))
    linked = new = 0
    for n in sorted(os.listdir(game)):
        src = os.path.join(game, n)
        if not os.path.isfile(src) or NO_LINK.match(n):
            continue
        dst = os.path.join(seat, n)
        if os.path.exists(dst) and os.path.samefile(src, dst):
            linked += 1
            continue
        if os.path.exists(dst):
            os.remove(dst)
        try:
            os.link(src, dst)
        except OSError as ex:
            raise Failed("could not link %s (%s) - the game must be on an NTFS drive" % (n, ex))
        linked += 1
        new += 1
    ok("%d file links to extracted\\ (%d new)" % (linked, new))
    exe = os.path.join(seat, "client_Release.exe")
    have = norm_sha(exe) if os.path.isfile(exe) else None
    if have == PATCHED_CLIENT:
        ok("client_Release.exe: seat 1's patched copy already in place")
    elif have and have == english_copy(os.path.join("seat1", "client_Release.exe")):
        ok("client_Release.exe: seat 1's patched copy with the kit's English text already in place")
    else:
        put_file(patched_client(game), exe)
        if K.sha256(exe) != PATCHED_CLIENT:
            raise Failed("seat 1's exe did not write correctly")
        ok("client_Release.exe: seat 1's own copy, 15 changes, the tested exe byte for byte")
    rename_hook_import(exe, "seat 1's client_Release.exe")
    copy_if_different(os.path.join(K.PROGRAMS, "wccfk.dll"), os.path.join(seat, "wccfk.dll"), "wccfk.dll (the kit's hook)")
    for old in ("winmm.dll", "winmm_orig.dll"):      # from a kit before this one
        p = os.path.join(seat, old)
        if os.path.isfile(p):
            os.remove(p)
    write_text(os.path.join(seat, "local", "client_user_option.conf"), CONF_SEAT1, "seat 1 settings")
    copy_if_different(os.path.join(game, "local", "SBWG_Table.dat"), os.path.join(seat, "local", "SBWG_Table.dat"),
                      "local\\SBWG_Table.dat")
    print("in %s:" % K.misc_dir(game))
    helper = os.path.join(K.misc_dir(game), "FlatPanelReader_Emulator", "exe")
    os.makedirs(helper, exist_ok=True)
    copy_if_different(os.path.join(K.PROGRAMS, "FPR_Emu.exe"), os.path.join(helper, "FPR_Emu.exe"), "FPR_Emu.exe")


# the folders a kit before 6 used (the 2026-10-11 folder move): code\ was scripts\, programs\ was bin\, art\ and
# data\cache\ were overlay\, languages\english\ was english\.  An update removes the old kit's files but not their
# folders, and never the catalogue and card pictures setup made; a kit unzipped by hand over an old one keeps all of
# it.  Only the old kit's own files go; anything else stays, and so does its folder.  A folder name (a str) = the old
# copies of the files that folder of this kit holds now; a tuple = those files by name.  scripts\: every file name
# kits 5 to 5.5.1 shipped there (git ls-tree of each kit-* tag) - kit 6 renamed them, so "is it in code\" no longer finds them.
OLD_SCRIPTS = ("_debug_launch.py", "_icc_reader.py", "_jvs_board.py", "_keys_seat1.py", "_kit_helper.py",
               "_log_inbox.py", "_no_quickedit.py", "_relay.py", "_ringedge_services.py", "_seat_broker.py",
               "_seat_lease.py", "_xscn_watch.py", "boards.py", "cards.py", "club_card_schema.py", "club_view.py",
               "club_wallet.py", "codes_inferred.py", "decode_club_card.py", "edit_club_card.py", "english.py",
               "kit_common.py", "play.py", "send_logs.py", "setup.py", "sound_defaults.py", "ys_lzw.py")
OLD_LAYOUT = {"scripts": OLD_SCRIPTS, "english": os.path.join("languages", "english"),
              "bin": ("winmm.dll", "winmm_orig.dll", "wccfk.dll", "FPR_Emu.exe", "logowin.exe"),
              "overlay": ("wccfpanel.dll", "skin.tex", "inject.exe")}
# what an older kit wrote beside its scripts while it ran: the key driver's and I/O board's files, server debug logs
OLD_RUNTIME = re.compile(r"^(_jvs_seat1_\w+|_dbg_\w+|keys_crash)\.txt$", re.I)


def tidy_old_layout():
    """move an old overlay\\ catalogue + card pictures into data\\cache\\, remove the old kit's files and then the
    empty old folders.  Housekeeping: never stops a setup (a file held open just stays, and is said)."""
    old = os.path.join(K.KIT, "overlay")
    for name in ("catalogue.tsv", "cards"):          # made from the player's own game: moved, not made again
        src, dst = os.path.join(old, name), os.path.join(K.CACHE, name)
        try:
            if not os.path.exists(src):
                continue
            if os.path.exists(dst):                  # already made in the new place: the old copy is spare
                shutil.rmtree(src) if os.path.isdir(src) else os.remove(src)
            else:
                os.makedirs(K.CACHE, exist_ok=True)
                os.replace(src, dst)
                ok("%s moved from overlay\\ to data\\cache\\" % name)
        except OSError as ex:
            note("overlay\\%s could not be moved (%s) - it is made again in data\\cache\\" % (name, ex))
    for folder, files in OLD_LAYOUT.items():
        d = os.path.join(K.KIT, folder)
        if not os.path.isdir(d):
            continue
        if isinstance(files, str):
            now = os.path.join(K.KIT, files)
            files = [n for n in os.listdir(d) if os.path.isfile(os.path.join(now, n))]
        files = list(files) + [n for n in os.listdir(d) if OLD_RUNTIME.match(n)]
        shutil.rmtree(os.path.join(d, "__pycache__"), ignore_errors=True)
        for n in files:
            try:
                os.remove(os.path.join(d, n))
            except FileNotFoundError:
                pass
            except OSError as ex:
                note("%s\\%s (an older kit's) could not be removed: %s" % (folder, n, ex))
        try:
            os.rmdir(d)
            ok("the older kit's %s\\ folder removed (this kit keeps those files in code\\, programs\\, art\\, "
               "languages\\ and data\\cache\\)" % folder)
        except OSError:
            note("%s\\ is from an older kit and still holds files that are not the kit's - left as it is" % folder)


def setup_cards(game, force=False):
    print("in the kit's data\\cache folder:")
    os.makedirs(K.CACHE, exist_ok=True)
    cat, pics = os.path.join(K.CACHE, "catalogue.tsv"), os.path.join(K.CACHE, "cards")
    have = len([n for n in os.listdir(pics) if n.endswith(".png")]) if os.path.isdir(pics) else 0
    if not force and os.path.isfile(cat) and have >= catalogue.RECORDS:
        ok("catalogue and %d card pictures already made" % have)
        return
    print("  making the catalogue and the card pictures from your game files (about a minute) ...", flush=True)
    if catalogue.main([game, K.CACHE]) != 0:
        raise Failed("the card catalogue could not be made (see above)")
    ok("catalogue and card pictures made")


def undo(game):
    if K.game_processes(game):
        raise Failed("the game is running - close its window first, then undo")
    if os.path.isfile(os.path.join(ENGLISH_BACKUP, "manifest.json")):
        raise Failed("English is on - press JAPANESE in SETUP.exe first, so Sega's files go back before the undo")
    seat = K.seat_dir(game)
    if os.path.isdir(seat):
        if not os.path.isfile(os.path.join(seat, MARKER)):
            raise Failed("%s was not made by this kit - left alone" % seat)
        keep = os.path.join(K.SAVE, "seat1_backup")
        for n in os.listdir(seat):
            if SEAT_DATA.match(n) and os.path.isfile(os.path.join(seat, n)):
                os.makedirs(keep, exist_ok=True)
                shutil.copyfile(os.path.join(seat, n), os.path.join(keep, n))
        if os.path.isdir(keep):
            ok("seat 1's formation and cabinet settings copied to data\\save\\seat1_backup")
        for n in os.listdir(seat):
            p = os.path.join(seat, n)
            if os.path.isjunction(p):
                os.rmdir(p)                          # the link only; extracted\'s folder is untouched
        for n in os.listdir(seat):
            p = os.path.join(seat, n)
            if os.path.isdir(p):
                for dp, dns, fns in os.walk(p):
                    if any(os.path.isjunction(os.path.join(dp, d)) for d in dns):
                        raise Failed("unexpected link inside %s - stopped" % p)
                shutil.rmtree(p)
            else:
                os.remove(p)                         # a file link: removes the link, never extracted\'s file
        os.rmdir(seat)
        ok("seat1\\ removed (extracted\\'s files untouched)")
    helper = os.path.join(K.misc_dir(game), "FlatPanelReader_Emulator", "exe", "FPR_Emu.exe")
    if os.path.isfile(helper):
        os.remove(helper)
        for d in (os.path.dirname(helper), os.path.dirname(os.path.dirname(helper)), K.misc_dir(game)):
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        ok("misc\\FlatPanelReader_Emulator removed")
    for n in ("client_Release.exe", "control_Release.exe", "match_Release.exe"):
        p = os.path.join(game, n)
        if os.path.isfile(p):
            data = open(p, "rb").read()
            if H.imports_hook(data):                 # a pure swap: this restores Sega's exact original bytes
                put_file(H.rename_import(data, frm=H.HOOK_DLL, to=H.SYS_DLL), p)
                ok("extracted\\%s: Sega's WINMM import restored" % n)
    for n in ("wccfk.dll", "winmm.dll", "winmm_orig.dll"):
        p = os.path.join(game, n)
        if os.path.isfile(p):
            if n in ("wccfk.dll", "winmm.dll") and b"mxhook attached" not in open(p, "rb").read():
                note("extracted\\%s is not the kit's hook - left alone" % n)
                continue
            os.remove(p)
            ok("extracted\\%s removed" % n)
    lw, sega = os.path.join(game, "logowin.exe"), os.path.join(game, "logowin_sega.exe")
    if os.path.isfile(sega) and K.sha256(sega) == SEGA_LOGOWIN:
        if os.path.isfile(lw):
            os.remove(lw)
        os.replace(sega, lw)
        ok("Sega's logowin.exe back in place")
    for n, text in (("client_user_option.conf", CONF_PROJECTOR), ("ctrl_user_option.conf", CONF_CONTROL)):
        p = os.path.join(game, "local", n)
        if os.path.isfile(p):
            if open(p, "rb").read() == text.encode("ascii"):
                os.remove(p)
                ok("extracted\\local\\%s removed" % n)
            else:
                note("extracted\\local\\%s was changed after setup - left alone" % n)
    s = K.load_settings()
    s.pop("game", None)
    K.save_settings(s)
    print("Undone. The game folder is as it was before setup, apart from the files the game itself writes when it "
          "runs (busram*.bin, eeprom*.bin). Your club card stays in data\\save.")


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    mode = "undo" if argv[:1] == ["undo"] else "setup"
    rest = argv[1:] if mode == "undo" else argv
    force_cards = "cards" in rest
    rest = [a for a in rest if a != "cards"]
    game = K.find_game(rest[0]) if rest else K.find_game(K.load_settings().get("game"))
    if rest and not game:
        print("no WCCF 2010-11 game files in %s (client_Release.exe, control_Release.exe, match_Release.exe)" % rest[0])
        return 2
    if not game and mode == "setup":
        print("Where is the game? Drag the game folder (the one with client_Release.exe) into this window, then press "
              "Enter:")
        try:
            game = K.find_game(input("> "))
        except EOFError:
            game = None
        if not game:
            print("no WCCF 2010-11 game files there - run setup again and give the \"extracted\" folder")
            return 2
    if not game:
        print("no game folder is set up - nothing to undo")
        return 2
    print("WCCF 2010-11 kit - %s - game: %s" % (mode, game))
    try:
        if mode == "undo":
            undo(game)
            return 0
        check_game(game)
        setup_extracted(game)
        setup_seat(game)
        for d in (K.LOGS, K.SAVE):
            os.makedirs(d, exist_ok=True)
        s = K.load_settings()
        s["game"] = game
        K.save_settings(s)
        print("in the kit's folder:")
        tidy_old_layout()
        setup_cards(game, force_cards)
    except Failed as ex:
        print("  FAIL  %s" % ex)
        return 1
    except OSError as ex:
        print("  FAIL  %s" % ex)
        return 1
    print("Setup done. Start the game with PLAY.exe.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
