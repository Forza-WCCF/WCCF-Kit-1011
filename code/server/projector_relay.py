# -*- coding: utf-8 -*-
r"""projector_relay.py - the projector for every player, on the PC (or cloud machine) that runs the server
(2026-10-17).  Control takes ONE projector (seat 0): a second one is refused (INVALID_ID) and that PC shows "Network,
Error".  This holds that one connection itself and passes what control sends it to every player's projector, so each
player PC can show the big screen too.  play.py server starts it beside the seat desk; a player PC's projector connects
here instead of to control when the seat desk offers it (online\seat.py's RELAY word, "SEAT n PROJECTOR 20031").

    python code\server\projector_relay.py LIFE_SECONDS [LOG_FILE]        (play.py server starts it; TCP port 20031)

What goes on the wire is the game's own: batches of u32 record count, u32 total size (with these 8 bytes), then each
record's 16-byte name (NUL-padded), u32 body size and body - little-endian, the same as source\hook\wholemsg.h.  What
the game expects of a projector was read from control and the client (static only, 2026-10-17; the research notes
projector-fanout-20261017\re\FINDINGS.md and traffic\TRAFFIC.md, outside the repo):
- A projector's INIT is answered HERE, at once, with INIT REPLY "OK\0" (control's answer has no session number, so one
  answer fits all).  Control never sees a second INIT.  The ONE connection to control (127.0.0.1:20002) is opened only
  once a player is in the game - the seat desk's reading of control's debug log tells (seat_desk.InGame) - with the
  first projector's INIT, its seat-count field set to 8 (eight_seats); it is closed when the last projector leaves.
- One reader drains control without pause into this relay's own queues: control sends with one non-blocking send(),
  and a full 3 MiB buffer there silently cuts messages, which would corrupt the stream for every projector.
- KEEP_ALIVE: the relay sends control one for each CONTROL_STATE, as a projector does (at 11 missed, control drops
  the seat); the projectors' own KEEP_ALIVEs stay here.
- A projector's REQ_* goes on to control, one at a time per name for all projectors: the same bytes waiting or on their
  way are not sent again, another request of that name waits until control has answered the one on its way (its
  reply's name: REQ_RNK_ACP_INF -> RNK_ACP_STATE) or REQ_WAIT seconds have passed.  Requests made before control's
  connection is open wait for it.  Control's replies carry no request number, so every projector gets each one.
- A projector's GAME_READY (it sends one as a match starts, 2026-10-17 live run) goes on to control once a match: the
  first one after the match's LIVE_INFO / TO MATCH INI, as one projector would send it; the others stay here.
- To control only whole batches, one record each.  A projector that sends anything before its INIT, a record over
  BODY_MAX bytes, bytes that are no batch, or more than FLOOD records a second, is cut; past RATE a second its records
  are dropped here (logged once) and it stays.  Any other message of a joined projector stays here
  (logged once a name): control hears seat 0 say only INIT, KEEP_ALIVE, REQ_* and GAME_READY.
- A projector that joins late gets what it missed, latest of each, in the order control gives it at the start:
  INIT REPLY, CONTROL_STATE, GAME_CTRL, LOGSVR_INFO, the *_STATE replies, and during a match LIVE_INFO and TO MATCH
  INI - then the live TO MATCH frames (INI must come before any frame: the match view is built from it).
- A slow projector never holds the others or control up: each has its own queue; past QUEUE bytes its oldest TO MATCH
  frames go (each frame holds whole positions, the client checks no gap), then a finished match's TO MATCH INI once a
  newer one waits, and a newer message of a name already waiting replaces it; the newest TO MATCH INI and INIT REPLY
  are never dropped, nor the replay a joiner is sent.  One with more than HARD bytes waiting even so, or whose socket
  takes nothing for STUCK seconds, is cut.  Both are generous (2026-10-17): a projector cut is dead until its PC
  starts it again (helpers\panel.py ProjectorKeeper), so the relay sheds first and cuts only a projector that is
  gone - STUCK is as long as the projector's own link waits out a drop (source\hook\patience.h, TCP_MAXRT 100 s).  TCP_NODELAY; no
  compression.
- Control's connection is a session: what a reader of an older one passes on is dropped (2026-10-17).  Control's own
  INIT REPLY stays here.  When control takes nothing - UP_QUEUE bytes waiting, or a send held UP_WAIT seconds - the
  connection is closed and opened again; the reader of control never waits on a projector or on control.
"""
import collections
import os
import socket
import struct
import sys
import threading
import time

