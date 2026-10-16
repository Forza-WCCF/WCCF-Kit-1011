# -*- coding: utf-8 -*-
r"""english.py - WCCF 2010-11 in English.  Built on this PC from YOUR game files, every line checked, then swapped in
with Sega's files kept; "off" puts Sega's back.  Nothing of Sega's ships with the kit: languages\english\ holds only English
text and fingerprints (SHA-256) of Sega's files.

    python english.py on       (SETUP.exe: ENGLISH)   build, check, then put the English files in place
    python english.py on it    (SETUP.exe: ITALIANO)  the same in Italian: languages\italian\ first, the English where a line has none
    python english.py off      (SETUP.exe: JAPANESE)  Sega's Japanese files back
    python english.py check                           say what "on" would do; changes nothing

What changes, in the game's extracted\ folder (seat 1 reads the same files through setup's folder links):
  data\string\string_list.bin + .hf       the screen text: about 7,200 lines in English
  prog_data\player_data\player_data.bin   player names, short and full, in Sega's own Latin spelling (accents dropped) +
                                          skill names
  prog_data\cpu_team\cpu_0..251.dat       the CPU teams' names
  client_Release.exe (the projector's) and seat1\client_Release.exe (seat 1's own patched copy)
                                          text inside the program: the "Next match: ..." ticker, dates as 2026/10/5
  control_Release.exe (the server)        the shop name it sends when the network gives none ("Local Shop")
  data\wccf_data.xaf                      pictures with writing (languages\english\pictures.tsv: the six team stats, OK / BACK),
                                          redrawn in Windows' Arial Bold and ADDED at the archive's end; only their
                                          table-of-contents entries change, and "off" cuts the added end away again
                                          (switched OFF - see PICTURES below)
  data\english_pictures\ (the kit's)      pictures.tsv's "memory" pictures (the six team stats round the hexagon, the
                                          menu's OK / BACK, the bar's "please wait for the next match"), redrawn as the
                                          same kind of picture; the kit's hook gives the game the English one as it loads
                                          Sega's (source\hook\pictures.h) - no game file changes for them.  A row with
                                          `art` takes its English lettering from that file in languages\english\ (our
                                          words only, made to match Sega's), the others are drawn in Arial Bold
The first "on" COPIES Sega's files to data\english_backup\ - only files whose fingerprint shows they are Sega's Rev D
originals; later runs build from that backup again.  Each game file is then replaced in ONE step ("off" too), so a
switch stopped half way (a crash, a kill, a full disk) leaves every file in place - some English, some not - and
never a missing one: a missing exe would keep the game from starting (2026-10-06).  Kept in Japanese on purpose: country and prefecture names (the
game finds its weather table by them; English ones crashed the server) and the network-ranking areas.  Other pictures
with writing in them are not changed.
Where the English comes from: languages\english\screen_text.tsv (this kit's translation), Sega's own English that the game files
already hold (a second language column), and languages\english\sega_rstring.tsv (lines from Sega's European English of the
older WCCF, matched by identical Japanese).
Exit 0 done; 1 refused or a check failed (nothing changed); 2 no game set up (run SETUP.exe first).
"""
import bisect
import collections
import csv
import hashlib
import io
import json
import os
import re
import struct
import sys
import unicodedata

import kit_common as K
from cards import catalogue
from cards import unpack
from helpers import hook as H

BACK = os.path.join(K.DATA, "english_backup")
# The writing in the game's pictures (#29) is OFF: with the redrawn pictures in the archive the game no longer read a
# club card - it gave the card straight back, every time (2026-10-11, a real start on the test game: English text
# without the pictures read it, Japanese read it, English with the pictures did not).  The code stays for whoever
# finds why; WCCF_PICTURES=1 turns it on for that test.  Never on by default before a running game reads a card with it.
PICTURES = os.environ.get("WCCF_PICTURES") == "1"
PICTURES_OFF = "pictures stay Japanese: their English is switched off (with it the game did not read a club card)"
# The "memory" pictures (2026-10-15) never touch the archive: each is redrawn into this folder, named by Sega's picture
# (its size and FNV-1a 64-bit fingerprint, as the hook computes it), and the hook hands the game the English file
# when the game loads Sega's (D3DXCreateTextureFromFileInMemoryEx). play.py names the folder to seat 1's hook.
PIC_DIR = K.ENGLISH_PICTURES
LANGS = {"en": "English", "it": "Italian"}         # "on it": Italian, with the English wherever a line has none
LANG_FILE = os.path.join(BACK, "language.txt")    # the language that is on (kit_common.game_language reads it)
MANIFEST = os.path.join(BACK, "manifest.json")
BIN, HF = os.path.join("data", "string", "string_list.bin"), os.path.join("data", "string", "string_list.hf")
PLAYERS = os.path.join("prog_data", "player_data", "player_data.bin")
TEAMS = os.path.join("prog_data", "cpu_team")
PROJECTOR = "client_Release.exe"
SEAT_EXE = os.path.join("seat1", "client_Release.exe")     # seat 1's own copy, beside extracted\ (see where())
SERVER = "control_Release.exe"                             # the server; SETUP never changes it (setup.py SEGA_OTHERS)
SEGA = {BIN: "F71368483B76E3DA89AA4651B33BFDE6BFEE9A3C381F9EEC8CA6E9E8C9DF43F4",       # Rev D, unchanged
        HF: "B6A56A3DFC6494017151371F4313FCAC8BDF80C5B83B3DD9D84A652CC25BAF2A",
        PLAYERS: "B0D39E32C195C60E9D366071A94932CBCE4E2EEAF3C83A897664F147161C2519",
        PROJECTOR: "AEF9998D8A77B4DD7A0CFF3753A11FC8689A6700E133265D6681EF28D3E9CEA4",
        SEAT_EXE: "6243C394E9A57B33C23519326EF8A77B0992873A0033B5892A9155C5B827E20A",   # = setup.py's PATCHED_CLIENT
        SERVER: "23B9553096BB195FC991A1FC141D719DF3C8AE88460959A88CDFC18863A1376F"}
