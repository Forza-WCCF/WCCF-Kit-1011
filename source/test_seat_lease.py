# -*- coding: utf-8 -*-
"""test_seat_lease.py - the seat lease reconnects and re-claims its seat after the desk connection breaks (A5).
A tiny fake seat desk on loopback hands out seat 3, then drops the first connection; the lease must come back with
"WANT SEAT 3" (check.ps1 runs it; loopback only, no game, no real desk).
    python source\\test_seat_lease.py"""
import json
import os
import socket
import sys
import tempfile
import threading
import time

# a free loopback port, and fast timers, BEFORE importing the lease (it reads these at import)
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
PORT = _s.getsockname()[1]
_s.close()
os.environ["WCCF_BROKER_PORT"] = str(PORT)
os.environ["WCCF_LEASE_PING"] = "0.2"
os.environ["WCCF_LEASE_RETRY"] = "0.2"

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import _seat_lease as L  # noqa: E402

fails = []
claims = []                     # the first line of every connection the fake desk received


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


def fake_desk(srv, stop):
    srv.settimeout(0.2)
    n = 0
    while not stop[0]:
        try:
            c, _ = srv.accept()
        except OSError:                              # timeout, or the listening socket closed at shutdown
            continue
        n += 1
        threading.Thread(target=handle, args=(c, n), daemon=True).start()


def handle(c, n):
    c.settimeout(5)
    buf = bytearray()

    def line():
        while b"\n" not in buf:
            d = c.recv(256)
            if not d:
                raise OSError("closed")
            buf.extend(d)
        i = buf.index(b"\n")
        out = bytes(buf[:i])
        del buf[:i + 1]
        return out

    try:
        claims.append(line().decode())
        c.sendall(b"SEAT 3 PROJECTOR 0\n")
        pings = 0
        while True:
            if line() == b"PING":
                pings += 1
                if n == 1:                       # the first connection: drop it after one ping, to force a reconnect
                    c.close()
                    return
                c.sendall(b"PONG\n")
    except OSError:
        pass
    finally:
        try:
            c.close()
        except OSError:
            pass


srv = socket.socket()
srv.bind(("127.0.0.1", PORT))
srv.listen(8)
stop = [False]
threading.Thread(target=fake_desk, args=(srv, stop), daemon=True).start()

t = tempfile.mkdtemp(prefix="wccf-lease-")
try:
    out = os.path.join(t, "seat_lease.json")
    lease = threading.Thread(target=L.main, args=(["127.0.0.1", out, "2.5", "3"],), daemon=True)
    lease.start()
    lease.join(timeout=8)
    check(not lease.is_alive(), "the lease finished within its life (did not hang)")
    got = json.load(open(out))
    check(got == {"seat": 3, "projector": 0}, "the lease wrote its seat once: %r" % got)
    check(len(claims) >= 2, "the lease reconnected after the drop (got %d connections)" % len(claims))
    check(all(c == "WANT SEAT 3" for c in claims), "every claim re-asked for the same seat 3: %r" % claims)
finally:
    stop[0] = True
    srv.close()
    import shutil
    shutil.rmtree(t, ignore_errors=True)

n = 4
print("seat_lease: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