from server.seat_desk import InGame

PORT = int(os.environ.get("WCCF_PROJECTOR_PORT", "20031"))
CONTROL_PORT = int(os.environ.get("WCCF_CONTROL_PORT", "20002"))
QUEUE = int(os.environ.get("WCCF_PROJECTOR_QUEUE", str(64 * 1024)))     # bytes waiting for one projector before its
                                                                       # oldest frames go (~3 s of the match at 60/s)
HARD = int(os.environ.get("WCCF_PROJECTOR_HARD", str(4 << 20)))       # bytes waiting for one projector after the
                                                                       # shedding (INIs, replies): past it, cut
STUCK = float(os.environ.get("WCCF_PROJECTOR_STUCK", "100"))           # seconds a projector may take nothing: cut
REQ_WAIT = 5.0                  # seconds a request stays "on its way" when no reply of its name comes
PENDING = 64                    # requests waiting for control, all projectors together; more are dropped
UP_QUEUE = 64 * 1024            # bytes waiting for control (KEEP_ALIVEs, REQ_*): past it control takes nothing - closed
UP_WAIT = 5.0                   # seconds one send to control may wait for room
MATCH_GAP = 10.0                # seconds without a TO MATCH frame (after some came): the match is over
RATE = 100                      # records a second a projector may send (it sends a KEEP_ALIVE every ~3 s, a few REQ_*);
FLOOD = 10 * RATE               # the rest of that second's are dropped; past FLOOD it is cut
BODY_MAX = 4096                 # bytes in a projector's INIT / KEEP_ALIVE / REQ_* body
BATCH_MAX = 0x80000             # control's own receive buffer (wholemsg.h WM_MAX_BATCH)
FRAME, INI = "TO MATCH", "TO MATCH INI"
FIRST = ("CONTROL_STATE", "GAME_CTRL", "LOGSVR_INFO")       # what control sends a projector as it is let in
MATCH = ("LIVE_INFO", INI)                                  # once a match, before its frames
NEVER_DROP = (INI, "INIT REPLY")
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


def pack(name, body):
    """one record in a batch of its own"""
    return struct.pack("<II16sI", 1, 28 + len(body), name.encode("ascii"), len(body)) + body


def unpack(buf, limit):
    """the records of the whole batches at the start of buf (a bytearray; what is used is taken out): [(name, body)];
    a batch not all here yet stays.  ValueError when the bytes cannot be a batch (wholemsg.h's rules)"""
    out = []
    while len(buf) >= 8:
        count, total = struct.unpack_from("<II", buf)
        if total < 8 or total > limit or count > (total - 8) // 20:
            raise ValueError("not a batch (%d records in %d bytes)" % (count, total))
        if len(buf) < total:
            break
        off = 8
        for _ in range(count):
            if off + 20 > total:
                raise ValueError("a record that starts past its batch's end")
            name, size = bytes(buf[off:off + 16]).split(b"\0", 1)[0], struct.unpack_from("<I", buf, off + 16)[0]
            if not name or any(c < 0x20 or c > 0x7e for c in name) or size > total - off - 20:
                raise ValueError("a record that cannot be one (%r, %d bytes)" % (name[:16], size))
            out.append((name.decode("ascii"), bytes(buf[off + 20:off + 20 + size])))
            off += 20 + size
        if off != total:
            raise ValueError("records that do not fill their batch")
        del buf[:total]
    return out


def reply_of(name):
    """the name of control's reply to a request: REQ_X_INF -> X_STATE (REQ_RNK_ACP_INF -> RNK_ACP_STATE, the client's
    name table read 2026-10-17), REQ_STATE_INFO -> CONTROL_STATE; None for the few no rule fits (REQ_*_OFF, REQ_BANNED,
    REQ_DIST_PIC, REQ_LSVR_RES, REQ_WCCFCUP_STA): those are let go after REQ_WAIT seconds"""
    if name == "REQ_STATE_INFO":
        return "CONTROL_STATE"
    return name[4:-4] + "_STATE" if name.endswith("_INF") else None


