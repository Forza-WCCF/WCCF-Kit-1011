# -*- coding: utf-8 -*-
r"""seat.py - this PC's seat on a server (2026-10-06): asks the server's seat desk (server\seat_desk.py, TCP 20030) for a seat,
writes the answer for play.py, then HOLDS the seat by pinging every 20 s for as long as the run lasts. If the
connection breaks (a network blip, or the desk restarting), it RECONNECTS and re-claims the SAME seat (A5,
2026-10-11) - before, one missed reply ended the lease for good and the desk then freed the seat under the running
game. The end of the run ends the lease and the seat is free again at once.

    python code\online\seat.py ADDRESS OUT_FILE LIFE_SECONDS [SEAT]

OUT_FILE gets {"seat": n, "projector": 1|0, "relay": port|0}, or {"error": "no broker" | "no answer" | "full" | "taken" | "signin" |
"refused", "detail": "..."} - written ONCE, from the first claim, for play.py. "no broker" = nothing answered on the
port (a server without the desk - play.py then plays as before); "no answer" = the desk was reached but did not
reply in time (play.py stops rather than risk two PCs on one seat); "signin" = the desk wants a wccf.online sign-in,
or refused this PC's (play.py then plays on this PC and says why).

THE SIGN-IN (2026-10-14): when this PC is signed in (online\account.py, data\account.json) every WANT line ends with
"TOKEN <the token>" - the first claim and every reclaim. The token is read from the file here, so it never travels on
a command line, and it is never written to a log.

THE CLUB CARD (2026-10-15): online, play.py gives the account's club card (WCCF_CLUB_CARD); its id goes before the
token, "CARD <id>", so the server can tell two signed-in players behind one address (one house) apart.  A desk from
before that answers "ERR say ...": the same claim again without the card, the sign-in kept (then, for a desk from
before sign-ins, without the token too).

THE PROJECTOR RELAY (2026-10-17): every claim says "RELAY" after the seat - this PC can show the projector through the
server's projector relay - and the desk answers "SEAT n PROJECTOR 20031", the relay's port ("relay" in OUT_FILE;
"projector" 1 stays kit 5's desk: this PC is the projector, straight to control).  A desk from before that answers
"ERR say ...": the same claim again without the word, then as above.

DREAM TEAM (2026-10-15, play.py WCCF_DREAM_TEAM=1): no TOKEN, even on a signed-in PC - a DREAM TEAM match earns no
card and saves nothing to wccf.online.
"""
import json
import os
import re
import socket
import sys
import time

PORT = int(os.environ.get("WCCF_BROKER_PORT", "20030"))
PING = float(os.environ.get("WCCF_LEASE_PING", "20"))          # seconds between pings (the desk waits 75)
RETRY = float(os.environ.get("WCCF_LEASE_RETRY", "3"))         # seconds between reclaim tries after a break
ACCOUNT = os.environ.get("WCCF_ACCOUNT_FILE") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "account.json")


def signed():
    """b" TOKEN <token>" when this PC is signed in (online\\account.py), else b"" - a token that is not plain hex is
    not sent, and DREAM TEAM (WCCF_DREAM_TEAM=1) sends none"""
    if os.environ.get("WCCF_DREAM_TEAM") == "1":
        return b""
    try:            # this server's bank's sign-in file (account.use sets it) - never another bank's token
        with open(os.environ.get("WCCF_ACCOUNT_FILE") or ACCOUNT, encoding="utf-8") as f:
            token = json.load(f).get("token", "")
    except (OSError, ValueError, AttributeError):
        return b""
    if not (isinstance(token, str) and 0 < len(token) <= 128 and all(c in "0123456789abcdef" for c in token)):
        return b""
    return b" TOKEN " + token.encode("ascii")


def card_word():
    """b" CARD <id>" - the club card this PC plays online (WCCF_CLUB_CARD): its serial (block 6, bytes 12-15, big-endian),
    which the game writes into the club's data as SYSTEM_CARD_ID - else b"" (offline, or not a card file)"""
    try:
        with open(os.environ.get("WCCF_CLUB_CARD") or "", "rb") as f:
            raw = f.read(4113)
    except OSError:
        return b""
    serial = int.from_bytes(raw[124:128], "big") if len(raw) == 4112 else 0
    return b" CARD %d" % serial if serial >= 10000000 else b""


