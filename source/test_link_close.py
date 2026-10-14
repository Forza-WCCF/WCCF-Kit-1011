# -*- coding: utf-8 -*-
"""test_link_close.py - the panel's watch on the server link (wccfpanel.c link_watch; check.ps1 runs it after
build.ps1; no game, no server): a link that drops while the game runs is written LOST - the reason play.py sends a
run's logs to the server by itself - and the link the game drops because the player closed its window is not
(2026-10-11: three normal closes went to the server as runs that went wrong).  fakegame.exe holds a TCP link to this
script's listener on the server's port, 127.0.0.1:20002.  The close goes through the panel only where it hooks the
window, which needs a Direct3D device: on a machine without one that half says NOT RUN (CI's Windows machine has one -
4 checks there too, the first run).
    python source\\test_link_close.py"""
import os
import shutil
import socket
import subprocess
import tempfile
import threading

SRC = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(SRC)
try:
    listener = socket.create_server(("127.0.0.1", 20002))
except OSError as ex:
    raise SystemExit("link close: port 20002 is taken on this PC (a server running?) - stop it and run again: %s" % ex)
held = []                                    # the server side of each link, kept open: only the game ends a link here


def serve():
    while True:
        try:
            held.append(listener.accept()[0])
        except OSError:
            return


threading.Thread(target=serve, daemon=True).start()


def run(*steps):
    """the panel in fakegame through the steps: (server_link.txt, the panel's log)"""
    t = tempfile.mkdtemp(prefix="wccf-link-")
    try:
        os.makedirs(os.path.join(t, "data"))
        shutil.copy(os.path.join(SRC, "build", "fakegame.exe"), t)
        env = dict(os.environ, WCCFPANEL_ROLE="seat1", WCCFPANEL_DRYKEYS="1", WCCFPANEL_FULLSCREEN="0",
                   WCCF_DATA=os.path.join(t, "data"), WCCF_KEYS=os.path.join(t, "data", "keys.txt"), WCCF_LOGS=t,
                   WCCF_SKIN=os.path.join(KIT, "art", "skin.tex"))
        subprocess.run([os.path.join(t, "fakegame.exe"), os.path.join(KIT, "programs", "wccfpanel.dll")] + list(steps),
                       cwd=t, env=env, timeout=90, check=True)
        out = []
        for name in ("server_link.txt", "wccfpanel.log"):
            try:
                with open(os.path.join(t, name), encoding="utf-8", errors="replace") as f:
                    out.append(f.read())
            except OSError:
                out.append("")
        return out
    finally:
        shutil.rmtree(t, ignore_errors=True)


# the link drops while the game runs (the server gone, the internet down): written, then the player closes
link, log = run("connect:20002", "wait:3500", "disconnect", "wait:3500", "close", "wait:500")
assert " UP 127.0.0.1" in link, "the link coming up must be written: %r\n%s" % (link, log[-1500:])
assert " LOST (it was up " in link, "a link lost while the game runs must be written: %r" % link

# the player closes the window, then the game drops its link as it ends: nothing
link, log = run("connect:20002", "wait:3500", "close", "wait:300", "disconnect", "wait:3500")
assert " UP 127.0.0.1" in link, "the link coming up must be written: %r" % link
if "close: the window closes - the game ends" in log:
    assert " LOST" not in link, "the player closed the game - its link going is no fault: %r" % link
    print("link close: 4 checks passed")
else:
    print("link close: 3 checks passed; the player's close NOT RUN - the panel did not hook the window here "
          "(no Direct3D device)")
