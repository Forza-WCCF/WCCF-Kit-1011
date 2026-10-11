# -*- coding: utf-8 -*-
r"""boards.py - every club card keeps its own cards on the table (2026-10-08).

The table is what the card board shows and FPR_Emu hands the game: fpr_table0.txt, and the board's copy of it,
fpr_panel_state.json, in the game's seat folder.  A club card does not hold it - so when another card came into the
slot (a CLUB CARD switch, or the kit put on other game files) the old club's cards stayed on the table (the player,
2026-10-08: "why is there a conflict with my formation and the players in the card?").

Each card FILE keeps its table beside it, in a folder of the same name: data\save\seat1_club.board for the card in the
slot, data\save\cards\NAME.board for NAME.bin among YOUR CARDS (club_wallet.switch moves the two together).  A board
folder holds the two files and id.txt, a random id; fpr_board_owner.txt in the seat folder names the board that is
out.  Not a club's name or players: clubs share names, founding dates and the very same 16 cards (the player's own,
2026-10-08: Eindhoven United and an AAAA card, FUTBUL and Rosso).
  - at every start (play.py, after a CLUB CARD switch, before the card reader and the overlay): the table out is
    copied back to its own board, wherever its card went; then the slot card's board comes out - a card with none yet
    gets its registered players laid out where the board's "+ CARD" puts them (11 in a 4-4-2, the rest on the bench).
    A table out that belongs to no board here (the first start with this, other game files) becomes the slot card's
    when its registered players are 11 of its cards or more (all of them, for fewer), else it is kept in
    data\save\boards_unknown - never lost
  - at every stop the table out is copied back to its board, so data\save always holds the latest
  - no club in the slot (a new card the game is making a club on): the table is copied back to its board and stays
    out, owned by nobody - the club the game makes from those cards takes it at the next start
Nothing is ever deleted.  play.py catches anything this raises: the table then stays as it is.
    python boards.py            what is where (read-only)
"""
import datetime
import json
import os
import sys
import uuid

import kit_common as K

FILES = ("fpr_table0.txt", "fpr_panel_state.json")
OWNER = "fpr_board_owner.txt"
ID = "id.txt"
CARD = os.path.join(K.SAVE, "seat1_club.bin")
UNKNOWN = "boards_unknown"
MATCH = 11                     # a card's registered players among a table's cards that make an unowned table its own
# where the board's "+ CARD" puts a card (wccfpanel.c board_add_locked: x -1..+1 touchline to touchline, y -1 the far
# goal line .. +1 the own goal line); the bench boxes beside the pitch (BENCH_X, BENCH_Y)
SPOTS = [("GK", 0.0, 0.9),
         ("DF", -0.6, 0.55), ("DF", -0.2, 0.6), ("DF", 0.2, 0.6), ("DF", 0.6, 0.55),
         ("MF", -0.6, 0.1), ("MF", -0.2, 0.15), ("MF", 0.2, 0.15), ("MF", 0.6, 0.1),
         ("FW", -0.25, -0.45), ("FW", 0.25, -0.45)]
BENCH = [(1.24, -0.68), (1.24, -0.34), (1.24, 0.0), (1.24, 0.34), (1.24, 0.68)]


def board_of(card):
    """a card file's own board folder: NAME.bin -> NAME.board"""
    return os.path.splitext(card)[0] + ".board"


def board_id(folder):
    try:
        with open(os.path.join(folder, ID), encoding="ascii", errors="replace") as f:
            return f.read().strip() or None
    except OSError:
        return None


def all_boards(save):
    """{id: folder} of every card's board in data\\save (the slot's and YOUR CARDS')"""
    found = [os.path.join(save, "seat1_club.board")]
    try:
        found += [os.path.join(save, "cards", f) for f in os.listdir(os.path.join(save, "cards"))
                  if f.lower().endswith(".board")]
    except OSError:
        pass
    return {board_id(f): f for f in found if os.path.isdir(f) and board_id(f)}


