# -*- coding: utf-8 -*-
"""test_hold_projector.py - the seat desk keeps the projector box out of the game until a player is in it
(scripts\\_seat_broker.py, data\\hold_projector.txt; check.ps1 runs it).  The real desk on 127.0.0.1:20933, a scratch
control log written as the game would, and WCCF_HOLD_FW: the firewall rule's on/off goes to a scratch file instead of
Windows' firewall.  The box is 10.0.0.9; players are 10.0.0.5.
    python source\\test_hold_projector.py"""
import os
import socket
import subprocess
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name, ("  - " + detail) if detail else ""))


def ask(port, line):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(line.encode("ascii") + b"\n")
    out = s.recv(64).decode("ascii").strip()
    s.close()
    return out


def joined(seat, ip):
    return ("t+  9.00s INFO  ClientManage  ClientManage::INIT() : client[0] : sateID=%d,version=7128,serial=PC\n"
            "t+  9.00s INFO  ClientManage  ClientManage::INIT() : ++ACCEPT++  '%s:4000', 2026/10/9(Fri) 18:20:43\n"
            % (seat, ip))


def left(seat):
    return "t+ 99.00s INFO  ClientManage  ClientManage::INIT(): ---DISCONNECT--- sateID=%d,sockID=0, 2026/10/9(Fri) 18:42:56\n" % seat


def fw_lines(fw):
    try:
        with open(fw, encoding="ascii") as f:
            return f.read().split("\n")[:-1]
    except OSError:
        return []


def wait_for(fn, secs=4.0):
    end = time.time() + secs
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.2)
    return fn()


def desk(tmp, port, hold_text, fw):
    logs = os.path.join(tmp, "data", "logs")
    os.makedirs(logs, exist_ok=True)
    if hold_text is not None:
        with open(os.path.join(tmp, "data", "hold_projector.txt"), "w", encoding="ascii") as f:
            f.write(hold_text)
    env = dict(os.environ, WCCF_BROKER_PORT=str(port), WCCF_HOLD_FW=fw)
    p = subprocess.Popen([sys.executable, "-B", os.path.join(KIT, "scripts", "_seat_broker.py"), "60",
                          os.path.join(logs, "seat_broker.txt")], env=env, stdout=subprocess.DEVNULL)
    wait_for(lambda: os.path.exists(os.path.join(logs, "seat_broker.txt")), 5)
    time.sleep(0.5)
    return p, os.path.join(logs, "_dbg_control.txt"), os.path.join(logs, "seat_broker.txt")


procs = []
try:
    tmp = tempfile.mkdtemp(prefix="hold_")
    fw = os.path.join(tmp, "fw.txt")
    p, game, deskl = desk(tmp, 20933, "10.0.0.9\n", fw)
    procs.append(p)
    check("a new run, nobody in the game: the box is held at once (block 10.0.0.9)", fw_lines(fw) == ["block 10.0.0.9"],
          str(fw_lines(fw)))
    check("HOLD -> HOLD 1", ask(20933, "HOLD") == "HOLD 1")
    a = ask(20933, "WANT SEAT 1")
    check("the box still gets its seat and the projector (the hold is on the game's port, not the desk's)",
          a == "SEAT 1 PROJECTOR 1", a)

    with open(game, "w", encoding="utf-8") as f:
        f.write("t+  0.10s DEBUG  start\n" + joined(2, "10.0.0.5"))
    check("a player in the game: lifted within a second or two (open)",
          wait_for(lambda: fw_lines(fw)[-1:] == ["open"]), str(fw_lines(fw)))
    check("HOLD -> HOLD 0", ask(20933, "HOLD") == "HOLD 0")
    with open(game, "a", encoding="utf-8") as f:
        f.write(joined(0, "10.0.0.9") + left(2))
    time.sleep(1.5)
    check("the player leaves while the box is in the game: not held again", fw_lines(fw)[-1:] == ["open"] and
          len(fw_lines(fw)) == 2, str(fw_lines(fw)))
    with open(game, "a", encoding="utf-8") as f:
        f.write(left(0))
    check("the box leaves too, nobody in: held again", wait_for(lambda: fw_lines(fw)[-1:] == ["block 10.0.0.9"]),
          str(fw_lines(fw)))
    with open(game, "w", encoding="utf-8") as f:                    # control restarted: a new, empty run
        f.write("t+  0.10s DEBUG  start\n" + joined(0, "10.0.0.9"))
    time.sleep(1.5)
    check("a run where only the box got in somehow: it counts as in the game - lifted, never fought",
          fw_lines(fw)[-1:] == ["open"], str(fw_lines(fw)))
    with open(deskl, encoding="utf-8") as f:
        text = f.read()
    check("the desk's log says each change", "held - it joins the game once a player is in" in text and
          "let in - a player is in the game" in text, "")
    p.kill(); p.wait()

    tmp2 = tempfile.mkdtemp(prefix="hold_")
    fw2 = os.path.join(tmp2, "fw.txt")
    p, _g, _d = desk(tmp2, 20934, None, fw2)
    procs.append(p)
    check("no hold_projector.txt: nothing held, no rule touched", ask(20934, "HOLD") == "HOLD 0" and not fw_lines(fw2))
    p.kill(); p.wait()

    tmp3 = tempfile.mkdtemp(prefix="hold_")
    fw3 = os.path.join(tmp3, "fw.txt")
    p, _g, _d = desk(tmp3, 20935, "not an address 999", fw3)
    procs.append(p)
    check("a hold file without an address: nothing held", ask(20935, "HOLD") == "HOLD 0" and not fw_lines(fw3))
    p.kill(); p.wait()

    tmp4 = tempfile.mkdtemp(prefix="hold_")
    p, _g, d4 = desk(tmp4, 20936, "10.0.0.9", tmp4)                # WCCF_HOLD_FW is a folder: the rule cannot be set
    procs.append(p)
    time.sleep(1.0)
    with open(d4, encoding="utf-8") as f:
        t4 = f.read()
    check("the rule cannot be set: said, HOLD 0 (the box is not told it is held), seats still given",
          "could not be set" in t4 and ask(20936, "HOLD") == "HOLD 0" and ask(20936, "WANT").startswith("SEAT"), "")
finally:
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass
print("hold the projector box: %d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
