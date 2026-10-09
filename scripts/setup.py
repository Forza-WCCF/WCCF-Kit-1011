# -*- coding: utf-8 -*-
r"""setup.py - make your own copy of WCCF 2010-11 (Rev D) run on this PC with the kit.
Run it once (SETUP.exe); running it again checks everything and repairs what is missing.

    python setup.py [GAME]     GAME = the game folder, the one that holds client_Release.exe (or the folder above
                               it); asked for if not given, then remembered in data\settings.json
    python setup.py undo       put the game folder back the way it was before setup

What it changes, and nothing else on the PC:
  in extracted\   + winmm.dll (the kit's hook) and winmm_orig.dll (a copy of this PC's own Windows winmm.dll)
                  logowin.exe stays Sega's: the hook keeps the server from starting it (a kit before 2026-10-09
                  put a stand-in there, Sega's as logowin_sega.exe - Sega's goes back)
                  + local\client_user_option.conf (the projector) and local\ctrl_user_option.conf (the server)
  beside it       seat1\   the player cabinet: links to extracted\'s folders and files, its own patched
                           client_Release.exe (15 changes, checked byte for byte) and its own local\ settings
                  misc\FlatPanelReader_Emulator\exe\FPR_Emu.exe   the card-table helper the game starts
  in the kit      overlay\catalogue.tsv, overlay\cards\   the catalogue and card pictures, made from YOUR files
                  data\   settings, your club card (data\save), logs
Exit: 0 done; 1 a step failed (the message says which); 2 no usable game folder.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import cards
import kit_common as K

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
NO_LINK = re.compile(r"^(busram\d+\.bin|eeprom\d+\.bin|logowin_messages\.txt|client_release\.exe|winmm\.dll|"
                     r"mxsram\.bin|.*\.log|.*\.bmp|.*\.tmp)$", re.I)
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
CONF_SEAT1 = CONF_HEAD % "the PLAYER CABINET (seat 1)" + CLIENT_KEYS % (1, "MANAGEMENT_0910=0\r\n", 1)
CONF_CONTROL = ("# WCCF 2010-11 - the SERVER (control) - written by the kit's setup.py: everything on this PC.\r\n"
                "# CLIENT_MAX must stay 9 (the game's own default): fewer made the server crash.\r\n"
                "# FIX_REST_ENTRY_TIME = seconds the entry window stays open each cycle (the game's own: 40). Longer, so\r\n"
                "# seat 1 can still enter the first match after starting and the projector does not wait a whole\r\n"
                "# 12-minute cycle on \"Now Synchronizing\".\r\n"
                "DHCP=0\r\nIS_RINGEDGE=0\r\nALLNET_AUTH=0\r\nACCEPT_ALL_IP=1\r\nCLIENT_MAX=9\r\nACCEPT_IP_0=127.0.0.1\r\n"
                "CONTROL_PORT=20002\r\nMATCH_PORT=20003\r\nGAME_SVR_IP=127.0.0.1\r\nFIX_REST_ENTRY_TIME=120\r\n")
EARLIER_KIT_CONFS = {   # byte for byte what an earlier kit wrote: replaced without keeping a copy (any other text is
    # a hand edit and is kept as .before-kit).  The first kit's server settings, before FIX_REST_ENTRY_TIME:
    b"# WCCF 2010-11 - the SERVER (control) - written by the kit's setup.py: everything on this PC.\r\n"
    b"# CLIENT_MAX must stay 9 (the game's own default): fewer made the server crash.\r\n"
    b"DHCP=0\r\nIS_RINGEDGE=0\r\nALLNET_AUTH=0\r\nACCEPT_ALL_IP=1\r\nCLIENT_MAX=9\r\nACCEPT_IP_0=127.0.0.1\r\n"
    b"CONTROL_PORT=20002\r\nMATCH_PORT=20003\r\nGAME_SVR_IP=127.0.0.1\r\n"}
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


# the lines play.py sets at each start (the server's address, the seat, whether to wait for a projector): a file that
# differs from ours only there is ours, as play.py left it - not a hand edit (2026-10-06: online play changes them)
RUNTIME_LINES = re.compile(rb"(?m)^(CONTROL_IP|MATCH_IP|SATELLITE_NO|WAIT_PROJECTOR)=[^\r\n]*(\r?\n|$)")


def write_text(path, text, what):
    if os.path.isfile(path) and open(path, "rb").read() == text.encode("ascii"):
        ok("%s already in place" % what)
        return
    if os.path.isfile(path) and RUNTIME_LINES.sub(b"", open(path, "rb").read()) == RUNTIME_LINES.sub(b"", text.encode("ascii")):
        ok("%s already in place (with the server address / seat play.py set)" % what)
        return
    if os.path.isfile(path) and open(path, "rb").read() not in EARLIER_KIT_CONFS:
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
    if K.sha256(p) != SEGA_CLIENT and os.path.isfile(b) and K.sha256(b) == SEGA_CLIENT:
        return b
    return p


def english_copy(rel):
    """SHA-256 of the English file english.py put at rel (its manifest), or None when English is off"""
    try:
        with open(os.path.join(ENGLISH_BACKUP, "manifest.json"), encoding="utf-8") as f:
            return json.load(f).get(rel, {}).get("english")
    except (OSError, ValueError, AttributeError):
        return None


def patched_client(game):
    """Sega's client exe with the 15 changes, checked before and after"""
    data = bytearray(open(sega_client(game), "rb").read())
    for va, off, old, new, what in PATCHES:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        if cards.va_to_offset(data, va) != off or bytes(data[off:off + len(old)]) != old:
            raise Failed("client_Release.exe at 0x%08X is not Sega's Rev D bytes (%s)" % (va, what))
        data[off:off + len(new)] = new
    if K.sha256(data) != PATCHED_CLIENT:
        raise Failed("the patched exe does not come out as the tested one - not written")
    return bytes(data)


