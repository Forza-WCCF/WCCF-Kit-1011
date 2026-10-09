# -*- coding: utf-8 -*-
r"""club_view.py - the club card as the game reads it, written out for the CLUB CARD panel in seat 1's window.
wccfpanel.dll cannot run Python, so _kit_helper.py writes this view whenever the card file changes.

The card is read by decode_club_card.py: the research decoder, shipped UNCHANGED beside this file, built from the
exe's own field tables (docs\research\CLUB-CARD-2010-11.md) - the same reader the website and server will use, so a
club never reads two ways.  Read-only: the card file is opened, read in one go and closed; nothing here writes it.

    python club_view.py          write data\club_view.txt now, and print it

The view (data\club_view.txt) is ASCII lines for the overlay's ASCII font:
  state|ok  /  state|none|why  /  state|new|why  /  state|unreadable|why
  head|TITLE                               a section
  row|LABEL|VALUE|COLOUR                   w white, g green, y yellow, r red, o orange, d dim
  squad|NUMBER|NAME|POSITION|APPS|GOALS|ASSISTS|CONDITION|INJURY
  session|open / closed / cut / new / none / unreadable      the slot's card session (kit_common.card_session)
  backup|WHEN
  wallet|FILE|CLUB|SUMMARY[|transferred]   your other cards (club_wallet.py), with every state; "transferred": a
                                           used-up card the game will not play again (no PLAY THIS CLUB for it)
Field meanings checked against the game's own CLUB TEAM DATA screen for the test club (2026-10-06): contract left
(91), salary and prize money in $100 units ($207,500, $3,597,000), record (W7 D2 L0), birthday, and the squad in the
game's order (by position, then card order).  The manager level and the fan count are left out: not yet tied to
the screen.
"""
import csv
import os
import sys
import time
import unicodedata

import kit_common as K
import decode_club_card as D
from english import fold                 # accents dropped as the English kit drops them in the game's own names

CARD = os.path.join(K.SAVE, "seat1_club.bin")
BACKUPS = os.path.join(K.SAVE, "backup")
VIEW = os.path.join(K.DATA, "club_view.txt")
RUNNING = os.path.join(K.DATA, "running.json")
CATALOGUE = os.path.join(K.OVERLAY, "catalogue.tsv")
POS_ORDER = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}

# katakana -> romaji (Hepburn), for names typed in kana (the overlay's font is ASCII); hiragana is turned into
# katakana first.  Small ya/yu/yo and small vowels join the syllable before them; a small tsu doubles the next
# consonant; the long mark repeats the vowel before it.
_KANA = dict(zip(
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴ",
    "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho ma mi mu me mo ya yu yo "
    "ra ri ru re ro wa wo n ga gi gu ge go za ji zu ze zo da ji zu de do ba bi bu be bo pa pi pu pe po vu".split()))
_SMALL = {"ャ": "ya", "ュ": "yu", "ョ": "yo", "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o"}


def _romaji(s):
    out, double = [], False
    for ch in s:
        if "ぁ" <= ch <= "ゖ":
            ch = chr(ord(ch) + 0x60)                                    # hiragana -> katakana
        if ch == "ッ":
            double = True
            continue
        if ch in _SMALL and out and out[-1][-1:] in "aiueo" and out[-1].isalpha():
            prev, small = out.pop(), _SMALL[ch]
            if small in ("ya", "yu", "yo"):                             # kya, sha, cha, ja ...
                stem = prev[:-1]
                out.append((stem if stem in ("sh", "ch", "j") else stem + "y") + small[-1])
            else:                                                       # fa, ti, she ... (a small vowel)
                out.append(prev[:-1] + small)
            continue
        if ch == "ー":
            out.append(out[-1][-1] if out and out[-1][-1:] in "aiueo" else "-")
            continue
        r = _KANA.get(ch)
        if r is None:
            out.append(ch)
            double = False
            continue
        if double and r[0] not in "aiueon":
            r = r[0] + r
        double = False
        out.append(r)
    return "".join(out)


def ascii_name(s):
    """a name as the panel can draw it: full-width letters made plain, kana in romaji (capitals), accents dropped
    as the English kit drops them (english.fold: VITOR BAIA, KAKA, PELE), anything else ?"""
    s = unicodedata.normalize("NFKC", s or "")                          # ＡＢＣ -> ABC, ｱｲﾝ -> アイン
    if any("ぁ" <= c <= "ヿ" for c in s):
        s = _romaji(s).upper()
    return fold(s).replace("|", "?").strip()