def log(msg):
    print("%s  %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def write(path, data):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)


def send_want(conn, want):
    """send one WANT line and read the desk's reply, split into tokens. Raises OSError if it does not reply in time."""
    conn.settimeout(10)
    conn.sendall(want)
    buf = b""
    while b"\n" not in buf:
        data = conn.recv(256)
        if not data:
            raise OSError("the broker closed the connection")
        buf += data
    return buf.split(b"\n", 1)[0].decode("ascii", "replace").split()


def hold(conn, end):
    """ping the desk every PING s until the connection breaks or `end` is reached; returns on either. Never raises."""
    try:
        while time.time() < end:
            time.sleep(PING)
            conn.sendall(b"PING\n")
            conn.settimeout(15)
            if b"PONG" not in conn.recv(64):
                return
    except OSError:
        return


def bank(ip):
    """where the server at ip has its players sign in (its seat desk's answer to BANK, 2026-10-23): its own card bank
    (server\\card_bank.py) on its port at ip, or a website's address -> that address; None from a desk from before it,
    or none at all (wccf.online, as before)"""
    try:
        with socket.create_connection((ip, PORT), timeout=6) as c:
            words = send_want(c, b"BANK\n")
    except OSError:
        return None
    if len(words) == 3 and words[:2] == ["BANK", "PORT"] and words[2].isdigit() and 0 < int(words[2]) < 65536:
        return "http://%s:%d" % (ip, int(words[2]))
    if len(words) == 2 and words[0] == "BANK" and re.match(r"^https?://[A-Za-z0-9.:/-]+$", words[1]):
        return words[1].rstrip("/")
    return None


def main(argv):
    ip, out, life = argv[0], argv[1], float(argv[2])
    asked = int(argv[3]) if len(argv) > 3 else None
    sign, card, relay = signed(), card_word(), b" RELAY"

    def want(seat):
        return (b"WANT SEAT %d" % seat if seat else b"WANT") + relay + card + sign + b"\n"
    end = time.time() + life

    # the first claim - the only write to OUT_FILE (play.py reads it to set up the game)
    try:
        conn = socket.create_connection((ip, PORT), timeout=6)
    except OSError as ex:
        write(out, {"error": "no broker", "detail": str(ex)})       # nothing listening: play.py plays as before
        return 1
    try:
        words = send_want(conn, want(asked))
        if words[:2] == ["ERR", "say"]:                             # a seat desk from before the relay word: the same
            conn.close()                                            # claim again without it
            relay = b""
            log("this server's seat desk does not know the projector relay - asking without it")
            conn = socket.create_connection((ip, PORT), timeout=6)
            words = send_want(conn, want(asked))
        if card and words[:2] == ["ERR", "say"]:                    # a seat desk from before the card word: the same
            conn.close()                                            # claim again without it, the sign-in kept
            card = b""
            log("this server's seat desk does not know the club card word - asking without it")
            conn = socket.create_connection((ip, PORT), timeout=6)
            words = send_want(conn, want(asked))
        if sign and words[:2] == ["ERR", "say"]:                    # a seat desk from before the sign-in (kit 6 and
            conn.close()                                            # older servers - hosts update when they like):
            sign = b""                                              # the same claim again, without the token
            log("this server's seat desk does not know sign-ins - asking without one")
            conn = socket.create_connection((ip, PORT), timeout=6)
            words = send_want(conn, want(asked))
    except OSError as ex:
        write(out, {"error": "no answer", "detail": str(ex)})       # reached but silent: play.py stops (A4)
        conn.close()
        return 1
    if not (len(words) == 4 and words[0] == "SEAT" and words[2] == "PROJECTOR"):
        kind = "signin" if words[:2] == ["ERR", "sign"] else \
            {"FULL": "full", "TAKEN": "taken"}.get(words[0] if words else "", "refused")
        write(out, {"error": kind, "detail": " ".join(words)})
        conn.close()
        return 1
    seat, proj = int(words[1]), int(words[3]) if words[3].isdigit() else 0
    write(out, {"seat": seat, "projector": int(proj == 1), "relay": proj if proj > 1 else 0})
    log("seat %d held (projector %s)" % (seat, words[3]))
    want_reclaim = want(seat)

    # hold the seat for the life of the run; reconnect and reclaim the SAME seat after any break (A5)
    while time.time() < end:
        hold(conn, end)                                             # returns when the connection breaks or life ends
        try:
            conn.close()
        except OSError:
            pass
        if time.time() >= end:
            break
        log("the seat desk connection broke - reclaiming seat %d" % seat)
        conn = None
        while time.time() < end and conn is None:                   # retry through a blip / a desk restart / the old
            try:                                                    # lease not yet reaped (TAKEN until the desk frees it)
                c = socket.create_connection((ip, PORT), timeout=6)
                words = send_want(c, want_reclaim)
            except OSError:
                time.sleep(RETRY)
                continue
            if len(words) == 4 and words[0] == "SEAT":
                conn = c
                log("reclaimed seat %d" % seat)
            else:
                c.close()
                time.sleep(RETRY)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
