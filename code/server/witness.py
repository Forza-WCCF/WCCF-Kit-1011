# -*- coding: utf-8 -*-
r"""witness.py - a finished match earns a card (2026-10-14, kit 7, phase 3).

On a server with a wccf.online secret (data\server_name.txt and data\server_secret.txt - play.py starts this only
then), the hook in control (source\hook\wccfk.c) keeps the club data each cabinet sends at a session's start (ENTRY
SVR), at each match's start (TEAM DATA - a match played on from the locker room sends only this) and after a match
(TEAM DATA RSLT: the locker room, a finished match) as files in data\witness\, named with the cabinet's address. This tells wccf.online whose they were - the seat desk's data\leases.json gives the signed-in account at that
address - with the server's secret, never a player's token. The website keeps what it saw and gives a finished match's
account one card. Each file then goes to data\witness\done\ (what the server saw, kept), and one line says what
happened. An address with no signed-in seat: nothing is sent, and it says why. Two signed-in seats at one address (one
house, two players - 2026-10-15): the club card's id in the message (SYSTEM_CARD_ID) names the seat whose lease has
that card (kit 7's seat.py says it to the desk); if none or both do, nothing is sent, and it says why.
A seat freed a moment ago still counts for RECENT seconds (a player who quits right after the locker room).
    python code\server\witness.py SECONDS LOGFILE
"""
import base64
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # code\, when run on its own
from online import account  # noqa: E402  (its post(): the website, WCCF_WEBSITE)

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(KIT, "data")
NAME = re.compile(r"^\d{8}-\d{6}-\d+-(entry|team|rslt)-([0-9.]+)_\d+\.bin$")      # the hook's file names
RECENT = 120                    # seconds a freed seat's account still counts
RETRY = 30                      # seconds before a file is tried again when the website could not be reached
CARD_ID = (263, 32)             # SystemInfo.SYSTEM_CARD_ID in a club's data: its first bit, its width (the website's
                                # WCCFGAME_CARD_ID; = the card's serial)
log_file = None


def msg_card(kind, body):
    """the club card's id in a kept message, or None - its club data where the website reads it (wccfgame_msg_data):
    TEAM DATA RSLT +0 the size (u32), +4 the data; ENTRY SVR and TEAM DATA +0x38 the size (u16), +0x3a the data"""
    if kind == "rslt":
        data = body[4:4 + int.from_bytes(body[0:4], "little")] if len(body) >= 4 else b""
    else:
        data = body[0x3a:0x3a + int.from_bytes(body[0x38:0x3a], "little")] if len(body) >= 0x3a else b""
    start, width = CARD_ID
    if len(data) * 8 < start + width:
        return None
    v = 0
    for i in range(start, start + width):           # the bits in the website's order (wccfgame_bits)
        v = (v << 1) | ((data[i >> 3] >> (7 - (i & 7))) & 1)
    return v


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def server_id(data):
    """(name, secret) of this server on wccf.online, or None - the secret is never said"""
    try:
        with open(os.path.join(data, "server_name.txt"), encoding="ascii") as f:
            name = f.read().strip()
        with open(os.path.join(data, "server_secret.txt"), encoding="ascii") as f:
            secret = f.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return (name, secret) if name and len(secret) >= 32 else None