def eight_seats(body):
    """the first projector's INIT as control gets it, its cabinet field saying 8 seats.  The field is the INIT body's
    u32 [4] (bytes 16-19): control reads [0] sateID and [1] version from the same buffer for its log line (0x42c0f0),
    and [4] at 0x42c577; a seat-0 INIT sets the seat count from it through the jump table at 0x42d35c - 0-3 = 8 seats,
    4-5 = 6, 6-7 = 4, above 7 = left as it was - and refuses every seat above (0x42c593-0x42c722).  Read in the code
    only, never yet in a live INIT: fairly sure of the offset, sure of the table.  A value meaning 8 already is kept."""
    if len(body) < 20 or struct.unpack_from("<I", body, 16)[0] <= 3:
        return body
    return body[:16] + struct.pack("<I", 0) + body[20:]


class Projector:
    """one projector PC: its queue (shed when it falls behind) and a writer thread that empties it"""

    def __init__(self, conn, peer):
        self.conn, self.peer, self.joined, self.closed = conn, peer, False, False
        self.q, self.size, self.shed, self.why, self.shed_rate = collections.deque(), 0, 0, "", False
        self.head = 0                   # the replay at the queue's head: kept whole and in order until it is sent
        self.cv = threading.Condition()

    def put(self, name, data, head=False):
        """head: part of the replay a joiner gets first (only while nothing else waits for it)"""
        with self.cv:
            if self.closed:
                return
            if head:
                self.head += 1
            elif name != FRAME and name not in NEVER_DROP:      # the latest of a name is all a projector needs
                for i in range(self.head, len(self.q)):
                    if self.q[i][0] == name:
                        self.size -= len(self.q[i][1])
                        del self.q[i]
                        break
            self.q.append((name, data))
            self.size += len(data)
            while self.size > QUEUE:                            # behind: its oldest frames go, then old matches' INIs
                i = next((i for i in range(self.head, len(self.q)) if self.q[i][0] == FRAME), None)
                if i is None:                                   # no frame left before them: an INI with a newer one
                    inis = [i for i in range(self.head, len(self.q)) if self.q[i][0] == INI]
                    i = inis[0] if len(inis) > 1 else None
                if i is None:
                    break
                self.size -= len(self.q[i][1])
                del self.q[i]
                self.shed += 1
            if self.size > HARD:                                # behind on what cannot be shed: cut
                self.cut("%d bytes waiting for it" % self.size)
            self.cv.notify()

    def cut(self, why):
        """from anywhere, locks held or not: the queue goes, the socket is shut, and its reader then calls leave()"""
        with self.cv:
            self.why = self.why or why
            self.closed = True
            self.q.clear()
            self.size = 0
            self.cv.notify()
        try:
            self.conn.shutdown(socket.SHUT_RDWR)        # a close alone does not wake this socket's reader
        except OSError:
            pass

    def write(self, hub):
        try:
            while True:
                with self.cv:
                    while not self.q and not self.closed:
                        self.cv.wait()
                    if self.closed:
                        return
                    q, self.q, self.size, self.head = self.q, collections.deque(), 0, 0
                data = b"".join(d for _, d in q)            # outside the lock: control's reader puts under it
                view = memoryview(data)
                while view:                                     # each send waits STUCK s at most for room
                    view = view[self.conn.send(view):]
        except socket.timeout:
            self.why = "took nothing for %d s" % STUCK
        except OSError as ex:
            self.why = self.why or str(ex)
        finally:
            hub.leave(self)

    def close(self):
        self.cut("")
        try:
            self.conn.close()
        except OSError:
            pass


class Upstream:
    """one session with control: its socket, and what waits to go to it (a reader or writer of an older session
    touches only its own)"""

    def __init__(self, sock, gen):
        self.sock, self.gen, self.closed = sock, gen, False
        self.q, self.size, self.cv = collections.deque(), 0, threading.Condition()


