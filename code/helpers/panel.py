# -*- coding: utf-8 -*-
r"""panel.py - does what the in-game panels ask for and cannot do from inside the game.  play.py starts it
(hidden) with the cabinets; the end of the run ends it with everything else.
    python panel.py SECONDS [DATA PLAY_EXE [hidden]]        (DATA, PLAY_EXE, hidden: tests only)

RESTART NOW (the SETTINGS panel, 2026-10-06): the panel writes data\restart.request; this helper takes the file away
and opens "PLAY.exe restart" in a window of its own: a stop by the card rule (during a card session it explains
and asks), then a plain start with the NEXT START settings.  It has to come from out here: seat 1 runs under a
debugger that follows the programs it starts, so a restart started by the game itself would be killed half way.
A request that is already there when the helper starts (left by a run that ended) is removed, never carried out.

THE CLUB CARD panel's view (2026-10-06): data\club_view.txt, rewritten by view.py (with decode.py, the
reader the website will use) whenever the card, its backups or the run change - once the card has held still for a
second, so the game's bursts of saves are not read half way.  A view that cannot be written is said once and never
stops the helper: RESTART NOW does not depend on it.

SEND LOGS (the SETTINGS panel, 2026-10-09): the panel writes data\sendlogs.request with the server's address; this
helper takes it away, packs and sends the logs (online\send_logs.py) in a thread of its own, and writes data\sendlogs.result
for the panel: "sending", then "ok CODE" or "fail WHY".  An old request at the start is removed, never sent.

THE ONLINE CLUB CARD (2026-10-14): online and signed in (play.py WCCF_CLUB_CARD), each save of the account's club
card goes to wccf.online (online\club.py upload) once the card has held still for 2 s and its last save was the
locker-room save - never mid-match - in a thread of its own; a send that cannot reach the website is tried again a
minute later, and the next start sends what is left.  The new card a manager transfer puts beside it (NAME.new.bin,
2026-10-15) is watched the same way: its first locker-room save goes up as the account's card at once, so the card
that match earned is found and shown (watching only the old card, the real game's transfer showed none).  Once the
website has the save, the cards on the table and where each stands go up too (online\club.py send_formation), for
the account's profile on wccf.online (2026-10-16).

THE ONLINE PROJECTOR COMES BACK (2026-10-17): online, the projector's link to the server (through its projector relay)
is looked at every 2 s.  Once it is gone - the game puts up Error 3000 and never reconnects by itself - this helper runs
"play.py projector" (hidden, output to data\logs\run_projector_restart.txt): that projector ends and a fresh one
starts, joins the relay again and shows the next phase.  The cabinet is never touched.  A projector whose window the
player closed is gone, and stays gone: only a projector that still has its window is ever restarted.  See keep_projector.
SETTINGS' OPEN / CLOSE PROJECTOR (2026-10-17): the panel writes data\projector.request ("open" or "close"); this
helper runs "play.py projector open|close" - a fresh projector (the tries back), or the projector closed as the player
would, never brought back.  data\projector.state ("open" / "closed") tells the panel which the button offers.

THE STARTING VOLUMES (2026-10-06): sound.py - the projector muted, seat 1 very low - set once for each, as
soon as it has opened its sound (looked for every 0.5 s for 10 minutes after the start); never again, so a change in
the Volume Mixer stays.  The game folder comes from play.py (WCCF_GAME); without it nothing is set.  Like the view, it
never stops the helper.
"""
import os
import re
import subprocess
import sys
import threading
import time

import kit_common as K

HERE = os.path.dirname(os.path.abspath(__file__))
CREATE_NEW_CONSOLE, CREATE_NO_WINDOW = 0x10, 0x08000000


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class ClubView:
    """the CLUB CARD panel's view of the card in DATA (data\\club_view.txt)"""

    def __init__(self, data, online_card=None):
        save = os.path.join(data, "save")
        self.card, self.backups = os.path.join(save, "seat1_club.bin"), os.path.join(save, "backup")
        self.cards = os.path.join(save, "cards")                       # your other club cards (wallet.py)
        if online_card:      # online and signed in (play.py WCCF_CLUB_CARD): the account's club, no other cards
            folder = os.path.dirname(online_card)
            self.card, self.backups, self.cards = online_card, os.path.join(folder, "backup"), os.path.join(folder, "cards")
        self.running, self.out = os.path.join(data, "running.json"), os.path.join(data, "club_view.txt")
        self.catalogue = os.path.join(data, "cache", "catalogue.tsv")     # made by SETUP (was overlay\)
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
                from cards import view
                self.mod = view
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


