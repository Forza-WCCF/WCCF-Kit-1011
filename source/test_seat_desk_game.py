# -*- coding: utf-8 -*-
"""test_seat_desk_game.py - the seat desk (scripts\\_seat_broker.py) never gives a seat that is in the game: a scratch
"control debug log" is written line by line as the game would, and the real desk answers on a test port (check.ps1
runs it; nothing of the game runs).  The PCs asking are 127.0.0.1; the cabinets already in the game are 10.0.0.5.
    python source\\test_seat_desk_game.py"""
import os
import socket
import subprocess
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 20932
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name, ("  - " + detail) if detail else ""))


def ask(line):
    """one request -> (the answer, the open socket: the seat stays while it is open)"""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    s.sendall(line.encode("ascii") + b"\n")
    return s.recv(256).decode("ascii").strip(), s


def joined(seat, ip):
    return ("t+  9.00s INFO  ClientManage  ClientManage::INIT() : client[0] : sateID=%d,version=7128,serial=PC\n"
            "t+  9.00s INFO  ClientManage  ClientManage::INIT() : ++ACCEPT++  '%s:4000', 2026/10/9(Fri) 18:20:43\n"
            % (seat, ip))


def left(seat):
    return "t+ 99.00s INFO  ClientManage  ClientManage::INIT(): ---DISCONNECT--- sateID=%d,sockID=0, 2026/10/9(Fri) 18:42:56\n" % seat


tmp = tempfile.mkdtemp(prefix="seatgame_")
game = os.path.join(tmp, "_dbg_control.txt")
deskl = os.path.join(tmp, "seat_broker.txt")
env = dict(os.environ, WCCF_BROKER_PORT=str(PORT), WCCF_BROKER_SILENT="30")
desk = subprocess.Popen([sys.executable, "-B", os.path.join(KIT, "scripts", "_seat_broker.py"), "60", deskl], env=env,
                        stdout=subprocess.DEVNULL)
socks = []
try:
    time.sleep(1.0)
    a, s = ask("WANT")
    socks.append(s)
    check("no game log yet (control not started): seat 1 + the projector, as before", a == "SEAT 1 PROJECTOR 1", a)
    s.close()
    socks.clear()
    time.sleep(0.3)

    with open(game, "w", encoding="utf-8") as f:                  # the desk finds it beside its own log
        f.write("t+  0.10s DEBUG  start\n" + joined(0, "10.0.0.5") + joined(1, "10.0.0.5"))
    a, s = ask("WANT")
    socks.append(s)
    check("seat 1 and the projector in the game from another address, no lease: seat 2, no projector",
          a == "SEAT 2 PROJECTOR 0", a)
    a, s = ask("WANT SEAT 1")
    socks.append(s)
    check("WANT SEAT 1 while another address has it in the game: TAKEN 1", a == "TAKEN 1", a)

    with open(game, "a", encoding="utf-8") as f:
        f.write(joined(3, "127.0.0.1"))
    a, s = ask("WANT SEAT 3")
    socks.append(s)
    check("the same address takes its own seat back (in the game, lease lost with the old desk): SEAT 3", a == "SEAT 3 PROJECTOR 0", a)

    with open(game, "a", encoding="utf-8") as f:
        f.write(left(1) + left(0) + "t+ 99.50s INFO  ClientManage  ClientManage::INIT() : client[0] : sateID=5")
    a, s = ask("WANT")
    socks.append(s)
    check("seat 1 and the projector left the game: seat 1 + the projector again", a == "SEAT 1 PROJECTOR 1", a)

    with open(game, "a", encoding="utf-8") as f:                  # the half line ends; seat 5 joins from elsewhere
        f.write(",version=7128,serial=PC\nt+ 99.60s INFO  ClientManage  ClientManage::INIT() : ++ACCEPT++  '10.0.0.5:4001', 2026/10/9(Fri) 18:43:00\n")
    a, s = ask("WANT")
    socks.append(s)
    check("a line read half-written, finished later, still counts: seat 4 (5 is in the game)", a == "SEAT 4 PROJECTOR 0", a)
    a, s = ask("WANT")
    socks.append(s)
    check("the next: seat 6 (5 skipped)", a == "SEAT 6 PROJECTOR 0", a)

    for x in socks:
        x.close()
    socks.clear()
    time.sleep(0.5)
    with open(game, "w", encoding="utf-8") as f:                  # control restarted: a new, shorter log
        f.write("t+  0.10s DEBUG  start\n" + joined(2, "10.0.0.5"))
    a, s = ask("WANT")
    socks.append(s)
    b, s2 = ask("WANT")
    socks.append(s2)
    check("a new run's log is read from its start (old seats gone; 2 in the game): seats 1 and 3", (a, b) ==
          ("SEAT 1 PROJECTOR 1", "SEAT 3 PROJECTOR 0"), "%s / %s" % (a, b))

    os.remove(game)
    for x in socks:
        x.close()
    socks.clear()
    time.sleep(0.5)
    a, s = ask("WANT")
    socks.append(s)
    check("the game log gone: nobody in the game, seat 1 + the projector", a == "SEAT 1 PROJECTOR 1", a)
    with open(deskl, encoding="utf-8") as f:
        text = f.read()
    check("the desk's log says why seats were skipped and refused",
          "skipped - in the game (10.0.0.5)" in text and "(in the game by 10.0.0.5)" in text, "")
finally:
    for x in socks:
        x.close()
    desk.kill()
    desk.wait()
print("seat desk vs the game: %d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
