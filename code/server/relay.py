# -*- coding: utf-8 -*-
r"""relay.py - the match relay on the PC (or cloud machine) that runs the server (2026-10-06).  In a match between
two players the cabinets send their moves to each other directly, over UDP (port 20000 + seat); home routers drop
that, and the game then falls back to a CPU match.  With the relay each cabinet's overlay (wccfpanel.dll) sends those
packets here instead, and this passes each one on to the other seat - so every player only ever talks to the server,
which works through any router, and installs nothing.

    python code\server\relay.py LIFE_SECONDS [LOG_FILE]        (play.py server starts it; UDP port 20040)

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

A live seat belongs to the public address that holds it (A6, 2026-10-11): while the owner is still heard from (within
30 s), a packet that claims its seat from ANOTHER public address is rejected, so no one on the internet can send
"WRL1R" + a seat and redirect another player's match to themselves. Once the owner goes quiet (> 30 s) the seat is
free for a new address (a player whose public address changed waits at most that long). The same public address on a
NEW PORT takes the seat at once when it sends game data (2026-10-15: a player's router gave the game a new port at
kick-off, the relay rejected his packets for 30 s, and both games fell back to a CPU match). Once data chooses a
socket, a hello ("R") from another port cannot move or refresh that live route, even during a pause in outgoing data:
legacy panels keep sending hellos from old sockets. Only the selected socket refreshes its lifetime; same-IP data
still migrates immediately. An expired route is available to a hello or data from any address. The stronger tie - a
token the seat desk gives each PC, carried in the packet - needs a coordinated protocol/client update.
"""
import os
import queue
import socket
import sys
import threading
import time
from datetime import datetime

PORT = int(os.environ.get("WCCF_RELAY_PORT", "20040"))
FORGET = float(os.environ.get("WCCF_RELAY_FORGET", "30"))
MAGIC = b"WRL1"
TRAFFIC_GAP = 1.0                     # diagnostic only: mark each direction's silence once, then its next data arrival
log_file = None
_logger = None
LOG_QUEUE = 256
LOG_STOP_WAIT = 1.0


def _stamp(msg):
    return "%s %s" % (datetime.now().astimezone().isoformat(" ", timespec="milliseconds"), msg)


def _write_log(line, path):
    try:
        print(line, flush=True)
    except (OSError, ValueError):         # a closed launcher pipe must not stop match forwarding
        pass
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


class _AsyncLog:
    """One bounded, best-effort writer. Producers never wait for output or queue space. The lock protects only
    drop counters; it is never held during I/O. A stalled disk/stdout may lose diagnostics, never match packets."""
    def __init__(self, path, capacity=LOG_QUEUE):
        self.path, self.items = path, queue.Queue(maxsize=capacity)
        self.stopping, self.counter_lock = threading.Event(), threading.Lock()
        self.dropped, self.reported, self.failed = 0, 0, 0
        self.worker = threading.Thread(target=self._run, name="relay-log", daemon=True)
        self.worker.start()

    def submit(self, line):
        try:
            self.items.put_nowait(line)
        except queue.Full:
            with self.counter_lock:
                self.dropped += 1

    def _emit(self, line):
        try:
            _write_log(line, self.path)
        except Exception:                # diagnostics cannot kill their worker or affect the serving thread
            self.failed += 1

    def _report_drops(self):
        with self.counter_lock:
            lost = self.dropped - self.reported
            self.reported = self.dropped
        if lost:
            self._emit(_stamp("relay diagnostic queue full: %d events omitted (total %d)" % (lost, self.reported)))

    def _run(self):
        while not self.stopping.is_set() or not self.items.empty():
            try:
                line = self.items.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if line is not None:     # a wake-up for an empty queue at clean shutdown
                    self._report_drops()
                    self._emit(line)
            finally:
                self.items.task_done()
        self._report_drops()

    def stop(self, timeout=LOG_STOP_WAIT):
        self.stopping.set()
        try:
            self.items.put_nowait(None)
        except queue.Full:
            pass                         # draining queued events already wakes the worker
        self.worker.join(timeout)
        return not self.worker.is_alive()


def log(msg):
    line = _stamp(msg)
    if _logger is None:
        _write_log(line, log_file)         # direct claim tests / startup failure, outside the serving loop
    else:
        _logger.submit(line)


def claim(seats, seat, addr, now, rejects, data=False, ignored=None):
    """Record addr as where `seat` is, unless ANOTHER public address holds it and was heard within FORGET: a live seat
    cannot be taken over from elsewhere (A6). Same-IP data on a new port takes it at once. Once data chose a live
    route, an alternate-port hello neither moves it nor refreshes its lifetime: old sockets must not steal a match
    while it only receives. seats[seat] = [address, last heard from that address, last data or None]. All times are
    monotonic receive times. False means rejected public-IP ownership; an ignored same-IP hello returns True."""
    known = seats.get(seat)
    live = known and now - known[1] <= FORGET
    if live and known[0][0] != addr[0]:
        rejects[seat] = rejects.get(seat, 0) + 1
        if rejects[seat] == 1:
            log("seat %d rejected %s from %s:%d; owner %s:%d heard %.3f s ago" % (
                seat, "data" if data else "hello", addr[0], addr[1], known[0][0], known[0][1], now - known[1]))
        return False
    if live and known[0] != addr and not data and known[2] is not None:
        if ignored is not None:
            ignored[seat] = ignored.get(seat, 0) + 1
            if ignored[seat] == 1:
                log("seat %d ignored alternate-port hello from %s:%d; data route stays %s:%d, heard %.3f s ago" % (
                    seat, addr[0], addr[1], known[0][0], known[0][1], now - known[1]))
        return True
    if not live or known[0] != addr:
        previous = "; previous %s:%d, heard %.3f s ago" % (
            known[0][0], known[0][1], now - known[1]) if known else ""
        log("seat %d is at %s:%d (%s%s)" % (seat, addr[0], addr[1], "data" if data else "hello", previous))
    seats[seat] = [addr, now, now if data else (known[2] if live and known[0] == addr else None)]
    return True