class SendLogs:
    """SEND LOGS: data\\sendlogs.request (the address) -> online\\send_logs.py in a thread -> data\\sendlogs.result"""

    def __init__(self, data):
        self.req, self.res = os.path.join(data, "sendlogs.request"), os.path.join(data, "sendlogs.result")
        self.kit, self.job = os.path.dirname(os.path.abspath(data)), None
        if os.path.exists(self.req):
            try:
                os.remove(self.req)
                say("an old SEND LOGS request (from a run that ended) removed - not sent")
            except OSError:
                pass

    def result(self, text):
        try:
            with open(self.res + ".tmp", "w", encoding="ascii", errors="replace") as f:
                f.write(text + "\n")
            os.replace(self.res + ".tmp", self.res)
        except OSError as ex:
            say("SEND LOGS: the result could not be written: %s" % ex)

    def run(self, address):
        try:
            from online import send_logs
            blob, n = send_logs.pack(self.kit)
            ok, what = send_logs.send(address, blob, send_logs.version(self.kit))
            say("SEND LOGS to %s: %d files, %d KB - %s" % (address, n, len(blob) // 1024,
                                                          "code " + what if ok else "not sent: " + what))
            self.result(("ok %s" if ok else "fail %s") % what)
        except Exception as ex:             # never stops the helper: the panel is told
            say("SEND LOGS failed: %r" % ex)
            self.result("fail could not pack the logs (%s)" % ex.__class__.__name__)

    def tick(self):
        if not os.path.exists(self.req) or (self.job and self.job.is_alive()):
            return
        try:
            with open(self.req, encoding="ascii", errors="replace") as f:
                address = f.read().strip()
            os.remove(self.req)             # taken first: one request, one upload
        except OSError:
            return
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", address):
            self.result("fail no server address - type it under PLAY ON first")
            return
        self.result("sending")
        say("SEND LOGS asked - packing and sending to %s" % address)
        self.job = threading.Thread(target=self.run, args=(address,), daemon=True)
        self.job.start()


class SoundDefaults:
    """the projector muted and seat 1 at sound.GAME_VOLUME, each set once, when it has first opened its
    sound; a projector started again (again(), ProjectorKeeper) is set too - each process once.  mod: helpers.sound,
    or a stand-in (the tests)"""
    LOOK, FOR = 0.5, 600.0

    def __init__(self, game, now, mod=None):
        self.targets = {}
        if game:
            game = os.path.abspath(game)
            self.targets = {os.path.normcase(os.path.join(game, "client_Release.exe")): "projector",
                            os.path.normcase(os.path.join(os.path.dirname(game), "seat1", "client_Release.exe")):
                                "seat 1"}
        self.want, self.done = set(self.targets.values()), set()       # the roles still to set; the pids set
        self.mod, self.next, self.until, self.said = mod, 0.0, now + self.FOR, False

    def again(self, now):
        """the projector started again: its new process is muted too"""
        self.want.add("projector")
        self.until = max(self.until, now + self.FOR)

    def tick(self, now):
        if not self.want or now < self.next or now > self.until:
            return
        self.next = now + self.LOOK
        try:
            if self.mod is None:
                from helpers import sound
                self.mod = sound
            s = self.mod
            for pid, path, _level, _muted in s.sessions():
                role = self.targets.get(os.path.normcase(path or ""))
                if role not in self.want or pid in self.done:      # the projector before keeps its old pid
                    continue
                if role == "projector":
                    n = s.apply(pid, volume=s.GAME_VOLUME, mute=s.PROJECTOR_MUTED)
                    what = "muted" if s.PROJECTOR_MUTED else "at %d%%" % round(s.GAME_VOLUME * 100)
                else:
                    n, what = s.apply(pid, volume=s.GAME_VOLUME, mute=False), "at %d%%" % round(s.GAME_VOLUME * 100)
                if n:
                    self.want.discard(role)
                    self.done.add(pid)
                    say("sound: %s starts %s (pid %d) - the Volume Mixer changes it from here" % (
                        "the projector" if role == "projector" else role, what, pid))
        except Exception as ex:                 # the volumes never stop the helper: the game plays as Windows has it
            if not self.said:
                say("sound: the starting volumes could not be set (%r) - tried again every %.1f s" % (ex, self.LOOK))
                self.said = True


