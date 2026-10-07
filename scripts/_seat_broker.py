# -*- coding: utf-8 -*-
r"""_seat_broker.py - hands out cabinet seats on the PC (or cloud machine) that runs the server (2026-10-06): every PC
that plays on this server asks it for a seat before starting its cabinet and gets the lowest free one, 1-8 - and the
projector (seat 0) when no other PC has it - so nobody types a seat number (two PCs on one seat break the game).
A seat stays taken while that PC's _seat_lease.py keeps its connection, pinging every 20 s; a PC that stops,
crashes or goes away frees its seat: its connection closes, or it stays silent for 75 s.

    python _seat_broker.py LIFE_SECONDS [LOG_FILE]          (play.py server starts it)

TCP port 20030 (WCCF_BROKER_PORT for the tests).  Lines, ASCII, one per message:
    PC -> "WANT"                broker -> "SEAT n PROJECTOR 1|0"   the lowest free seat; 1 = this PC shows the projector
    PC -> "WANT SEAT n"         broker -> the same for seat n, or "TAKEN n"
                                broker -> "FULL" (8 cabinets) / "ERR ..." (anything else) - then it closes
    PC -> "PING"                broker -> "PONG"                   while it runs
It never touches the game: the seats it gives out are only what the PCs then write into their own cabinet settings.
"""
import os
import socket
import sys
import threading
import time

PORT = int(os.environ.get("WCCF_BROKER_PORT", "20030"))
SILENT = float(os.environ.get("WCCF_BROKER_SILENT", "75"))       # seconds without a line: the PC is gone
SEATS = range(1, 9)

lock = threading.Lock()
leases = {}                     # seat -> (peer, lease id)
projector = None                # the seat whose PC shows the projector
next_id = 0
log_file = None


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    if log_file:
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def read_line(conn, buf):
    """one line (without its end) from conn, keeping what follows in buf; raises OSError when the PC is gone"""
    while b"\n" not in buf[0]:
        if len(buf[0]) > 200:
            raise OSError("line too long")
        data = conn.recv(256)
        if not data:
            raise OSError("closed")
        buf[0] += data
    line, buf[0] = buf[0].split(b"\n", 1)
    return line.strip().decode("ascii", "replace")


def taken():
    return ", ".join("%d%s" % (s, " (projector)" if s == projector else "") for s in sorted(leases)) or "none"


def serve(conn, peer):
    global projector, next_id
    seat, lid, buf = None, None, [b""]
    conn.settimeout(SILENT)
    try:
        words = read_line(conn, buf).split()
        with lock:
            if words == ["WANT"]:
                free = [s for s in SEATS if s not in leases]
                if not free:
                    conn.sendall(b"FULL\n")
                    log("%s: no seat - all 8 taken" % peer)
                    return
                seat = free[0]
            elif len(words) == 3 and words[:2] == ["WANT", "SEAT"] and words[2].isdigit() and int(words[2]) in SEATS:
                if int(words[2]) in leases:
                    conn.sendall(b"TAKEN %d\n" % int(words[2]))
                    log("%s: seat %s refused - taken" % (peer, words[2]))
                    return
                seat = int(words[2])
            else:
                conn.sendall(b"ERR say WANT or WANT SEAT n\n")
                return
            next_id += 1
            lid = next_id
            leases[seat] = (peer, lid)
            show = projector is None
            if show:
                projector = seat
            conn.sendall(b"SEAT %d PROJECTOR %d\n" % (seat, 1 if show else 0))
            log("%s: seat %d%s - taken now: %s" % (peer, seat, " + the projector" if show else "", taken()))
        while True:
            if read_line(conn, buf) == "PING":
                conn.sendall(b"PONG\n")
    except (OSError, ValueError):
        pass
    finally:
        with lock:
            if seat is not None and leases.get(seat, (None, None))[1] == lid:
                del leases[seat]
                if projector == seat:
                    projector = None
                log("%s: seat %d free again - taken now: %s" % (peer, seat, taken()))
        try:
            conn.close()
        except OSError:
            pass


def main(argv):
    global log_file
    life = float(argv[0]) if argv else 12 * 3600
    log_file = argv[1] if len(argv) > 1 else None
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("0.0.0.0", PORT))
    except OSError as ex:
        log("cannot listen on TCP %d (%s) - is a seat broker already running?" % (PORT, ex))
        return 1
    srv.listen(16)
    srv.settimeout(1.0)
    log("seat broker listening on TCP %d: seats 1-8, the first PC also shows the projector" % PORT)
    end = time.time() + life
    while time.time() < end:
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            continue
        threading.Thread(target=serve, args=(conn, "%s:%d" % addr), daemon=True).start()
    log("seat broker: its time is up - stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