class Hub:
    """control's one projector connection and the projectors it feeds"""

    def __init__(self, in_game):
        self.lock = threading.Lock()
        self.in_game = in_game
        self.projectors = set()             # joined ones (INIT answered): every message from control goes to them
        self.init = None                    # the first projector's INIT body: the upstream INIT
        self.up = None                      # the session with control (Upstream)
        self.gen = 0                        # +1 each time a session starts or ends, or the last projector leaves
        self.cache = {}                     # name -> the latest batch of it (never TO MATCH, never TRUNCATION)
        self.frame_at = None                # when this match's last TO MATCH frame came (None: none yet / no match)
        self.pending = collections.deque()  # (REQ name, batch) not sent to control yet, oldest first
        self.asked = {}                     # REQ name -> (its batch, when it went to control): one per name
        self.keep_alive = pack("KEEP_ALIVE", b"\x01")    # a projector's own, byte for byte (the 2026-10-07 capture)
        self.ready_sent = False             # this match's GAME_READY has gone to control
        self.unknown = set()                # projector message names kept here and logged once
        self.fails = 0

    # ---- the projectors
    def from_projector(self, p, name, body):
        if len(body) > BODY_MAX:
            raise ValueError("a %s of %d bytes" % (name, len(body)))
        if name == "INIT":
            if p.joined:
                raise ValueError("a second INIT")
            with self.lock:
                p.put("INIT REPLY", pack("INIT REPLY", b"OK\0"), head=True)     # control's own answer, given here
                p.joined = True
                if self.init is None:
                    self.init = body
                if self.up:
                    self.replay(p)
                self.projectors.add(p)
                n = len(self.projectors)
            log("%s: projector in - %d now" % (p.peer, n))
        elif name == "KEEP_ALIVE":
            pass                                                        # the relay keeps control's seat alive itself
        elif not p.joined:
            raise ValueError("%s before INIT" % name)
        elif name.startswith("REQ_"):
            self.request(name, body)
        elif name == "GAME_READY":
            with self.lock:
                first, self.ready_sent = not self.ready_sent, True
                up = self.up
            if first:
                self.to_control(up, [pack(name, body)])
        elif name not in self.unknown:
            self.unknown.add(name)
            log("%s: a projector's %s kept here (not sent to control)" % (p.peer, name))

    def replay(self, p):
        """what a projector that comes in late missed, in control's order, at the head of its queue (lock held)"""
        for n in FIRST:
            if n in self.cache:
                p.put(n, self.cache[n], head=True)
        for n, d in self.cache.items():
            if n not in FIRST and n not in MATCH:
                p.put(n, d, head=True)
        if INI in self.cache:
            for n in MATCH:
                if n in self.cache:
                    p.put(n, self.cache[n], head=True)

    def request(self, name, body):
        data = pack(name, body)
        with self.lock:
            if self.asked.get(name, (None,))[0] == data or any(d == data for _, d in self.pending):
                return                          # the same request waits or is on its way: its reply goes to all
            if len(self.pending) >= PENDING:
                log("%d requests wait for control: %s dropped" % (PENDING, name))
                return
            self.pending.append((name, data))
            up, out = self.up, self.next_requests()
        self.to_control(up, out)

    def next_requests(self):
        """the waiting requests that may go now, marked as on their way (lock held)"""
        out, now = [], time.time()
        if self.up:
            for item in list(self.pending):
                if item[0] not in self.asked:
                    self.asked[item[0]] = (item[1], now)
                    self.pending.remove(item)
                    out.append(item[1])
        return out

    def leave(self, p):
        p.close()
        with self.lock:
            if p not in self.projectors and not p.joined:
                return
            p.joined = False
            self.projectors.discard(p)
            left, up = len(self.projectors), None
            if not left:                        # decided and done under one lock: a joiner after it starts afresh
                up, self.up, self.init, self.gen = self.up, None, None, self.gen + 1
                self.pending.clear()
                self.asked = {}
        log("%s: projector out (%s)%s - %d now" % (p.peer, p.why or "closed", ", %d frames shed" % p.shed
                                                   if p.shed else "", left))
        if up:
            self.drop(up, "the last projector left")

    # ---- control
    def tick(self):
        """once a second: the match cache cleared when the frames have stopped; requests with no reply let go;
        control's connection opened when a projector waits and a player is in the game"""
        now = time.time()
        with self.lock:
            if self.frame_at and now - self.frame_at > MATCH_GAP:
                for n in MATCH:
                    self.cache.pop(n, None)
                self.frame_at = None
            for n in [n for n, (_, t) in self.asked.items() if now - t > REQ_WAIT]:
                del self.asked[n]
            up, out = self.up, self.next_requests()
            want, init, gen = self.init is not None and not self.up, self.init, self.gen
        self.to_control(up, out)
        if not want or not any(s >= 1 for s in self.in_game.now()):
            return
        try:
            sock = socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=5)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(UP_WAIT)                    # sends; the reader takes a timeout as "nothing yet"
            sock.sendall(pack("INIT", eight_seats(init)))
        except OSError as ex:
            self.fails += 1
            if self.fails in (1, 30) or self.fails % 600 == 0:
                log("control on TCP %d cannot be reached (%s, try %d)" % (CONTROL_PORT, ex, self.fails))
            return
        self.fails = 0
        with self.lock:
            if self.gen != gen or self.init is None:    # the last projector left while this connected
                up = None
            else:
                self.gen += 1
                up = self.up = Upstream(sock, self.gen)
                self.cache, self.frame_at = {}, None    # a new session
                out, n = self.next_requests(), len(self.projectors)
        if up is None:
            self.drop(Upstream(sock, gen), "no projector waits any more")
            return
        log("control: connected as the projector, for %d projector%s" % (n, "" if n == 1 else "s"))
        threading.Thread(target=self.read_control, args=(up,), daemon=True).start()
        threading.Thread(target=self.write_control, args=(up,), daemon=True).start()
        self.to_control(up, out)

    def to_control(self, up, batches):
        """never waits on control: past UP_QUEUE bytes waiting, the session is closed"""
        if not up or not batches:
            return
        with up.cv:
            if up.closed:
                return
            up.q.extend(batches)
            up.size += sum(len(b) for b in batches)
            over = up.size
            up.cv.notify()
        if over > UP_QUEUE:
            self.close_up("control takes nothing (%d bytes wait for it)" % over, up)

    def write_control(self, up):
        """the relay's whole batches to control, never from the reader: a send can wait, the reader must not"""
        try:
            while True:
                with up.cv:
                    while not up.q and not up.closed:
                        up.cv.wait()
                    if up.closed:
                        return
                    q, up.q, up.size = up.q, collections.deque(), 0
                up.sock.sendall(b"".join(q))            # UP_WAIT s at most for room
        except OSError as ex:
            self.close_up("could not send to control (%s)" % ex, up)

    def read_control(self, up):
        buf, why = bytearray(), "the reader stopped"
        try:
            while True:
                try:
                    data = up.sock.recv(1 << 20)
                except socket.timeout:                  # control is quiet: not a fault
                    continue
                if not data:
                    raise OSError("control closed the connection")
                buf += data
                for name, body in unpack(buf, BATCH_MAX):
                    self.from_control(up, name, body)
        except (OSError, ValueError) as ex:
            why = str(ex)
        finally:
            self.close_up(why, up)

    def from_control(self, up, name, body):
        data, now = pack(name, body), time.time()
        with self.lock:
            if self.up is not up:                       # an older session's reader: nothing of it counts now
                return
            if name == "INIT REPLY":                    # control's answer to the relay's INIT: each projector had its own
                ok = body == b"OK\0"
            elif name == FRAME:
                self.frame_at = now
            elif name == "FORCE_END":
                for n in MATCH:
                    self.cache.pop(n, None)
                self.frame_at = None
            elif name != "TRUNCATION":
                if name in MATCH:                       # a new match: its own clock, from its first frame
                    self.frame_at = None
                    self.ready_sent = False
                self.cache[name] = data
            done = [n for n in self.asked if reply_of(n) == name]
            for n in done:
                del self.asked[n]
            out = self.next_requests() if done else []
            if name != "INIT REPLY":
                for p in self.projectors:
                    p.put(name, data)
        if name == "INIT REPLY":
            if not ok:
                log("control answered the relay's INIT with %r" % body[:32])
            return
        if name == "CONTROL_STATE":
            out.append(self.keep_alive)
        self.to_control(up, out)

    def close_up(self, why, up=None):
        """the session closed (up: only if it is still that one); its requests on their way wait for the next one"""
        with self.lock:
            if self.up is None or (up is not None and self.up is not up):
                return
            up, self.up, self.gen = self.up, None, self.gen + 1
            self.pending.extendleft(reversed([(n, d) for n, (d, _) in self.asked.items()]))
            self.asked = {}
        self.drop(up, why)

    def drop(self, up, why):
        """an Upstream taken out of the hub: its writer stops, its socket shut (no lock held)"""
        with up.cv:
            up.closed = True
            up.cv.notify_all()
        try:
            up.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            up.sock.close()
        except OSError:
            pass
        log("control: connection closed (%s)" % why)


