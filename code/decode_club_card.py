# -*- coding: utf-8 -*-
"""Read-only decoder for WCCF 2010-11 club card files (the kit's card file: a 16-byte header + 256 blocks of 16 bytes).

    python decode_club_card.py CARD.bin                    summary, checks, checksums, squad
    python decode_club_card.py CARD.bin --all              + every field that is not at its default
    python decode_club_card.py CARD.bin --all --defaults   + every field, defaults included
    python decode_club_card.py CARD.bin --json             everything as JSON (for tools / a server)
    python decode_club_card.py CARD.bin --diff OTHER.bin   the fields that differ between two cards
    python decode_club_card.py CARD.bin --copy B           decode copy B instead of the copy the game would use
    python decode_club_card.py --verify-schema [EXE]       re-read the field tables from client_Release.exe and
                                                           compare them with club_card_schema.py
    python decode_club_card.py --sram MXSRAM.bin           list the game's own card backups in an mxsram image

The card file is opened read-only, read in one go and closed at once; nothing is ever written. Exit codes:
0 = the game would accept this card; 1 = the game would refuse it (or --diff found differences / --verify-schema
found a mismatch); 2 = the file could not be read (missing, wrong size).

Where each rule comes from is in docs\\research\\CLUB-CARD-2010-11.md. In short (all read in client_Release.exe):
  payload = 10 parameter groups (FUN_00422210), stored: SystemInfo, UserInfo, Coach, Club, Player x16, Title x30,
  Etc = 1,676 bytes, MSB-first bits, each group padded to a byte; + a 32-bit checksum = (sum of the 419
  little-endian dwords) + 1 (FUN_004d7d20); copy A = blocks 8-112, copy B = blocks 113-217 (same bytes);
  a copy is good when stored == sum or sum + 1 (FUN_004d7bb0).
"""
import argparse
import csv
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from club_card_schema import FIELDS, GROUP_ORDER, EXE_SHA256
except ImportError:      # an error, never an exit: play.py, the panel helper and boards.py load this module themselves
    raise ImportError("club_card_schema.py is missing: it must sit beside this file "
                      "(make it with make_schema_module.py)") from None

CARD_BYTES = 16 + 256 * 16          # the kit's card file (_icc_reader.py CARD_BYTES)
RAW_BYTES = 256 * 16                # a bare block dump, no header
COPY_BYTES = 0x690                  # one copy: payload + checksum
PAYLOAD_BYTES = 0x68C               # 1,676
DEFAULT_EXE = os.path.join(HERE, "..", "..", "..", "wccf1011-revd", "sbwg", "extracted", "client_Release.exe")
DEFAULT_CATALOGUE = os.path.join(HERE, "..", "..", "playercards1011", "catalogue.tsv")


class CardError(Exception):
    pass


# ---------------------------------------------------------------- reading ----

def read_file(path):
    with open(path, "rb") as f:                     # read-only, closed at once
        return f.read()


def read_card(path):
    try:
        raw = read_file(path)
    except OSError as e:
        raise CardError("cannot read %s (%s)" % (path, e))
    if len(raw) == CARD_BYTES:
        header = {"uid": raw[0:4].hex(), "p_type": raw[4], "counter": raw[5] | raw[6] << 8,
                  "header_padding_zero": not any(raw[7:16])}
        body = raw[16:]
    elif len(raw) == RAW_BYTES:
        header = None
        body = raw
    else:
        raise CardError("%s is %d bytes; a kit card file is %d (or %d without its header)"
                        % (path, len(raw), CARD_BYTES, RAW_BYTES))
    blocks = [body[16 * i:16 * i + 16] for i in range(256)]
    return header, blocks


def copy_of(blocks, which):
    data = b"".join(blocks[8:218])
    return data[:COPY_BYTES] if which == "A" else data[COPY_BYTES:]


