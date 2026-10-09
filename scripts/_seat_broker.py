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

It does READ the game (2026-10-09): a seat whose cabinet is in the game now is not given to another PC, even with no
lease for it - after a server restart a cabinet rejoins the game by itself on its old seat, but its PC's lease died
with the old desk, and that night the desk gave seat 3 to a second PC: it was never let in (4 tries in 12 minutes).
Who is on which seat comes from control's debug log (_dbg_control.txt beside this desk's log, written line by line):
"sateID=n" then "++ACCEPT++ 'address'" = a cabinet on seat n, "---DISCONNECT--- sateID=n" = gone; sateID 0 is the
projector. The same address may take its seat back (WANT SEAT n), and the projector's role is not given out while
another address shows the projector. Two PCs behind one router share an address: the desk cannot tell them apart.
"""
import os
import re
import socket
import sys
import threading
import time

PORT = int(os.environ.get("WCCF_BROKER_PORT", "20030"))
SILENT = float(os.environ.get("WCCF_BROKER_SILENT", "75"))       # seconds without a line: the PC is gone
SEATS = range(1, 9)
SATE = re.compile(r"client\[\d+\]\s*:\s*sateID=(\d+)")
ACCEPT = re.compile(r"\+\+ACCEPT\+\+\s+'([0-9.]+):\d+'")
GONE = re.compile(r"---DISCONNECT---\s*sateID=(\d+)")

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


class InGame:
    """the seats control has a cabinet on now: {seat: address} (0 = the projector), from its debug log.  Each look reads
    only what control wrote since the last one; a new run's log (made again at control's start) is read from its start;
    no log yet = nobody in the game.  Never raises."""

    def __init__(self, path):
        self.path, self.born, self.pos, self.part, self.seats, self.seat = path, None, 0, "", {}, None

    def now(self):
        try:
            st = os.stat(self.path)
        except OSError:
            self.born, self.pos, self.part, self.seats, self.seat = None, 0, "", {}, None
            return {}
        born = getattr(st, "st_birthtime", st.st_ctime)
        if born != self.born or st.st_size < self.pos:              # another run's log: from its start
            self.born, self.pos, self.part, self.seats, self.seat = born, 0, "", {}, None
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                data = f.read()
        except OSError:
            return dict(self.seats)
        self.pos += len(data)
        lines = (self.part + data.decode("utf-8", "replace")).split("\n")
        self.part = lines.pop()                                     # a line control is still writing: next time
        for line in lines:
            m = SATE.search(line)
            if m:
                self.seat = int(m.group(1))
            m = ACCEPT.search(line)
            if m and self.seat is not None:
                self.seats[self.seat] = m.group(1)
            m = GONE.search(line)
            if m:
                self.seats.pop(int(m.group(1)), None)
        return dict(self.seats)


in_game = InGame(os.environ.get("WCCF_CONTROL_LOG") or "")


def serve(conn, peer):
    global projector, next_id
    seat, lid, buf = None, None, [b""]
    conn.settimeout(SILENT)
    try:
        words = read_line(conn, buf).split()
        ip = peer.rsplit(":", 1)[0]
        with lock:
            game = in_game.now()
            others = {s: a for s, a in game.items() if a != ip}     # seats another address has in the game
            if words == ["WANT"]:
                free = [s for s in SEATS if s not in leases and s not in others]
                if not free:
                    conn.sendall(b"FULL\n")
                    log("%s: no seat - all 8 taken" % peer)
                    return
                seat = free[0]
                skipped = [s for s in SEATS if s < seat and s not in leases and s in others]
                if skipped:
                    log("%s: seat %s skipped - in the game (%s) with no lease" % (
                        peer, ", ".join(map(str, skipped)), ", ".join(others[s] for s in skipped)))
            elif len(words) == 3 and words[:2] == ["WANT", "SEAT"] and words[2].isdigit() and int(words[2]) in SEATS:
                if int(words[2]) in leases or int(words[2]) in others:
                    conn.sendall(b"TAKEN %d\n" % int(words[2]))
                    log("%s: seat %s refused - taken%s" % (peer, words[2], "" if int(words[2]) in leases else
                                                           " (in the game by %s)" % others[int(words[2])]))
                    return
                seat = int(words[2])
            else:
                conn.sendall(b"ERR say WANT or WANT SEAT n\n")
                return
            next_id += 1
            lid = next_id
            leases[seat] = (peer, lid)
            show = projector is None and 0 not in others            # nobody else shows the projector in the game
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
    if not in_game.path and log_file:                               # control's debug log is beside this desk's log
        in_game.path = os.path.join(os.path.dirname(os.path.abspath(log_file)), "_dbg_control.txt")
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