# families the game may use as DATA: kept Japanese unless switched on below.  The server and the client look their
# weather table up by the COUNTRY / PREFECTURE name (control FUN_004229b0, client FUN_00430b20) - English ones crashed
# the server; cities and stadiums are referred to by key and are safe (checked in the code, 2026-10-05).
DATA_FAMILIES = ("MAKE_", "NET_RANK", "GAM_OROGINAL", "GAM_REAL", "GAM_STA", "SYS_TEAM", "INF_SUPPORTER",
                 "SYS_COACH", "PRO_PRO", "INF_FRE")
SWITCHED_ON = ("SYS_TEAM", "PRO_PRO", "GAM_OROGINAL", "GAM_REAL", "GAM_STA", "INF_FRE", "SYS_COACH", "INF_SUPPORTER",
               "MAKE_city", "MAKE_area")
# every conversion the game's C runtime takes, so an English line keeps exactly the codes of the game's Japanese line
# (2026-10-07: Sega's European line "They're giving 110% out there." is "% o" to printf - an octal number - which the
# old list [dsxXuc] did not see; it went in and Team Training showed "11037620322074ut there")
FMT = re.compile(r"%[-+ 0#]*(?:\*|[0-9]+)?(?:\.(?:\*|[0-9]+))?(?:hh|h|ll|l|L|I32|I64|I|w)?[cCdiouxXeEfgGaAnpsSZ%]")
REC = 0x328                                          # player_data.bin: one player
SHORT_KANA, SHORT_LATIN, SKILL_EN, SKILL_JP, FIELD = 0x8C, 0xCC, 0x1B7, 0x1F7, 0x40
# the full name: Sega's Latin one (UTF-16) goes over the card name (katakana; the client's CARD_NAME, read only by the
# screens).  The other katakana full name at 0x177 stays: it is the key into partnership.bin (client FUN_004e3ea0)
FULL_LATIN, CARD_NAME = 0x0C, 0x4C
NAME_AT, NAME_END = 0x144, 0x17C                     # cpu_N.dat: the team name field
FOLD = {"Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "ß": "SS", "Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "Œ": "OE",
        "œ": "oe", "ı": "i", "Þ": "TH", "ð": "d"}


class Failed(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest().upper()


def sheet(name, folder="english"):
    with open(os.path.join(K.LANGUAGES, folder, name), encoding="utf-8", newline="") as fh:   # languages\<folder>\
        return list(csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE))


def where(game, rel):
    """a file's place: under extracted\\, or seat1\\... = seat 1's folder beside it"""
    if rel.startswith("seat1" + os.sep):
        return os.path.join(K.seat_dir(game), rel[len("seat1") + 1:])
    return os.path.join(game, rel)


def sega_file(game, rel):
    """the original: the backup once English has been on, else the game's own file. For a program, its import is
    un-renamed back to Sega's WINMM.dll (norm), so English builds from Sega's original bytes even after SETUP has
    pointed the program at the kit's hook (wccfk.dll)."""
    b = os.path.join(BACK, rel)
    with open(b if os.path.isfile(b) else where(game, rel), "rb") as f:
        return norm(f.read(), rel)


