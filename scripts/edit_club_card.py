# -*- coding: utf-8 -*-
r"""edit_club_card.py - change the data on the club card (the kit's card file: a 16-byte header + 256 blocks of
16 bytes, normally data\save\seat1_club.bin).

    python scripts\edit_club_card.py CARD.bin --set FIELD=VALUE [--set FIELD=VALUE ...] [--write] [--force]
    python scripts\edit_club_card.py --self-test

Fields are addressed as GROUP.FIELD - Club.CLUB_GET_PRIZE, Coach.COACH_LAST_TERM, Coach.COACH_NAME,
UserInfo.USER_INJUSTICE_NUM - or, for the repeated groups, Player0.FIELD ... Player15.FIELD and
Title0.FIELD ... Title29.FIELD.  A name that is unique on the card may be written bare (CLUB_GET_PRIZE).
A text field (club and manager names) takes the text; SYSTEM_COACH_ID takes hex; an array of numbers takes
a comma-separated list of exactly the field's length.  Numbers are decimal, or hex with 0x.

The field table is the one decode_club_card.py reads out of client_Release.exe, so list names, lengths and
limits with:   python scripts\decode_club_card.py CARD.bin --all --defaults

Nothing is written without --write.  The changed card is checked with the game's own acceptance rules before
it is put in place, the old card is kept in backup\ beside it, and the file is replaced in one step (a crash
cannot leave a half card).  A value outside the field's own limits is refused unless --force is given.

The game must be closed first (close its window): the card reader stand-in holds the card in memory from its start,
and a game save after an edit here would put the game's own copy back over it.  The edited card is read at
the next start, so edits show from then on - in the game, and in the CLUB CARD panel.
"""
import argparse
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import decode_club_card as D
except ImportError:
    print("decode_club_card.py and club_card_schema.py must sit beside this file")
    sys.exit(2)

BACKUP_KEEP = 20                    # backups kept in backup\ (the same number the card reader keeps)

INDEX = {}                          # (group, instance, name) -> (schema row, first bit)
for _g, _inst, _r, _b in D.LAYOUT:
    INDEX[(_g, _inst, _r[1])] = (_r, _b)
INSTANCES = {}                      # name -> [(group, instance)]
for _key in INDEX:
    INSTANCES.setdefault(_key[2], []).append((_key[0], _key[1]))


class EditError(Exception):
    pass


# ------------------------------------------------------------------ fields ---

def resolve(spec):
    """'Club.CLUB_GET_PRIZE' / 'Player3.PLAYER_MASTERY' / a bare unique name -> ((group, instance, name), row, bit)"""
    spec = spec.strip()
    if "." in spec:
        where, name = spec.rsplit(".", 1)
        name = name.strip().upper()
        where, inst = where.strip(), None
        m = re.match(r"^([A-Za-z_]+?)[ _-]?(\d+)$", where)
        if m and m.group(1).lower() in ("player", "title"):
            group, inst = m.group(1), int(m.group(2))
        else:
            group = where
        hits = [(k, r, b) for k, (r, b) in INDEX.items()
                if k[0].lower() == group.lower() and k[2] == name and (inst is None or k[1] == inst)]
    else:
        name = spec.upper()
        where = INSTANCES.get(name, [])
        if len(where) == 1:
            hits = [((where[0][0], where[0][1], name),) + INDEX[(where[0][0], where[0][1], name)]]
        elif where:
            raise EditError("%s is in %d places (%s) - write it as Player0.%s, Title0.%s, ..." % (
                name, len(where), ", ".join(sorted({g for g, _ in where})), name, name))
        else:
            hits = []
    if not hits:
        raise EditError("no field %r on the card (names are listed by decode_club_card.py --all --defaults)" % spec)
    if len(hits) > 1:
        raise EditError("%r is there more than once (%s) - name the instance" % (
            spec, ", ".join("%s%d" % (k[0], k[1]) for k, _r, _b in hits[:8])))
    key, row, bit = hits[0]
    return key, row, bit