class Seats:
    """who sits where, from the seat desk's data\\leases.json, remembering each signed-in seat RECENT seconds after it
    is freed"""

    def __init__(self, path):
        self.path, self.seen = path, {}         # (seat, ip, uid) -> (last seen, username, club card id or None)

    def look(self, now):
        try:
            with open(self.path, encoding="utf-8") as f:
                leases = json.load(f)
        except (OSError, ValueError):
            leases = {}
        for seat, lease in (leases.items() if isinstance(leases, dict) else []):
            if isinstance(lease, dict) and isinstance(lease.get("uid"), int) and lease.get("ip"):
                card = lease.get("card") if isinstance(lease.get("card"), int) else None
                self.seen[(seat, lease["ip"], lease["uid"])] = (now, lease.get("username") or "?", card)
        self.seen = {k: v for k, v in self.seen.items() if now - v[0] <= RECENT}

    def at(self, ip, card=None):
        """("ok", {"seat", "uid", "username"}) or ("none", why); card = the club card's id in the message, which tells
        two signed-in players at one address apart"""
        found = {(seat, uid): (name, c) for (seat, a, uid), (_t, name, c) in self.seen.items() if a == ip}
        uids = {uid for _seat, uid in found}
        if not uids:
            return "none", "no signed-in seat at %s" % ip
        if len(uids) > 1:                                           # one house, two players: whose club card is it?
            found = {k: v for k, v in found.items() if card is not None and v[1] == card}
            if len({uid for _seat, uid in found}) != 1:
                return "none", "%d signed-in accounts at %s (one house), and the message's club card (%s) is not one " \
                               "seat's - whose it was cannot be told" % (len(uids), ip, card)
        (seat, uid), (name, _c) = next(iter(found.items()))
        return "ok", {"seat": seat, "uid": uid, "username": name}


def handle(path, ident, seats):
    """one kept file -> (done, what to say); not done = the website could not be reached, try again later"""
    m = NAME.match(os.path.basename(path))
    if not m:
        return True, "%s: not a name the hook gives - set aside" % os.path.basename(path)
    kind, ip = m.group(1), m.group(2)
    what = {"entry": "before a match", "team": "a match starting", "rslt": "a finished match"}[kind]
    try:
        with open(path, "rb") as f:
            body = f.read()
    except OSError as ex:
        return False, "%s from %s: could not be read (%s)" % (what, ip, ex)
    state, who = seats.at(ip, msg_card(kind, body))
    if state != "ok":
        return True, "%s from %s: %s - nothing sent" % (what, ip, who)
    status, got = account.post("wccf_witness", {"server": ident[0], "secret": ident[1], "uid": who["uid"], "kind": kind,
                                                "body": base64.b64encode(body).decode("ascii")})
    head = "seat %s (%s, uid %s): %s" % (who["seat"], who["username"], who["uid"], what)
    if status == 200:
        return True, "%s - %s" % (head, ("card %d" % got["card_no"]) if got.get("card_no") else
                                  "kept, no card (%s)" % got.get("why", "?"))
    if status in (403, 404, 422):
        return True, "%s - refused by wccf.online (%s)" % (head, got.get("error") or "HTTP %s" % status)
    return False, "%s - wccf.online could not be reached (%s); tried again in %d s" % (
        head, got.get("error") or "HTTP %s" % status, RETRY)


def tick(folder, ident, seats, retry, now):
    """every kept file once: sent, then moved to done\\ - or left for a later try"""
    seats.look(now)
    try:
        files = sorted(f for f in os.listdir(folder) if f.endswith(".bin"))
    except OSError:
        return
    for f in files:
        path = os.path.join(folder, f)
        if retry.get(path, 0) > now:
            continue
        done, line = handle(path, ident, seats)
        log(line)
        if done:
            retry.pop(path, None)
            os.makedirs(os.path.join(folder, "done"), exist_ok=True)
            try:
                os.replace(path, os.path.join(folder, "done", f))
            except OSError as ex:
                log("%s could not go to done\\ (%s)" % (f, ex))
                retry[path] = now + 3600
        else:
            retry[path] = now + RETRY


def main(argv):
    global log_file
    life = float(argv[0]) if argv else 12 * 3600
    log_file = argv[1] if len(argv) > 1 else None
    folder = os.environ.get("WCCF_WITNESS_DIR") or os.path.join(DATA, "witness")
    ident = server_id(DATA)
    if not ident:
        log("witness: no server secret in data\\server_name.txt + server_secret.txt - finished matches earn no "
            "cards here")
        return 2
    os.makedirs(folder, exist_ok=True)
    log("witness: %s is this server on wccf.online; the club data before and after each match from %s" % (
        ident[0], folder))
    seats, retry = Seats(os.environ.get("WCCF_LEASES_FILE") or os.path.join(DATA, "leases.json")), {}
    end = time.time() + life
    while time.time() < end:
        tick(folder, ident, seats, retry, time.time())
        time.sleep(1.0)
    log("witness: its time is up - stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
