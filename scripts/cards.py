# -*- coding: utf-8 -*-
r"""cards.py - make the CATALOGUE's files from your own copy of WCCF 2010-11 (Rev D).  Only READS the game's files.

    python cards.py GAME OUT
      GAME  the folder with client_Release.exe in it (the "extracted" folder of the sbwg download)
      OUT   where catalogue.tsv and cards\ are written (the overlay's folder)

Writes  catalogue.tsv           one line per card: number, season, rarity, names, line, club, the six stats, total ...
        cards\<number>.png      each card's picture, 128x128 (the overlay shows its left 88 columns: the face)
Reads   client_Release.exe                       its card-number -> record table (VA 0x00AF8610); the kit's patches
                                                 do not touch those bytes, so a patched exe gives the same result
        prog_data\player_data\player_data.bin    3,927 player records of 0x328 bytes
        data\wccf_data.xaf                       the archive: its table of contents, then data/player_card/*.dds
Exit    0 written and every check passed; 1 a check failed (nothing written if it was a catalogue check);
        2 a game file is missing or OUT cannot be written.

Club, nationality and season names are not stored in the game: they are read off the players who carry each code
(codes_inferred.py).  The columns and their order are the WCCF project's catalogue's, so the overlay reads them where
it always has; the one column that pointed at the older 2005-06 pack (alt_png_2005_06_build) is kept, empty.
"""
import collections
import io
import os
import struct
import sys

from PIL import Image

import codes_inferred as CI
import ys_lzw

REC = 0x328                     # record size (the client freads 0x328-byte records)
RECORDS = 3927                  # Rev D's player_data.bin
CARD_TABLE_VA = 0x00AF8610      # int32[0x26E0]: card number -> record index (-1 = none)
CARD_TABLE_N = 0x26E0
XAF_ENTRY = 0xB0                # one table-of-contents entry in wccf_data.xaf
POSITIONS = {0: "GK", 1: "DF", 2: "MF", 3: "FW"}
RARITY = {1: ("REGULAR", "Normal"), 2: ("SPECIAL", "Black"), 3: ("RARE", "Silver"),
          4: ("LEGEND", "Gold"), 5: ("ALL TIME LEGEND", "Gold")}
STAT_NAMES = ("offence", "defence", "technique", "power", "speed", "stamina")
COLS = ["card_no", "record_index", "set_no", "edition", "edition_label", "season", "rarity", "rarity_name",
        "rarity_frame", "is_placeholder", "name_full_latin", "name_short_latin", "name_display_ascii",
        "name_full_kana", "name_short_kana", "position_name", "club_id", "club_name", "nationality_id",
        "nationality_name", "shirt_numbers", "birth_date", "height_cm", "weight_kg"] + \
       ["stat_" + s for s in STAT_NAMES] + \
       ["stats_total", "skill_en", "skill_jp", "model_key", "image_archive_path", "image_xaf_offset",
        "image_xaf_stored_size", "image_size", "image_packed", "alt_png_2005_06_build", "hidden_params",
        "u16_04", "u16_06", "u16_08", "bytes_125_12e", "byte_136", "byte_31a", "byte_31b", "bytes_31c_326"]


def game_files(game):
    """{'exe', 'players', 'xaf'} under GAME (or under GAME\\extracted), or None after saying what is missing."""
    rel = {"exe": "client_Release.exe", "players": os.path.join("prog_data", "player_data", "player_data.bin"),
           "xaf": os.path.join("data", "wccf_data.xaf")}
    for root in (game, os.path.join(game, "extracted")):
        if all(os.path.isfile(os.path.join(root, r)) for r in rel.values()):
            return {k: os.path.join(root, r) for k, r in rel.items()}
    for k, r in rel.items():
        if not os.path.isfile(os.path.join(game, r)):
            print("missing: %s" % os.path.join(game, r))
    return None


def va_to_offset(d, va):
    lfa = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, lfa + 6)[0]
    optsz = struct.unpack_from("<H", d, lfa + 20)[0]
    base = struct.unpack_from("<I", d, lfa + 24 + 28)[0]
    for i in range(nsec):
        o = lfa + 24 + optsz + 40 * i
        vsz, sva, rsz, roff = struct.unpack_from("<IIII", d, o + 8)
        if base + sva <= va < base + sva + rsz:
            return roff + va - base - sva
    raise ValueError("VA 0x%08x is not in the file's initialised data" % va)