def parse_value(row, text, force=False):
    """the written value as a list of numbers, in the field's own encoding (text -> cp932 bytes, hex rows,
    comma lists); refuses anything the field cannot hold."""
    _g, name, _desc, count, bits, lo, hi, _default, _settable, _flags = row
    where = "(%d characters, cp932)" % count if name in D.TEXT_FIELDS else "(up to %d hex bytes)" % count
    try:
        if name in D.TEXT_FIELDS:
            raw = text.encode("cp932")
            if len(raw) > count:
                raise EditError("%s is %d bytes in cp932, the field holds %d %s" % (text, len(raw), count, where))
            vals = list(raw) + [0] * (count - len(raw))
        elif count > 1 and bits == 8:
            raw = bytes.fromhex(text.replace(" ", "").replace(":", ""))
            if len(raw) > count:
                raise EditError("%s is %d bytes, the field holds %d %s" % (text, len(raw), count, where))
            vals = list(raw) + [0] * (count - len(raw))
        elif count > 1:
            parts = [p for p in text.replace(" ", "").split(",") if p]
            if len(parts) != count:
                raise EditError("the field is %d numbers; %d were given" % (count, len(parts)))
            vals = [int(p, 0) for p in parts]
        else:
            vals = [int(text, 0)]
    except ValueError as e:
        raise EditError("%r is not a value (%s)" % (text, e))
    for v in vals:
        if not 0 <= v < (1 << bits):
            raise EditError("%d does not fit in the field's %d bits" % (v, bits))
    if count == 1 and not lo <= vals[0] <= hi and not force:
        raise EditError("%d is outside the field's own range %d..%d (--force writes it anyway)"
                        % (vals[0], lo, hi))
    return vals


def write_bits(buf, start, width, value):
    for k in range(width):
        i = start + k
        if (value >> (width - 1 - k)) & 1:
            buf[i >> 3] |= 1 << (7 - (i & 7))
        else:
            buf[i >> 3] &= ~(1 << (7 - (i & 7))) & 0xFF


# ------------------------------------------------------------------- card ----

def read(path):
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) == D.CARD_BYTES:
        header, body = raw[:16], raw[16:]
    elif len(raw) == D.RAW_BYTES:
        header, body = None, raw
    else:
        raise EditError("%s is %d bytes; a card file is %d (%d without its header)"
                        % (path, len(raw), D.CARD_BYTES, D.RAW_BYTES))
    return header, [bytearray(body[16 * i: 16 * i + 16]) for i in range(256)]


def header_dict(h):
    """the header as decode_club_card.py reads it (None when the file has no 16-byte header)."""
    if h is None:
        return None
    return {"uid": h[0:4].hex(), "p_type": h[4], "counter": h[5] | h[6] << 8,
            "header_padding_zero": not any(h[7:16])}


def good_copy(header, blocks):
    """(name, bytes) of the copy the game would read; refuses the cards the game refuses."""
    if header and header[5] | header[6] << 8 == 0xFFFF:
        raise EditError("this is a NEW card (nothing on it yet) - put it in the game once, then edit")
    a, b, chosen, verdict = D.game_choice(header_dict(header), blocks)
    if chosen is None:
        raise EditError("the game would not read this card: %s" % verdict)
    return chosen, bytearray(D.copy_of(blocks, chosen))


def stamp_copy(header, blocks, copy):
    """put the finished copy into both copy areas, with the checksum the game itself writes (sum + 1)."""
    copy = bytearray(copy)
    s = D.dword_sum(copy[:D.PAYLOAD_BYTES])
    struct.pack_into("<I", copy, D.PAYLOAD_BYTES, (s + 1) & 0xFFFFFFFF)
    body = bytearray(b"".join(blocks))
    body[8 * 16: 8 * 16 + D.COPY_BYTES] = copy
    body[113 * 16: 113 * 16 + D.COPY_BYTES] = copy
    return (bytes(header) if header else b"") + bytes(body)


def check(raw):
    """run the game's own acceptance rules over a finished file, as decode_club_card.py does (read-only)."""
    header, body = (raw[:16], raw[16:]) if len(raw) == D.CARD_BYTES else (None, raw)
    blocks = [body[16 * i: 16 * i + 16] for i in range(256)]
    _a, _b, chosen, verdict = D.game_choice(header_dict(header), blocks)
    checks = D.card_checks(header_dict(header), blocks)
    bad = [c for c in checks if not c[2]]
    if chosen is None or bad:
        raise EditError("the changed card would not be accepted (%s%s)" % (
            verdict, "" if not bad else "; " + "; ".join("%s: %s" % (c[0], c[1]) for c in bad)))
    return verdict


def save(path, raw, backup_dir=None):
    """the reader's own way of saving a card: a temp file flushed to the disk, then one replace; the old card
    is copied into backup\\ first (the newest BACKUP_KEEP are kept)."""
    folder = backup_dir or os.path.join(os.path.dirname(os.path.abspath(path)), "backup")
    try:
        os.makedirs(folder, exist_ok=True)
        base = os.path.basename(path)
        dst = os.path.join(folder, "%s.%s.bak" % (base, time.strftime("%Y%m%d-%H%M%S")))
        with open(path, "rb") as f, open(dst, "wb") as o:
            o.write(f.read())
        old = sorted(f for f in os.listdir(folder) if f.startswith(base + ".") and f.endswith(".bak"))
        for f in old[:-BACKUP_KEEP]:
            os.remove(os.path.join(folder, f))
    except OSError as e:
        raise EditError("the old card could not be backed up (%s) - nothing was written" % e)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(50):
        try:
            os.replace(tmp, path)
            return dst
        except PermissionError:
            if attempt == 49:
                raise EditError("the card file stayed busy for a second - nothing was written (is the game up?)")
            time.sleep(0.02)