def watch_traffic(traffic, now):
    """One silence marker per direction, with bounded state (at most 8 x 8 seat pairs). Arrival silence can be a
    normal game phase; this describes what reached the relay, not what either game received or why data stopped."""
    for (a, b), state in list(traffic.items()):
        gap = now - state[0]
        if not state[1] and gap >= TRAFFIC_GAP:
            log("traffic %d->%d: no data received for %.3f s" % (a, b, gap))
            state[1] = True
        if gap > FORGET:
            del traffic[(a, b)]


def received_data(traffic, a, b, addr, now):
    previous = traffic.get((a, b))
    if not previous:
        log("traffic %d->%d: data received from %s:%d" % (a, b, addr[0], addr[1]))
    elif now - previous[0] >= TRAFFIC_GAP:
        log("traffic %d->%d: data resumed after %.3f s from %s:%d" % (a, b, now - previous[0], addr[0], addr[1]))
    traffic[(a, b)] = [now, False]


def main(argv):
    global log_file, _logger
    life = float(argv[0]) if argv else 12 * 3600
    log_file = argv[1] if len(argv) > 1 else None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("0.0.0.0", PORT))
    except OSError as ex:
        s.close()
        log("cannot listen on UDP %d (%s) - is a relay already running?" % (PORT, ex))
        return 1
    s.settimeout(1.0)
    logger = _AsyncLog(log_file)
    _logger = logger
    try:
        return _serve(s, life)
    finally:
        s.close()
        logger.stop()                    # at most one second, even if stdout or disk is permanently stalled
        _logger = None


def _serve(s, life):
    log("match relay listening on UDP %d" % PORT)
    seats = {}                          # seat -> [addr, last heard from selected socket, last data or None]
    traffic = {}                        # (from seat, to seat) -> [last data arrival, silence already reported]
    counts, drops, rejects, ignored, send_errors = {}, {}, {}, {}, {}
    next_report = time.monotonic() + 30
    end = time.monotonic() + life
    while time.monotonic() < end:
        now = time.monotonic()
        watch_traffic(traffic, now)
        if now >= next_report:
            if counts or drops or rejects or ignored or send_errors:
                log("last 30 s: %s%s%s%s%s" % (", ".join("%d->%d %d" % (a, b, n) for (a, b), n in sorted(counts.items())) or
                                           "nothing passed",
                                           "; dropped (seat not known): %s" % ", ".join(
                                               "->%d %d" % (b, n) for b, n in sorted(drops.items())) if drops else "",
                                           "; rejected (seat held by another address): %s" % ", ".join(
                                               "seat %d %d" % (b, n) for b, n in sorted(rejects.items())) if rejects else "",
                                           "; ignored alternate-port hello: %s" % ", ".join(
                                               "seat %d %d" % (b, n) for b, n in sorted(ignored.items())) if ignored else "",
                                           "; send errors: %s" % ", ".join(
                                               "->%d %d" % (b, n) for b, n in sorted(send_errors.items())) if send_errors else ""))
            counts, drops, rejects, ignored, send_errors, next_report = {}, {}, {}, {}, {}, now + 30
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
        now = time.monotonic()          # recvfrom may have waited: lifetimes use this packet's actual receive time
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
            claim(seats, data[5], addr, now, rejects, ignored=ignored)  # strangers cannot take a live seat (A6)
        elif kind == b"D" and len(data) >= 7 and 1 <= data[5] <= 8 and 1 <= data[6] <= 8:
            to_seat, from_seat = data[5], data[6]
            if not claim(seats, from_seat, addr, now, rejects, data=True):
                continue                                    # not this seat's owner: drop the packet
            received_data(traffic, from_seat, to_seat, addr, now)
            target = seats.get(to_seat)
            if not target or now - target[1] > FORGET:
                drops[to_seat] = drops.get(to_seat, 0) + 1
                if drops[to_seat] == 1:
                    reason = "not registered" if not target else "expired; selected socket heard %.3f s ago" % (now - target[1])
                    log("traffic %d->%d dropped: destination %s" % (from_seat, to_seat, reason))
                continue
            try:
                s.sendto(MAGIC + b"F" + bytes([from_seat]) + socket.inet_aton(addr[0]) + data[7:], target[0])
                counts[(from_seat, to_seat)] = counts.get((from_seat, to_seat), 0) + 1
            except OSError as ex:
                send_errors[to_seat] = send_errors.get(to_seat, 0) + 1
                if send_errors[to_seat] == 1:
                    log("traffic %d->%d send failed to %s:%d: %s" % (
                        from_seat, to_seat, target[0][0], target[0][1], ex))
    log("match relay: its time is up - stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
