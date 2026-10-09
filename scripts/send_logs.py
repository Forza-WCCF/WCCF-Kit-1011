# -*- coding: utf-8 -*-
r"""send_logs.py - SEND LOGS (the SETTINGS panel, 2026-10-09): this kit's logs in one ZIP, sent to a server's log
inbox (_log_inbox.py, TCP 20050), so the people who run the server can see what went wrong on this PC.  The panel
asks _kit_helper.py, which calls pack() and send(); by hand:
    python send_logs.py ADDRESS

In the ZIP: data\logs (this run and the one before - not the zipped archive), the panel's logs (seat1\wccfpanel.log,
data\logs\wccfpanel_projector.log), data\panel.txt, data\keys.txt, data\running.json and VERSION.txt - each its last
2 MB at most.  NEVER the club card (data\save).  In the text, what points at the person is replaced: the Windows user
folder (%USERPROFILE%), the user name (USER) and the PC's name (PC).
"""
import io
import os
import re
import socket
import sys
import zipfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("WCCF_INBOX_PORT", "20050"))
TAIL = 2 * 1024 * 1024
LIMIT = 7 * 1024 * 1024                    # the inbox takes 8 MB: a bigger ZIP is made again with shorter tails


def version(kit=KIT):
    """this kit's VERSION.txt ("5.5 (f13c146)"), or "dev" - one word for the inbox: "5.5" """
    try:
        with open(os.path.join(kit, "VERSION.txt"), encoding="ascii", errors="replace") as f:
            words = f.read().split()
        return words[0] if words else "dev"
    except OSError:
        return "dev"


def files(kit=KIT, game=None):
    """[(name in the ZIP, path)] of what goes in; game: the game folder (for seat1\\wccfpanel.log), from WCCF_GAME"""
    data, out = os.path.join(kit, "data"), []
    logs = os.path.join(data, "logs")
    for sub in ("", "previous", "hook"):
        folder = os.path.join(logs, sub)
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            p = os.path.join(folder, n)
            if os.path.isfile(p):
                out.append(("logs/" + (sub + "/" if sub else "") + n, p))
    for n in ("panel.txt", "keys.txt", "running.json"):
        out.append(("data/" + n, os.path.join(data, n)))
    out.append(("VERSION.txt", os.path.join(kit, "VERSION.txt")))
    game = game or os.environ.get("WCCF_GAME")
    if game:
        out.append(("seat1/wccfpanel.log", os.path.join(os.path.dirname(os.path.abspath(game)), "seat1",
                                                        "wccfpanel.log")))
    return [(a, p) for a, p in out if os.path.isfile(p)]


def scrubbers():
    """(compiled pattern, replacement) pairs over bytes, in the order they apply"""
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    pairs = []
    for enc in ("utf-8", "mbcs" if os.name == "nt" else "latin-1"):
        for old, new, whole in ((home, b"%USERPROFILE%", False), (home.replace("\\", "/"), b"%USERPROFILE%", False),
                                (os.environ.get("USERNAME") or "", b"USER", True),
                                (os.environ.get("COMPUTERNAME") or "", b"PC", True)):
            if len(old) < 3:                # "PC" or "Al": too short to take out of text without breaking it
                continue
            try:
                raw = re.escape(old.encode(enc))
            except UnicodeEncodeError:
                continue
            pairs.append((re.compile((rb"(?<![0-9A-Za-z])" + raw + rb"(?![0-9A-Za-z])") if whole else raw, re.I), new))
    return pairs


def scrub(data, pairs):
    for pat, new in pairs:
        data = pat.sub(new, data)
    return data


def pack(kit=KIT, game=None, tail=TAIL):
    """the ZIP (bytes) and how many files are in it"""
    pairs, buf, n = scrubbers(), io.BytesIO(), 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, path in files(kit, game):
            try:
                with open(path, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(max(0, size - tail))
                    data = f.read()
            except OSError:
                continue                    # busy or gone: the rest still goes
            if size > tail:
                data = b"[... the first %d bytes left out - the last %d follow]\n" % (size - tail, tail) + data
            z.writestr(arc, scrub(data, pairs))
            n += 1
    blob = buf.getvalue()
    if len(blob) > LIMIT and tail > 64 * 1024:
        return pack(kit, game, tail // 4)
    return blob, n


def send(address, blob, ver, port=PORT, timeout=60.0):
    """-> (True, the code the inbox gave) or (False, why)"""
    try:
        with socket.create_connection((address, port), timeout=15) as s:
            s.settimeout(timeout)
            s.sendall(b"WCCFLOGS1 %d %s\n" % (len(blob), ver.encode("ascii", "replace")))
            s.sendall(blob)
            s.shutdown(socket.SHUT_WR)
            answer = b""
            while b"\n" not in answer and len(answer) < 200:
                chunk = s.recv(200)
                if not chunk:
                    break
                answer += chunk
    except OSError as ex:
        return False, "the server's log inbox did not answer (%s)" % ex.__class__.__name__
    words = answer.decode("ascii", "replace").strip().split(" ", 1)
    if words[0] == "OK" and len(words) == 2 and re.fullmatch(r"[A-Z0-9]{3,12}", words[1]):
        return True, words[1]
    return False, (words[1] if len(words) == 2 and words[0] == "NO" else "an answer it did not understand")


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 2
    blob, n = pack()
    ok, what = send(argv[0], blob, version())
    print(("sent %d files (%d KB) - code %s: tell us this code" if ok else "not sent (%d files, %d KB): %s") %
          (n, len(blob) // 1024, what))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