TCP_MAXRT = 5                       # Windows' IPPROTO_TCP option: seconds a connection resends before it gives up


def patience(conn):
    """on Windows the projector's connection resends for STUCK s, as the hook has the projector's own end do
    (source\\hook\\wccfk.c patience_tcp): Windows' own gives up at ~24 s, long before STUCK (2026-10-17)"""
    if os.name != "nt":
        return True
    try:
        conn.setsockopt(socket.IPPROTO_TCP, TCP_MAXRT, int(STUCK))
        return True
    except OSError as ex:
        log("projector: Windows refused the link's waiting time (%s) - its own (~24 s) stays" % ex)
        return False


def serve(hub, conn, peer):
    p = Projector(conn, peer)
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        patience(conn)
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, QUEUE)     # a short kernel queue: the relay sheds, not it
        conn.settimeout(STUCK)
        threading.Thread(target=p.write, args=(hub,), daemon=True).start()
        buf, second, n = bytearray(), int(time.time()), 0
        while True:
            try:
                data = conn.recv(65536)
            except socket.timeout:                      # a projector says little until control talks: not a fault
                continue
            if not data:
                break
            buf += data
            for name, body in unpack(buf, 8 + 4 * (20 + BODY_MAX)):
                if int(time.time()) != second:
                    second, n = int(time.time()), 0
                n += 1
                if n > FLOOD:
                    raise ValueError("more than %d messages a second" % FLOOD)
                if n > RATE:                            # a burst (a link back after a drop): the rest of it stays here
                    if not p.shed_rate:
                        p.shed_rate = True
                        log("projector %s: more than %d messages a second - the rest of that second's dropped" %
                            (p.peer, RATE))
                    continue
                hub.from_projector(p, name, body)
    except (OSError, ValueError) as ex:
        p.why = p.why or str(ex)
    finally:                                            # whatever stopped the reader, the projector is let go
        hub.leave(p)