def dword_sum(buf):
    return sum(struct.unpack("<%dI" % (len(buf) // 4), buf)) & 0xFFFFFFFF


def copy_check(copy):
    s = dword_sum(copy[:PAYLOAD_BYTES])
    stored = struct.unpack_from("<I", copy, PAYLOAD_BYTES)[0]
    zero = s == 0 and stored == 0
    good = (stored == s or stored == (s + 1) & 0xFFFFFFFF) and not zero
    return {"sum": s, "stored": stored, "good": good, "all_zero": zero,
            "written_by_game": stored == (s + 1) & 0xFFFFFFFF}


# --------------------------------------------------------------- the checks --

def card_checks(header, blocks):
    """The detection checks of client FUN_004d6c40 / FUN_004d6060 / FUN_004d7bb0 that a file can show."""
    out = []
    counter = header["counter"] if header else None
    new = counter == 0xFFFF
    if header:
        out.append(("Card Status byte", "0x%02X" % header["p_type"], header["p_type"] != 0x20,
                    "must not be 0x20 (else error 5)"))
    sig = struct.unpack_from("<I", blocks[4], 8)[0] & 0xF0FFFFFF
    out.append(("block 4 signature", "0x%08X" % sig, sig == 0x40667195, "must be 0x40667195 (else error 4/5)"))
    serial = struct.unpack(">I", blocks[6][12:16])[0]
    out.append(("block 6 serial", str(serial), serial >= 10000000, "must be >= 10,000,000 (else error 4)"))
    if counter is not None:
        low = counter & 0xFF
        if new:
            meaning = "NEW card: the game writes block 7, zeroes the data and goes to Club Make"
        elif low == 0:
            meaning = "used up (error 8)"
        elif low == 1:
            meaning = "last use (error 7, the game still goes on)"
        elif low == 0xFF:
            meaning = "low byte 0xFF without 0xFFFF: treated as new but the checksum check runs (error 0xA)"
        else:
            meaning = "in use; %d decrements since new" % (0xFFFF - counter)
        out.append(("use counter (block 5)", "0x%04X" % counter, low not in (0,), meaning))
    if not new:
        out.append(("block 7 == block 0", str(blocks[7] == blocks[0]), blocks[7] == blocks[0],
                    "anti-copy binding (else error 6)"))
        ver = struct.unpack(">i", blocks[8][:4])[0]
        out.append(("SYSTEM_VERSION (block 8 bytes 0-3)", str(ver), not 1 <= ver <= 4,
                    "1-4 are refused (error 4)"))
    return out


def game_choice(header, blocks):
    """Which copy the game reads (FUN_004d7bb0 + FUN_004d7530), or why it refuses the card."""
    a, b = copy_check(copy_of(blocks, "A")), copy_check(copy_of(blocks, "B"))
    if header and header["counter"] == 0xFFFF:
        return a, b, None, "new card: checksums are not checked"
    if a["all_zero"] or b["all_zero"]:
        return a, b, None, "REFUSED (error 0xA): a copy is all zeros"
    if a["good"]:
        return a, b, "A", "copy A is good: the game reads copy A"
    if b["good"]:
        return a, b, "B", "copy A is bad, copy B is good: the game reads copy B"
    return a, b, None, "REFUSED (error 0xA): both copies fail their checksum"


# ---------------------------------------------------------------- decoding ---

def layout():
    """[(group, instance, row, first_bit)] in card order, and the payload length in bytes."""
    by_group = {}
    for row in FIELDS:
        by_group.setdefault(row[0], []).append(row)
    out, pos = [], 0
    for gname, reps in GROUP_ORDER:
        rows = by_group[gname]
        bits = sum(r[3] * r[4] for r in rows)
        nbytes = (bits + 7) // 8
        for inst in range(reps):
            b = pos * 8
            for r in rows:
                out.append((gname, inst, r, b))
                b += r[3] * r[4]
            pos += nbytes
    return out, pos


LAYOUT, LAYOUT_BYTES = layout()
assert LAYOUT_BYTES == PAYLOAD_BYTES, "schema does not add up to 0x68C bytes"


def bits_at(buf, start, width):
    v = 0
    for k in range(width):
        i = start + k
        v = (v << 1) | ((buf[i >> 3] >> (7 - (i & 7))) & 1)
    return v


def decode(copy):
    """{(group, instance, name): [values]} in card order."""
    out = {}
    for gname, inst, r, b in LAYOUT:
        count, width = r[3], r[4]
        out[(gname, inst, r[1])] = [bits_at(copy, b + k * width, width) for k in range(count)]
    return out


ROW = {r[1]: r for r in FIELDS}
TEXT_FIELDS = {"COACH_NAME", "COACH_NAME_READ", "CLUB_NAME", "CLUB_NAME_CALL", "SYSTEM_MACHINE_SERIAL_NO"}
DATE_FIELDS = {"SYSTEM_LAST_PLAY_DAY", "COACH_BIRTHDAY", "CLUB_FOUNDATION", "SYSTEM_COACH_ENTRY_TIME"}
REDACT = [False]                    # --redact-dates: print [date] instead of any date or time (for reports)


def text(vals):
    b = bytes(vals)
    z = b.find(b"\0")
    if z >= 0:
        b = b[:z]
    try:
        return b.decode("cp932")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def ymd8(v):
    if REDACT[0]:
        return "[date]" if v else "-"
    return "%04d-%02d-%02d" % (v // 10000, v // 100 % 100, v % 100) if v else "-"


def ymd6(v):
    if REDACT[0]:
        return "[date]" if v else "-"
    return "20%02d-%02d-%02d" % (v // 10000, v // 100 % 100, v % 100) if v else "-"


def shown(name, vals):
    """A readable form of one field (only for fields whose encoding was checked on real cards)."""
    if REDACT[0] and name in DATE_FIELDS:
        return "[date]" if vals[0] else "0"
    if name in TEXT_FIELDS:
        return text(vals)
    if name == "SYSTEM_COACH_ID":
        return bytes(vals).hex(" ")
    v = vals[0] if len(vals) == 1 else None
    if v is None:
        return ",".join(str(x) for x in vals)
    if name == "SYSTEM_LAST_PLAY_DAY":
        return "%d (%s)" % (v, ymd6(v))
    if name in ("COACH_BIRTHDAY", "CLUB_FOUNDATION"):
        return "%d (%s)" % (v, ymd8(v))
    if name == "SYSTEM_COACH_ENTRY_TIME":
        return "%d (%02d-%02d %02d:%02d:%02d)" % (v, v // 100000000, v // 1000000 % 100, v // 10000 % 100,
                                                    v // 100 % 100, v % 100) if v else "0"
    if name in ("COACH_SALARY", "COACH_SUCCESSION_SALARY", "COACH_SALARY_0506"):
        return "%d (= $%s on screen)" % (v, "{:,}".format(v * 100))
    return str(v)


# --------------------------------------------------------------- catalogue ---

def load_catalogue(path):
    if not path or not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        r = csv.reader(f, delimiter="\t")
        head = next(r)
        ix = {n: i for i, n in enumerate(head)}
        for row in r:
            try:
                no = int(row[0])
            except (ValueError, IndexError):
                continue
            get = lambda k: row[ix[k]] if k in ix and ix[k] < len(row) else ""
            out[no] = (get("name_short_latin") or get("name_display_ascii"), get("position_name"), get("club_name"))
    return out


# ---------------------------------------------------------------- reports ----

def league(d):
    """Regular League table from the card. Entry 0 of the CLUB_RL_IMAGINE_* arrays equals the club's own record on
    every sample checked, so entries 1-7 are the other seven teams [inferred]."""
    w, dr, l = d[("Club", 0, "CLUB_RL_WIN")][0], d[("Club", 0, "CLUB_RL_DRAW")][0], d[("Club", 0, "CLUB_RL_LOSE")][0]
    gf, ga = d[("Club", 0, "CLUB_RL_GET_GOAL")][0], d[("Club", 0, "CLUB_RL_LOSE_GOAL")][0]
    pts = d[("Club", 0, "CLUB_RL_IMAGINE_POINT")][0]
    tp, tf, ta = (d[("Club", 0, "CLUB_RL_IMAGINE_POINT")], d[("Club", 0, "CLUB_RL_IMAGINE_GOAL_POINT")],
                  d[("Club", 0, "CLUB_RL_IMAGINE_GOAL_LOST_POINT")])
    me = (3 * w + dr, gf - ga, gf)
    better = sum(1 for k in range(1, 8) if (tp[k], tf[k] - ta[k], tf[k]) > me)
    return {"win": w, "draw": dr, "lose": l, "goals_for": gf, "goals_against": ga, "points": 3 * w + dr,
            "entry0_points": pts, "entry0_is_club": (tp[0], tf[0], ta[0]) == (3 * w + dr, gf, ga),
            "position_computed": better + 1, "position_stored": d[("Club", 0, "CLUB_RL_LAST_RANK")][0] + 1,
            "division": d[("Club", 0, "CLUB_RL_PRESENT_DIVISION")][0], "leg": d[("Club", 0, "CLUB_RL_SECTION")][0]}


def one(d, g, name):
    return d[(g, 0, name)][0]


def print_summary(path, header, blocks, which, d, cat):
    a, b, chosen, verdict = game_choice(header, blocks)
    print("CARD FILE  %s" % path)
    if header:
        print("header     uid %s  Card Status 0x%02X  use counter 0x%04X  padding zero: %s" % (
            header["uid"], header["p_type"], header["counter"], header["header_padding_zero"]))
    else:
        print("header     none (a bare 4,096-byte block dump)")
    print()
    print("CHECKS (the reader-level checks the game makes at detection)")
    ok_all = True
    for label, value, ok, rule in card_checks(header, blocks):
        ok_all &= ok
        print("  %-34s %-12s %-4s %s" % (label, value, "ok" if ok else "FAIL", rule))
    print()
    print("CHECKSUMS  (sum of 419 little-endian dwords; the game stores sum+1 and accepts sum or sum+1)")
    for name, c in (("A (blocks 8-112)", a), ("B (blocks 113-217)", b)):
        print("  copy %-19s sum 0x%08X stored 0x%08X  %s%s" % (
            name, c["sum"], c["stored"], "GOOD" if c["good"] else "BAD",
            " (all zero)" if c["all_zero"] else (" (sum+1: written by the game)" if c["written_by_game"] else "")))
    print("  copy A == copy B: %s" % (copy_of(blocks, "A") == copy_of(blocks, "B")))
    print("  verdict: %s" % verdict)
    new = bool(header and header["counter"] == 0xFFFF)
    accepted = ok_all and (chosen is not None or new)
    print("  OVERALL: %s" % ("the game would accept this card" if accepted else
                             "the game would REFUSE this card (see FAIL / REFUSED above)"))
    if d is None:
        return ok_all and (chosen is not None or (header and header["counter"] == 0xFFFF))
    print("  decoded: copy %s" % which)
    print()
    sal = one(d, "Coach", "COACH_SALARY")
    lg = league(d)
    print("CLUB")
    print("  manager            %s   (reading %s)" % (text(d[("Coach", 0, "COACH_NAME")]), text(d[("Coach", 0, "COACH_NAME_READ")])))
    print("  club               %s   (reading %s)" % (text(d[("Club", 0, "CLUB_NAME")]), text(d[("Club", 0, "CLUB_NAME_CALL")])))
    print("  founded            %s   card made %s   last played %s" % (
        ymd8(one(d, "Club", "CLUB_FOUNDATION")), shown("SYSTEM_COACH_ENTRY_TIME", [one(d, "SystemInfo", "SYSTEM_COACH_ENTRY_TIME")]),
        ymd6(one(d, "SystemInfo", "SYSTEM_LAST_PLAY_DAY"))))
    print("  card version       %d" % one(d, "SystemInfo", "SYSTEM_VERSION"))
    print("  Regular League     division %d, leg %d: W%d L%d D%d, goals %d-%d, %d points, position %d (computed), %d (stored rank+1)" % (
        lg["division"], lg["leg"], lg["win"], lg["lose"], lg["draw"], lg["goals_for"], lg["goals_against"],
        lg["points"], lg["position_computed"], lg["position_stored"]))
    print("  all matches        manager W%d D%d L%d; club W%d D%d L%d; win streak %d (best %d); official streak %d" % (
        one(d, "Coach", "COACH_TOTAL_WIN_NUM"), one(d, "Coach", "COACH_TOTAL_DRAW_NUM"), one(d, "Coach", "COACH_TOTAL_LOSE_NUM"),
        one(d, "Club", "CLUB_RECORD_WIN"), one(d, "Club", "CLUB_RECORD_DRAW"), one(d, "Club", "CLUB_RECORD_LOSE"),
        one(d, "Club", "CLUB_RECORD_SERIES_WIN"), one(d, "Club", "CLUB_RECORD_MAX_SERIES_WIN"),
        one(d, "Club", "CLUB_RECORD_OFFICIAL_SERIES_WIN")))
    print("  annual salary      %d  (= $%s on screen)" % (sal, "{:,}".format(sal * 100)))
    print("  prize money        %d   finance points %d   supporters %d" % (
        one(d, "Club", "CLUB_GET_PRIZE"), one(d, "Club", "CLUB_FINANCIAL_POITN"), one(d, "Club", "CLUB_SUPPORTER_NUM")))
    print("  contract left      %d matches   manager level %d   stadium name index %d" % (
        one(d, "Coach", "COACH_LAST_TERM"), one(d, "Coach", "COACH_LEVEL"), one(d, "Club", "CLUB_STADIUM_NAME")))
    print("  trades             rights %d, remaining %d" % (
        one(d, "SystemInfo", "CLUB_TRADE_RIGHT_NUM"), one(d, "SystemInfo", "CLUB_TRADE_REMAINDER_NUM")))
    print()
    print("SESSION SAFETY")
    flag = one(d, "UserInfo", "USER_INJUSTICE_FLAG")
    print("  improper flag      %d  %s" % (flag, "(a session is open, or the last one did not end normally)" if flag else "(closed: last write was a locker-room save or a game-over state)"))
    print("  improper count     %d  (penalties: trade rights at 2+, money/contract/streaks at every 5th)" % one(d, "UserInfo", "USER_INJUSTICE_NUM"))
    print("  WAN flag / count   %d / %d" % (one(d, "SystemInfo", "USER_WAN_INJUSTICE_FLAG"), one(d, "UserInfo", "USER_WAN_INJUSTICE_NUM")))
    print("  unsent plays       %d  (matches since the server last confirmed this card)" % one(d, "UserInfo", "USER_FAILURE_TRANSMISSION_PLAY_NUM"))
    print("  network IDs        manager %d  card %d   card id %d   shop id %d" % (
        one(d, "SystemInfo", "SYSTEM_NETWORK_COACH_ID"), one(d, "SystemInfo", "SYSTEM_NETWORK_CARD_ID"),
        one(d, "SystemInfo", "SYSTEM_CARD_ID"), one(d, "SystemInfo", "SYSTEM_SHOP_ID")))
    print("  coach id (server key) %s" % bytes(d[("SystemInfo", 0, "SYSTEM_COACH_ID")]).hex(" "))
    print()
    print("SQUAD (16 registered players)")
    print("  #   card   name                   pos back apps goals asst cond fatigue mastery injury")
    for i in range(16):
        g = lambda n: d[("Player", i, n)][0]
        no = g("PLAYER_CARD_NO")
        nm = cat.get(no, ("", "", ""))
        inj = "%d/%d/%d" % (g("PLAYER_INJURY_PART"), g("PLAYER_INJURY_DEGREE"), g("PLAYER_INJURY_HEALING")) if g("PLAYER_INJURY_PART") else "-"
        print("  %-3d %-6d %-22s %-3s %-4d %-4d %-5d %-4d %-4d %-7d %-7d %s" % (
            i, no, nm[0][:22], nm[1][:3], g("PLAYER_BACK_NUMBER"), g("PLAYER_PARTICIPATE_NUM"), g("PLAYER_OFFICIAL_GOAL"),
            g("PLAYER_OFFICIAL_ASSIST"), g("PLAYER_CONDITION"), g("PLAYER_TEAM_ACCUMULATE_FATIGUE"), g("PLAYER_MASTERY"), inj))
    if not cat:
        print("  (no names: .work\\playercards1011\\catalogue.tsv not found; pass --catalogue)")
    return ok_all and (chosen is not None or bool(header and header["counter"] == 0xFFFF))


def print_all(d, defaults):
    print()
    print("ALL FIELDS%s  (group[instance] NAME description = value)" % ("" if defaults else " NOT AT THEIR DEFAULT"))
    for (g, inst, name), vals in d.items():
        r = ROW[name]
        if not defaults and all(v == r[7] for v in vals) and not (name in TEXT_FIELDS and any(vals)):
            continue
        tag = "%s[%d]" % (g, inst) if g in ("Player", "Title") else g
        print("  %-11s %-44s %s = %s" % (tag, name, r[2], shown(name, vals)))


def as_json(path, header, blocks, d, which):
    a, b, chosen, verdict = game_choice(header, blocks)
    out = {"file": path, "header": header, "copy_A": a, "copy_B": b, "copies_equal": copy_of(blocks, "A") == copy_of(blocks, "B"),
           "verdict": verdict, "decoded_copy": which,
           "checks": [{"check": c[0], "value": c[1], "ok": c[2], "rule": c[3]} for c in card_checks(header, blocks)],
           "schema_exe_sha256": EXE_SHA256, "fields": {}}
    if d is not None:
        for (g, inst, name), vals in d.items():
            key = "%s[%d].%s" % (g, inst, name) if g in ("Player", "Title") else "%s.%s" % (g, name)
            if REDACT[0] and name in DATE_FIELDS:
                out["fields"][key] = "[date]" if vals[0] else 0
                continue
            out["fields"][key] = text(vals) if name in TEXT_FIELDS else (vals[0] if len(vals) == 1 else vals)
        out["league"] = league(d)
    return out


# ------------------------------------------------------------- self checks ---

def verify_schema(exe):
    """Re-read the descriptor tables from the exe (read-only) and compare with FIELDS."""
    tables = {"SystemInfo": (0x00BD03D8, 0x44), "UserInfo": (0x00BD4370, 7), "Coach": (0x00B3D800, 0xFA),
              "Club": (0x00B13FB0, 0x305), "Player": (0x00BCD048, 0x3C), "Title": (0x00BD3E48, 6),
              "Etc": (0x00B4AED8, 0x3F)}
    d = read_file(exe)
    pe_off = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe_off + 6)[0]
    optsz = struct.unpack_from("<H", d, pe_off + 20)[0]
    base = struct.unpack_from("<I", d, pe_off + 52)[0]
    secs = []
    for i in range(nsec):
        s = pe_off + 24 + optsz + 40 * i
        vsize, va, rsize, raw = struct.unpack_from("<IIII", d, s + 8)
        secs.append((base + va, max(vsize, rsize), raw, rsize))

    def at(va, n):
        for sva, size, raw, rsize in secs:
            if sva <= va < sva + size:
                o = va - sva
                return d[raw + o: raw + o + n]
        raise ValueError(hex(va))

    rows = []
    for g, _ in GROUP_ORDER:
        tva, n = tables[g]
        recs = []
        for i in range(n):
            rec = at(tva + i * 0xDC, 0xDC)
            name = rec[:0x40].split(b"\0")[0].decode("latin-1")
            desc = rec[0x40:0xC0].split(b"\0")[0].decode("cp932", "replace")
            c0, c4 = struct.unpack_from("<II", rec, 0xC0)
            mx, mn, df = struct.unpack_from("<iii", rec, 0xCC)
            recs.append((g, name, desc, c0, rec[0xD8], mn, mx, df, c4, rec[0xC8:0xCC].hex()))
        i = 0
        while i < n:
            j = i
            while j + 1 < n and recs[j + 1][1] == recs[i][1]:
                j += 1
            r = recs[i]
            rows.append((r[0], r[1], r[2], j - i + 1, r[4], r[5], r[6], r[7], r[8], r[9]))
            i = j + 1
    same = rows == [tuple(x) for x in FIELDS]
    print("schema in club_card_schema.py: %d fields; re-read from %s: %d fields -> %s" % (
        len(FIELDS), exe, len(rows), "IDENTICAL" if same else "DIFFERENT"))
    if not same:
        for x, y in zip(rows, FIELDS):
            if tuple(x) != tuple(y):
                print("  first difference: exe %r vs table %r" % (x, y))
                break
    return same


def sram_backups(path):
    """The game's own backup slots (FUN_004d76f0: slot k at base + k*0xFB0; +9 = the card's block 0, +0x19 = copy A).
    The base offsets 0x4C08 and 0xEA08 were found by searching real mxsram images, not read in code."""
    d = read_file(path)
    print("SRAM %s (%d bytes)" % (path, len(d)))
    for base in (0x4C08, 0xEA08):
        print("  area at 0x%05X  header %s" % (base - 8, d[base - 8: base].hex(" ")))
        for k in range(10):
            s = base + k * 0xFB0
            key, data = d[s + 9: s + 25], d[s + 25: s + 25 + COPY_BYTES]
            if not any(key) and not any(data):
                continue
            c = copy_check(data)
            dd = decode(data)
            print("    slot %d  key %s  checksum %s  manager %s  club %s  last played %s  improper flag %d count %d" % (
                k, key.hex(), "GOOD" if c["good"] else "BAD", text(dd[("Coach", 0, "COACH_NAME")]),
                text(dd[("Club", 0, "CLUB_NAME")]), ymd6(dd[("SystemInfo", 0, "SYSTEM_LAST_PLAY_DAY")][0]),
                dd[("UserInfo", 0, "USER_INJUSTICE_FLAG")][0], dd[("UserInfo", 0, "USER_INJUSTICE_NUM")][0]))


# -------------------------------------------------------------------- main ---

def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Read-only WCCF 2010-11 club card decoder")
    ap.add_argument("card", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--defaults", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--diff")
    ap.add_argument("--copy", choices=["A", "B"])
    ap.add_argument("--catalogue", default=DEFAULT_CATALOGUE)
    ap.add_argument("--verify-schema", nargs="?", const=DEFAULT_EXE)
    ap.add_argument("--sram")
    ap.add_argument("--redact-dates", action="store_true")
    a = ap.parse_args(argv)
    REDACT[0] = a.redact_dates
    try:
        if a.verify_schema:
            return 0 if verify_schema(a.verify_schema) else 1
        if a.sram:
            sram_backups(a.sram)
            return 0
        if not a.card:
            ap.print_help()
            return 2
        header, blocks = read_card(a.card)
    except (CardError, OSError, ValueError) as e:
        print("cannot read: %s" % e)
        return 2
    _, _, chosen, _ = game_choice(header, blocks)
    which = a.copy or chosen or "A"
    d = decode(copy_of(blocks, which))
    if header and header["counter"] == 0xFFFF and not a.copy:
        d = None if not any(copy_of(blocks, "A")) else d
    if a.diff:
        try:
            h2, b2 = read_card(a.diff)
        except CardError as e:
            print("cannot read: %s" % e)
            return 2
        _, _, c2, _ = game_choice(h2, b2)
        d2 = decode(copy_of(b2, a.copy or c2 or "A"))
        n = 0
        print("FIELDS THAT DIFFER  %s  ->  %s" % (a.card, a.diff))
        if header and h2 and header["counter"] != h2["counter"]:
            print("  header use counter: 0x%04X -> 0x%04X" % (header["counter"], h2["counter"]))
        for key, vals in d.items():
            if d2[key] != vals:
                g, inst, name = key
                tag = "%s[%d]" % (g, inst) if g in ("Player", "Title") else g
                print("  %-11s %-44s %s -> %s" % (tag, name, shown(name, vals), shown(name, d2[key])))
                n += 1
        bl = [i for i in range(256) if blocks[i] != b2[i]]
        print("  %d fields differ; %d blocks differ: %s" % (n, len(bl), bl))
        return 1 if n or bl else 0
    if a.json:
        print(json.dumps(as_json(a.card, header, blocks, d, which), ensure_ascii=False, indent=1))
        return 0 if chosen else 1
    ok = print_summary(a.card, header, blocks, which, d, load_catalogue(a.catalogue))
    if a.all and d is not None:
        print_all(d, a.defaults)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
