# -*- coding: utf-8 -*-
"""test_projector_relay.py - the projector relay (code\\server\\projector_relay.py) between a fake control and fake
projectors, all on 127.0.0.1: the relay on 20960, control on 20961, a scratch control debug log saying who is in the
game (check.ps1 runs it; nothing of the game runs).
    python source\\test_projector_relay.py"""
import os
import socket
import struct
import sys
import tempfile
import threading
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
RELAY, CONTROL = 20960, 20961
tmp = tempfile.mkdtemp(prefix="projrelay_")
CONTROL_LOG = os.path.join(tmp, "_dbg_control.txt")
os.environ.update(WCCF_PROJECTOR_PORT=str(RELAY), WCCF_CONTROL_PORT=str(CONTROL), WCCF_CONTROL_LOG=CONTROL_LOG,
                  WCCF_PROJECTOR_STUCK="3", WCCF_PROJECTOR_HARD=str(256 * 1024))
from server import projector_relay as P  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name, ("  - " + str(detail)) if detail else ""))


def wait_for(fn, secs=4.0):
    end = time.time() + secs
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return bool(fn())


class Peer:
    """one end of a connection: every record it gets, read by a thread (paused = it reads nothing)"""

    def __init__(self, sock):
        self.sock, self.got, self.eof, self.go = sock, [], False, threading.Event()
        self.go.set()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        buf = bytearray()
        try:
            while True:
                self.go.wait()
                data = self.sock.recv(65536)
                if not data:
                    break
                buf += data
                self.got += P.unpack(buf, P.BATCH_MAX)
        except (OSError, ValueError):
            pass
        self.eof = True

    def send(self, *records):
        self.sock.sendall(b"".join(P.pack(n, b) for n, b in records))

    def names(self):
        return [n for n, _ in self.got]


def projector(small=False):
    s = socket.socket()
    if small:                                           # a slow PC: little room on its side either
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    s.connect(("127.0.0.1", RELAY))
    return Peer(s)


control = {}


def fake_control():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", CONTROL))
    srv.listen(4)
    while True:
        c, _ = srv.accept()
        control.setdefault("all", []).append(c)
        control["peer"] = Peer(c)


def player_in():
    with open(CONTROL_LOG, "a", encoding="utf-8") as f:
        f.write("t+  9.00s INFO  ClientManage  ClientManage::INIT() : client[0] : sateID=1,version=7128,serial=PC\n"
                "t+  9.00s INFO  ClientManage  ClientManage::INIT() : ++ACCEPT++  '10.0.0.5:4000', 2026/10/17\n")


def frame(i):
    return ("TO MATCH", struct.pack("<I", i) + bytes(280))


INIT = struct.pack("<5I", 0, 7128, 0, 0, 6) + bytes(12)        # seat 0, version 7128, [4] = 6 (a 4-seat cabinet)

# the wire helpers: one record per batch out; a batch of two records in
two = struct.pack("<II16sI", 2, 8 + 20 + 3 + 20 + 1, b"A", 3) + b"abc" + struct.pack("<16sI", b"B", 1) + b"z"
buf = bytearray(two + b"\x01")
check("a batch of two records reads as two, the next batch's start kept", P.unpack(buf, 1 << 19) ==
      [("A", b"abc"), ("B", b"z")] and buf == b"\x01")
try:
    P.unpack(bytearray(struct.pack("<II", 1, 0x9F5406C1)), 1 << 19)
    check("a wild length is not a batch", False)
except ValueError:
    check("a wild length is not a batch", True)
check("the seat-count field: 6 (4 seats) becomes 0 (8 seats); 2 (8 seats already) is kept",
      struct.unpack_from("<I", P.eight_seats(INIT), 16)[0] == 0 and P.eight_seats(INIT[:16] + struct.pack("<I", 2))[16:20]
      == struct.pack("<I", 2))

open(CONTROL_LOG, "w").close()                                  # control runs, nobody in the game
threading.Thread(target=fake_control, daemon=True).start()
threading.Thread(target=P.main, args=(["120", os.path.join(tmp, "projector_relay.txt")],), daemon=True).start()
time.sleep(0.8)

a = projector()
a.send(("INIT", INIT))
check("A's INIT is answered by the relay: INIT REPLY \"OK\\0\"", wait_for(lambda: a.got[:1] == [("INIT REPLY", b"OK\0")]),
      a.got)