def card_table(exe):
    """{card_number: record_index} for every card number the exe's static table maps."""
    d = open(exe, "rb").read()
    if d[:2] != b"MZ":
        raise ValueError("%s is not a Windows program" % exe)
    tab = struct.unpack_from("<%di" % CARD_TABLE_N, d, va_to_offset(d, CARD_TABLE_VA))
    return {c: i for c, i in enumerate(tab) if i >= 0}


def records(path):
    d = open(path, "rb").read()
    if len(d) % REC:
        raise ValueError("player_data.bin size %d is not a multiple of 0x%x" % (len(d), REC))
    return [d[i * REC:(i + 1) * REC] for i in range(len(d) // REC)]


def _utf16(r, o, n):
    return r[o:o + n].decode("utf-16-le", errors="replace").split("\x00")[0]


def _cp932(r, o, n):
    return r[o:o + n].split(b"\x00")[0].decode("cp932", errors="replace")


def _ascii(r, o, n):
    return r[o:o + n].split(b"\x00")[0].decode("latin-1")     # latin-1: any stray byte survives


def birth_iso(s):
    """'1987/6/24' -> '1987-06-24'; anything else -> ''."""
    p = s.split("/")
    if len(p) == 3 and all(x.isdigit() for x in p):
        return "%04d-%02d-%02d" % (int(p[0]), int(p[1]), int(p[2]))
    return ""


def parse(r):
    """One 0x328-byte record -> its fields, raw."""
    card_no, set_no, u04, u06, u08 = struct.unpack_from("<5H", r, 0)
    return {
        "card_no": card_no, "set_no": set_no, "u16_04": u04, "u16_06": u06, "u16_08": u08,
        "edition": r[0x0A], "rarity": r[0x0B],
        "name_full_latin": _utf16(r, 0x0C, 0x40), "name_full_kana": _cp932(r, 0x4C, 0x40),
        "name_short_kana": _cp932(r, 0x8C, 0x40), "name_short_latin": _utf16(r, 0xCC, 0x40),
        "club_id": r[0x10C], "shirt_numbers": list(r[0x10D:0x111]), "position": r[0x111],
        "birth_date_raw": _ascii(r, 0x112, 0x10), "height_cm": r[0x122], "weight_kg": r[0x123],
        "nationality_id": r[0x124], "bytes_125_12e": list(r[0x125:0x12F]), "stats": list(r[0x12F:0x135]),
        "stats_total": r[0x135], "byte_136": r[0x136], "name_display_ascii": _ascii(r, 0x137, 0x40),
        "name_full_kana_2": _cp932(r, 0x177, 0x40), "skill_en": _ascii(r, 0x1B7, 0x40),
        "skill_jp": _cp932(r, 0x1F7, 0x40), "hidden_params": list(r[0x237:0x29A]), "model_key": _ascii(r, 0x29A, 0x40),
        "image_name": _ascii(r, 0x2DA, 0x40), "byte_31a": r[0x31A], "byte_31b": r[0x31B],
        "bytes_31c_326": r[0x31C:0x327].hex(),
    }


def xaf_toc(path):
    """The archive's table of contents: [{path, name, is_file, size, stored, offset}], without reading the data."""
    with open(path, "rb") as f:
        hdr = f.read(0x100)
        if hdr[:4] != b"xaf0":
            raise ValueError("%s is not an xaf0 archive" % path)
        version, sector, n = struct.unpack_from("<3I", hdr, 4)
        raw = f.read(n * XAF_ENTRY)
    ents = []
    for i in range(n):
        e = raw[i * XAF_ENTRY:(i + 1) * XAF_ENTRY]
        size, stored = struct.unpack_from("<II", e, 0x94)
        ents.append(dict(i=i, name=e[:0x80].split(b"\0")[0].decode("latin-1"), is_file=e[0x80],
                         parent=struct.unpack_from("<i", e, 0x84)[0], size=size, stored=stored,
                         offset=struct.unpack_from("<I", e, 0xA0)[0] * sector))
    for e in ents:                           # full path by walking parents
        parts, p = [e["name"]], e["parent"]
        while p >= 0:
            parts.append(ents[p]["name"])
            p = ents[p]["parent"]
        e["path"] = "/".join(reversed(parts))
    return ents


def build_rows(files, check):
    """Every card's catalogue row, in card-number order; the checks go to check()."""
    table, recs = card_table(files["exe"]), records(files["players"])
    check("record count %d" % RECORDS, len(recs) == RECORDS, "%d records" % len(recs))
    check("the exe's table maps one card number to each record", sorted(table.values()) == list(range(len(recs))),
          "%d card numbers" % len(table))
    ents = xaf_toc(files["xaf"])
    images = {e["name"].lower(): e for e in ents if e["is_file"] and e["path"].startswith("data/player_card/")}
    faces = {e["name"].lower() for e in ents if e["is_file"] and e["path"].startswith("data/models/face/")}
    rows, by_club, by_nat = [], collections.defaultdict(list), collections.defaultdict(list)
    mism = exact_case = face_ok = beyond = 0
    for card_no, idx in sorted(table.items()):
        if idx >= len(recs):
            beyond += 1
            continue
        f = parse(recs[idx])
        mism += f["card_no"] != card_no
        rname, rframe = RARITY.get(f["rarity"], ("", ""))
        elabel, season, _ = CI.EDITION.get(f["edition"], ("", "", ""))
        club_name, _ = CI.name_for(CI.CLUB, f["club_id"])
        nat_name, _ = CI.name_for(CI.NATIONALITY, f["nationality_id"])
        if f["edition"] == 13:               # placeholders carry codes 0 / 5 by default, not a real club
            club_name, nat_name = "", ""
        img = images.get((f["image_name"] + ".dds").lower())
        exact_case += bool(img) and img["name"] == f["image_name"] + ".dds"
        face_ok += (f["model_key"] + ".svo").lower() in faces
        row = {k: f[k] for k in ("card_no", "set_no", "edition", "rarity", "name_full_latin", "name_short_latin",
                                 "name_display_ascii", "name_full_kana", "name_short_kana", "club_id",
                                 "nationality_id", "shirt_numbers", "height_cm", "weight_kg", "stats_total",
                                 "skill_en", "skill_jp", "hidden_params", "model_key", "u16_04", "u16_06", "u16_08",
                                 "bytes_125_12e", "byte_136", "byte_31a", "byte_31b", "bytes_31c_326")}
        row.update({
            "record_index": idx, "edition_label": elabel, "season": season, "rarity_name": rname,
            "rarity_frame": rframe, "is_placeholder": f["edition"] == 13, "position": f["position"],
            "position_name": POSITIONS.get(f["position"], ""), "club_name": club_name, "nationality_name": nat_name,
            "birth_date": birth_iso(f["birth_date_raw"]), "image_archive_path": "data/player_card/%s.dds" % f["image_name"],
            "image_xaf_offset": img["offset"] if img else None, "image_xaf_stored_size": img["stored"] if img else None,
            "image_size": img["size"] if img else None, "image_packed": (img["stored"] != img["size"]) if img else None,
            "alt_png_2005_06_build": None, "stats": f["stats"],
        })
        row.update({"stat_" + s: v for s, v in zip(STAT_NAMES, f["stats"])})
        rows.append(row)
        if not row["is_placeholder"]:
            by_club[f["club_id"]].append(row)
            by_nat[f["nationality_id"]].append(row)
    real = [r for r in rows if not r["is_placeholder"]]
    check("every card number in the exe's table has its record", beyond == 0, "%d point past the file's end" % beyond)
    check("the number at the start of each record is its card number", mism == 0, "%d differ" % mism)
    check("every card's picture is in the archive", all(r["image_xaf_offset"] is not None for r in rows))
    check("picture names match the archive's case", exact_case == len(rows), "%d/%d" % (exact_case, len(rows)))
    # card 443 (GARGO) stores 77 while its six sum to 78 - the same in the 2005-06 game, so it is Sega's data
    off_sum = sorted(r["card_no"] for r in rows if sum(r["stats"]) != r["stats_total"])
    check("total = the six stats added up (except Sega's card 443)", off_sum in ([], [443]), str(off_sum))
    check("every card's face model is in the archive", face_ok == len(rows), "%d/%d" % (face_ok, len(rows)))
    check("every position is GK, DF, MF or FW", all(r["position"] in POSITIONS for r in rows))
    check("every rarity is 1..5", all(r["rarity"] in RARITY for r in rows))
    check("every edition has a label", all(r["edition_label"] for r in rows))
    check("every stat is 1..20", all(1 <= v <= 20 for r in rows for v in r["stats"]))
    check("every real card's birth date reads", all(r["birth_date"] for r in real),
          "%d do not" % sum(1 for r in real if not r["birth_date"]))
    check("card numbers are unique", len({r["card_no"] for r in rows}) == len(rows))
    check("every club code has a name entry", all(c in CI.CLUB for c in by_club), "")
    check("every nationality code has a name entry", all(c in CI.NATIONALITY for c in by_nat), "")
    return rows, {e["path"]: e for e in ents if e["is_file"] and e["path"].startswith("data/player_card/")}


def cell(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    if v is None:
        return ""
    return str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write_catalogue(rows, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(COLS) + "\n")
        for r in rows:
            fh.write("\t".join(cell(r.get(c)) for c in COLS) + "\n")
    os.replace(tmp, path)                     # whole or not at all: the overlay never reads half a catalogue


def write_pictures(rows, toc, xaf, folder):
    """cards\\<card_no>.png for every row -> (written, [failures])"""
    done, fails, cache = 0, [], {}
    with open(xaf, "rb") as f:
        for n, r in enumerate(rows, 1):
            path = r["image_archive_path"]
            try:
                if path not in cache:
                    e = toc[path]
                    f.seek(e["offset"])
                    raw = f.read(e["stored"])
                    dds = ys_lzw.decompress(raw, e["size"]) if e["stored"] < e["size"] else raw
                    if len(dds) != e["size"] or dds[:4] != b"DDS ":
                        raise ValueError("decoded %d bytes, magic %r" % (len(dds), dds[:4]))
                    cache[path] = dds
                im = Image.open(io.BytesIO(cache[path]))
                im.load()
                out = os.path.join(folder, "%d.png" % r["card_no"])
                im.save(out + ".tmp", "PNG")
                os.replace(out + ".tmp", out)
                done += 1
            except Exception as ex:                 # one bad picture must not stop the rest
                fails.append("card %d (%s): %r" % (r["card_no"], path, ex))
            if n % 500 == 0:
                print("  pictures %d / %d" % (n, len(rows)), flush=True)
    return done, fails


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if len(argv) != 2:
        print(__doc__)
        return 2
    game, out = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    files = game_files(game)
    if not files:
        print("GAME must be the folder that holds client_Release.exe (the sbwg download's \"extracted\" folder)")
        return 2
    cards_dir = os.path.join(out, "cards")
    if os.path.islink(cards_dir) or (hasattr(os.path, "isjunction") and os.path.isjunction(cards_dir)):
        print("refused: %s is a link to another folder - writing would change that folder" % cards_dir)
        return 2
    try:
        os.makedirs(cards_dir, exist_ok=True)
    except OSError as ex:
        print("cannot make %s: %s" % (cards_dir, ex))
        return 2
    print("game files: %s" % os.path.dirname(files["exe"]))

    checks = []
    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
    try:
        rows, toc = build_rows(files, check)
    except (ValueError, struct.error, OSError) as ex:
        print("FAIL  reading the game's files: %s" % ex)
        return 1
    for name, ok, detail in checks:
        print("  %s  %s%s" % ("PASS" if ok else "FAIL", name, ("  - " + detail) if detail and not ok else ""))
    if not all(ok for _, ok, _ in checks):
        print("not written: this copy does not match WCCF 2010-11 Rev D's player data")
        return 1

    write_catalogue(rows, os.path.join(out, "catalogue.tsv"))
    print("catalogue.tsv: %d cards (%d real, %d placeholders)" % (
        len(rows), sum(1 for r in rows if not r["is_placeholder"]), sum(1 for r in rows if r["is_placeholder"])))
    done, fails = write_pictures(rows, toc, files["xaf"], cards_dir)
    print("pictures: %d of %d written" % (done, len(rows)))
    for msg in fails[:20]:
        print("  FAIL  " + msg)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
