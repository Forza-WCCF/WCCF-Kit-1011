# -*- coding: utf-8 -*-
"""test_send_logs.py - SEND LOGS: send_logs.py packs and sends, _log_inbox.py keeps - and refuses what it must (check.ps1
runs it; nothing of the game runs).  A scratch kit; inboxes on 127.0.0.1:20952 and :20953.
    python source\\test_send_logs.py"""
import io
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import send_logs as S  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name, ("  - " + detail) if detail else ""))


def inbox(port, folder, log, **env):
    e = dict(os.environ, WCCF_INBOX_PORT=str(port), **{k: str(v) for k, v in env.items()})
    p = subprocess.Popen([sys.executable, "-B", os.path.join(KIT, "scripts", "_log_inbox.py"), "60", log, folder], env=e,
                         stdout=subprocess.DEVNULL)
    end = time.time() + 10
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return p
        except OSError:
            time.sleep(0.2)
    return p


def raw(port, data, hang_up=False):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(data)
    if hang_up:
        s.close()
        return ""
    s.shutdown(socket.SHUT_WR)
    out = s.recv(200).decode("ascii", "replace").strip()
    s.close()
    return out


def a_zip(text=b"x"):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("a.txt", text)
    return b.getvalue()


tmp = tempfile.mkdtemp(prefix="sendlogs_")
procs = []
try:
    kit = os.path.join(tmp, "kit")
    for d in ("data/logs/previous", "data/logs/archive", "data/save"):
        os.makedirs(os.path.join(kit, d))
    home = os.environ.get("USERPROFILE", "")
    with open(os.path.join(kit, "data/logs/run_seat1.txt"), "w", encoding="utf-8") as f:
        f.write("start\n" + "x" * 5000 + "\nopened %s\\Desktop\\a.txt\nthe end\n" % home)
    for n, body in (("data/logs/archive/old.zip", "an old run"), ("data/save/seat1_club.bin", "THE CLUB CARD"),
                    ("data/panel.txt", "server=1.2.3.4"), ("version.txt", "kit-5.5")):
        with open(os.path.join(kit, n), "w", encoding="utf-8") as f:
            f.write(body)

    blob, n = S.pack(kit, game=os.path.join(tmp, "nogame"), tail=1000)
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = z.namelist()
    check("pack: the run's log, panel.txt and version.txt in; never the club card or the zipped archive",
          sorted(names) == ["data/panel.txt", "logs/run_seat1.txt", "version.txt"], ", ".join(names))
    text = z.read("logs/run_seat1.txt").decode("utf-8")
    check("pack: a big log keeps its last bytes, and says what was left out",
          text.startswith("[... the first") and text.rstrip().endswith("the end"), text[:60])
    check("pack: the Windows user folder is taken out", (not home or home not in text) and "%USERPROFILE%" in text, "")
    check("version: version.txt without kit-", S.version(kit) == "5.5", S.version(kit))

    keep, port = os.path.join(tmp, "keep"), 20952
    procs.append(inbox(port, keep, os.path.join(tmp, "inbox.txt"), WCCF_INBOX_PER_HOUR=4))   # junk and too big: not counted
    ok, code = S.send("127.0.0.1", blob, "5.5", port=port)
    files = os.listdir(keep) if os.path.isdir(keep) else []
    check("send: kept, and a 5-letter code back, in the file's name", ok and len(code) == 5 and len(files) == 1 and
          ("_%s_127.0.0.1_5.5.zip" % code) in files[0], "%s %s %s" % (ok, code, files))
    check("a junk request: NO a bad request", raw(port, b"HELLO\n").startswith("NO a bad request"))
    check("more than 8 MB said: NO too big", raw(port, b"WCCFLOGS1 9000000 5.5\n").startswith("NO too big"))
    check("not a ZIP: NO not a ZIP", raw(port, b"WCCFLOGS1 5 5.5\nhello").startswith("NO not a ZIP"))
    raw(port, b"WCCFLOGS1 1000 5.5\n" + a_zip()[:20], hang_up=True)            # hangs up half way
    time.sleep(0.5)
    check("a PC that hangs up half way: nothing kept, the inbox goes on",
          len(os.listdir(keep)) == 1 and S.send("127.0.0.1", a_zip(), "5.5", port=port)[0], str(os.listdir(keep)))
    ok, why = S.send("127.0.0.1", a_zip(), "5.5", port=port)
    check("the 5th upload in an hour from one address (4 allowed here, 6 on a server): refused",
          not ok and "too many" in why, why)
    names = os.listdir(keep)
    check("only ZIPs kept, no half files", all(n.endswith(".zip") for n in names) and len(names) == 2, str(names))
    ok, why = S.send("127.0.0.1", blob, "5.5", port=20959)
    check("no inbox at that address: not sent, said why", not ok and "did not answer" in why, why)

    keep2, port2 = os.path.join(tmp, "keep2"), 20953
    procs.append(inbox(port2, keep2, os.path.join(tmp, "inbox2.txt"), WCCF_INBOX_KEEP=len(blob) + 50))
    first = S.send("127.0.0.1", blob, "5.5", port=port2)[1]
    time.sleep(1.1)
    second = S.send("127.0.0.1", blob, "5.5", port=port2)[1]
    left = os.listdir(keep2)
    check("over its size the oldest goes (1 GB on a server; here one ZIP)", len(left) == 1 and second in left[0] and
          first not in left[0], str(left))
finally:
    for p in procs:
        p.kill()
        p.wait()
    shutil.rmtree(tmp, ignore_errors=True)
print("send logs: %d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