time.sleep(1.5)
check("no player in the game: control is not connected yet", "peer" not in control)
player_in()
check("a player in: the relay connects to control", wait_for(lambda: "peer" in control and control["peer"].got))
ctl = control.get("peer")
first = ctl.got[0] if ctl and ctl.got else ("", b"")
check("... with A's INIT, its seat-count field set to 8 seats (0), the rest as A sent it",
      first[0] == "INIT" and first[1] == P.eight_seats(INIT) and first[1][:16] == INIT[:16], first)

b = projector(small=True)
b.send(("INIT", INIT))
check("B's INIT is answered by the relay too", wait_for(lambda: b.names()[:1] == ["INIT REPLY"]))
time.sleep(0.3)
check("control never sees a second INIT", ctl.names() == ["INIT"], ctl.names())

ctl.send(("INIT REPLY", b"OK\0"), ("CONTROL_STATE", b"s1"), ("GAME_CTRL", b"g" * 844), ("LOGSVR_INFO", b"l" * 18))
ctl.send(("CONTROL_STATE", b"s2"))
a.send(("KEEP_ALIVE", b"\x01"))
b.send(("KEEP_ALIVE", b"\x01"))
ctl.send(("CONTROL_STATE", b"s3"))
check("one KEEP_ALIVE to control per CONTROL_STATE, the relay's own; the projectors' stay here",
      wait_for(lambda: ctl.names().count("KEEP_ALIVE") == 3) and (time.sleep(0.3) or ctl.names().count("KEEP_ALIVE") == 3)
      and ctl.got[-1] == ("KEEP_ALIVE", b"\x01"), ctl.names())
check("both projectors get control's messages (a newer CONTROL_STATE may replace one still waiting)",
      wait_for(lambda: a.got[-1:] == b.got[-1:] == [("CONTROL_STATE", b"s3")] and "GAME_CTRL" in a.names() + b.names()))

check("control's own INIT REPLY stays in the relay: each projector has one", wait_for(
    lambda: "LOGSVR_INFO" in a.names()) and a.names().count("INIT REPLY") == b.names().count("INIT REPLY") == 1, a.names())
a.send(("REQ_RNK_ACP_INF", b"1"))
b.send(("REQ_RNK_ACP_INF", b"1"))
time.sleep(0.4)
check("the same request from two projectors goes to control once", ctl.names().count("REQ_RNK_ACP_INF") == 1,
      ctl.names())
ctl.send(("RNK_STATE", b"ranking"))
ctl.send(("RNK_ACP_STATE", b"ranking"))
check("control's reply goes to both", wait_for(lambda: ("RNK_ACP_STATE", b"ranking") in a.got and
                                              ("RNK_ACP_STATE", b"ranking") in b.got))
a.send(("REQ_RNK_ACP_INF", b"2"))
check("after the reply, a new request of that name goes", wait_for(lambda: ctl.names().count("REQ_RNK_ACP_INF") == 2))

ctl.send(("LIVE_INFO", b"L" * 8), ("TO MATCH INI", b"I" * 8524), frame(0), frame(1), ("TRUNCATION", b""))
check("A gets the match", wait_for(lambda: a.names()[-3:] == ["TO MATCH", "TO MATCH", "TRUNCATION"]))
c = projector()
c.send(("INIT", INIT))
time.sleep(0.3)
ctl.send(frame(2))
want = ["INIT REPLY", "CONTROL_STATE", "GAME_CTRL", "LOGSVR_INFO", "RNK_STATE", "RNK_ACP_STATE", "LIVE_INFO",
        "TO MATCH INI", "TO MATCH"]
check("a projector that joins mid-match: what it missed, in control's order, INI before the live frames",
      wait_for(lambda: c.names() == want) and c.got[1] == ("CONTROL_STATE", b"s3") and c.got[-1] == frame(2), c.names())

# B stops reading: A keeps getting every frame at once, B's oldest frames go; a new match's INI is never dropped
b.go.clear()
time.sleep(0.2)
before = len(b.got)
t0 = time.time()
for k in range(0, 2000, 10):                                    # ~1,000 frames a second: 15-30 times the game's rate
    ctl.send(*[frame(1000 + i) for i in range(k, k + 10)])
    time.sleep(0.01)