def club_of(card, names=None):
    """(name, squad) of a card file - squad = its registered players [(card number, position)] in the card's order -
    or (None, why): "none" (no file), "new" (no club yet), "unreadable", "refused" (the game would not take it)"""
    import club_view as V
    D = V.D
    state, _bad = K.card_session(card)
    if state in ("none", "unreadable", "new"):
        return None, state
    try:
        header, blocks = D.read_card(card)
    except D.CardError:
        return None, "unreadable"
    if header and header["counter"] == 0xFFFF:
        return None, "new"
    _a, _b, chosen, _verdict = D.game_choice(header, blocks)
    if chosen is None:
        return None, "refused"
    d = D.decode(D.copy_of(blocks, chosen))
    names = V.load_names(V.CATALOGUE) if names is None else names
    squad = []
    for i in range(16):
        no = d[("Player", i, "PLAYER_CARD_NO")][0]
        if no:
            squad.append((no, (names.get(no, ("", ""))[1] or "?").upper()))
    return V.ascii_name(D.text(d[("Club", 0, "CLUB_NAME")])) or "the club", squad


def table(seat):
    """the cards out on the table, as FPR_Emu reads them: [(slot, card, x, y)] - "#" starts a note, commas or spaces"""
    out = []
    try:
        with open(os.path.join(seat, FILES[0]), encoding="ascii", errors="replace") as f:
            for line in f:
                parts = line.split("#", 1)[0].replace(",", " ").split()
                if len(parts) != 4:
                    continue
                try:
                    slot, no, x, y = int(parts[0]), int(parts[1]), float(parts[2]), float(parts[3])
                except ValueError:
                    continue
                if 1 <= slot <= 20 and no >= 1:
                    out.append((slot, no, x, y))
    except OSError:
        pass
    return out


