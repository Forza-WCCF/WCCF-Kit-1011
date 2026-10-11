# -*- coding: utf-8 -*-
r"""_seat_lease.py - this PC's seat on a server (2026-10-06): asks the server's seat desk (server\seat_desk.py, TCP 20030) for a seat,
writes the answer for play.py, then HOLDS the seat by pinging every 20 s for as long as the run lasts. If the
connection breaks (a network blip, or the desk restarting), it RECONNECTS and re-claims the SAME seat (A5,
2026-10-11) - before, one missed reply ended the lease for good and the desk then freed the seat under the running
game. The end of the run ends the lease and the seat is free again at once.

    python _seat_lease.py ADDRESS OUT_FILE LIFE_SECONDS [SEAT]

OUT_FILE gets {"seat": n, "projector": 1|0}, or {"error": "no broker" | "no answer" | "full" | "taken" | "refused",
"detail": "..."} - written ONCE, from the first claim, for play.py. "no broker" = nothing answered on the port (a
server without the desk - play.py then plays as before); "no answer" = the desk was reached but did not reply in
time (play.py stops rather than risk two PCs on one seat).
"""
import json
import os
import socket
import sys
import time

PORT = int(os.environ.get("WCCF_BROKER_PORT", "20030"))
PING = float(os.environ.get("WCCF_LEASE_PING", "20"))          # seconds between pings (the desk waits 75)
RETRY = float(os.environ.get("WCCF_LEASE_RETRY", "3"))         # seconds between reclaim tries after a break


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


def main(argv):
    ip, out, life = argv[0], argv[1], float(argv[2])
    want_initial = b"WANT SEAT %d\n" % int(argv[3]) if len(argv) > 3 else b"WANT\n"
    end = time.time() + life

    # the first claim - the only write to OUT_FILE (play.py reads it to set up the game)
    try:
        conn = socket.create_connection((ip, PORT), timeout=6)
    except OSError as ex:
        write(out, {"error": "no broker", "detail": str(ex)})       # nothing listening: play.py plays as before
        return 1
    try:
        words = send_want(conn, want_initial)
    except OSError as ex:
        write(out, {"error": "no answer", "detail": str(ex)})       # reached but silent: play.py stops (A4)
        conn.close()
        return 1
    if not (len(words) == 4 and words[0] == "SEAT" and words[2] == "PROJECTOR"):
        write(out, {"error": {"FULL": "full", "TAKEN": "taken"}.get(words[0] if words else "", "refused"),
                    "detail": " ".join(words)})
        conn.close()
        return 1
    seat = int(words[1])
    write(out, {"seat": seat, "projector": int(words[3])})
    log("seat %d held (projector %s)" % (seat, words[3]))
    want_reclaim = b"WANT SEAT %d\n" % seat

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
