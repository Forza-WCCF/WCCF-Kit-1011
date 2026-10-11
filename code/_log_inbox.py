# -*- coding: utf-8 -*-
r"""_log_inbox.py - keeps the logs players send with SEND LOGS (the SETTINGS panel), on the PC (or cloud machine) that
runs the server (2026-10-09, the player: "a button in the settings to send logs to the server, so people can send us
their logs from their own game").  play.py server starts it beside the seat desk.

    python _log_inbox.py LIFE_SECONDS LOG_FILE [FOLDER]

TCP port 20050 (WCCF_INBOX_PORT for the tests).  One upload per connection, from send_logs.py:
    PC -> "WCCFLOGS1 SIZE VERSION\n" then SIZE bytes (a ZIP)
    inbox -> "OK CODE\n"   (a short code the player tells us, e.g. K7Q2M)   or   "NO reason\n"
Kept as FOLDER\DATE_TIME_CODE_ADDRESS_VERSION.zip (FOLDER: data\player_logs beside LOG_FILE's folder).  An open port
must not fill the disk: 8 MB an upload, 6 uploads an hour from one address, 4 at a time, 1 GB in all (the oldest
go).  It never opens what it keeps.
"""
import os
import random
import re
import socket
import sys
import threading
import time

PORT = int(os.environ.get("WCCF_INBOX_PORT", "20050"))
MAX_BYTES = 8 * 1024 * 1024
PER_HOUR = int(os.environ.get("WCCF_INBOX_PER_HOUR", "6"))
KEEP_BYTES = int(os.environ.get("WCCF_INBOX_KEEP", str(1024 * 1024 * 1024)))
TIMEOUT = 60.0
CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"          # no 0/O, 1/I/L: read out loud or typed from a screen

lock = threading.Lock()
recent = {}                                            # address -> times of its uploads in the last hour
slots = threading.BoundedSemaphore(4)
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


def read_exact(conn, n, first=b""):
    data = bytearray(first)
    while len(data) < n:
        chunk = conn.recv(min(65536, n - len(data)))
        if not chunk:
            raise OSError("the PC hung up after %d of %d bytes" % (len(data), n))
        data += chunk
    return bytes(data)


def trim(folder):
    """the oldest uploads go while the folder holds more than KEEP_BYTES"""
    try:
        files = sorted((os.path.getmtime(p), os.path.getsize(p), p) for p in
                       (os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".zip")))
    except OSError:
        return
    total = sum(s for _t, s, _p in files)
    for _t, s, p in files:
        if total <= KEEP_BYTES:
            break
        try:
            os.remove(p)
            total -= s
            log("inbox full: removed the oldest, %s" % os.path.basename(p))
        except OSError:
            pass


def serve(conn, ip, folder):
    def no(why):
        conn.sendall(("NO %s\n" % why).encode("ascii"))
        log("%s: refused - %s" % (ip, why))
    try:
        conn.settimeout(TIMEOUT)
        buf = b""
        while b"\n" not in buf:
            if len(buf) > 120:
                return no("a bad request")
            chunk = conn.recv(256)
            if not chunk:
                return
            buf += chunk
        head, rest = buf.split(b"\n", 1)
        words = head.decode("ascii", "replace").split()
        if len(words) != 3 or words[0] != "WCCFLOGS1" or not words[1].isdigit():
            return no("a bad request")
        size, version = int(words[1]), re.sub(r"[^0-9A-Za-z.\-]", "_", words[2])[:24]
        if not 0 < size <= MAX_BYTES:
            return no("too big - %d bytes, at most %d" % (size, MAX_BYTES))
        now = time.time()
        with lock:
            times = [t for t in recent.get(ip, []) if now - t < 3600]
            if len(times) >= PER_HOUR:
                return no("too many from this address - try again in an hour")
            recent[ip] = times + [now]
        data = read_exact(conn, size, rest[:size])
        if not data.startswith(b"PK\x03\x04"):
            return no("not a ZIP")
        code = "".join(random.SystemRandom().choice(CODE_CHARS) for _ in range(5))
        name = "%s_%s_%s_%s.zip" % (time.strftime("%Y-%m-%d_%H%M%S"), code, ip, version)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path + ".part", "wb") as f:
            f.write(data)
        os.replace(path + ".part", path)
        trim(folder)                                   # before the answer: what the PC hears is what the folder holds
        conn.sendall(("OK %s\n" % code).encode("ascii"))
        log("%s: logs kept, code %s, kit %s, %d KB -> %s" % (ip, code, version, len(data) // 1024, name))
    except (OSError, ValueError) as ex:
        log("%s: upload failed - %s" % (ip, ex))
    finally:
        try:
            conn.close()
        except OSError:
            pass


def handle(conn, ip, folder):
    try:
        serve(conn, ip, folder)
    finally:
        slots.release()


def main(argv):
    global log_file
    if not argv or not argv[0].replace(".", "", 1).isdigit():
        print(__doc__)
        return 2
    life = float(argv[0])
    log_file = argv[1] if len(argv) > 1 else None
    base = os.path.dirname(os.path.dirname(os.path.abspath(log_file))) if log_file else os.getcwd()
    folder = argv[2] if len(argv) > 2 else os.path.join(base, "player_logs")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind(("0.0.0.0", PORT))
    except OSError as ex:
        log("cannot listen on TCP %d (%s) - is a log inbox already running?" % (PORT, ex))
        return 1
    srv.listen(16)
    srv.settimeout(1.0)
    log("log inbox listening on TCP %d: players' SEND LOGS kept in %s" % (PORT, folder))
    end = time.time() + life
    while time.time() < end:
        try:
            conn, addr = srv.accept()
        except (socket.timeout, OSError):
            continue
        if not slots.acquire(blocking=False):
            try:
                conn.sendall(b"NO busy - try again in a minute\n")
                conn.close()
            except OSError:
                pass
            log("%s: refused - 4 uploads already coming in" % addr[0])
            continue
        threading.Thread(target=handle, args=(conn, addr[0], folder), daemon=True).start()
    log("log inbox: its time is up - stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
