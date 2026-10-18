# -*- coding: utf-8 -*-
r"""seat_desk.py - hands out cabinet seats on the PC (or cloud machine) that runs the server (2026-10-06): every PC
that plays on this server asks it for a seat before starting its cabinet and gets the lowest free one, 1-8, so nobody
types a seat number (two PCs on one seat break the game).  It never gives out the projector (seat 0, 2026-10-11 - the
owner: players on the server get only their own game), and the server does not wait for a projector (play.py server,
WAIT_PROJECTOR=0).  A projector box joins as seat 0 by itself.  Since 2026-10-17 a PC that asks with the RELAY word
is told the projector relay's port (server\projector_relay.py), and may show the projector through it.
A seat stays taken while that PC's online\seat.py keeps its connection, pinging every 20 s; a PC that stops,
crashes or goes away frees its seat: its connection closes, or it stays silent for 75 s.

    python code\server\seat_desk.py LIFE_SECONDS [LOG_FILE]        (play.py server starts it)

TCP port 20030 (WCCF_BROKER_PORT for the tests).  Lines, ASCII, one per message:
    PC -> "WANT"                broker -> "SEAT n PROJECTOR 0"     the lowest free seat (PROJECTOR 0: no projector;
                                                                   kit 5's PCs ran a projector on 1)
    PC -> "WANT RELAY"          broker -> "SEAT n PROJECTOR 20031" the same, and the projector relay's port
    PC -> "WANT SEAT n"         broker -> the same for seat n, or "TAKEN n"
                                broker -> "FULL" (8 cabinets) / "ERR ..." (anything else) - then it closes
    PC -> "PING"                broker -> "PONG"                   while it runs
It never touches the game: the seats it gives out are only what the PCs then write into their own cabinet settings.

It does READ the game (2026-10-09): a seat whose cabinet is in the game now is not given to another PC, even with no
lease for it - after a server restart a cabinet rejoins the game by itself on its old seat, but its PC's lease died
with the old desk, and that night the desk gave seat 3 to a second PC: it was never let in (4 tries in 12 minutes).
Who is on which seat comes from control's debug log (_dbg_control.txt beside this desk's log, written line by line):
"sateID=n" then "++ACCEPT++ 'address'" = a cabinet on seat n, "---DISCONNECT--- sateID=n" = gone; sateID 0 is the
projector. The same address may take its seat back (WANT SEAT n). Two PCs behind one router share an address: the
desk cannot tell them apart.

THE PROJECTOR BOX ON HOLD (2026-10-09): a machine that only shows the projector (a stream box) is kept out of the game
until a player is in it.  On the shared server every run whose FIRST client was that box took (almost) no player in
afterwards - 6 runs, 1 player let in of about 17 tries - and every run a player joined first took everyone (3 runs);
a pattern, not a proof.  data\hold_projector.txt (the data folder above this desk's logs) names the box's address.
While no player is in the game and the box is not in it, a Windows firewall rule ("WCCF hold projector box") keeps
that address off TCP 20002; as soon as a player is in, it is lifted and the box joins in seconds.  Looked at every
second.  The box asks "HOLD" -> "HOLD 1" (held) or "HOLD 0", and its keeper does not restart it while it is held.
No file: nothing is held (every other server).  Needs the rights to change the firewall (the server task's SYSTEM).

THE wccf.online SIGN-IN (2026-10-14): a PC signed in (online\account.py) ends its WANT line with "TOKEN <token>"
("WANT TOKEN t", "WANT SEAT n TOKEN t").  The desk asks the website who that is (xmlhttp.php?action=wccf_whoami,
WCCF_WEBSITE, default https://wccf.online), outside its lock, and keeps the answer CHECKED seconds.  A token the
website refuses (revoked, banned): "ERR sign in again: ..." and no seat.  The website out of reach: let in unchecked
(never lock everyone out because the website is down).  No token: let in - unless data\require_signin.txt exists
(looked at on every claim, so switching it needs no restart): then "ERR sign in: ...", and kit 7 plays on its own PC
instead and says why.  The lease remembers the account; the log names it, never the token.

THE CLUB CARD WORD (2026-10-15): kit 7 also says which club card it plays: "WANT [SEAT n] [CARD c] [TOKEN t]", c = the
card's id (its serial, which the game writes into the club's data as SYSTEM_CARD_ID).  A signed-in seat's lease keeps
it (leases.json "card"), so the witness can tell two signed-in players behind ONE address (one house) apart by the card
id in each message.  An older desk answers a CARD word with "ERR say ..."; online\seat.py then asks without it.

THE RELAY WORD (2026-10-17): a PC that can show the projector through the projector relay says so: "WANT [SEAT n]
[RELAY] [CARD c] [TOKEN t]", and gets "SEAT n PROJECTOR <the relay's port>" (WCCF_PROJECTOR_PORT, 20031).  Without
the word the answer stays PROJECTOR 0, so an older kit never starts a projector that connects straight to control
(control takes one projector and refuses the next, INVALID_ID).  An older desk answers RELAY with "ERR say ...";
online\seat.py then asks without it.
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PORT = int(os.environ.get("WCCF_BROKER_PORT", "20030"))
SILENT = float(os.environ.get("WCCF_BROKER_SILENT", "75"))       # seconds without a line: the PC is gone
WEBSITE = os.environ.get("WCCF_WEBSITE", "https://wccf.online").rstrip("/")
CHECKED = float(os.environ.get("WCCF_SIGNIN_KEEP", "600"))       # seconds a website answer about a token is kept
RELAY_PORT = int(os.environ.get("WCCF_PROJECTOR_PORT", "20031"))   # server\projector_relay.py
SEATS = range(1, 9)
SATE = re.compile(r"client\[\d+\]\s*:\s*sateID=(\d+)")
ACCEPT = re.compile(r"\+\+ACCEPT\+\+\s+'([0-9.]+):\d+'")
GONE = re.compile(r"---DISCONNECT---\s*sateID=(\d+)")

lock = threading.Lock()
leases = {}                     # seat -> (peer, lease id, account {"uid", "username"} or None)
next_id = 0
log_file = None
require_file = None             # data\require_signin.txt: when it exists, a PC must be signed in
known = {}                      # sha256(token) -> (when, ("ok", account) or ("refused", why))


def website_check(token):
    """("ok", {"uid", "username"}) / ("refused", why) / ("unreachable", why) - from the website's who-am-I; ok and
    refused are kept CHECKED seconds, unreachable is asked again next time.  Never raises."""
    key = hashlib.sha256(token.encode("ascii", "replace")).hexdigest()
    hit = known.get(key)
    if hit and time.time() - hit[0] < CHECKED:
        return hit[1]
    req = urllib.request.Request(WEBSITE + "/xmlhttp.php?action=wccf_whoami",
                                 data=urllib.parse.urlencode({"token": token}).encode("ascii"),
                                 headers={"User-Agent": "WCCF-seat-desk"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            body = json.loads(r.read().decode("utf-8", "replace") or "{}")
        if not (isinstance(body, dict) and body.get("username")):
            return "unreachable", "the website's answer named nobody"
        res = ("ok", {"uid": body.get("uid"), "username": str(body["username"])})
    except urllib.error.HTTPError as ex:
        if ex.code not in (401, 403):
            return "unreachable", "HTTP %d" % ex.code
        try:
            why = json.loads(ex.read().decode("utf-8", "replace") or "{}").get("error", "")
        except (ValueError, AttributeError):
            why = ""
        res = ("refused", why or "HTTP %d" % ex.code)
    except (OSError, ValueError) as ex:
        return "unreachable", str(ex)
    known[key] = (time.time(), res)
    return res


def require_signin():
    return bool(require_file) and os.path.exists(require_file)


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
    return ", ".join(str(s) for s in sorted(leases)) or "none"


leases_file = None              # data\leases.json: who sits where, for server\witness.py (2026-10-14)


def publish():
    """the seats taken now and who sits there -> data\\leases.json, for the server's witness (a card per finished
    match): each seat's address and account - never a token.  Lock held.  Never raises."""
    if not leases_file:
        return
    out = {str(s): dict({"ip": p.rsplit(":", 1)[0], "uid": (a or {}).get("uid"), "username": (a or {}).get("username")},
                        **({"card": a["card"]} if a and a.get("card") else {}))      # the club card it plays (kit 7)
           for s, (p, _lid, a) in leases.items()}
    try:
        with open(leases_file + ".tmp", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(leases_file + ".tmp", leases_file)
    except OSError:
        pass


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

HOLD_RULE = "WCCF hold projector box"
hold_ip, held, hold_fails = None, None, 0        # the box's address; held now (None = not set yet); failed tries


def read_hold_ip(path):
    """the address in data\\hold_projector.txt (its first word, four numbers 0-255), or None"""
    try:
        with open(path, encoding="ascii", errors="replace") as f:
            words = f.read().split()
    except OSError:
        return None
    ip = words[0] if words else ""
    parts = ip.split(".")
    return ip if len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) else None