# ---------------------------------------------------------------- the screen text
def build_strings(game, lang="en"):
    raw, hf_raw = sega_file(game, BIN), sega_file(game, HF)
    if sha(raw) != SEGA[BIN] or sha(hf_raw) != SEGA[HF]:
        raise Failed("data\\string\\string_list.* are not Sega's Rev D files - the English is made for those only")
    tag, body = raw[:4], raw[8:]
    hf_lines = hf_raw.splitlines(keepends=True)
    nl = b"\r\n" if b"\r\n" in body else b"\n"

    def at(p, b=body):
        return b[p:b.find(b"\0", p)]

    keys = {}
    for i, line in enumerate(hf_lines[1:], 1):
        p = line.split()
        keys[p[0].decode("ascii")] = (i, [int(x) for x in p[1:]])

    def family(k):
        return "_".join(k.split("_")[:2])

    def blocked(k):
        f = family(k)
        return f.startswith(DATA_FAMILIES) and not any(f.startswith(e) for e in SWITCHED_ON)

    english = {}
    for r in sheet("screen_text.tsv"):
        if (r.get("english") or "").strip() and r["key"] not in english:
            english[r["key"]] = (r["english"].strip("\r"), "kit")
    rstring = {r["key"]: r["english"] for r in sheet("sega_rstring.tsv")}
    for k, (_, nums) in keys.items():
        if k in english or not any(c >= 0x80 for c in at(nums[0])):
            continue
        s2 = at(nums[1])
        if s2 and not any(c >= 0x80 for c in s2):
            english[k] = (s2.decode("ascii"), "SEGA second column")
        elif k in rstring:
            english[k] = (rstring[k], "SEGA European English")
    # each line's choices, best first: Italian (the kit's, then Sega's European Italian) before the English, which
    # stays the fallback - a line with no usable Italian is English, never Japanese
    choices = {k: [v] for k, v in english.items()}
    if lang == "it":
        for name, src in (("sega_rstring.tsv", "SEGA European Italian"), ("screen_text.tsv", "kit Italian")):
            for r in sheet(name, "italian"):
                if (r.get("italiano") or "").strip():
                    choices.setdefault(r["key"], []).insert(0, (r["italiano"].strip("\r"), src))

    def encoded(jp, text):
        """the line as the game's bytes, or None and what is wrong with it"""
        if text.strip() == "<empty>":
            if FMT.findall(jp) or "$c" in jp or "$p" in jp:
                return None, "<empty> would drop the Japanese line's codes"
            return b"", None
        en = text.replace("\\n", "\n")
        if FMT.findall(jp) != FMT.findall(en):
            return None, "codes %s, the game's line has %s" % (FMT.findall(en), FMT.findall(jp))
        if FMT.sub("", en).count("%") > FMT.sub("", jp).count("%"):
            return None, "a % sign that is no printf code - the game would show junk or stop"
        if jp.count("$c[") != en.count("$c[") or jp.count("$c") != en.count("$c"):
            return None, "colour codes differ from the game's line"
        try:
            b = en.encode("cp932")
        except UnicodeEncodeError:
            return None, "a letter the game's font cannot show"
        b = b.replace(b"\n", nl) if nl != b"\n" else b
        if b"\0" in b:
            return None, "holds an end byte"
        return b, None

    bad, enc, used, sega_bad = [], {}, {}, 0
    for k, options in sorted(choices.items()):
        if k not in keys:
            bad += ["%s: no such line in the game" % k for _, src in options if src.startswith("kit")]
            continue
        if blocked(k):
            continue
        jp = at(keys[k][1][0]).decode("cp932", "replace")
        for text, src in options:
            b, problem = encoded(jp, text)
            if not problem:
                enc[k], used[k] = b, src
                break
            if src.startswith("kit"):
                bad.append("%s: %s" % (k, problem))
            else:
                sega_bad += 1
    if bad:
        raise Failed("the kit's text has %d problem(s), e.g. %s" % (len(bad), "; ".join(bad[:3])))

    # free space: a translated line's old Japanese, if nothing else points at it or inside it; then the zero padding
    refs = collections.defaultdict(set)
    for k, (_, nums) in keys.items():
        for s, n in enumerate(nums):
            refs[n].add((k, s))
    ref_sorted = sorted(refs)
    own, free = {}, []
    for k in enc:
        p = keys[k][1][0]
        end = p + len(at(p)) + 1
        lo, hi = bisect.bisect_left(ref_sorted, p), bisect.bisect_left(ref_sorted, end)
        if refs[p] == {(k, 0)} and hi - lo == 1:
            own[k] = (p, end)
    pad_at = max(len(body.rstrip(b"\0")) + 1, ref_sorted[-1] + 1) + 16
    new_body = bytearray(body)
    for k, (p, end) in own.items():
        new_body[p:end] = bytes(end - p)
    pos, spill = {}, []
    for k, b in sorted(enc.items(), key=lambda kv: -len(kv[1])):
        if k in own and len(b) + 1 <= own[k][1] - own[k][0]:
            p = own[k][0]
            new_body[p:p + len(b)] = b
            pos[k] = p
            if own[k][1] - (p + len(b) + 1) > 1:
                free.append((p + len(b) + 1, own[k][1]))
        else:
            spill.append(k)
            if k in own:
                free.append(own[k])
    free.append((pad_at, len(body) - 1))
    for k in spill:
        b = enc[k]
        for i, (s, e) in enumerate(free):
            if e - s >= len(b) + 1:
                new_body[s:s + len(b)] = b
                pos[k] = s
                free[i] = (s + len(b) + 1, e)
                break
        else:
            raise Failed("no room in string_list.bin for %s" % k)
    new_bin = tag + len(new_body).to_bytes(4, "little") + bytes(new_body)
    new_hf = list(hf_lines)
    for k, p in pos.items():
        i = keys[k][0]
        m = re.match(rb"(\S+\s+)(\d+)", hf_lines[i])
        new_hf[i] = m.group(1) + str(p).encode("ascii") + hf_lines[i][m.end():]
    nb, wrong = bytes(new_body), 0                     # read back every slot of every key
    for i, line in enumerate(new_hf[1:], 1):
        p = line.split()
        k, nums = p[0].decode("ascii"), [int(x) for x in p[1:]]
        old = keys[k][1]
        if nums[1:] != old[1:]:
            wrong += 1
        for s, n in enumerate(nums):
            if at(n, nb) != (enc[k] if (s == 0 and k in pos) else at(old[s])):
                wrong += 1
    if wrong or len(new_bin) != len(raw) or new_hf[0] != hf_lines[0]:
        raise Failed("the built screen text does not read back as intended (%d places) - nothing changed" % wrong)
    by = collections.Counter(used[k] for k in pos)
    note = "%d lines in %s (%s)" % (len(pos), LANGS[lang], ", ".join("%s %d" % kv for kv in sorted(by.items())))
    if sega_bad:
        note += "; %d of Sega's own lines unusable, the next choice taken" % sega_bad
    # lines a player can meet that are still Japanese ("check" shows them; the debug menus are left out on purpose)
    left = sorted(k for k, (_, nums) in keys.items() if k not in pos and not blocked(k) and any(c >= 0x80 for c in at(
        nums[0])) and family(k) not in ("SYS_DEBUG", "COM_debug"))
    if left:
        note += "; %d still Japanese (%s%s)" % (len(left), ", ".join(left[:3]), ", ..." if len(left) > 3 else "")
    return {BIN: new_bin, HF: b"".join(new_hf)}, note


# ---------------------------------------------------------------- player and team names
def fold(s):
    s = "".join(FOLD.get(c, c) for c in s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in s)