ctl.send(("TO MATCH INI", b"J" * 8524), *[frame(5000 + i) for i in range(50)])
got_all = wait_for(lambda: a.got[-1:] == [frame(5049)], 4.0)
late = len([1 for n, d in a.got if n == "TO MATCH" and struct.unpack_from("<I", d)[0] >= 1000])
check("B stalled: A still gets all 2,050 frames and the new INI, at once",
      got_all and late == 2050 and ("TO MATCH INI", b"J" * 8524) in a.got and time.time() - t0 < 5.0,
      "%.1f s, %d frames" % (time.time() - t0, late))
b.go.set()
check("B reads again: it gets the end of the stream", wait_for(lambda: b.got[-1:] == [frame(5049)], 4.0))
mine = b.got[before:]
frames = [n for n, _ in mine].count("TO MATCH")
ini = mine.index(("TO MATCH INI", b"J" * 8524)) if ("TO MATCH INI", b"J" * 8524) in mine else -1
check("B: its oldest frames were shed (%d of 2,050 came)" % frames, frames < 2050)
check("B: the new match's INI kept, and before every frame of that match", ini >= 0 and all(
    struct.unpack_from("<I", d)[0] < 5000 for n, d in mine[:ini] if n == "TO MATCH"), ini)

# B stops for good: cut once its socket takes nothing for STUCK s; A and control's connection go on
b.go.clear()
stop = time.time() + 6
while time.time() < stop and not wait_for(lambda: False, 0.02):
    ctl.send(*[frame(9000 + i) for i in range(20)])
b.go.set()
check("B, stuck: cut by the relay", wait_for(lambda: b.eof, 8.0))
ctl.send(("CONTROL_STATE", b"s4"))
check("... while A plays on and control's connection stays", wait_for(lambda: a.got[-1:] == [("CONTROL_STATE", b"s4")])
      and len(control["all"]) == 1 and not ctl.eof)

# a projector's GAME_READY as a match starts (2026-10-17 live run: the relay cut the projector for it - Error 3000)
a.send(("GAME_READY", b"r"))
c.send(("GAME_READY", b"r"))
check("GAME_READY from two projectors: control gets one, nobody is cut",
      wait_for(lambda: ctl.names().count("GAME_READY") == 1) and (time.sleep(0.3) or
      ctl.names().count("GAME_READY") == 1) and not a.eof and not c.eof, ctl.names().count("GAME_READY"))
ctl.send(("LIVE_INFO", b"L2"), ("TO MATCH INI", b"K" * 8524))
wait_for(lambda: ("TO MATCH INI", b"K" * 8524) in a.got)
a.send(("GAME_READY", b"r"))
check("... and one again for the next match", wait_for(lambda: ctl.names().count("GAME_READY") == 2))
a.send(("TEAM DATA", b"x"))
check("any other message of a joined projector stays here: not cut", (time.sleep(0.3) or True) and not a.eof)
check("... and control never sees it", "TEAM DATA" not in ctl.names())
a.send(*[("KEEP_ALIVE", b"\x01")] * (P.RATE + 50))
check("a burst over RATE messages a second (a link back after a drop): the rest dropped, not cut",
      (time.sleep(0.5) or True) and not a.eof)
a.sock.shutdown(socket.SHUT_RDWR)
c.sock.shutdown(socket.SHUT_RDWR)
check("the last projector leaves: control's connection is closed", wait_for(lambda: ctl.eof))

# ---- the 2026-10-17 review's cases, each once (loopback first, then a Hub of their own with no relay around it)
BAD = struct.pack("<II16sI", 2, 48, b"X", 20) + bytes(20)      # two records declared, the first fills the batch
try:
    P.unpack(bytearray(BAD), 1 << 19)
    check("a record past its batch's end is not a batch", False)
except ValueError:
    check("a record past its batch's end is not a batch", True)
d = projector()
d.send(("INIT", INIT))
check("a new projector: control is reached again", wait_for(lambda: len(control["all"]) == 2 and control["peer"].got))
ctl2 = control["peer"]
ctl2.sock.sendall(BAD)
check("control sends a bad batch: that connection is closed and a new one opened", wait_for(
    lambda: ctl2.eof and len(control["all"]) == 3 and control["peer"].names()[:1] == ["INIT"], 6.0),
    len(control["all"]))