def firewall(block):
    """the hold rule on (block hold_ip on TCP 20002) or off; never two of it.  WCCF_HOLD_FW=FILE (the tests): a line
    "block ADDRESS" or "open" is added to FILE instead"""
    test = os.environ.get("WCCF_HOLD_FW")
    if test:
        try:
            with open(test, "a", encoding="ascii") as f:
                f.write(("block %s\n" % hold_ip) if block else "open\n")
            return True
        except OSError:
            return False
    netsh = [os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "netsh.exe"), "advfirewall", "firewall"]
    try:
        subprocess.run(netsh + ["delete", "rule", "name=" + HOLD_RULE], capture_output=True, timeout=30,
                       creationflags=0x08000000)
        if not block:
            return True
        r = subprocess.run(netsh + ["add", "rule", "name=" + HOLD_RULE, "dir=in", "action=block", "protocol=TCP",
                                    "localport=20002", "remoteip=" + hold_ip], capture_output=True, timeout=30,
                           creationflags=0x08000000)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def hold_tick():
    """the box held while no player is in the game and it is not in it itself; a change is logged"""
    global held, hold_fails
    with lock:
        game = in_game.now()
    player = any(s >= 1 for s in game)
    want = not player and game.get(0) != hold_ip
    if want == held:
        return
    if not firewall(want):
        hold_fails += 1
        if hold_fails in (1, 60) or hold_fails % 600 == 0:
            log("projector box %s: the firewall rule could not be %s (try %d) - is this the server task (SYSTEM)?" % (
                hold_ip, "set" if want else "lifted", hold_fails))
        return
    held, hold_fails = want, 0
    log("projector box %s: %s" % (hold_ip, "held - it joins the game once a player is in" if want else
                                  "let in - a player is in the game" if player else "in the game - not held"))


