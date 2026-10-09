# -*- coding: utf-8 -*-
r"""_seat_lease.py - this PC's seat on a server (2026-10-06): asks the server's _seat_broker.py (TCP 20030) for a seat,
writes the answer for play.py, then HOLDS the seat by pinging every 20 s for as long as it runs - the end of the run ends it and
the seat is free again at once.

    python _seat_lease.py ADDRESS OUT_FILE LIFE_SECONDS [SEAT]

OUT_FILE gets {"seat": n, "projector": 1|0}, or {"error": "no broker" | "full" | "taken" | "...", "detail": "..."}:
"no broker" = nothing answered on that port (a server without the broker - play.py then does what it did before).
"""
import json
import os
import socket
import sys
import time

PORT = int(os.environ.get("WCCF_BROKER_PORT", "20030"))
PING = float(os.environ.get("WCCF_LEASE_PING", "20"))          # seconds between pings (the desk waits 75)


def write(path, data):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)


def main(argv):
    ip, out, life = argv[0], argv[1], float(argv[2])
    want = b"WANT SEAT %d\n" % int(argv[3]) if len(argv) > 3 else b"WANT\n"
    try:
        conn = socket.create_connection((ip, PORT), timeout=6)
    except OSError as ex:
        write(out, {"error": "no broker", "detail": str(ex)})
        return 1
    try:
        conn.settimeout(10)
        conn.sendall(want)
        buf = b""
        while b"\n" not in buf:
            data = conn.recv(256)
            if not data:
                raise OSError("the broker closed the connection")
            buf += data
        words = buf.split(b"\n", 1)[0].decode("ascii", "replace").split()
    except OSError as ex:
        write(out, {"error": "no answer", "detail": str(ex)})
        return 1
    if len(words) == 4 and words[0] == "SEAT" and words[2] == "PROJECTOR":
        write(out, {"seat": int(words[1]), "projector": int(words[3])})
    else:
        write(out, {"error": {"FULL": "full", "TAKEN": "taken"}.get(words[0] if words else "", "refused"),
                    "detail": " ".join(words)})
        return 1
    end = time.time() + life
    try:
        while time.time() < end:
            time.sleep(PING)
            conn.sendall(b"PING\n")
            conn.settimeout(15)
            if b"PONG" not in conn.recv(64):
                break
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
