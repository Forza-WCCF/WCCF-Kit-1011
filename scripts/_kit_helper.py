# -*- coding: utf-8 -*-
r"""_kit_helper.py - does what the in-game panels ask for and cannot do from inside the game.  play.py starts it
(hidden) with the cabinets; STOP ends it with everything else.
    python _kit_helper.py SECONDS [DATA PLAY_EXE [hidden]]        (DATA, PLAY_EXE, hidden: tests only)

RESTART NOW (the SETTINGS panel, 2026-10-06): the panel writes data\restart.request; this helper takes the file away
and opens "PLAY.exe restart" in a window of its own: a stop by STOP's own rules (during a card session it explains
and asks), then a plain start with the NEXT START settings.  It has to come from out here: seat 1 runs under a
debugger that follows the programs it starts, so a restart started by the game itself would be killed half way.
A request that is already there when the helper starts (left by a run that ended) is removed, never carried out.

THE CLUB CARD panel's view (2026-10-06): data\club_view.txt, rewritten by club_view.py (with decode_club_card.py, the
reader the website will use) whenever the card, its backups or the run change - once the card has held still for a
second, so the game's bursts of saves are not read half way.  A view that cannot be written is said once and never
stops the helper: RESTART NOW does not depend on it.

THE STARTING VOLUMES (2026-10-06): sound_defaults.py - the projector muted, seat 1 very low - set once for each, as
soon as it has opened its sound (looked for every 0.5 s for 10 minutes after the start); never again, so a change in
the Volume Mixer stays.  The game folder comes from play.py (WCCF_GAME); without it nothing is set.  Like the view, it
never stops the helper.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CREATE_NEW_CONSOLE, CREATE_NO_WINDOW = 0x10, 0x08000000


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class ClubView:
    """the CLUB CARD panel's view of the card in DATA (data\\club_view.txt)"""

    def __init__(self, data):
        save = os.path.join(data, "save")
        self.card, self.backups = os.path.join(save, "seat1_club.bin"), os.path.join(save, "backup")
        self.cards = os.path.join(save, "cards")                       # your other club cards (club_wallet.py)
        self.running, self.out = os.path.join(data, "running.json"), os.path.join(data, "club_view.txt")
        self.catalogue = os.path.join(os.path.dirname(HERE), "overlay", "catalogue.tsv")
        self.seen, self.since, self.done, self.mod, self.said, self.retry_at = None, 0.0, None, None, False, 0.0

    def signature(self):
        def st(p):
            try:
                s = os.stat(p)
                return s.st_mtime_ns, s.st_size
            except OSError:
                return None
        def listing(folder):
            try:
                return tuple(sorted((n, st(os.path.join(folder, n))) for n in os.listdir(folder)))
            except OSError:
                return ()
        return st(self.card), listing(self.backups), st(self.running), listing(self.cards)

    def tick(self, now):
        sig = self.signature()
        if sig != self.seen:                    # changed: wait until it holds still for a second
            self.seen, self.since = sig, now
            return
        if sig == self.done or now - self.since < 1.0 or now < self.retry_at:
            return
        try:
            if self.mod is None:
                import club_view
                self.mod = club_view
            lines = self.mod.build(card=self.card, catalogue=self.catalogue, backups=self.backups,
                                   running=self.running, cards=self.cards)
            self.mod.write(lines, self.out)
            self.done = sig                     # only once written: a failed write is tried again
            say("club card view written: %s" % (lines[0] if lines else "-"))
        except Exception as ex:                 # the view never stops the helper; again in 5 s
            self.retry_at = now + 5.0
            if not self.said:
                say("club card view could not be written (tried again every 5 s): %r" % ex)
                self.said = True


class SoundDefaults:
    """the projector muted and seat 1 at sound_defaults.GAME_VOLUME, each set once, when it has first opened its
    sound; mod: sound_defaults, or a stand-in (the tests)"""
    LOOK, FOR = 0.5, 600.0

    def __init__(self, game, now, mod=None):
        self.targets = {}
        if game:
            game = os.path.abspath(game)
            self.targets = {os.path.normcase(os.path.join(game, "client_Release.exe")): "projector",
                            os.path.normcase(os.path.join(os.path.dirname(game), "seat1", "client_Release.exe")):
                                "seat 1"}
        self.mod, self.done, self.next, self.until, self.said = mod, set(), 0.0, now + self.FOR, False

    def tick(self, now):
        if not self.targets or len(self.done) == len(self.targets) or now < self.next or now > self.until:
            return
        self.next = now + self.LOOK
        try:
            if self.mod is None:
                import sound_defaults
                self.mod = sound_defaults
            s = self.mod
            for pid, path, _level, _muted in s.sessions():
                role = self.targets.get(os.path.normcase(path or ""))
                if not role or role in self.done:
                    continue
                if role == "projector":
                    n = s.apply(pid, volume=s.GAME_VOLUME, mute=s.PROJECTOR_MUTED)
                    what = "muted" if s.PROJECTOR_MUTED else "at %d%%" % round(s.GAME_VOLUME * 100)
                else:
                    n, what = s.apply(pid, volume=s.GAME_VOLUME, mute=False), "at %d%%" % round(s.GAME_VOLUME * 100)
                if n:
                    self.done.add(role)
                    say("sound: %s starts %s (pid %d) - the Volume Mixer changes it from here" % (
                        "the projector" if role == "projector" else role, what, pid))
        except Exception as ex:                 # the volumes never stop the helper: the game plays as Windows has it
            if not self.said:
                say("sound: the starting volumes could not be set (%r) - tried again every %.1f s" % (ex, self.LOOK))
                self.said = True


def main(argv):
    if not argv or not argv[0].isdigit():
        print(__doc__)
        return 2
    life = int(argv[0])
    data = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(HERE), "data")
    play = argv[2] if len(argv) > 2 else os.path.join(os.path.dirname(HERE), "PLAY.exe")
    flags = CREATE_NO_WINDOW if argv[3:] == ["hidden"] else CREATE_NEW_CONSOLE
    req = os.path.join(data, "restart.request")
    if os.path.exists(req):
        try:
            os.remove(req)
            say("an old restart request (from a run that ended) removed - not carried out")
        except OSError as ex:
            say("an old restart request could not be removed: %s" % ex)
    say("watching %s" % req)
    view = ClubView(data)
    sound = SoundDefaults(os.environ.get("WCCF_GAME"), time.time())
    end = time.time() + life
    while time.time() < end:
        view.tick(time.time())
        sound.tick(time.time())
        if os.path.exists(req):
            try:
                os.remove(req)                  # taken first: one request, one restart
            except OSError:
                time.sleep(0.5)
                continue
            say("RESTART NOW asked - opening PLAY.exe restart in its own window")
            try:
                subprocess.Popen([play, "restart"], cwd=os.path.dirname(play), creationflags=flags, close_fds=True)
            except OSError as ex:
                say("could not open PLAY.exe restart: %s" % ex)
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