def hold_loop(end):
    while time.time() < end:
        hold_tick()
        time.sleep(1.0)


def serve(conn, peer):
    global next_id
    seat, lid, buf = None, None, [b""]
    conn.settimeout(SILENT)
    try:
        words = read_line(conn, buf).split()
        ip = peer.rsplit(":", 1)[0]
        if words == ["HOLD"]:                                       # the projector box: held? (no seat taken)
            conn.sendall(b"HOLD 1\n" if held else b"HOLD 0\n")
            return
        account = None
        if len(words) >= 3 and words[-2] == "TOKEN":                # a signed-in PC (2026-10-14): who is it?
            state, got = website_check(words[-1])                   # outside the lock: the website may be slow
            words = words[:-2]
            if state == "refused":
                conn.sendall(b"ERR sign in again: wccf.online refused this PC's sign-in (%s)\n" %
                             str(got)[:80].encode("ascii", "replace"))
                log("%s: refused - the website refused its sign-in (%s)" % (peer, got))
                return
            if state == "ok":
                account = got
            else:
                log("%s: the website could not be asked about its sign-in (%s) - let in unchecked" % (peer, got))
        elif require_signin():
            conn.sendall(b"ERR sign in: this server needs a wccf.online account - update the kit and start again\n")
            log("%s: refused - not signed in, and this server needs it" % peer)
            return
        if len(words) >= 3 and words[-2] == "CARD" and words[-1].isdigit():  # the club card it plays (2026-10-15)
            if account:
                account = dict(account, card=int(words[-1]))
            words = words[:-2]
        relay = words[-1:] == ["RELAY"]                             # it can show the projector through the relay
        if relay:
            words = words[:-1]
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
            leases[seat] = (peer, lid, account)
            publish()
            conn.sendall(b"SEAT %d PROJECTOR %d\n" % (seat, RELAY_PORT if relay else 0))
            log("%s: seat %d - taken now: %s" % (peer, seat, taken()))
            log("%s: seat %d is %s" % (peer, seat, "signed in as %s (uid %s)%s" % (
                account["username"], account["uid"], ", club card %s" % account["card"] if account.get("card") else "")
                if account else "not signed in"))
        while True:
            if read_line(conn, buf) == "PING":
                conn.sendall(b"PONG\n")
    except (OSError, ValueError):
        pass
    finally:
        with lock:
            if seat is not None and leases.get(seat, (None, None))[1] == lid:
                del leases[seat]
                publish()
                log("%s: seat %d free again - taken now: %s" % (peer, seat, taken()))
        try:
            conn.close()
        except OSError:
            pass


def main(argv):
    global log_file, hold_ip, require_file, leases_file
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
    log("seat broker listening on TCP %d: seats 1-8, no projector for the PCs" % PORT)
    end = time.time() + life
    data =os.path.dirname(os.path.dirname(os.path.abspath(log_file))) if log_file else ""
    hold_ip = read_hold_ip(os.environ.get("WCCF_HOLD_FILE") or os.path.join(data, "hold_projector.txt"))
    require_file = os.environ.get("WCCF_REQUIRE_FILE") or (os.path.join(data, "require_signin.txt") if data else None)
    leases_file = os.environ.get("WCCF_LEASES_FILE") or (os.path.join(data, "leases.json") if data else None)
    with lock:
        publish()                                                   # a new run: nobody sits yet
    log("sign-in: %s (%s)" % ("NEEDED" if require_signin() else "not needed - players without one get in too",
                              require_file or "no data folder"))
    if hold_ip:
        hold_tick()                                                 # at once: the box must not be the first in
        threading.Thread(target=hold_loop, args=(end,), daemon=True).start()
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