def check_game(game):
    if K.game_processes(game):
        raise Failed("the game is running - close its window first, then run setup again")
    h = K.sha256(sega_client(game))
    if sega_client(game) != os.path.join(game, "client_Release.exe"):
        ok("English is on (SETUP.exe's ENGLISH): Sega's client_Release.exe is checked in data\\english_backup")
    if h == PATCHED_CLIENT:
        raise Failed("the game folder's client_Release.exe is already PATCHED - setup needs the unchanged exe there "
                     "(only seat1\\ gets the patched copy). Put your own unchanged client_Release.exe back first.")
    if h != SEGA_CLIENT:
        raise Failed("the game folder's client_Release.exe is not Rev D (SHA-256 %s...) - this kit is for Rev D only"
                     % h[:16])
    ok("client_Release.exe is Sega's Rev D")
    for n, want in SEGA_OTHERS.items():
        if K.sha256(os.path.join(game, n)) != want:
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
    copy_if_different(WINMM, os.path.join(game, "winmm_orig.dll"), "winmm_orig.dll (this PC's own winmm.dll)")
    copy_if_different(os.path.join(K.BIN, "winmm.dll"), os.path.join(game, "winmm.dll"), "winmm.dll (the hook)")
    # logowin.exe (2026-10-09): the server starts it for its logo and error screens - a white window over the whole
    # screen.  The hook (winmm.dll, above) now answers that start itself and runs nothing, so Sega's file stays.  A kit
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
    have = K.sha256(exe) if os.path.isfile(exe) else None
    if have == PATCHED_CLIENT:
        ok("client_Release.exe: seat 1's patched copy already in place")
    elif have and have == english_copy(os.path.join("seat1", "client_Release.exe")):
        ok("client_Release.exe: seat 1's patched copy with the kit's English text already in place")
    else:
        put_file(patched_client(game), exe)
        if K.sha256(exe) != PATCHED_CLIENT:
            raise Failed("seat 1's exe did not write correctly")
        ok("client_Release.exe: seat 1's own copy, 15 changes, the tested exe byte for byte")
    copy_if_different(os.path.join(K.BIN, "winmm.dll"), os.path.join(seat, "winmm.dll"), "winmm.dll (the hook)")
    write_text(os.path.join(seat, "local", "client_user_option.conf"), CONF_SEAT1, "seat 1 settings")
    copy_if_different(os.path.join(game, "local", "SBWG_Table.dat"), os.path.join(seat, "local", "SBWG_Table.dat"),
                      "local\\SBWG_Table.dat")
    print("in %s:" % K.misc_dir(game))
    helper = os.path.join(K.misc_dir(game), "FlatPanelReader_Emulator", "exe")
    os.makedirs(helper, exist_ok=True)
    copy_if_different(os.path.join(K.BIN, "FPR_Emu.exe"), os.path.join(helper, "FPR_Emu.exe"), "FPR_Emu.exe")


def setup_cards(game, force=False):
    print("in the kit's overlay folder:")
    cat, pics = os.path.join(K.OVERLAY, "catalogue.tsv"), os.path.join(K.OVERLAY, "cards")
    have = len([n for n in os.listdir(pics) if n.endswith(".png")]) if os.path.isdir(pics) else 0
    if not force and os.path.isfile(cat) and have >= cards.RECORDS:
        ok("catalogue and %d card pictures already made" % have)
        return
    print("  making the catalogue and the card pictures from your game files (about a minute) ...", flush=True)
    if cards.main([game, K.OVERLAY]) != 0:
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
    for n in ("winmm.dll", "winmm_orig.dll"):
        p = os.path.join(game, n)
        if os.path.isfile(p):
            if n == "winmm.dll" and b"mxhook attached" not in open(p, "rb").read():
                note("extracted\\winmm.dll is not the kit's hook - left alone")
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