e = projector()
e.send(("INIT", INIT))
wait_for(lambda: e.names()[:1] == ["INIT REPLY"])
e.sock.sendall(BAD)
control["peer"].send(("CONTROL_STATE", b"s5"))
check("a projector sends a bad batch: it is let go, the others go on", wait_for(lambda: e.eof) and wait_for(
    lambda: ("CONTROL_STATE", b"s5") in d.got))
d.sock.shutdown(socket.SHUT_RDWR)
wait_for(lambda: control["peer"].eof)


class Game:
    def now(self):
        return [1]                                  # a player in the game


class Fake:
    """a projector as the hub sees it, keeping what it is given"""

    def __init__(self):
        self.got, self.joined, self.why, self.shed, self.peer = [], False, "", 0, "fake"

    def put(self, name, data, head=False):
        self.got.append((name, data))

    def close(self):
        pass


def session(h, read=True):
    """a session with a control of socketpair()'s other end, as tick() would open it"""
    u, c = socket.socketpair()
    u.settimeout(P.UP_WAIT)
    with h.lock:
        h.gen += 1
        up = h.up = P.Upstream(u, h.gen)
    threading.Thread(target=h.write_control, args=(up,), daemon=True).start()
    return up, (Peer(c) if read else c)


# a protected-message flood: cut, never more than HARD bytes held
u, c = socket.socketpair()
u.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
u.settimeout(P.STUCK)
fp, h, most = P.Projector(u, "flood"), P.Hub(Game()), 0
threading.Thread(target=fp.write, args=(h,), daemon=True).start()
for k in range(150):                                            # 150 INIs, 1.3 MB, to a PC that reads nothing
    fp.put(P.INI, P.pack(P.INI, bytes([k]) * 8524))
    most = max(most, fp.size)
check("150 INIs to a PC that reads nothing: the older matches' go, never more than QUEUE and one INI held, not cut",
      not fp.closed and most <= P.QUEUE + 8600 and P.INI in [n for n, _ in fp.q], "%d bytes at most" % most)
fp.close()                                                      # its STUCK cut: "B, stuck" above

# control reads nothing: the session is closed, control's reader never waits
h = P.Hub(Game())
up, c = session(h, read=False)
c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
t0 = time.time()
for k in range(20000):                                          # each wants a KEEP_ALIVE sent: 580 kB
    h.from_control(up, "CONTROL_STATE", b"s" * 300)
took = time.time() - t0
check("control reads nothing: its session is closed, its reader never held up", wait_for(lambda: h.up is None, 8.0)
      and took < 3.0 and up.closed, "%.2f s for 20,000 messages" % took)

# a reader of an older session changes nothing
h, f = P.Hub(Game()), Fake()
h.from_projector(f, "INIT", INIT)
old, _ = session(h)
h.from_control(old, P.INI, b"old")
h.close_up("test", old)
new, _ = session(h)
h.from_control(new, P.INI, b"new")
h.from_control(old, P.INI, b"old, late")
check("an older session's reader: the cache and the projectors never see it",
      h.cache.get(P.INI) == P.pack(P.INI, b"new") and (P.INI, P.pack(P.INI, b"old, late")) not in f.got)

# the last projector leaves while another joins: the joiner gets a session of its own
h, f1, f2 = P.Hub(Game()), Fake(), Fake()
h.from_projector(f1, "INIT", INIT)
up1, _ = session(h)
drop = h.drop


def join_then_drop(up, why):                                    # the join lands between the decision and the close
    h.from_projector(f2, "INIT", INIT[:20] + b"2" * 12)
    drop(up, why)


h.drop = join_then_drop
h.leave(f1)
h.drop = drop
n = len(control["all"])
h.tick()
check("the last one leaves as another joins: the old session closed, the joiner's opened",
      up1.closed and h.up is not None and h.up is not up1 and h.init == INIT[:20] + b"2" * 12 and
      wait_for(lambda: len(control["all"]) == n + 1))
h.close_up("test")

# the last projector leaves while tick() connects: that connection is closed at once
h, f = P.Hub(Game()), Fake()
h.from_projector(f, "INIT", INIT)
connect = socket.create_connection


def leave_then_connect(*args, **kw):
    h.leave(f)
    return connect(*args, **kw)


P.socket.create_connection = leave_then_connect
n = len(control["all"])
try:
    h.tick()
finally:
    P.socket.create_connection = connect