def main(argv):
    global log_file
    life = float(argv[0]) if argv else 12 * 3600
    log_file = argv[1] if len(argv) > 1 else None
    path = os.environ.get("WCCF_CONTROL_LOG") or (                  # control's debug log, as the seat desk reads it
        os.path.join(os.path.dirname(os.path.abspath(log_file)), "_dbg_control.txt") if log_file else "")
    hub = Hub(InGame(path))
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name != "nt":     # Linux keeps the last run's links in TIME_WAIT ~60 s: a quick restart could not listen
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)   # (2026-10-17, on the Linux server); on Windows it
    try:                                                            # would let a second relay share the port, so not there
        srv.bind(("0.0.0.0", PORT))
    except OSError as ex:
        log("cannot listen on TCP %d (%s) - is a projector relay already running?" % (PORT, ex))
        return 1
    srv.listen(16)
    srv.settimeout(1.0)
    log("projector relay listening on TCP %d: every player's projector, through one connection to control" % PORT)
    end, next_tick = time.time() + life, 0.0
    while time.time() < end:
        if time.time() >= next_tick:
            hub.tick()
            next_tick = time.time() + 1.0
        try:
            conn, addr = srv.accept()
        except OSError:                                 # socket.timeout too
            continue
        threading.Thread(target=serve, args=(hub, conn, "%s:%d" % addr), daemon=True).start()
    log("projector relay: its time is up - stopping")
    hub.close_up("the relay stops")
    srv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