class ClubSync:
    """the online club card's saves to wccf.online (see the top); card None: not online, nothing to do"""

    CHECKS = (5, 15, 35, 60)    # seconds after a save: the card the match earned (phase 3: the server tells the website)

    def __init__(self, card, data=None, seat=None):
        self.card, self.seen, self.since, self.done, self.retry_at, self.busy = card, None, 0.0, None, 0.0, None
        self.data, self.checks, self.seat = data or K.DATA, [], seat    # seat: its table goes up after each save

    def tick(self, now):
        if not self.card or (self.busy and self.busy.is_alive()):
            return
        if self.checks and now >= self.checks[0]:          # after a match: did it earn a card yet?
            self.checks.pop(0)
            self.busy = threading.Thread(target=self.look, daemon=True)
            self.busy.start()
            return
        try:                                    # the card's bytes, not its time: two saves in one tick of Windows'
            with open(self.card, "rb") as f:    # clock (about 16 ms) have the same time (a test missed one)
                sig = hash(f.read())
        except OSError:
            sig = None
        if sig != self.seen:                    # changed: wait until it holds still
            self.seen, self.since = sig, now
            return
        if sig is None or sig == self.done or now - self.since < 2.0 or now < self.retry_at:
            return
        if K.card_session(self.card)[0] != "closed":     # mid-match, a blank card, unreadable: not now
            return
        self.busy = threading.Thread(target=self.send, args=(sig, now), daemon=True)
        self.busy.start()

    def send(self, sig, now):
        from online import account, club
        token = (account.load() or {}).get("token")
        if not token:
            self.done = sig
            say("club card: this PC is not signed in - not sent to wccf.online")
            return
        state, detail = club.upload(token, self.card, os.path.dirname(self.card))
        say("club card -> wccf.online: %s" % {"kept": "kept (version %s)" % detail,
                                              "same": "it has this save already"}.get(state, "%s - %s" % (state, detail)))
        if state == "unreachable":
            self.retry_at = now + 60
        else:
            self.done = sig
            self.checks = [now + s for s in self.CHECKS]
        if self.seat and state in ("kept", "same"):     # the website has this club: its table for the profile too
            got, why = club.send_formation(token, self.seat)
            say("formation -> wccf.online: %s" % {"kept": "kept (%s cards)" % why,
                                                  "empty": "no card on the table - not sent"}.get(got, "%s - %s" % (got, why)))

    def look(self):
        from online import account, club
        token = (account.load() or {}).get("token")
        new = club.new_cards(token, self.data) if token else []
        if new:
            self.checks = []
            say("new card from wccf.online: %s - in the CATALOGUE now" % ", ".join(map(str, new)))


PROJECTOR_PORTS = (20002, 20031)        # the server: control itself, or its projector relay (play.py PROJECTOR_PORT)
WAIT_LINK = 90                          # s: a projector just started has this long to link up
BACKOFF = (10, 30, 60)                  # s without the link before each restart: 3 tries ...
HOLD = 600                              # ... and a link that then holds this long earns them back