check("the last one leaves while control is being reached: that connection is closed, none kept",
      h.up is None and wait_for(lambda: len(control["all"]) == n + 1 and control["peer"].eof))

# requests: one before control is there waits for it; two of one name both go, each after the other's reply
h, f = P.Hub(Game()), Fake()
h.from_projector(f, "INIT", INIT)
h.request("REQ_CMN_USR_INF", b"early")
h.tick()
check("a request before control's connection is open goes once it is",
      wait_for(lambda: control["peer"].names() == ["INIT", "REQ_CMN_USR_INF"]), control["peer"].names())
h.close_up("test")
h, f = P.Hub(Game()), Fake()
h.from_projector(f, "INIT", INIT)
up, cp = session(h)
h.request("REQ_RNK_ACP_INF", b"page 1")
h.request("REQ_RNK_ACP_INF", b"page 2")
h.request("REQ_RNK_ACP_INF", b"page 2")
time.sleep(0.3)
first = list(cp.got)
h.from_control(up, "CMN_USR_STATE", b"other")
h.from_control(up, "CONTROL_STATE", b"s")
time.sleep(0.3)
second = list(cp.got)
h.from_control(up, "RNK_ACP_STATE", b"page 1")
check("two different requests of one name: the second waits for the first's reply (not any other), then goes",
      first == [("REQ_RNK_ACP_INF", b"page 1")] and second == first + [("KEEP_ALIVE", b"\x01")] and
      wait_for(lambda: cp.got[2:] == [("REQ_RNK_ACP_INF", b"page 2")]) and (time.sleep(0.3) or len(cp.got) == 3),
      cp.got)
h.close_up("test")

# the replay: a CONTROL_STATE before the joiner's writer runs goes after it, never into it
h = P.Hub(Game())
h.from_projector(Fake(), "INIT", INIT)
up, _ = session(h)
for n_, b_ in (("INIT REPLY", b"OK\0"), ("CONTROL_STATE", b"s1"), ("GAME_CTRL", b"g"), ("LOGSVR_INFO", b"l"),
               ("LIVE_INFO", b"L"), (P.INI, b"I")):
    h.from_control(up, n_, b_)
u, c = socket.socketpair()
jp = P.Projector(u, "joiner")                                   # its writer not started yet
h.from_projector(jp, "INIT", INIT)
h.from_control(up, "CONTROL_STATE", b"s2")
order = [(n_, P.unpack(bytearray(d_), 1 << 19)[0][1]) for n_, d_ in jp.q]
check("a joiner's replay stays whole and in order; control's INIT REPLY is not in it", order == [
    ("INIT REPLY", b"OK\0"), ("CONTROL_STATE", b"s1"), ("GAME_CTRL", b"g"), ("LOGSVR_INFO", b"l"), ("LIVE_INFO", b"L"),
    (P.INI, b"I"), ("CONTROL_STATE", b"s2")], order)

# a new match's INI is not cleared by the last match's clock
h.from_control(up, P.FRAME, frame(0)[1])
h.frame_at -= 20                                                # the last match's frames stopped 20 s ago
h.from_control(up, "LIVE_INFO", b"M")
h.from_control(up, P.INI, b"J")                                 # the next match begins before tick() looks
h.tick()
kept = h.cache.get(P.INI) == P.pack(P.INI, b"J")
h.from_control(up, P.FRAME, frame(1)[1])
h.frame_at -= 20
h.tick()
check("a new match's INI outlives the last match's clock; its own frames stopping clear it",
      kept and P.INI not in h.cache)
h.close_up("test")

# Windows: an accepted projector socket resends for STUCK s, not Windows' ~24 s (TCP_MAXRT; elsewhere nothing to set)
import inspect  # noqa: E402
ls = socket.create_server(("127.0.0.1", 0))
cl = socket.create_connection(ls.getsockname())
sv, _ = ls.accept()
ok = P.patience(sv)
got = sv.getsockopt(socket.IPPROTO_TCP, P.TCP_MAXRT) if os.name == "nt" else None
check("the relay's projector socket keeps resending for STUCK s (Windows: TCP_MAXRT)",
      ok and got == (int(P.STUCK) if os.name == "nt" else None) and "patience(conn)" in inspect.getsource(P.serve), got)
for s_ in (sv, cl, ls):
    s_.close()

print("projector relay: %d of %d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