def running_note(path):
    """the kit writes data\\running.json while everything runs and takes it away when the run ends; warn if it is there."""
    data = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    return os.path.join(data, "running.json")


def shown(name, vals):
    if name in D.TEXT_FIELDS:
        return D.text(vals) or "(empty)"
    if len(vals) == 1:
        return str(vals[0])
    return ",".join(str(v) for v in vals)


# ------------------------------------------------------------ bad endings ---
# The CLUB CARD panel's CLEAR BAD ENDINGS (the community, 2026-10-08: "some easy way to remove bad endings from the
# club card"): play.py calls clear_bad_endings() at the next start, while nothing runs.  The game counts a session cut
# before its locker-room save in USER_INJUSTICE_NUM (at 2 trade rights are lost, from the 5th it costs money) and marks
# a session open in USER_INJUSTICE_FLAG (a flag still set is counted at the next START); the WAN pair counts the same
# for online play.  All four go back to 0.  Trade rights or money the game already took stay as they are.
BAD_ENDING_FIELDS = ("UserInfo.USER_INJUSTICE_NUM", "UserInfo.USER_INJUSTICE_FLAG", "UserInfo.USER_WAN_INJUSTICE_NUM",
                     "SystemInfo.USER_WAN_INJUSTICE_FLAG")


def cleared_bad_endings(header, blocks):
    """(the finished card file with the bad-ending fields at 0, {field: old value}) - None for the file when all
    were 0 already"""
    _which, copy = good_copy(header, blocks)
    vals = D.decode(copy)
    old = {}
    for spec in BAD_ENDING_FIELDS:
        key, row, bit = resolve(spec)
        old[spec] = vals[key][0]
        write_bits(copy, bit, row[3] * row[4], 0)
    if not any(old.values()):
        return None, old
    raw = stamp_copy(header, blocks, copy)
    check(raw)
    return raw, old


def clear_bad_endings(path):
    """the card at path with its bad endings back to 0 (the old card kept in backup\\ first); what was done, in words"""
    if not os.path.exists(path):
        return "no card in the slot - nothing to clear"
    header, blocks = read(path)
    raw, old = cleared_bad_endings(header, blocks)
    if raw is None:
        return "no bad endings to clear"
    save(path, raw)
    num, wan = old["UserInfo.USER_INJUSTICE_NUM"], old["UserInfo.USER_WAN_INJUSTICE_NUM"]
    return "bad endings cleared (%d%s back to 0; the old card is in data\\save\\backup)" % (
        num, "" if not wan else ", online %d" % wan)


# ------------------------------------------------------------------ driver ---

def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Change fields of a WCCF 2010-11 club card",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("card", nargs="?", help="the card file, normally data\\save\\seat1_club.bin")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                    help="a change to make (may be given more than once)")
    ap.add_argument("--write", action="store_true", help="actually write; without it only the changes are shown")
    ap.add_argument("--force", action="store_true", help="allow a value outside the field's own range")
    ap.add_argument("--self-test", action="store_true", help="run the built-in checks and exit")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.card:
        ap.print_help()
        return 2
    try:
        header, blocks = read(a.card)
        which, copy = good_copy(header, blocks)
        before = D.decode(copy)
        changes = []
        for item in a.set:
            if "=" not in item:
                raise EditError("--set wants FIELD=VALUE, not %r" % item)
            spec, text = item.split("=", 1)
            key, row, bit = resolve(spec)
            vals = parse_value(row, text, a.force)
            old = list(before[key])
            write_bits(copy, bit, row[3] * row[4], 0)
            for k, v in enumerate(vals):
                write_bits(copy, bit + k * row[4], row[4], v)
            changes.append((key, row, old, vals))
            before[key] = vals
        if not changes:
            print("nothing to change: give --set FIELD=VALUE (see --help)")
            return 2
        print("CARD  %s" % a.card)
        print("copy  %s (the one the game reads)" % which)
        for (g, inst, name), row, old, new in changes:
            tag = "%s%d.%s" % (g, inst, name) if g in ("Player", "Title") else "%s.%s" % (g, name)
            print("  %-42s %s -> %s   %s" % (tag, shown(name, old), shown(name, new), row[2]))
        raw = stamp_copy(header, blocks, copy)
        verdict = check(raw)
        print("check  the game would accept the changed card: %s" % verdict)
        if not a.write:
            print("dry run - nothing written; add --write to put this card in place")
            return 0
        if os.path.exists(running_note(a.card)):
            raise EditError("the game is running (data\\running.json is there) - close the game first")
        kept = save(a.card, raw)
        print("written  %s   (the old card is kept as %s)" % (a.card, kept))
        print("next    start the game (PLAY.exe): the card is read at the start, so the change shows from then on")
        return 0
    except EditError as e:
        print("refused: %s" % e)
        return 1