def keep_projector(st, now, pid, window, linked):
    """Pure: True = restart the projector now.  st: this rule's memory (a dict, {} at first); pid: the projector's
    process, None when there is none (never started, or ended: its window closed - and a close stays closed);
    window: its window is up; linked: it has its link to the server.  A link gone (or a fresh projector without one
    after WAIT_LINK) waits BACKOFF[tries] before the restart; after the last try nothing more until the run ends"""
    if pid != st.get("pid"):                             # a new projector (the first, or one restarted): its start
        st.update(pid=pid, due=now + WAIT_LINK, up=None)
    if pid is None or not window or st.get("closed"):   # (closed: CLOSE PROJECTOR - the player's close too)                        # gone, or its window closing: never brought back
        return False
    tries = st.get("tries", 0)
    if linked:
        st["up"] = st["up"] or now
        st["due"] = None
        if tries and now - st["up"] >= HOLD:
            st["tries"] = 0
        return False
    st["up"] = None
    if st["due"] is None:                               # the link just went
        st["due"] = now + BACKOFF[min(tries, len(BACKOFF) - 1)]
    if tries >= len(BACKOFF) or now < st["due"]:
        return False
    st.update(tries=tries + 1, due=None)
    return True


def projector_request(st, text):
    """Pure: SETTINGS' OPEN / CLOSE PROJECTOR - text: data\\projector.request's ("open ..." / "close ...").  The word for
    "play.py projector WORD", or None: no such word - the press is dropped.  open gives keep_projector its tries back;
    close is the player's close, at once: never brought back until an open (2026-10-17: also while a restart runs)"""
    word = (text.split() or [""])[0].lower()
    if word not in ("open", "close"):
        return None
    st.update(closed=word == "close", tries=0 if word == "open" else st.get("tries", 0), due=None)
    return word


def projector_up(st, pid, linked):
    """Pure: what the panel's button offers - True: CLOSE PROJECTOR (one runs), False: OPEN PROJECTOR (none, closed,
    or given up: out of tries and not linked)"""
    return bool(pid) and not st.get("closed") and (linked or st.get("tries", 0) < len(BACKOFF))


class ProjectorKeeper:
    """the online projector, restarted once it has lost the server for good (keep_projector); game None or not an
    online run with a projector: nothing to do"""
    LOOK = 2.0

    def __init__(self, game, data, run=None):
        self.exe = os.path.normcase(os.path.join(os.path.abspath(game), "client_Release.exe")) if game else None
        self.running, self.logs = os.path.join(data, "running.json"), os.path.join(data, "logs")
        self.run = run or self.restart                   # tests: a stand-in
        self.st, self.next, self.job, self.shown, self.want, self.run_id = {}, 0.0, None, None, None, None
        self.state = os.path.join(data, "projector.state")

    def online_projector(self):
        """an online run with a projector on this PC (running.json); its id kept for play.py projector run=ID"""
        try:
            import json
            with open(self.running, encoding="utf-8") as f:
                info = json.load(f)
            self.run_id = info.get("run")
            return info.get("mode") == "remote" and (bool(info.get("projector")) or
                                                     "projector launcher" in info.get("processes", {}).values())
        except (OSError, ValueError, AttributeError):
            return False

    def busy(self):
        return bool(self.job and self.job.poll() is None)

    def asked(self, text):
        """data\\projector.request: SETTINGS' OPEN / CLOSE PROJECTOR.  While a restart runs, the last press waits for it
        (tick) - a CLOSE then closes the projector that restart brings"""
        word = projector_request(self.st, text)
        if word is None:
            say("projector request %r dropped (not open/close)" % text.strip())
            return
        self.next = 0.0
        if word == "close":
            self.show(False)                             # the panel offers OPEN at once: no restart comes now
        if self.busy():
            self.want = word
            say("%s PROJECTOR asked in SETTINGS - after the restart under way" % word.upper())
            return
        self.online_projector()
        self.run(self.st.get("tries", 0), word)

    def show(self, up):
        """data\\projector.state for the panel's OPEN / CLOSE PROJECTOR"""
        if up != self.shown:
            with open(self.state, "w", encoding="utf-8") as f:
                f.write("open\n" if up else "closed\n")
            self.shown = up

    def restart(self, tries, word=None):
        if word:
            say("%s PROJECTOR asked in SETTINGS" % word.upper())
        else:
            say("the projector has lost the server - starting it again (try %d of %d)" % (tries, len(BACKOFF)))
        try:
            with open(os.path.join(self.logs, "run_projector_restart.txt"), "a", encoding="utf-8") as out:
                self.job = subprocess.Popen([sys.executable, "-u", os.path.join(os.path.dirname(HERE), "play.py"),
                                             "projector"] + ([word] if word else []) +
                                            (["run=%s" % self.run_id] if self.run_id else []),
                                            stdout=out, stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
                                            close_fds=True)
        except OSError as ex:
            say("could not run play.py projector: %s" % ex)

    def tick(self, now):
        if not self.exe or self.busy():
            return
        if self.want:                                   # a press that waited for a restart: it goes first
            word, self.want = self.want, None
            self.online_projector()
            self.run(self.st.get("tries", 0), word)
            return
        if now < self.next:
            return
        self.next = now + self.LOOK
        try:
            if not self.online_projector():
                return
            pid = next((p[0] for p in K.processes() if os.path.normcase(p[3]) == self.exe), None)
            links = K.links_of(pid) if pid else set()
            if links is None:                           # Windows' table unreadable: no decision on that
                return
            linked = any(p in links for p in PROJECTOR_PORTS)
            if keep_projector(self.st, now, pid, bool(pid and K.windows_of(pid)), linked):
                self.run(self.st["tries"])
            self.show(projector_up(self.st, pid, linked))
        except Exception as ex:                         # never stops the helper
            say("projector watch: %r" % ex)


