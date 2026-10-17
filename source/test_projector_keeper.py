# -*- coding: utf-8 -*-
"""test_projector_keeper.py - the panel helper's rule for the online projector (code\\helpers\\panel.py keep_projector;
check.ps1 runs it; nothing live, no game): a projector that lost the server is restarted after a wait that grows, a few
times at most; one whose window the player closed is never brought back.
    python source\\test_projector_keeper.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from helpers import panel  # noqa: E402

keep, B, W = panel.keep_projector, panel.BACKOFF, panel.WAIT_LINK

# linked, then the link goes: restart only after BACKOFF[0], once
st = {}
assert not keep(st, 0, 100, True, True), "linked: nothing"
assert not keep(st, 50, 100, True, False), "the link just went: wait"
assert not keep(st, 50 + B[0] - 1, 100, True, False), "... still within the first wait"
assert keep(st, 50 + B[0], 100, True, False), "gone for BACKOFF[0]: restart"
assert not keep(st, 50 + B[0] + 2, 100, True, False), "the restart under way: not twice"

# the fresh projector (a new pid) gets WAIT_LINK to link up; then its loss waits the longer BACKOFF[1]
t = 100
assert not keep(st, t, None, False, False), "between the old and the new one: nothing"
assert not keep(st, t + 1, 101, True, False), "a fresh projector, not linked yet: wait"
assert not keep(st, t + 5, 101, True, True), "it linked"
assert not keep(st, t + 20, 101, True, False), "lost again: wait"
assert not keep(st, t + 20 + B[0], 101, True, False), "... the first wait is not enough now"
assert keep(st, t + 20 + B[1], 101, True, False), "BACKOFF[1]: second restart"

# a fresh one that never links: restarted after WAIT_LINK, and after the last try never again
t = 300
assert not keep(st, t, 102, True, False) and not keep(st, t + W - 1, 102, True, False), "a fresh one waits WAIT_LINK"
assert keep(st, t + W, 102, True, False), "never linked: third restart"
assert st["tries"] == len(B)
assert not keep(st, t + 1000, 103, True, False) and not keep(st, t + 5000, 103, True, False), "out of tries: no more"

# a link that holds HOLD earns the tries back
assert not keep(st, 6000, 103, True, True) and not keep(st, 6000 + panel.HOLD, 103, True, True)
assert st.get("tries") == 0, "a link held HOLD: the tries come back"

# the player closed the window (the process goes; while it ends, no window): never restarted
st = {}
assert not keep(st, 0, 200, True, True)
for s in range(1, 600, 2):
    assert not keep(st, s, 200, False, False), "its window closing: never restarted"
for s in range(600, 2000, 2):
    assert not keep(st, s, None, False, False), "closed and gone: never brought back"
assert not st.get("tries"), "no try spent on a close"

# never a projector on this PC: nothing
st = {}
assert not any(keep(st, s, None, False, False) for s in range(0, 1000, 2))


# the starting volumes: the projector muted, and a projector started again muted too (each process once)
class Sound:
    GAME_VOLUME, PROJECTOR_MUTED = 0.04, True

    def __init__(self):
        self.list, self.set = [], []

    def sessions(self):
        return self.list

    def apply(self, pid, volume=None, mute=None):
        self.set.append((pid, mute))
        return 1


game = os.path.join("C:\\", "kit", "extracted")
proj, seat1 = os.path.join(game, "client_Release.exe"), os.path.join("C:\\", "kit", "seat1", "client_Release.exe")
s = Sound()
sd = panel.SoundDefaults(game, 0, s)
s.list = [(1, proj, 1.0, False), (2, seat1, 1.0, False)]
sd.tick(1)
assert sorted(s.set) == [(1, True), (2, False)], s.set
sd.tick(2)
assert len(s.set) == 2, "each set once: the Volume Mixer has it from here"
sd.again(900)                                     # restarted after the first 10 minutes, the old session still listed
s.list.append((3, proj, 1.0, False))
sd.tick(901)
assert s.set[2:] == [(3, True)], "the projector started again is muted too, nothing else touched: %r" % s.set
sd.tick(902)
assert len(s.set) == 3

# SETTINGS' OPEN / CLOSE PROJECTOR (data\\projector.request)
req, up = panel.projector_request, panel.projector_up
st = {"tries": len(B), "pid": 300}
assert not up(st, 300, False), "out of tries, not linked: the button offers OPEN"
assert req(st, "nonsense") is None and req(st, "") is None
assert req(st, "OPEN PROJECTOR - asked\n") == "open" and st["tries"] == 0, "open: the tries come back"
assert up(st, 301, False) and up(st, 301, True), "a fresh projector: CLOSE"
assert req(st, "CLOSE PROJECTOR - asked\n") == "close" and not up(st, 301, True), "closed: OPEN"
assert not keep(st, 400, 301, True, False) and not keep(st, 400 + W + 100, 301, True, False), "closed: never brought back"
assert not keep(st, 1000, None, False, False) and not up(st, None, False)
assert req(st, "open") == "open" and not st["closed"], "open after a close: the keeper looks after it again"
assert not keep(st, 1001, 302, True, False) and keep(st, 1001 + W, 302, True, False), "... restarts it when it never links"
assert not up({}, None, True), "no projector: OPEN"

# CLOSE PROJECTOR while an automatic restart runs (2026-10-17): kept, no restart of its own meanwhile, and it closes the
# projector that restart brings once it has finished; a press waiting goes before the keeper's own look
import tempfile  # noqa: E402


class Job:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


ran, data = [], tempfile.mkdtemp(prefix="keeper_")
k = panel.ProjectorKeeper(game, data, lambda tries, word=None: ran.append(word))
k.job = Job()                                     # the automatic restart under way
k.asked("CLOSE PROJECTOR - asked\n")
assert ran == [] and k.st["closed"], "CLOSE while one runs: kept, and no restart of the keeper's own from now"
with open(os.path.join(data, "projector.state")) as f:
    assert f.read() == "closed\n", "the panel offers OPEN at once"
k.tick(10)
assert ran == [], "... nothing while the restart runs"
k.job.code = 0
k.tick(11)
assert ran == ["close"], "the restart done: the projector it brought is closed (%r)" % ran
k.asked("OPEN PROJECTOR")
k.job = Job()
k.asked("CLOSE PROJECTOR")
k.asked("OPEN PROJECTOR")
k.job.code = 0
k.tick(20)
assert ran == ["close", "open", "open"] and not k.st["closed"], "the last press counts: %r" % ran

# play.py has the commands the helper runs
with open(os.path.join(KIT, "code", "play.py"), encoding="utf-8") as f:
    assert 'if words in ([], ["open"], ["close"]):' in f.read(), "play.py lost a 'projector' command (panel.py)"
with open(os.path.join(KIT, "code", "helpers", "panel.py"), encoding="utf-8") as f:
    t = f.read()
    assert t.index("keeper.asked(text)") < t.index("keeper.tick(time.time())"), "a press goes before the keeper's look"
print("projector keeper: all checks passed")