# ---------------------------------------------------------------- self-check --

def self_test():
    """the packing, the checksum and the acceptance check on a card made here: no game files needed."""
    checks = []

    def ok(what, cond):
        checks.append((what, bool(cond)))

    blocks = [bytearray(16) for _ in range(256)]
    blocks[4][8:12] = bytes([0x95, 0x71, 0x66, 0x40])              # the reader signature
    blocks[6][12:16] = bytes([0x00, 0x98, 0x96, 0x81])             # the serial
    header = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x18, 0x10, 0x00]) + bytes(9)
    raw = stamp_copy(header, blocks, bytearray(D.COPY_BYTES))
    ok("a fresh copy passes the game's checks", check(raw) is not None)

    _h, b2 = read_bytes(raw)
    _which, copy = good_copy(_h, b2)
    key, row, bit = resolve("Club.CLUB_GET_PRIZE")
    vals = parse_value(row, "12345")
    base = bytearray(copy)
    write_bits(copy, bit, row[3] * row[4], vals[0])
    ok("a written field comes back", D.decode(copy)[key] == vals)
    touched = [i for i in range(len(copy)) if copy[i] != base[i]]
    ok("only the field's own bytes change", all(bit // 8 <= i <= (bit + row[4] - 1) // 8 for i in touched))
    write_bits(copy, bit, row[3] * row[4], 0)
    ok("writing the old value back restores the bytes", bytes(copy) == bytes(base))

    key, row, bit = resolve("Club.CLUB_NAME")
    vals = parse_value(row, "TEST CLUB")
    write_bits(copy, bit, row[3] * row[4], 0)
    for k, v in enumerate(vals):
        write_bits(copy, bit + k * 8, 8, v)
    ok("text round-trips", D.text(D.decode(copy)[key]) == "TEST CLUB")

    raw2 = stamp_copy(header, b2, copy)
    h3, b3 = read_bytes(raw2)
    ok("both copies carry the change", D.copy_of(b3, "A") == D.copy_of(b3, "B"))
    ok("the changed card is accepted", check(raw2) is not None)

    try:
        parse_value(resolve("Club.CLUB_GET_PRIZE")[1], str(1 << 24))
        ok("a value too wide is refused", False)
    except EditError:
        ok("a value too wide is refused", True)
    try:
        parse_value(resolve("Player0.PLAYER_MASTERY")[1], "999")
        ok("a value past the field's range is refused", False)
    except EditError:
        ok("a value past the field's range is refused", True)
    try:
        resolve("NOSUCHFIELD")
        ok("an unknown field is refused", False)
    except EditError:
        ok("an unknown field is refused", True)

    copy = bytearray(D.COPY_BYTES)                                 # bad endings: 2 counted, a session left open
    for spec, v in (("UserInfo.USER_INJUSTICE_NUM", 2), ("UserInfo.USER_INJUSTICE_FLAG", 1)):
        key, row, bit = resolve(spec)
        write_bits(copy, bit, row[3] * row[4], v)
    h4, b4 = read_bytes(stamp_copy(header, blocks, copy))
    raw4, old4 = cleared_bad_endings(h4, b4)
    after = D.decode(good_copy(*read_bytes(raw4))[1]) if raw4 else {}
    ok("bad endings are cleared", raw4 is not None and old4["UserInfo.USER_INJUSTICE_NUM"] == 2 and
       all(after[resolve(sp)[0]] == [0] for sp in BAD_ENDING_FIELDS))
    ok("the rest of the card is unchanged by it", raw4 is not None and
       {k for k in after if after[k] != D.decode(good_copy(h4, b4)[1])[k]} ==
       {resolve(sp)[0] for sp in BAD_ENDING_FIELDS if old4[sp]})
    ok("a card without bad endings is left alone", cleared_bad_endings(_h, b2)[0] is None)

    bad = 0
    for what, cond in checks:
        print("  %-44s %s" % (what, "ok" if cond else "FAIL"))
        bad += 0 if cond else 1
    print("self-test: %d checks, %s" % (len(checks), "all ok" if not bad else "%d FAILED" % bad))
    return 1 if bad else 0


def read_bytes(raw):
    header, body = (raw[:16], raw[16:]) if len(raw) == D.CARD_BYTES else (None, raw)
    return header, [bytearray(body[16 * i: 16 * i + 16]) for i in range(256)]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