def money(v):
    """a stored money value ($100 units, as the game shows salary and prize money) in dollars"""
    return "${:,}".format(v * 100)


def ordinal(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def load_names(path):
    """{card number: (name, position)}: the catalogue's short Latin name - 14 of the test club's 16 exactly as the
    game shows them (2026-10-06); the game also puts an initial on a few surnames other footballers share (I.CORDOBA,
    M.DIARRA), which no catalogue column holds, so those two show as CORDOBA and DIARRA"""
    out = {}
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                try:
                    no = int(row["card_no"])
                except (KeyError, ValueError, TypeError):
                    continue
                name = row.get("name_short_latin") or row.get("name_display_ascii") or ""
                out[no] = (ascii_name(name), (row.get("position_name") or "").strip())
    except OSError:
        pass
    return out


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def build(card=CARD, catalogue=CATALOGUE, backups=BACKUPS, running=RUNNING, cards=None):
    """the view's lines for this card file and your other cards (never raises for a bad card: it says what is
    wrong).  The other cards and the session line come with every state - an empty or broken slot must still let
    the player switch to another card (never locked out)"""
    import club_wallet as W                              # here: club_wallet uses this module's names
    lines = []
    found = sorted((f for f in os.listdir(backups) if f.endswith(".bak")), reverse=True) \
        if os.path.isdir(backups) else []
    back = [stamp(os.path.getmtime(os.path.join(backups, f))) for f in found[:6]]
    try:
        since = os.path.getmtime(running)
    except OSError:
        since = None
    session, bad = K.card_session(card, since)
    folder = cards or os.path.join(os.path.dirname(card), "cards")
    tail = ["session|%s" % session] + ["backup|" + b for b in back] + \
           ["wallet|%s|%s|%s%s" % (f, name or "-", summary, "|transferred" if W.used_up(os.path.join(folder, f)) else "")
            for f, name, summary in W.wallet(folder)]
    if session == "none":
        return ["state|none|no club card in the slot yet - put one in with the CARD key"] + tail
    try:
        header, blocks = D.read_card(card)
    except D.CardError as ex:
        return ["state|unreadable|%s" % ascii_name(str(ex))] + tail
    if header and header["counter"] == 0xFFFF:
        return ["state|new|a new card - no club made yet (put it in and press START)"] + tail
    a, b, chosen, verdict = D.game_choice(header, blocks)
    if chosen is None:
        return ["state|unreadable|the game would refuse this card: %s" % ascii_name(verdict)] + tail
    d = D.decode(D.copy_of(blocks, chosen))

    def one(g, n):
        return d[(g, 0, n)][0]
    lg = D.league(d)
    lines.append("state|ok")
    lines.append("head|CLUB")
    lines.append("row|CLUB|%s  (founded %s)|w" % (ascii_name(D.text(d[("Club", 0, "CLUB_NAME")])) or "-",
                                                 D.ymd8(one("Club", "CLUB_FOUNDATION"))))
    lines.append("row|MANAGER|%s  (born %s)|w" % (ascii_name(D.text(d[("Coach", 0, "COACH_NAME")])) or "-",
                                                 D.ymd8(one("Coach", "COACH_BIRTHDAY"))))
    c = W.counter(card)                                  # 0 is a real counter (used up): not "or" - it would drop it
    left, low = one("Coach", "COACH_LAST_TERM"), (0xFFFF if c is None else c) & 0xFF
    if low == 0:                                         # used up: its manager moved to a new card (Sega's transfer)
        lines.append("row|CONTRACT|transferred - the game will not play this card again|r")
    elif low == 1 or left == 0:                          # last use: the next insert offers the transfer to a new card
        lines.append("row|CONTRACT|ended - put the card in: the game moves your manager to a new card|o")
    else:
        lines.append("row|CONTRACT|%d matches left|%s" % (left, "y" if left <= 10 else "w"))
    lines.append("row|SALARY|%s a year|w" % money(one("Coach", "COACH_SALARY")))
    lines.append("row|LEAGUE|Div %d, leg %d: %s - W%d D%d L%d, %d-%d, %d pts|w" % (
        lg["division"], lg["leg"], ordinal(lg["position_computed"]), lg["win"], lg["draw"], lg["lose"],
        lg["goals_for"], lg["goals_against"], lg["points"]))
    lines.append("row|ALL MATCHES|W%d D%d L%d - best win streak %d|w" % (
        one("Club", "CLUB_RECORD_WIN"), one("Club", "CLUB_RECORD_DRAW"), one("Club", "CLUB_RECORD_LOSE"),
        one("Club", "CLUB_RECORD_MAX_SERIES_WIN")))
    lines.append("row|PRIZE MONEY|%s|w" % money(one("Club", "CLUB_GET_PRIZE")))
    lines.append("row|TRADE RIGHTS|%d  (%d left)|w" % (one("SystemInfo", "CLUB_TRADE_RIGHT_NUM"),
                                                      one("SystemInfo", "CLUB_TRADE_REMAINDER_NUM")))
    lines.append("row|LAST PLAYED|%s|w" % D.ymd6(one("SystemInfo", "SYSTEM_LAST_PLAY_DAY")))
    lines.append("head|CARD HEALTH")
    lines.append("row|SESSION|%s" % {"open": "OPEN - a match is on: do not stop the game|o",
                                      "cut": "the last session did not end normally|y",
                                      "closed": "closed - safe to stop|g"}.get(session, session + "|w"))
    lines.append("row|BAD ENDINGS|%s" % ("0|g" if not bad else "1 - at 2, trade rights are lost|y" if bad == 1
                                         else "%d - trade rights lost; 5th costs money|r" % bad))
    if a["good"] and b["good"] and D.copy_of(blocks, "A") == D.copy_of(blocks, "B"):
        lines.append("row|SAVED COPIES|both good, the same|g")
    elif chosen == "A":
        lines.append("row|SAVED COPIES|copy A good, copy B %s|y" % ("bad" if not b["good"] else "different"))
    else:
        lines.append("row|SAVED COPIES|copy A bad - the game reads copy B|y")
    lines.append("row|CARD SAVED|%s|w" % stamp(os.path.getmtime(card)))
    lines.append("row|BACKUPS|%s|%s" % (("%d kept, newest %s" % (len(found), back[0])) if found else
                                        "none yet - made when a session starts", "w" if found else "d"))
    names = load_names(catalogue)
    squad = []
    for i in range(16):
        def p(n):
            return d[("Player", i, n)][0]
        no = p("PLAYER_CARD_NO")
        if not no:
            continue
        name, pos = names.get(no, ("card %d" % no, "?"))
        # injured when PLAYER_INJURY_PART is set: the game agrees (Ferdinand on the player's card, checked by him in the game,
        # 2026-10-06); what the part, degree and healing numbers mean is not checked yet
        injury = "injured" if p("PLAYER_INJURY_PART") else "-"
        squad.append((POS_ORDER.get(pos, 4), i, "squad|%d|%s|%s|%d|%d|%d|%d|%s" % (
            p("PLAYER_BACK_NUMBER"), name or "card %d" % no, pos or "?", p("PLAYER_PARTICIPATE_NUM"),
            p("PLAYER_OFFICIAL_GOAL"), p("PLAYER_OFFICIAL_ASSIST"), p("PLAYER_CONDITION"), injury)))
    lines += [s for _o, _i, s in sorted(squad)]                         # GK, DF, MF, FW, then card order: the game's
    return lines + tail


def write(lines, path=VIEW):
    """the view whole: a temporary file, then one swap (the panel never reads half of it)"""
    text = ("# WCCF 2010-11 kit - the club card as the game reads it, for the CLUB CARD panel in seat 1. Written by\n"
            "# _kit_helper.py with decode_club_card.py whenever the card changes. Read-only, never edit.\n" +
            "\n".join(lines) + "\n")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="ascii", errors="replace", newline="\n") as f:
        f.write(text)
    for attempt in range(25):           # a scanner or indexer may hold a fresh file a moment: up to 0.5 s, as the
        try:                            # card reader does for the card
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 24:
                raise
            time.sleep(0.02)


def main(argv):
    lines = build()
    write(lines)
    print("\n".join(lines))
    print("written %s" % VIEW)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
