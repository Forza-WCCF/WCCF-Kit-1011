# -*- coding: utf-8 -*-
"""test_accept_no_address.py - a connection that comes with NO address must not stop a server helper (2026-11-17).
Under Wine, accept() sometimes answers (conn, None) - a connection reset before it was taken, an internet scanner.
On 2026-11-13 that killed the live server's seat desk ("%s:%d" % None), projector relay and log inbox: for four days
no finished match earned a card (no signed-in seat), SEND LOGS reached nobody.  Each helper's real main() runs here
with a listening socket whose accept() gives (conn, None) once, then a normal address: it must close the first,
serve on, and end only when its time is up.  No network, no game.
    python source\\test_accept_no_address.py"""
import os
import socket
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
TMP = tempfile.mkdtemp(prefix="wccf-no-address-")
LOGS = os.path.join(TMP, "logs")
os.makedirs(LOGS)
os.environ.update({"WCCF_HOLD_FILE": os.path.join(TMP, "no_hold.txt"), "WCCF_REQUIRE_FILE": os.path.join(TMP, "no_req.txt"),
                   "WCCF_LEASES_FILE": os.path.join(TMP, "leases.json"),
                   "WCCF_CONTROL_LOG": os.path.join(TMP, "_dbg_control.txt")})
from server import log_inbox, projector_relay, seat_desk  # noqa: E402

REAL = socket.socket


class Conn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    def __getattr__(self, name):            # a served connection: the other side has already closed it
        return lambda *_a, **_k: b""


class Listener:
    """a server socket: accept() gives (conn, None), then (conn, a normal address), then only timeouts"""
    def __init__(self, *_a, **_k):
        self.given = [(Conn(), None), (Conn(), ("203.0.113.9", 4321))]
        self.first = self.given[0][0]
        Listener.last = self

    def accept(self):
        if self.given:
            return self.given.pop(0)
        time.sleep(0.05)
        raise socket.timeout()

    def __getattr__(self, name):            # bind, listen, settimeout, setsockopt, close
        return lambda *_a, **_k: None


def run(name, mod, argv):
    socket.socket = Listener
    try:
        rc = mod.main(argv)
    except Exception as ex:                 # the bug: the helper's loop dies
        return "FAIL %s: died - %s: %s" % (name, type(ex).__name__, ex)
    finally:
        socket.socket = REAL
    lst = Listener.last
    if rc != 0:
        return "FAIL %s: returned %r" % (name, rc)
    if lst.given:
        return "FAIL %s: stopped taking connections" % name
    if not lst.first.closed:
        return "FAIL %s: the no-address connection was left open" % name
    return "ok   %s: no-address connection closed, served on, ended when its time was up" % name


results = [run("seat desk", seat_desk, ["0.6", os.path.join(LOGS, "seat_broker.txt")]),      # text, as play.py
           run("projector relay", projector_relay, ["0.6", os.path.join(LOGS, "projector_relay.txt")]),   # passes it
           run("log inbox", log_inbox, ["0.6", os.path.join(LOGS, "log_inbox.txt"), os.path.join(TMP, "inbox")])]
print("\n".join(results))
bad = [r for r in results if not r.startswith("ok")]
print("%d/%d passed" % (len(results) - len(bad), len(results)))
sys.exit(1 if bad else 0)
