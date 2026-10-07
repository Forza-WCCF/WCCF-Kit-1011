# -*- coding: utf-8 -*-
r"""_relay.py - the match relay on the PC (or cloud machine) that runs the server (2026-10-06).  In a match between
two players the cabinets send their moves to each other directly, over UDP (port 20000 + seat); home routers drop
that, and the game then falls back to a CPU match.  With the relay each cabinet's overlay (wccfpanel.dll) sends those
packets here instead, and this passes each one on to the other seat - so every player only ever talks to the server,
which works through any router, and installs nothing.

    python _relay.py LIFE_SECONDS [LOG_FILE]          (play.py server starts it; UDP port 20040)

Packets (binary; "WRL1" = 57 52 4C 31):
    cabinet -> relay   "WRL1" "R" seat                          I am seat n: send its packets here (every 5 s - it
                                                                also keeps the cabinet's router open for the replies)
    cabinet -> relay   "WRL1" "D" to_seat from_seat payload     a game packet for seat to_seat
    relay -> cabinet   "WRL1" "F" from_seat from_ip(4) payload  a game packet from seat from_seat, whose public address
                                                                the relay saw as from_ip
    cabinet -> relay   "WRL1" "P" token                         a ping (the cabinet's meter, 2026-10-07): answered
    relay -> cabinet   "WRL1" "Q" token                         at once with the same token - nothing else is done
A seat not heard from for 30 s is forgotten; a packet for a seat the relay does not know is dropped (and counted) -
the game resends lost packets.  It never looks inside a payload.
"""
import os
import socket
import sys
import time

PORT = int(os.environ.get("WCCF_RELAY_PORT", "20040"))
FORGET = float(os.environ.get("WCCF_RELAY_FORGET", "30"))
MAGIC = b"WRL1"
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


def main(argv):
    global log_file
    life = float(argv[0]) if argv else 12 * 3600
    log_file = argv[1] if len(argv) > 1 else None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", PORT))
    except OSError as ex:
        log("cannot listen on UDP %d (%s) - is a relay already running?" % (PORT, ex))
        return 1
    s.settimeout(1.0)
    log("match relay listening on UDP %d" % PORT)
    seats = {}                          # seat -> [addr, last heard]
    counts, drops, next_report = {}, {}, time.time() + 30
    end = time.time() + life
    while time.time() < end:
        now = time.time()
        if now >= next_report:
            if counts or drops:
                log("last 30 s: %s%s" % (", ".join("%d->%d %d" % (a, b, n) for (a, b), n in sorted(counts.items())) or
                                         "nothing passed",
                                         "; dropped (seat not known): %s" % ", ".join(
                                             "->%d %d" % (b, n) for b, n in sorted(drops.items())) if drops else ""))
            counts, drops, next_report = {}, {}, now + 30
            for seat in [k for k, v in seats.items() if now - v[1] > FORGET]:
                log("seat %d (%s:%d) not heard from for %d s - forgotten" % (seat, seats[seat][0][0], seats[seat][0][1],
                                                                          FORGET))
                del seats[seat]
        try:
            data, addr = s.recvfrom(4200)
        except socket.timeout:
            continue
        except OSError:                 # e.g. a "port unreachable" echo on Windows: ignore
            continue
        if len(data) < 6 or data[:4] != MAGIC:
            continue
        kind = data[4:5]
        if kind == b"P":                # a ping from a cabinet's meter (wccfpanel.dll, 2026-10-07): its bytes back, as "Q"
            if len(data) <= 64:
                try:
                    s.sendto(MAGIC + b"Q" + data[5:], addr)
                except OSError:
                    pass
            continue
        if kind == b"R" and 1 <= data[5] <= 8:
            seat = data[5]
            known = seats.get(seat)
            if not known or known[0] != addr:
                log("seat %d is at %s:%d" % (seat, addr[0], addr[1]))
            seats[seat] = [addr, now]
        elif kind == b"D" and len(data) >= 7 and 1 <= data[5] <= 8 and 1 <= data[6] <= 8:
            to_seat, from_seat = data[5], data[6]
            known = seats.get(from_seat)
            if not known or known[0] != addr:
                log("seat %d is at %s:%d" % (from_seat, addr[0], addr[1]))
            seats[from_seat] = [addr, now]
            target = seats.get(to_seat)
            if not target or now - target[1] > FORGET:
                drops[to_seat] = drops.get(to_seat, 0) + 1
                continue
            try:
                s.sendto(MAGIC + b"F" + bytes([from_seat]) + socket.inet_aton(addr[0]) + data[7:], target[0])
                counts[(from_seat, to_seat)] = counts.get((from_seat, to_seat), 0) + 1
            except OSError:
                drops[to_seat] = drops.get(to_seat, 0) + 1
    log("match relay: its time is up - stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