def club_syncs(card, data, seat=None):
    """the online club card's sends (card None: offline, nothing): the card - after each, the table in the seat folder
    (seat None: no game folder known, no table sent) - and the new card a manager transfer puts beside it (NAME.new.bin -
    card_reader.py NEWCARDFILE, play.py)"""
    return [ClubSync(card, data, seat), ClubSync(card and os.path.splitext(card)[0] + ".new.bin", data)]


def main(argv):
    if not argv or not argv[0].isdigit():
        print(__doc__)
        return 2
    life = int(argv[0])
    data = argv[1] if len(argv) > 1 else K.DATA
    play = argv[2] if len(argv) > 2 else os.path.join(K.KIT, "PLAY.exe")
    flags = CREATE_NO_WINDOW if argv[3:] == ["hidden"] else CREATE_NEW_CONSOLE
    req, preq = os.path.join(data, "restart.request"), os.path.join(data, "projector.request")
    for old in (req, preq, os.path.join(data, "projector.state")):
        if os.path.exists(old):
            try:
                os.remove(old)
                say("an old %s (from a run that ended) removed - not carried out" % os.path.basename(old))
            except OSError as ex:
                say("an old %s could not be removed: %s" % (os.path.basename(old), ex))
    say("watching %s" % req)
    view = ClubView(data, os.environ.get("WCCF_CLUB_CARD"))      # online: the account's club (play.py)
    sound = SoundDefaults(os.environ.get("WCCF_GAME"), time.time())
    logs = SendLogs(data)
    game = os.environ.get("WCCF_GAME")                                  # play.py: the game folder; seat 1 beside it
    syncs = club_syncs(os.environ.get("WCCF_CLUB_CARD"), data, K.seat_dir(game) if game else None)
    keeper = ProjectorKeeper(game, data)

    def run(tries, word=None):
        keeper.restart(tries, word)
        if word != "close":
            sound.again(time.time())                                    # the new projector starts muted too
    keeper.run = run
    end = time.time() + life
    while time.time() < end:
        if os.path.exists(preq):                # SETTINGS' OPEN / CLOSE PROJECTOR: before the keeper's own
            try:
                with open(preq, encoding="utf-8", errors="replace") as f:
                    text = f.read()
                os.remove(preq)                 # taken first: one press, one action
            except OSError:
                text = ""
            if text:
                keeper.asked(text)
        keeper.tick(time.time())
        view.tick(time.time())
        sound.tick(time.time())
        logs.tick()
        for sync in syncs:
            sync.tick(time.time())
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