def owner(seat):
    try:
        with open(os.path.join(seat, OWNER), encoding="ascii", errors="replace") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _write(path, text):
    """a file whole, in one step, with a new write time (FPR_Emu and the board read again when it changes)"""
    with open(path + ".boards", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(path + ".boards", path)


def _copy(src, dst):
    with open(src, "rb") as f:
        data = f.read()
    with open(dst + ".boards", "wb") as f:
        f.write(data)
    os.replace(dst + ".boards", dst)


def _copy_table(src, dst):
    for n in FILES:
        if os.path.exists(os.path.join(src, n)):
            _copy(os.path.join(src, n), os.path.join(dst, n))


def _free(path):
    """path, or "path (2)", "path (3)" ... - a name nothing has yet"""
    out, n = path, 2
    while os.path.exists(out):
        out, n = "%s (%d)" % (path, n), n + 1
    return out


def set_owner(seat, key):
    if key:
        _write(os.path.join(seat, OWNER), key + "\n")
    elif os.path.exists(os.path.join(seat, OWNER)):
        os.replace(os.path.join(seat, OWNER), os.path.join(seat, OWNER + ".before"))    # never deleted


def save_live(seat, save):
    """the table out copied back to the board it came from, wherever its card is now -> that folder, or None"""
    folder = all_boards(save).get(owner(seat) or "")
    if folder and os.path.exists(os.path.join(seat, FILES[0])):
        _copy_table(seat, folder)
        return folder
    return None


def make_board(folder, seat):
    """a new board for a card from the table out (a folder there without an id is kept aside first) -> its id"""
    if os.path.isdir(folder):
        os.rename(folder, _free(folder + " old"))
    os.makedirs(folder)
    _copy_table(seat, folder)
    key = uuid.uuid4().hex[:16]
    _write(os.path.join(folder, ID), key + "\n")
    return key


def put_aside(seat, save):
    """the table out kept in data\\save\\boards_unknown under the time (never over another) -> the folder"""
    folder = _free(os.path.join(save, UNKNOWN, datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")))
    os.makedirs(folder)
    _copy_table(seat, folder)
    return folder


def covers(live, squad):
    """a card's registered players are this table's cards: 11 of them or more (all of them, for a smaller table)"""
    cards = {c[1] for c in live}
    n = len(cards & {no for no, _p in squad})
    return n > 0 and n >= (MATCH if len(cards) >= MATCH else len(cards))


def layout(squad):
    """[(slot, card, x, y)] for a squad laid out as "+ CARD" would: each player on his own line's free spot (the
    card's order), the spots left over filled by the players left over, the rest on the bench; slot = card order"""
    spots = list(SPOTS)
    placed, left = [], []
    for i, (no, pos) in enumerate(squad[:16]):
        k = next((j for j, sp in enumerate(spots) if sp[0] == pos), None)
        if k is None:
            left.append((i, no))
        else:
            placed.append((i + 1, no, spots[k][1], spots[k][2]))
            del spots[k]
    order = {"DF": 0, "MF": 1, "FW": 2, "GK": 3}
    spots.sort(key=lambda sp: order.get(sp[0], 4))
    bench = list(BENCH)
    for i, no in left:
        if spots:
            sp = spots.pop(0)
            placed.append((i + 1, no, sp[1], sp[2]))
        elif bench:
            x, y = bench.pop(0)
            placed.append((i + 1, no, x, y))
    return sorted(placed)


def lay_out(seat, name, squad):
    """the squad's own lay-out written as the table out (the table file and the board's copy, which agree)"""
    cards = layout(squad)
    _write(os.path.join(seat, FILES[0]), "# laid out by the kit (boards.py) for %s - read by FPR_Emu.exe (table 0)\n" %
           name + "".join("%d %d %.3f %.3f\n" % c for c in cards))
    _write(os.path.join(seat, FILES[1]), json.dumps(
        {"placed": [{"slot": s, "no": n, "x": round(x, 3), "y": round(y, 3)} for s, n, x, y in cards], "mirror": False},
        indent=1) + "\n")
    return len(cards)


def sync(seat, card=CARD, save=None, names=None):
    """at a start, before anything reads the table: the slot card's cards out (see the top) -> what it did, said"""
    save = save or os.path.dirname(card)
    said = []
    saved = save_live(seat, save)                       # the table out goes back to its own board first
    name, squad = club_of(card, names)
    if name is None:                                    # no club in the slot: the table stays out, owned by nobody
        if owner(seat):
            set_owner(seat, None)
            said.append("no club in the slot: the cards on the table stay out%s" %
                        (" (and are kept with their card)" if saved else ""))
        return said
    folder = board_of(card)
    key = board_id(folder)
    if key and owner(seat) == key and os.path.exists(os.path.join(seat, FILES[0])):
        return said                                     # its own board is out (and was just copied back)
    live = table(seat)
    if os.path.exists(os.path.join(seat, FILES[0])) and not saved:     # a table out that belongs to no board here
        if live and not key and covers(live, squad):    # this club's players: this card's own from now on
            set_owner(seat, make_board(folder, seat))
            said.append("the cards on the table are %s's - kept with its card from now on" % name)
            return said
        aside = put_aside(seat, save)
        said.append("cards on the table that belong to no club card here kept in data\\save\\%s\\%s" %
                    (UNKNOWN, os.path.basename(aside)))
    if key:
        _copy_table(folder, seat)
        set_owner(seat, key)
        said.append("%s's own cards are on the table" % name)
    else:
        n = lay_out(seat, name, squad)
        set_owner(seat, make_board(folder, seat))
        said.append("%s had no cards kept yet: its %d registered players laid out (4-4-2, the rest on the bench)" %
                    (name, n))
    return said


def keep(seat, save=None):
    """at a stop: the table out copied back to its board -> the folder, or None"""
    return save_live(seat, save or K.SAVE)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    game = K.find_game(K.load_settings().get("game"))
    seat = K.seat_dir(game) if game else None
    if not seat:
        print("not set up yet - run SETUP.exe first")
        return 2
    name, _squad = club_of(CARD)
    boards = all_boards(K.SAVE)
    out = owner(seat)
    print("slot: %s; its board: %s" % (name or "no club", board_id(board_of(CARD)) or "none yet"))
    print("table out: %d cards, %s" % (len(table(seat)), "from %s" % os.path.relpath(boards[out], K.SAVE)
                                       if out in boards else "owned by %s" % (out or "nobody")))
    for k, f in sorted(boards.items(), key=lambda kv: kv[1]):
        print("  board %s  %s" % (k, os.path.relpath(f, K.SAVE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