def put_field(field, value, size):
    """value + end byte, then the field's own fill (whatever followed the original end byte)"""
    end = field.find(b"\0")
    fill = field[end + 1:end + 2] if 0 <= end < size - 1 else b"\0"
    out = value[:size - 1] + b"\0"
    return out + fill * (size - len(out))


def build_names(game):
    pd = bytearray(sega_file(game, PLAYERS))
    if sha(pd) != SEGA[PLAYERS] or len(pd) % REC:
        raise Failed("prog_data\\player_data\\player_data.bin is not Sega's Rev D file")
    for i in range(len(pd) // REC):
        r = i * REC
        kana = bytes(pd[r + SHORT_KANA:r + SHORT_KANA + FIELD]).split(b"\0")[0].decode("cp932", "replace")
        latin = bytes(pd[r + SHORT_LATIN:r + SHORT_LATIN + FIELD]).decode("utf-16-le", "replace").split("\0")[0].strip()
        if not latin:
            continue
        name = fold(latin)
        m = re.match(r"^([Ａ-Ｚ])．", kana)                # a katakana initial (Ｍ．ディアッラ) kept: M.DIARRA
        if m:
            ini = chr(ord(m.group(1)) - 0xFEE0) + "."
            if not name.startswith(ini):
                name = ini + name
        pd[r + SHORT_KANA:r + SHORT_KANA + FIELD] = put_field(bytes(pd[r + SHORT_KANA:r + SHORT_KANA + FIELD]),
                                                              name.encode("ascii"), FIELD)
        full = bytes(pd[r + FULL_LATIN:r + FULL_LATIN + FIELD]).decode("utf-16-le", "replace").split("\0")[0].strip()
        full = fold(full)
        if full:
            pd[r + CARD_NAME:r + CARD_NAME + FIELD] = put_field(bytes(pd[r + CARD_NAME:r + CARD_NAME + FIELD]),
                                                                full.encode("ascii"), FIELD)
        sk = bytes(pd[r + SKILL_EN:r + SKILL_EN + FIELD]).split(b"\0")[0]
        if sk and all(32 <= c < 127 for c in sk) and b"%" not in sk:
            pd[r + SKILL_JP:r + SKILL_JP + FIELD] = put_field(bytes(pd[r + SKILL_JP:r + SKILL_JP + FIELD]), sk, FIELD)
    files, skipped = {PLAYERS: bytes(pd)}, []
    for row in sheet("cpu_names.tsv"):
        rel = os.path.join(TEAMS, row["file"])
        d = bytearray(sega_file(game, rel))
        en = row["english"]
        if sha(d) != row["sega_sha256"]:
            skipped.append(row["file"])
            continue
        if len(en) > NAME_END - NAME_AT - 1 or "%" in en or not all(32 <= ord(c) < 127 for c in en):
            raise Failed("the kit's team name for %s does not fit" % row["file"])
        d[NAME_AT:NAME_END] = put_field(bytes(d[NAME_AT:NAME_END]), en.encode("ascii"), NAME_END - NAME_AT)
        files[rel] = bytes(d)
    note = "%d players, %d CPU teams" % (len(pd) // REC, len(files) - 1)
    if skipped:
        note += "; %d team files are not Sega's Rev D ones and stay as they are (%s...)" % (len(skipped), skipped[0])
    return files, note


# ---------------------------------------------------------------- text inside the programs (both client copies; the
# server only for its own rows - "server" in exe_text.tsv's program column, 2026-10-06: the shop name it sends)
def build_exe(game, lang="en"):
    sheet_rows, files = sheet("exe_text.tsv"), {}
    for rel, program, what in ((PROJECTOR, "client", "the projector's client_Release.exe (Sega's Rev D)"),
                               (SEAT_EXE, "client", "seat 1's client_Release.exe (the copy SETUP.exe makes)"),
                               (SERVER, "server", "the server's control_Release.exe (Sega's Rev D)")):
        rows = [r for r in sheet_rows if r["program"] == program]
        if not rows:
            continue
        d = bytearray(sega_file(game, rel))
        if sha(d) != SEGA[rel]:
            raise Failed("%s is not the expected file - run SETUP.exe first" % what)
        size = len(d)
        for r in rows:
            o, n = int(r["offset"], 16), int(r["length"])
            en = (r.get("italiano") or r["english"]) if lang == "it" else r["english"]
            if sha(bytes(d[o:o + n])) != r["sega_sha256"] or d[o + n] != 0:
                raise Failed("%s at %s is not the text the kit expects" % (what, r["offset"]))
            room = n + 1
            while o + room < len(d) and d[o + room] == 0:
                room += 1
            if len(en) + 1 > room or not all(32 <= ord(c) < 127 for c in en):
                raise Failed("the kit's text at %s does not fit" % r["offset"])
            # over exactly the room measured (the text, its end byte, the zeros that were there): never a byte more
            # or less - before 2026-10-06 a text longer than the original + 1 made the file grow, shifting everything
            # after it (docs\research\MONEY-2010-11.md 7.3)
            d[o:o + room] = en.encode("ascii") + b"\0" * (room - len(en))
        if len(d) != size:
            raise Failed("%s would change size (%d -> %d bytes) - nothing written" % (what, size, len(d)))
        files[rel] = bytes(d)
    unknown = sorted(set(r["program"] for r in sheet_rows) - {"client", "server"})
    if unknown:
        raise Failed("exe_text.tsv names a program the kit does not know: %s" % ", ".join(unknown))
    n_client = sum(1 for r in sheet_rows if r["program"] == "client")
    n_server = len(sheet_rows) - n_client
    return files, "%d texts inside the program, in the projector's and seat 1's copies%s" % (
        n_client, ", and %d in the server" % n_server if n_server else "")


# ---------------------------------------------------------------- writing in pictures (data\wccf_data.xaf)
# The game reads data\... only from the archive (client FUN_00424570: no loose file is looked at), so each English
# picture is ADDED at the archive's end and its table-of-contents entry pointed at it; no byte of Sega's is written
# over.  "off" puts the old entries back and cuts the file to its old length - no copy of the 1.4 GB file is needed.
# The archive has no checksum (FUN_00913e20) and the texture loader takes any DDS format (FUN_00765f30); 2026-10-10.
XAF = os.path.join("data", "wccf_data.xaf")
XAF_STATE = os.path.join(BACK, "wccf_data.xaf.json")
SECTOR, ENTRY, TOC_AT = 2048, 0xB0, 0x100
# the writing's colour, its halo (colour + strength, or none) and the halo's width, as Sega drew each picture
STYLES = {"glow": ((242, 228, 150), (223, 198, 57, 200), 4), "outline": ((240, 240, 245), (18, 17, 17, 220), 2),
          "grey": ((80, 80, 80), None, 0), "white": ((255, 255, 255), None, 0),
          # the bar's wait line (client_common\SCM_Foot\SCM_Foot_Wait.dds): Sega's off-white, left-aligned, the last line
          # mirrored below as Sega drew it (reflect_last)
          "wait": ((216, 225, 216), None, 0)}
# Sega's reflection in SCM_Foot_Wait.dds (measured 2026-10-15): the line on rows 19-31 mirrored onto rows 42-54, i.e.
# its top 11 rows below the line's last row, at 25% of the line's strength fading by 1.9% a row
REFLECT_GAP, REFLECT_TOP, REFLECT_FADE = 11, 0.25, 0.019


def arial_bold():
    p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf")
    return p if os.path.isfile(p) else None


def draw_label(im, box, text, style, font_path, left=False):
    """Sega's writing in box cleared, the English drawn in its place: as tall as the box allows, squeezed to fit;
    centred, or from the box's left edge"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    core, halo, spread = STYLES[style]
    x0, y0, x1, y1 = box
    im.paste((0, 0, 0, 0), (x0, y0, x1 + 1, y1 + 1))
    s = 4                                                # drawn 4x larger, then made small: smooth edges
    w, h = (x1 - x0 + 1 - 2 * spread) * s, (y1 - y0 + 1 - 2 * spread) * s
    font = ImageFont.truetype(font_path, int(h * 0.92))
    l, t, r, b = font.getbbox(text)
    m = Image.new("L", (r - l, b - t))
    ImageDraw.Draw(m).text((-l, -t), text, font=font, fill=255)
    mw, mh = max(1, round(m.width * min(1.0, w / m.width) / s)), max(1, round(m.height / s))
    mask = Image.new("L", im.size)
    mask.paste(m.resize((mw, mh), Image.LANCZOS), (x0 + (0 if left else (x1 - x0 + 1 - mw) // 2),
                                                   y0 + (y1 - y0 + 1 - mh) // 2))
    if halo:
        g = mask.filter(ImageFilter.MaxFilter(2 * (spread // 2) + 1)).filter(ImageFilter.GaussianBlur(spread / 2))
        im.alpha_composite(Image.merge("RGBA", Image.new("RGB", im.size, halo[:3]).split() +
                                       (g.point(lambda v: min(255, v * halo[3] // 160)),)))
    im.alpha_composite(Image.merge("RGBA", Image.new("RGB", im.size, core).split() + (mask,)))


def dds_argb(im):
    """an uncompressed A8R8G8B8 DDS, the header as Sega's own (e.g. club_make\\CL_Base\\Button.dds)"""
    w, h = im.size
    return (struct.pack("<4s7I44x8I5I", b"DDS ", 124, 0x81007, h, w, w * h * 4, 0, 0,
                        32, 0x41, 0, 32, 0xFF0000, 0xFF00, 0xFF, 0xFF000000, 0x1000, 0, 0, 0, 0)
            + im.tobytes("raw", "BGRA"))


def load_state():
    try:
        with open(XAF_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def dxt5(im, header):
    """im (RGBA, sides a multiple of 4) as DXT5 blocks after Sega's own 128-byte DDS header: the same kind and size of
    picture as Sega's.  Per 4x4 block: alpha between the block's highest and lowest (8 steps), colour between its
    brightest and darkest inked pixel (4 steps), each pixel the nearest step."""
    w, h = im.size
    px = im.load()
    out = bytearray(header)
    to565 = lambda c: ((c[0] >> 3) << 11) | ((c[1] >> 2) << 5) | (c[2] >> 3)
    from565 = lambda v: ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            blk = [px[bx + i % 4, by + i // 4] for i in range(16)]
            alphas = [p[3] for p in blk]
            a0, a1 = max(alphas), min(alphas)
            steps = [a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)] if a0 > a1 else [a0] * 8
            bits = sum(min(range(8), key=lambda k: abs(steps[k] - a)) << (3 * i) for i, a in enumerate(alphas))
            out += bytes((a0, a1)) + bits.to_bytes(6, "little")
            inked = [p[:3] for p in blk if p[3]] or [(0, 0, 0)]
            e0, e1 = to565(max(inked, key=sum)), to565(min(inked, key=sum))
            c0, c1 = from565(e0), from565(e1)
            pal = [c0, c1] + [tuple((2 * a + b) // 3 for a, b in zip(c0, c1)), tuple((a + 2 * b) // 3 for a, b in zip(c0, c1))]
            idx = [min(range(4), key=lambda k: sum((pal[k][j] - p[j]) ** 2 for j in range(3))) for p in blk]
            out += struct.pack("<HHI", e0, e1, sum(v << (2 * i) for i, v in enumerate(idx)))
    return bytes(out)


def fnv64(data):
    """FNV-1a 64-bit, as source\\hook\\pictures.h computes it over the bytes the game loads"""
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def memory_name(sega):
    """the English picture's file name in PIC_DIR: Sega's picture's size and fingerprint (the hook matches both)"""
    return "%d-%016X.dds" % (len(sega), fnv64(sega))


def reflect_last(im, box):
    """the last line mirrored under itself, as Sega drew the wait line's (REFLECT_*)"""
    from PIL import Image
    x0, y0, x1, y1 = box
    line = im.crop((0, y0, im.width, y1 + 1)).transpose(Image.FLIP_TOP_BOTTOM)
    a = line.getchannel("A")
    for y in range(line.height):
        f = max(0.0, REFLECT_TOP - REFLECT_FADE * y)
        for x in range(line.width):
            a.putpixel((x, y), int(a.getpixel((x, y)) * f))
    line.putalpha(a)
    top = y1 + REFLECT_GAP
    if top < im.height:
        im.alpha_composite(line.crop((0, 0, line.width, min(line.height, im.height - top))), (0, top))


def sega_pictures(game, how):
    """(row, archive path, entry, Sega's bytes) for each picture of pictures.tsv drawn `how` ("archive": added to the
    archive, off - PICTURES; "memory": given by the hook), each checked to be Sega's Rev D picture"""
    xaf, state = where(game, XAF), load_state() or {"entries": {}}
    ents = {e["path"]: e for e in catalogue.xaf_toc(xaf) if e["is_file"]}
    with open(xaf, "rb") as f:
        for row in sheet("pictures.tsv"):
            if row.get("how", "archive") != how:
                continue
            for p in row["files"].split():
                if p not in ents:
                    raise Failed("the archive has no %s" % p)
                e = ents[p]
                raw = bytes.fromhex(state["entries"][str(e["i"])]) if str(e["i"]) in state["entries"] else None
                if raw:                                   # English on: Sega's picture is still where it was
                    size, stored = struct.unpack_from("<II", raw, 0x94)
                    e = dict(e, size=size, stored=stored, offset=struct.unpack_from("<I", raw, 0xA0)[0] * SECTOR)
                f.seek(e["offset"])
                data = f.read(e["stored"])
                data = unpack.decompress(data, e["size"]) if e["stored"] < e["size"] else data
                if sha(data) != row["sega_sha256"]:
                    raise Failed("%s in the archive is not Sega's Rev D picture" % p)
                yield row, p, e, data


def draw_row(data, row, lang, font):
    """Sega's picture with the row's English (or Italian) drawn in: (the picture, how many words)"""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    labels = row["labels"].split(";")
    boxes = [[int(v) for v in lab.split("=")[0].split(",")] for lab in labels]
    if any(a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]
           for i, a in enumerate(boxes) for b in boxes[i + 1:]):
        raise Failed("english\\pictures.tsv: two boxes of %s overlap - one would clear the other" % row["files"])
    words = row["italiano"].split(";") if lang == "it" and row.get("italiano") else None
    if row.get("art") and not words:                     # the English lettering made to match Sega's (2026-10-16): a
        art = Image.open(os.path.join(K.LANGUAGES, "english", row["art"])).convert("RGBA")   # picture of our words
        if art.size != im.size:                          # only - each box cleared, then filled from it
            raise Failed("languages\\english\\%s is %dx%d, Sega's picture %dx%d" % ((row["art"],) + art.size + im.size))
        for x0, y0, x1, y1 in boxes:
            im.paste((0, 0, 0, 0), (x0, y0, x1 + 1, y1 + 1))
            im.alpha_composite(art.crop((x0, y0, x1 + 1, y1 + 1)), (x0, y0))
        return im, len(labels)
    wait = row["style"] == "wait"
    if wait:                                             # the whole picture is writing: all of Sega's goes, its mirror too
        im.paste((0, 0, 0, 0), (0, 0) + im.size)
    for n, lab in enumerate(labels):
        draw_label(im, boxes[n], words[n] if words else lab.split("=")[1], row["style"], font, left=wait)
    if wait:
        reflect_last(im, boxes[-1])
    return im, len(labels)


def build_pictures(game, lang="en"):
    """{archive path: (entry number, English DDS)} from Sega's pictures, each checked against languages\\english\\pictures.tsv"""
    font = arial_bold()
    if not font:
        return {}, "pictures stay Japanese: Windows' Arial Bold (Fonts\\arialbd.ttf) is missing"
    out, labels = {}, 0
    for row, p, e, data in sega_pictures(game, "archive"):
        im, n = draw_row(data, row, lang, font)
        labels += n
        out[p] = (e["i"], dds_argb(im))
    return out, "%d pictures with their writing in %s (%d words)" % (len(out), LANGS[lang], labels)


def build_memory_pictures(game, lang="en"):
    """{file name in PIC_DIR: English picture} for pictures.tsv's "memory" rows: the same kind and size of picture as
    Sega's (a DXT5 one without smaller copies: DXT5 after Sega's own header; others as A8R8G8B8)"""
    font = arial_bold()
    if not font:
        return {}, "the bar's wait line stays Japanese: Windows' Arial Bold (Fonts\\arialbd.ttf) is missing"
    out = {}
    for row, p, e, data in sega_pictures(game, "memory"):
        im, _ = draw_row(data, row, lang, font)
        same = data[84:88] == b"DXT5" and struct.unpack_from("<I", data, 28)[0] <= 1
        out[memory_name(data)] = dxt5(im, data[:128]) if same else dds_argb(im)
    return out, "%d picture(s) the game is given in %s as it loads them" % (len(out), LANGS[lang])


def memory_pictures_off():
    """PIC_DIR's pictures removed (the game then loads Sega's): how many"""
    gone = 0
    for n in (os.listdir(PIC_DIR) if os.path.isdir(PIC_DIR) else []):
        if n.lower().endswith(".dds"):
            os.remove(os.path.join(PIC_DIR, n))
            gone += 1
    if os.path.isdir(PIC_DIR) and not os.listdir(PIC_DIR):
        os.rmdir(PIC_DIR)
    return gone


def memory_pictures_on(pics):
    """PIC_DIR holds exactly these pictures, each read back"""
    memory_pictures_off()
    if not pics:
        return
    os.makedirs(PIC_DIR, exist_ok=True)
    for name, blob in pics.items():
        put(os.path.join(PIC_DIR, name), blob)
        with open(os.path.join(PIC_DIR, name), "rb") as f:
            if f.read() != blob:
                raise Failed("%s did not write correctly - press JAPANESE in SETUP.exe" % name)


def pictures_off(game):
    """Sega's table-of-contents entries and header back, the added pictures cut off; nothing to do if none"""
    state = load_state()
    if not state:
        return 0
    with open(where(game, XAF), "r+b") as f:
        for i, raw in state["entries"].items():
            f.seek(TOC_AT + int(i) * ENTRY)
            f.write(bytes.fromhex(raw))
        f.seek(0x18)
        f.write(bytes.fromhex(state["header"]))
        f.flush()
        os.fsync(f.fileno())
        f.truncate(state["length"])
    os.remove(XAF_STATE)
    return len(state["entries"])


def pictures_on(game, pics):
    pictures_off(game)                                   # from Sega's archive every time: never stacked twice
    if not pics:
        return
    with open(where(game, XAF), "r+b") as f:
        hdr = f.read(TOC_AT)
        length = f.seek(0, 2)
        if hdr[:4] != b"xaf0" or length % SECTOR or struct.unpack_from("<Q", hdr, 0x18)[0] * SECTOR != length:
            raise Failed("data\\wccf_data.xaf is not as Sega made it (its length) - pictures left as they are")
        state = {"length": length, "header": hdr[0x18:0x30].hex(), "entries": {}}
        for p, (i, _) in pics.items():
            f.seek(TOC_AT + i * ENTRY)
            state["entries"][str(i)] = f.read(ENTRY).hex()
        os.makedirs(BACK, exist_ok=True)                 # the way back is saved before the first byte is written
        with open(XAF_STATE + ".tmp", "w", encoding="utf-8") as s:
            json.dump(state, s, indent=1)
        os.replace(XAF_STATE + ".tmp", XAF_STATE)
        pos, entries = length, {}
        for p, (i, blob) in pics.items():                # 1: the pictures added (an interruption leaves only an end
            f.seek(pos)                                  #    that "off" cuts away)
            f.write(blob + bytes(-len(blob) % SECTOR))
            e = bytearray.fromhex(state["entries"][str(i)])
            e[0x81] = e[0x82] = 0                        # not packed (FUN_00913850 unpacks only with one of these)
            struct.pack_into("<II", e, 0x94, len(blob), len(blob))
            struct.pack_into("<I", e, 0xA0, pos // SECTOR)
            entries[i] = bytes(e)
            pos += len(blob) + (-len(blob) % SECTOR)
        f.flush()
        os.fsync(f.fileno())
        added = (pos - length) // SECTOR                 # 2: the entries pointed at them, the header's sizes grown
        total, toc_sectors, data_sectors = struct.unpack_from("<3Q", hdr, 0x18)
        f.seek(0x18)
        f.write(struct.pack("<3Q", total + added, toc_sectors, data_sectors + added))
        for i, e in entries.items():
            f.seek(TOC_AT + i * ENTRY)
            f.write(e)
        f.flush()
        os.fsync(f.fileno())
        for p, (i, blob) in pics.items():                # read back: each entry, each picture
            f.seek(TOC_AT + i * ENTRY)
            e = f.read(ENTRY)
            f.seek(struct.unpack_from("<I", e, 0xA0)[0] * SECTOR)
            if e != entries[i] or f.read(len(blob)) != blob:
                raise Failed("%s did not write correctly - press JAPANESE in SETUP.exe" % p)


def build_all(game, lang="en"):
    files, notes = {}, []
    for fn in (build_strings, build_names, build_exe):
        f, n = fn(game, lang) if fn is not build_names else fn(game)
        files.update(f)
        notes.append(n)
    return files, notes


# ---------------------------------------------------------------- swapping files in and out
def load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_manifest(m):
    os.makedirs(BACK, exist_ok=True)
    with open(MANIFEST + ".tmp", "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1)
    os.replace(MANIFEST + ".tmp", MANIFEST)


def put(path, data):
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)


def is_exe(rel):
    return rel.lower().endswith(".exe")


def norm(data, rel):
    """for a game program, its bytes with the kit's hook import renamed back to Sega's WINMM.dll; other files
    unchanged. So English's backups and fingerprints are Sega's original bytes whether or not SETUP has renamed the
    import to the kit's wccfk.dll (the Defender fix)."""
    return H.normalized(data) if is_exe(rel) else data


def apply_hook(rel, path):
    """after a program is placed, rename its import to the kit's hook so it loads wccfk.dll (not a fake winmm.dll).
    Idempotent; only for the .exe files."""
    if not is_exe(rel):
        return
    data = open(path, "rb").read()
    if not H.imports_hook(data):
        put(path, H.rename_import(data))


def backup_copy(rel, src, dst):
    """Sega's file copied into the backup and read back; it stays in place until its replacement lands in one step. A
    program is stored as Sega's WINMM original (the import un-renamed), so the backup matches sega_hash."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as f:
        data = norm(f.read(), rel)
    put(dst, data)
    with open(dst, "rb") as f:
        if f.read() != data:
            raise Failed("could not copy %s to the backup" % src)


def sega_hash(rel):
    if rel in SEGA:
        return SEGA[rel]
    for row in sheet("cpu_names.tsv"):
        if os.path.join(TEAMS, row["file"]) == rel:
            return row["sega_sha256"]
    return None


def turn_on(game, files):
    man = load_manifest()
    # a file needs its backup made if the list lacks it OR its backup is gone: an "off" stopped half way has put
    # some originals back (their backups removed) while the list still names them - a kill test found English then
    # written over those originals with no backup left (2026-10-06)
    def unsaved(rel):
        return rel not in man or not os.path.isfile(os.path.join(BACK, rel))
    for rel in files:                                    # first: every file to be backed up must be Sega's
        if unsaved(rel):
            with open(where(game, rel), "rb") as f:
                if sha(norm(f.read(), rel)) != sega_hash(rel):   # a program may already carry the kit's hook import
                    raise Failed("%s is neither Sega's original nor backed up - refusing to replace it" % rel)
    for rel, data in files.items():
        tgt = where(game, rel)
        if unsaved(rel):
            backup_copy(rel, tgt, os.path.join(BACK, rel))
            man[rel] = {"sega": sega_hash(rel)}
            save_manifest(man)                           # after each backup: an interruption never loses one
        put(tgt, data)                                   # one step: the game's file is never missing (2026-10-06)
        with open(tgt, "rb") as f:
            if sha(f.read()) != sha(data):
                raise Failed("%s did not write correctly - press JAPANESE in SETUP.exe" % rel)
        man[rel]["english"] = sha(data)                  # the English bytes with Sega's WINMM import (before the hook)
        apply_hook(rel, tgt)                              # then load the kit's hook by its own name (wccfk.dll)
    save_manifest(man)


def turn_off(game):
    man = load_manifest()
    lost = []
    for rel, h in man.items():
        bak, tgt = os.path.join(BACK, rel), where(game, rel)
        if os.path.isfile(bak):
            with open(bak, "rb") as f:
                data = f.read()
            if sha(data) != h["sega"]:
                raise Failed("the backup of %s is not Sega's file - left as it is" % rel)
            put(tgt, data)                               # one step: Sega's file back, never a moment without one
            apply_hook(rel, tgt)                          # it still loads the kit's hook by its own name (wccfk.dll)
            os.remove(bak)
        elif os.path.isfile(tgt):                        # no backup: put back already, or lost (older kits' bug)
            with open(tgt, "rb") as f:
                if sha(norm(f.read(), rel)) != h["sega"]:
                    lost.append(rel)
    if lost:                                             # said, and the list kept - never quietly forgotten
        raise Failed("%d file(s) are not Sega's and have no backup of Sega's file, so they stay as they are (%s%s)"
                     % (len(lost), lost[0], ", ..." if len(lost) > 1 else ""))
    if os.path.isfile(MANIFEST):
        os.remove(MANIFEST)
    for dp, dn, fn in os.walk(BACK, topdown=False):
        if not os.listdir(dp):
            os.rmdir(dp)
    return len(man)


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    mode = (argv[0].lower() if argv else "on")
    lang = argv[1].lower() if len(argv) > 1 else "en"
    if mode not in ("on", "off", "check") or lang not in LANGS:
        print(__doc__)
        return 1
    game = K.find_game(K.load_settings().get("game"))
    if not game:
        print("The game is not set up yet - run SETUP.exe first.")
        return 2
    print("WCCF 2010-11 kit - %s %s - game: %s" % (LANGS[lang], mode, game))
    try:
        if K.game_processes(game):
            if mode != "check":
                raise Failed("the game is running - close its window first, then run this again")
            print("  NOTE  the game is running: \"on\" and \"off\" will refuse until it is closed")
        if mode == "off":
            m = memory_pictures_off()                    # the game loads Sega's own pictures again
            if not load_manifest() and not load_state():
                print("  English is not on - nothing to do.")
                return 0
            p = pictures_off(game)
            n = turn_off(game)
            if os.path.isfile(LANG_FILE):
                os.remove(LANG_FILE)
                os.rmdir(BACK)                           # empty now: turn_off took everything else out
            print("  ok    Sega's Japanese files are back (%d files, %d pictures)." % (n, p + m))
            return 0
        print("  building from your game files ...", flush=True)
        files, notes = build_all(game, lang)
        pics, note = build_pictures(game, lang) if PICTURES else ({}, PICTURES_OFF)
        notes.append(note)
        mem, note = build_memory_pictures(game, lang)
        notes.append(note)
        for n in notes:
            print("  ok    " + n)
        if mode == "check":
            man = load_manifest()
            print("  check only - nothing changed.  \"on\" would replace %d files (%d of them backed up first)."
                  % (len(files), sum(1 for r in files if r not in man)))
            return 0
        turn_on(game, files)
        pictures_on(game, pics)
        memory_pictures_on(mem)
        with open(LANG_FILE, "w", encoding="ascii") as f:
            f.write(lang + "\n")
        print("  ok    %d files in place, %d pictures in the archive and %d in data\\english_pictures, each read back.  "
              "Sega's are in data\\english_backup (JAPANESE in SETUP.exe puts them back)."
              % (len(files), len(pics), len(mem)))
    except Failed as ex:
        print("  FAIL  %s" % ex)
        return 1
    except OSError as ex:
        print("  FAIL  %s" % ex)
        return 1
    print("%s is on. Start the game with PLAY.exe." % LANGS[lang])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
