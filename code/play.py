# -*- coding: utf-8 -*-
r"""play.py - start (and stop) WCCF 2010-11 on this PC: Sega's server, the projector (the shared big screen) and the
player cabinet (seat 1) with the overlay and your keyboard.  PLAY.exe runs it; run SETUP.exe first.

    python play.py            start everything on this PC - or, when the SETTINGS panel chose ONLINE, the cabinets
                              on its server (as "remote ADDRESS"), and this PC if that server does not answer;
                              closing the cabinet's window ends the run (there is no fixed time limit any more);
                              closing the projector's window stops nothing else
    python play.py local      everything on this PC, whatever the SETTINGS panel chose
    python play.py server     only the server side (scene service, server, its 4 match engines): for the PC or
                              cloud machine that hosts the game for others - its TCP port 20002 must be open to them;
                              it runs up to 32 days
    python play.py remote ADDRESS
                              only the cabinet on this PC, playing on the server at ADDRESS (four numbers with dots -
                              the game takes no names): the server's seat desk gives this PC the next free seat, and
                              when the server runs a projector relay this PC shows the projector through it (SETTINGS'
                              SHOW PROJECTOR, on unless switched off; a server without the desk: seat 1 and the
                              projector, as before). The address is remembered, so a later "play.py remote" alone uses
                              it again. "play.py local" puts this PC back.
    python play.py remote ADDRESS seat N
                              seat N (1-8), if it is free there
    python play.py remote ADDRESS dream
                              DREAM TEAM (2026-10-15; the SETTINGS panel's DREAM TEAM chip does the same): online
                              with this PC's own club card and any card, no wccf.online sign-in and no cards earned;
                              in friendlies the server pairs a DREAM TEAM club only with other DREAM TEAM clubs (the
                              game reports the top matching number, 16383 - docs\research\ARRANGE-FIXTURE-2010-11.md
                              9.2); league and cup rounds can still pair DREAM TEAM and ONLINE players
    python play.py debug      the same with full logs (the card reader then logs every byte, ~60 MB an hour) and
                              every window open (the server's console and settings window, the key driver's);
                              "debug" also goes with server or remote
    python play.py stop       stop everything - refused while your club card is in the reader (the game may be
                              saving it: press I in the game first); "stop force" stops anyway;
                              "stop check" only says what stop would do, and stops nothing
    python play.py ended      what PLAY.exe's watcher runs once a game window is closed: the cabinet's - stop the
                              rest (a server started on this PC with "server" stays, for the other players); the
                              projector's alone - nothing
    python play.py status     what is running
    python play.py show       show the server's hidden windows again: its console (the round-by-round log) and its
                              settings window - to look at; they are hidden again at the next start
    python play.py projector  what the panel helper runs when the online projector has lost the server for good
                              (Error 3000): that projector ends and a fresh one starts; the cabinet is not touched
    python play.py projector open|close   SETTINGS' OPEN / CLOSE PROJECTOR, through panel.py: a fresh projector (also
                              after the player closed it), or the projector closed as by its window's X
    python play.py restart    what the panels' RESTART NOW runs, through panel.py, in a window of its own: when a
                              plain start would play the same way (same THIS PC / ONLINE server, no English switch) -
                              a club card switch, say - only the cabinet restarts and the projector keeps running;
                              otherwise stop (the card rule), then a plain start

Order, each step waiting for the one before: scene service -> server (and its 4 match engines) -> projector ->
the cabinet's stand-ins (keychip and network, card reader, I/O board) -> seat 1 -> the overlay -> the key driver ->
the panel helper (panel.py: RESTART NOW).  Online the projector starts after the key driver, once the cabinet has its
match slot (see match_slot).
Only the game's own windows open (since 2026-10-06): the server's two windows and every script's start hidden,
unless "debug".
The SETTINGS panel in seat 1's window writes data\panel.txt (2026-10-06): "play_on=this_pc" or "play_on=online" with
"server=ADDRESS" (and "online_mode=dream" for its DREAM TEAM chip) - what a plain start does - "projector=off" (its SHOW
PROJECTOR chip off: online, no projector on this PC; kept) and "english=on" /
"english=it" / "english=off", a request done at the next start
(by english.py, while nothing runs) and then taken out of the file.
"remote" next to a server started on this PC with "server" uses that server's scene service and keeps its logs
(the cabinets' logs of the run before are then not kept); if such a start fails, everything on this PC is stopped,
the server too.
Logs: data\logs\ (the run before: data\logs\previous\; older runs zipped in data\logs\archive\, the oldest dropped
past ARCHIVE_LIMIT); the key driver's is run_keys.txt.
Exit: 0 ok, 1 a step failed, 2 not set up, 3 refused.
"""
import filecmp
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import zipfile

import kit_common as K

CONTROL_PORT = 20002
RELAY_PORT = 20040                                    # UDP, the server's match relay (server\relay.py)
PROJECTOR_PORT = 20031                                # TCP, the server's projector relay (server\projector_relay.py)
SERVER_ROLES = ("scene service", "server launcher", "seat desk", "match relay", "log inbox", "witness",
                "projector relay")
WITNESS = os.path.join(K.DATA, "witness")      # a server with a wccf.online secret keeps each match's club data here
                                               # (the hook, source\hook\wccfk.c) for server\witness.py (2026-10-14)


def witness_ready():
    """this server is one of wccf.online's (data\\server_name.txt + server_secret.txt): finished matches earn cards"""
    return all(os.path.isfile(os.path.join(K.DATA, n)) for n in ("server_name.txt", "server_secret.txt"))
SERVER_LIFE = 32 * 24 * 3600      # "play.py server" (2026-10-07): a month and a day - a server for others stays up
                                  # all month; a keeper task on that machine restarts it whenever it stops
LIFE = SERVER_LIFE                # the player side: a BACKSTOP only (A3, 2026-10-11). A player's run really ends when
                                  # its game window is closed (source\launcher\src\watch.rs ends the whole run then);
                                  # the old 12-hour limit killed a long session mid-match, costing the card a bad
                                  # ending - so there is no short limit any more, only this far-off safety net
PY = sys.executable
ICC_PIPE, JVS_PIPE = r"\\.\pipe\wccf_icc_seat1", r"\\.\pipe\wccf_jvs_seat1"
KEYS_INPUT = os.path.join(K.DATA, "_jvs_seat1_input.txt")        # = hardware\keyboard.LIVE; the board's outputs beside it
CARD = os.path.join(K.SAVE, "seat1_club.bin")
RUNNING = os.path.join(K.DATA, "running.json")
PANEL = os.path.join(K.DATA, "panel.txt")         # the SETTINGS panel's choices (wccfpanel.dll writes it)
CREATE_NEW_CONSOLE = 0x10
SW_HIDE, SW_SHOWMINNOACTIVE = 0, 7


class Failed(Exception):
    pass


class SignInRefused(Failed):
    """the server's seat desk wants a wccf.online sign-in, or refused this PC's (2026-10-14): main() then plays on this
    PC and says why - never a dead end"""


def say(msg):
    print(msg, flush=True)


def kit_pythons():
    """this kit's own Python processes (the stand-ins, the launchers, the key driver), except this one: the ones that
    run the kit's own python\\python.exe, whichever Python runs this (2026-10-06: "stop" run with the system's Python
    matched THAT one - it found 0 and left 6 stand-ins running, and would have stopped any other program of it)"""
    kit_py = os.path.join(K.KIT, "python", "python.exe")
    me = os.path.normcase(kit_py if os.path.isfile(kit_py) else PY)
    return [p for p in K.processes() if os.path.normcase(p[3]) == me and p[0] != os.getpid()]


def card_in():
    """True / False from the key driver's file (p2 bit 0x20 = the card sensor); None if it cannot be read"""
    if not os.path.exists(KEYS_INPUT):
        return False                     # no key driver has ever run here: no card can be in
    for _ in range(5):                   # the driver swaps the file in whole; a read can meet the swap - try again
        try:
            with open(KEYS_INPUT, encoding="ascii", errors="replace") as f:
                for line in f:
                    if line.startswith("p2="):
                        return bool(int(line[3:].split()[0], 0) & 0x20)
        except (OSError, ValueError, IndexError):
            pass
        time.sleep(0.05)
    return None


def start(script, args, log_name, env, show=SW_HIDE, quiet=False):
    """a kit script in its own (hidden) console; output to data\\logs\\<log_name>"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = show
    out = None
    if log_name:
        out = subprocess.DEVNULL if quiet else open(os.path.join(K.LOGS, log_name), "w", encoding="utf-8")
    return subprocess.Popen([PY, "-u", os.path.join(K.SCRIPTS, script)] + [str(a) for a in args], cwd=K.LOGS,
                            env=env, stdout=out, stderr=subprocess.STDOUT if out else None,
                            creationflags=CREATE_NEW_CONSOLE, startupinfo=si)


def valid_ipv4(s):
    """four numbers 0-255 with dots, at most 15 characters (the game keeps the address in 16 bytes, inet_addr);
    only the digits 0-9 (isdigit() alone takes Arabic-Indic digits, which the game cannot read)"""
    m = re.fullmatch(r"([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})", s)
    return bool(m) and all(int(x) <= 255 for x in m.groups())


def server_answers(ip, port=CONTROL_PORT, seconds=5):
    """True if something takes a TCP connection on ip:port (closed again at once)"""
    try:
        with socket.create_connection((ip, port), timeout=seconds):
            return True
    except OSError:
        return False


def set_control_ip(conf, ip):
    """put ip into the CONTROL_IP= and MATCH_IP= lines of a cabinet's client_user_option.conf and touch nothing
    else (the line ends stay); True if the file changed"""
    with open(conf, "rb") as f:
        raw = f.read()
    if not re.search(rb"(?m)^CONTROL_IP=", raw):
        raise Failed("%s has no CONTROL_IP line - run SETUP.exe again" % conf)
    out = re.sub(rb"(?m)^(CONTROL_IP|MATCH_IP)=[^\r\n]*", lambda m: m.group(1) + b"=" + ip.encode("ascii"), raw)
    if out == raw:
        return False
    with open(conf + ".tmp", "wb") as f:
        f.write(out)
    os.replace(conf + ".tmp", conf)
    with open(conf, "rb") as f:
        if f.read() != out:
            raise Failed("could not write %s" % conf)
    return True


def set_satellite_no(conf, n):
    """the cabinet's seat in its client_user_option.conf: setup.py writes SATELLITE_NO there (the game would read it
    from its command line, which breaks on folder names with spaces) - "remote ... seat N" sets N, every other start 1;
    touches nothing else; True if the file changed"""
    with open(conf, "rb") as f:
        raw = f.read()
    if not re.search(rb"(?m)^SATELLITE_NO=", raw):
        raise Failed("%s has no SATELLITE_NO line - run SETUP.exe again" % conf)
    out = re.sub(rb"(?m)^SATELLITE_NO=[^\r\n]*", b"SATELLITE_NO=%d" % n, raw)
    if out == raw:
        return False
    with open(conf + ".tmp", "wb") as f:
        f.write(out)
    os.replace(conf + ".tmp", conf)
    with open(conf, "rb") as f:
        if f.read() != out:
            raise Failed("could not write %s" % conf)
    return True


def set_conf_value(conf, key, value):
    """KEY=value in one of the game's settings files: the line replaced, or added (in the file's own line ends);
    nothing else touched; True if the file changed"""
    with open(conf, "rb") as f:
        raw = f.read()
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    line = key.encode("ascii") + b"=" + str(value).encode("ascii")
    pat = re.compile(rb"(?m)^" + re.escape(key.encode("ascii")) + rb"=[^\r\n]*")
    if pat.search(raw):
        out = pat.sub(lambda m: line, raw)
    else:
        out = raw + (b"" if raw.endswith(nl) or not raw else nl) + line + nl
    if out == raw:
        return False
    with open(conf + ".tmp", "wb") as f:
        f.write(out)
    os.replace(conf + ".tmp", conf)
    with open(conf, "rb") as f:
        if f.read() != out:
            raise Failed("could not write %s" % conf)
    return True


def running_roles():
    """{pid: role} from data\\running.json (written by the run that started them)"""
    try:
        with open(RUNNING, encoding="utf-8") as f:
            return {int(k): v for k, v in json.load(f).get("processes", {}).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def running_info():
    """data\\running.json as the run that started wrote it (mode, server, seat, processes); {} if there is none"""
    try:
        with open(RUNNING, encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except (OSError, ValueError):
        return {}


CABINET_ROLES = ("keychip / network stand-in", "card reader stand-in", "I/O board stand-in", "key driver")


def is_cabinet_role(role):
    """a seat cabinet's own part (2026-10-07): its stand-ins, its launcher, its key driver - never the projector, the
    scene service, the seat lease, the panel helper or a server's part"""
    return role in CABINET_ROLES or bool(re.fullmatch(r"seat \d+ launcher", role or ""))


# the overlay (seat 1's panels, the projector's money): the kit's hook (wccfk.dll, source\hook\wccfk.c) loads it once the
# game's window is up, in the game itself - for the two windows whose environment names it, never the server.  Before
# 2026-10-09 overlay\inject.exe wrote it into the running game from outside, which antivirus programs flag
PANEL_DLL = os.path.join(K.PROGRAMS, "wccfpanel.dll")     # not PANEL: that is data\panel.txt (Kit 5.5 reused the
                                                          # name, so a plain start read the dll and never went online)


def kit_env(game, online=None, dream=False):
    """what every program of a run gets: this PC's environment without an earlier run's MXHOOK_ / WCCF settings, and
    where the game and the logs are.  online (online\\club.py): the account's club card (WCCF_CLUB_CARD - the card
    reader, the panel and its helper use it instead of the slot card) and a CATALOGUE of its own cards only.  dream
    (DREAM TEAM): WCCF_DREAM_TEAM=1 - the seat lease asks without the sign-in, and the panel has the game report the top
    matching number (wccfpanel.c dream_team_install)"""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("MXHOOK_", "WCCF"))}
    env.update(WCCF_GAME=game, WCCF_LOGS=K.LOGS, MXHOOK_LOG_DIR=os.path.join(K.LOGS, "hook"),
               # where the panel (wccfpanel.dll, now in programs\) finds its own data, no longer beside the DLL:
               WCCF_SKIN=os.path.join(K.ART, "skin.tex"), WCCF_CATALOGUE=os.path.join(K.CACHE, "catalogue.tsv"),
               WCCF_CARDS=os.path.join(K.CACHE, "cards"))
    for k in ("WCCF_WEBSITE", "WCCF_ACCOUNT_FILE"):       # a test's website and sign-in file reach the run's programs
        if os.environ.get(k):
            env[k] = os.environ[k]
    if online:
        env.update(WCCF_CLUB_CARD=online["card"], WCCF_CATALOGUE=online["catalogue"])
    if dream:
        env["WCCF_DREAM_TEAM"] = "1"
    from online import account                # SETTINGS' ACCOUNT row: the name only - the panel never sees the token
    env["WCCF_ACCOUNT_NAME"] = str((online or account.load() or {}).get("username") or "")
    return env


def not_server_side(running, roles, py=None):
    """of the running processes (pid, parent, name, path), those that are NOT a server started with "server": the
    server, its match engines and logowin (children of the server), and the kit pythons whose role is the scene
    service or the server launcher"""
    py = os.path.normcase(py or PY)
    servers = {p[0] for p in running if p[2].lower() == "control_release.exe"}
    out = []
    for p in running:
        name = p[2].lower()
        if name == "control_release.exe":
            continue
        if name in ("match_release.exe", "logowin.exe") and p[1] in servers:
            continue
        if os.path.normcase(p[3]) == py and roles.get(p[0]) in SERVER_ROLES:
            continue
        out.append(p)
    return out


def wait_for(what, test, seconds, proc=None, log_name=None):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return
        if proc is not None and proc.poll() is not None:
            break
        time.sleep(0.5)
    raise Failed("%s did not come up%s" % (what, (" - see data\\logs\\%s" % log_name) if log_name else ""))


ARCHIVE_LIMIT = 200 * 1024 * 1024       # data\logs\archive: zipped runs kept up to this many bytes, the oldest go first


def archive_run(folder, archive, limit=ARCHIVE_LIMIT):
    r"""a run's log folder -> archive\run-<time of its last write>.zip (2026-10-09: the player's freeze was two runs
    back, gone with the old rmtree).  Then the oldest zips go until the archive fits in `limit`.  True = zipped."""
    files = [os.path.join(d, n) for d, _, ns in os.walk(folder) for n in ns]
    if not files:
        return False
    os.makedirs(archive, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(max(os.path.getmtime(f) for f in files)))
    out, n = os.path.join(archive, "run-%s.zip" % stamp), 2
    while os.path.exists(out):
        out, n = os.path.join(archive, "run-%s (%d).zip" % (stamp, n)), n + 1
    with zipfile.ZipFile(out + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, os.path.relpath(f, folder))
    os.replace(out + ".tmp", out)
    zips = sorted(os.path.join(archive, n) for n in os.listdir(archive) if n.endswith(".zip"))   # names sort by time
    total = sum(os.path.getsize(z) for z in zips)
    for z in zips[:-1]:                                  # the newest stays, however big
        if total <= limit:
            break
        total -= os.path.getsize(z)
        os.remove(z)
    return True


def rotate_logs():
    """Keep last run's logs in data\\logs\\previous and this run's fresh. Log housekeeping must NEVER stop a start, so
    every step that can fail on a file another program is holding (an antivirus, a tail, the user viewing it) is
    caught: a stuck 'previous' is set aside with a timestamp, a stuck current log is left where it is (A9)."""
    os.makedirs(K.LOGS, exist_ok=True)
    prev = os.path.join(K.LOGS, "previous")
    if os.path.isdir(prev):
        try:
            archive_run(prev, os.path.join(K.LOGS, "archive"))
        except (OSError, zipfile.BadZipFile) as ex:     # never a reason not to start: the old run's logs just go
            say("  logs: the run before last not archived (%s)" % ex)
        try:
            shutil.rmtree(prev)
        except OSError as ex:                           # a file in it is held open: set it aside so a fresh one can be made
            aside = prev + time.strftime("-%Y%m%d-%H%M%S")
            try:
                os.rename(prev, aside)
                say("  logs: last run's folder was busy (%s) - set aside as %s" % (ex, os.path.basename(aside)))
            except OSError:
                say("  logs: last run's folder is busy (%s) - starting without rotating this run's logs" % ex)
                return
    try:
        names = [n for n in os.listdir(K.LOGS) if not n.startswith("previous") and n != "archive"]
        if names:
            os.makedirs(prev, exist_ok=True)
            for n in names:
                try:
                    shutil.move(os.path.join(K.LOGS, n), os.path.join(prev, n))
                except OSError:
                    pass                                # a current log held open: leave it, the start goes on
    except OSError as ex:
        say("  logs: could not rotate this run's logs (%s) - starting anyway" % ex)
    os.makedirs(os.path.join(K.LOGS, "hook"), exist_ok=True)


def setup_state():
    game = K.find_game(K.load_settings().get("game"))
    seat = K.seat_dir(game) if game else None
    if not game or not os.path.isfile(os.path.join(seat, ".wccf-kit")):
        say("Not set up yet - run SETUP.exe first.")
        return None, None
    if not os.path.isfile(os.path.join(K.CACHE, "catalogue.tsv")):     # the panel's card browser only (A10) - not the
        say("  (the card CATALOGUE is not built yet - the panel's catalogue will be empty; SETUP.exe rebuilds it)")
    return game, seat                                                  # game: it must never stop a start


def ensure_hook(game, seat):
    """kit 6 loads its hook as wccfk.dll (setup renames the game's import to it).  A game set up by an older kit still
    has the fake winmm.dll Windows Defender deletes - kit 6 unzipped over the old one, or the update's "set up now?"
    answered no - and a newer kit unzipped over this one by hand leaves the game the OLD wccfk.dll (setup copies it).
    Set it up once, as SETUP.exe does, instead of starting the old hook or refusing.  True = ready."""
    kit = os.path.join(K.PROGRAMS, "wccfk.dll")
    try:
        if all(filecmp.cmp(kit, os.path.join(d, "wccfk.dll"), shallow=False) for d in (game, seat)):
            return True
    except OSError:                                  # a copy is missing
        pass
    say("The game's copy of the kit's helper (wccfk.dll) is missing or not this kit's - setting the game up for it "
        "once (as SETUP.exe does) ...")
    if subprocess.call([PY, os.path.join(K.SCRIPTS, "setup.py"), game]) == 0:
        return True
    say("Setting the game up did not finish (see above) - open SETUP.exe and press set up.")
    return False


RUN_KEYS = ("run", "projector", "show_projector", "born")    # what a cabinet's or projector's restart carries over


def write_running(roles, mode, ip, seat_no=1, online=None, dream=False, run=None):
    """online: the account's club in play (online\\club.py) - a stop, a cabinet restart and the card rule read it here;
    dream: a DREAM TEAM run (a cabinet restart keeps it DREAM TEAM).  run (2026-10-17): what the running.json before
    hands on - "run" (this run's id: a projector job for another run does nothing), "run_start" (the time its card
    sessions count from - a projector's restart keeps it, so an open session stays open; the file's write time is set
    to it, which is what the panel reads), "projector" (one runs on this PC: OPEN PROJECTOR), "show_projector"
    (SETTINGS' choice at the start: RESTART NOW), "born" (each process's start: a number Windows gave to another
    program since is not taken for it).  None: a new run.  Written whole, then swapped in"""
    run = dict(run or {})
    run.setdefault("run", "%x" % time.time_ns())
    run.setdefault("run_start", time.time())
    born = run.get("born") or {}
    run["born"] = {str(pid): born.get(str(pid)) or K.started(pid) for pid in roles}
    with open(RUNNING + ".tmp", "w", encoding="utf-8") as f:
        json.dump(dict({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode, "server": ip, "seat": seat_no,
                        "processes": roles}, **run, **({"online": online} if online else {}),
                       **({"dream": True} if dream else {})), f, indent=1)
    os.replace(RUNNING + ".tmp", RUNNING)
    os.utime(RUNNING, (run["run_start"], run["run_start"]))


def carried(info, *more):
    """of a running.json, what a restart writes again (RUN_KEYS, and more)"""
    return {k: info[k] for k in RUN_KEYS + more if k in info}


def live_roles(info):
    """{pid: role} of running.json's processes that still run as the kit's Python they were started as: one whose
    number Windows gave to another program since - even another of the kit's Pythons - is left out (2026-10-17:
    "born", the start of each; a running.json without it is matched by the program alone, as before)"""
    born, alive = info.get("born") or {}, {p[0] for p in kit_pythons()}
    return {int(k): r for k, r in (info.get("processes") or {}).items()
            if int(k) in alive and born.get(str(k)) in (None, K.started(int(k)))}


def online_of(info):
    """the online club a run recorded (write_running), or None"""
    o = info.get("online")
    return o if isinstance(o, dict) and isinstance(o.get("card"), str) and isinstance(o.get("catalogue"), str) else None


def read_panel(path=None):
    """{name: value} from the SETTINGS panel's file: lines "name=value", "#" starts a note; {} if there is none"""
    out = {}
    try:
        with open(path or PANEL, encoding="ascii", errors="replace") as f:
            for line in f:
                name, eq, value = line.split("#", 1)[0].partition("=")
                if eq and name.strip():
                    out[name.strip().lower()] = value.strip()
    except OSError:
        pass
    return out


def drop_panel_line(name, path=None):
    """take a request done out of the panel's file (only while nothing of the game runs: the panel is not writing)"""
    path = path or PANEL
    try:
        with open(path, encoding="ascii", errors="replace", newline="") as f:
            lines = f.readlines()
    except OSError:
        return
    keep = [ln for ln in lines if ln.split("#", 1)[0].partition("=")[0].strip().lower() != name]
    if keep != lines:
        with open(path + ".tmp", "w", encoding="ascii", errors="replace", newline="") as f:
            f.writelines(keep)
        os.replace(path + ".tmp", path)


def apply_english_request():
    """the SETTINGS panel's "english=on" / "english=it" / "english=off": done now, before anything starts (english.py
    refuses while the game runs), then taken out of the file - a request, not a lasting setting, so SETUP.exe's GAME
    LANGUAGE still works"""
    want = read_panel().get("english", "").lower()
    if want not in K.TEXT_LANGUAGE:
        return
    name = {"on": "English", "it": "Italian", "off": "Sega's Japanese"}[want]
    if K.TEXT_LANGUAGE[want] != K.game_language():
        say("  the game's text into %s, as the SETTINGS panel asked - this takes a moment ..." % name)
        try:            # english.py swaps each file in one step, so even a stop half way leaves every file in place
            r = subprocess.run([PY, os.path.join(K.SCRIPTS, "english.py")] + (["on", "it"] if want == "it" else [want]),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
            why = "" if r.returncode == 0 else (lines[-1] if lines else "english.py exit %d" % r.returncode)
        except (OSError, subprocess.TimeoutExpired) as ex:
            why = "it did not finish: %s" % ex
        if why:
            say("  the text could not be switched (%s) - the game starts as it is" % why)
        else:
            say("  done: the game's text is %s" % name)
    drop_panel_line("english")


def apply_card_request():
    """the CLUB CARD panel's "card=FILE" / "card=new" (2026-10-06): which club card goes into the slot, done now while
    nothing runs (wallet.switch: two renames, no card ever overwritten), then taken out of the file - only
    after the switch, so one stopped half way is finished at the next start.  Anything wrong: said, and the game
    starts with the card that is in the slot (never locked out).  First, a finished manager transfer is put away
    (wallet.finish_transfer, 2026-10-08): the new club into the slot, the old card to your cards."""
    try:
        from cards import wallet
        _done, what = wallet.finish_transfer()
    except Exception as ex:                    # e.g. a card file held by another program: both stay, said
        what = "the manager transfer could not be finished now (%s) - both cards stay where they are" % ex
    if what:
        say("  club card: %s" % what)
    want = read_panel().get("card", "")
    if not want:
        return
    try:
        from cards import wallet
        done, what = wallet.switch(want)
    except Exception as ex:                    # e.g. a card file held by another program: the slot stays as it is
        done, what = False, "the switch could not be done (%s) - the card in the slot stays" % ex
    say("  club card: %s" % what)
    drop_panel_line("card")


def apply_account_request():
    """the SETTINGS panel's "account=signout" (2026-10-14): this PC's wccf.online sign-in ended before anything starts
    (online\\account.py signout: the website refuses the token from then on), then taken out of the file - the next
    online start asks for a code"""
    if read_panel().get("account", "").lower() != "signout":
        return
    from online import account
    say("  wccf.online: %s, as the SETTINGS panel asked - the next online start asks for a code" % account.signout())
    drop_panel_line("account")


def online_club(ensure, prepare):
    """remote mode's rule (the owner, 2026-10-14: "they should only have this club card when they are logged in, and if
    they are playing offline thats when they can use the other club cards"): online = signed in to wccf.online AND the
    account's own club ready -> (club, None); anything less -> (None, why), and play() plays on this PC instead"""
    token = ensure()
    if not token:
        return None, "no wccf.online sign-in"
    club = prepare(token)
    return (club, None) if club else (None, "your online club is not ready")


def apply_card_fix():
    """the CLUB CARD panel's "card_fix=bad_endings" (2026-10-08): the slot card's bad endings back to 0
    (edit.clear_bad_endings: the game's own checks, the old card into data\\save\\backup first), done now
    while the card reader is not running, then taken out of the file.  Anything wrong: said, and the card stays as it
    was (never a reason not to start)."""
    want = read_panel().get("card_fix", "").lower()
    if not want:
        return
    if want == "bad_endings":
        try:
            from cards import edit
            what = edit.clear_bad_endings(CARD)
        except Exception as ex:
            what = "the bad endings were not cleared (%s) - the card stays as it was" % ex
        say("  club card: %s" % what)
    drop_panel_line("card_fix")


def apply_board(seat, online=None):
    """the cards on the table follow the club card in the slot (formation.py, 2026-10-08: the player saw another club's
    formation on the board) - or, online and signed in, the account's online club (online\\club.py, 2026-10-14) - done
    while nothing reads the table: the card reader, FPR_Emu and the overlay start after this.  Anything wrong: said,
    and the table stays as it is (never a reason not to start)."""
    try:
        if online:
            from online import club
            said = club.table(seat, online)
        else:
            from cards import formation
            said = formation.sync(seat)
        for what in said:
            say("  table: %s" % what)
    except Exception as ex:
        say("  table: left as it is (%s)" % ex)


def _seat_decision(got, seat_no, ip):
    """Pure: the seat lease's answer (a dict) -> ('seat', n, projector) or ('no_broker', n, projector); raises Failed
    on any other trouble.  Only "no broker" (a server with no seat desk at all) falls back to seat 1 as before; full /
    taken / refused / no answer must STOP, never take seat 1 - a second PC on seat 1 means one of them never gets into
    the game, and the relay then mixes their match packets (A4)."""
    if "seat" in got:
        return "seat", int(got["seat"]), bool(got.get("projector"))
    err = got.get("error")
    detail = got.get("detail") or err or "?"
    if err == "no broker":
        s = seat_no or 1
        return "no_broker", s, (s == 1)
    if err == "signin":
        raise SignInRefused(detail)
    raise Failed({
        "full": "the server at %s is full: 8 cabinets play there now" % ip,
        "taken": "seat %s is taken on the server at %s - leave the seat number out to get the next free one"
                 % (seat_no, ip),
        "no answer": "the server's seat desk at %s did not answer in time (%s) - not started, so this PC cannot land "
                     "on a seat another player is already holding. Try again, or PLAY.exe local." % (ip, detail),
    }.get(err, "the server's seat desk at %s would not give a seat (%s)" % (ip, detail)))


def projector_port(projector, relay, show):
    """Pure: the server port this PC's projector connects to, 0 = no projector (2026-10-17).  projector: the desk
    said this PC is THE projector (kit 5's desk, or no desk at all) - straight to control; relay: the desk's
    projector relay port - used when SETTINGS' SHOW PROJECTOR is on (show)"""
    if projector:
        return CONTROL_PORT
    return relay if relay and show else 0


def match_slot(hook_log):
    """Pure: the match-engine slot a game made (2026-10-17), from its hook log (data\\logs\\hook\\mxhook_<pid>.log):
    N of its 'CreateFileMappingA "MemmapComm memmap wccf_match_connectN"' line; None while it has none.  Each game
    makes the first free wccf_match_connectN; a match engine it starts takes the lowest slot no engine holds"""
    m = re.search(r'CreateFileMappingA\s+"MemmapComm memmap wccf_match_connect(\d+)"', hook_log)
    return int(m.group(1)) if m else None


def take_seat(ip, seat_no, env, roles):
    """remote mode (2026-10-06): this PC's seat on the server at ip, from the server's seat desk (server\\seat_desk.py,
    TCP 20030) through online\\seat.py, which keeps holding it while the game runs; seat_no None = the next free seat.
    Returns (seat, projector?, the projector relay's port or 0).  See _seat_decision for what each answer means."""
    out = os.path.join(K.DATA, "seat_lease.json")
    if os.path.exists(out):
        os.remove(out)
    p = start(os.path.join("online", "seat.py"), [ip, out, LIFE] + ([] if seat_no is None else [seat_no]), "run_seat_lease.txt", env)
    roles[p.pid] = "seat lease"                       # tracked AT ONCE, so a stop always cleans it up - even a lease
                                                      # that is slow to answer never keeps a seat untracked (A4)
    end = time.time() + 25                            # longer than the lease's worst case (6 s connect + 10 s answer)
    while time.time() < end and not os.path.exists(out) and p.poll() is None:
        time.sleep(0.2)
    try:
        with open(out, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {"error": "no answer", "detail": "the seat lease wrote nothing in time"}
    kind, seat_no, projector = _seat_decision(got, seat_no, ip)      # may raise Failed (the lease has exited by then)
    if kind == "no_broker":
        del roles[p.pid]                             # the lease exited after writing "no broker" - nothing to clean up
        say("  (the server at %s has no seat desk - seat %d%s, as before)" %
            (ip, seat_no, " with the projector" if projector else ""))
    return seat_no, projector, int(got.get("relay") or 0)


def start_cabinet(debug, env, mode, ip, seat_no, seat, roles):
    """steps 4-6 of a start, then the key driver: seat N's own side - the keychip / network, card reader and I/O board
    stand-ins, the cabinet (the seat1 folder) with its overlay - each new process into roles.  A cabinet restart
    (2026-10-07) runs only this: the projector, the scene service, the seat lease and the panel helper keep running."""
    p = start(os.path.join("hardware", "network.py"), [LIFE, "ringedge_log.txt"], "run_ringedge.txt", env)
    roles[p.pid] = "keychip / network stand-in"
    card = env.get("WCCF_CLUB_CARD") or CARD   # online and signed in: the account's own club (online\club.py)
    # NAME.new.bin beside it (wallet.NEW for the slot): room for a second card, for a manager transfer (2026-10-08)
    p = start(os.path.join("hardware", "card_reader.py"), [ICC_PIPE, LIFE, "icc_log.txt" if debug else "NUL", card,
                                                           os.path.splitext(card)[0] + ".new.bin"],
              "run_cardreader.txt", env, quiet=not debug)
    roles[p.pid] = "card reader stand-in"
    p = start(os.path.join("hardware", "io_board.py"), [JVS_PIPE, LIFE, "jvs_log.txt", KEYS_INPUT], "run_ioboard.txt", env)
    roles[p.pid] = "I/O board stand-in"
    wait_for("the cabinet's stand-ins", lambda: {40100, 40102, 40106} <= K.listening_ports() and
             {"wccf_icc_seat1", "wccf_jvs_seat1"} <= K.pipes(), 20)
    say("  4/6 cabinet stand-ins: keychip/network, card reader (card file %s), I/O board" % K.shown(card))

    senv = dict(env, MXHOOK_RINGEDGE="1",
                MXHOOK_COM="COM3=%s;COM1=%s;mxjvs=%s;COM4=%s" % (ICC_PIPE, ICC_PIPE, JVS_PIPE, JVS_PIPE))
    if mode == "remote":    # a match against another player goes through the server's relay (wccfpanel.dll, 2026-10-06)
        senv.update(WCCF_RELAY="%s:%d" % (ip, RELAY_PORT), WCCF_SEAT=str(seat_no))
    if debug:
        senv["MXHOOK_VERBOSE"] = "1"
    senv["WCCF_PANEL"] = PANEL_DLL
    # the English pictures the hook gives the game as it loads Sega's (english.py's "memory" pictures, made by SETUP's
    # ENGLISH / ITALIANO): named only while there are some - in Japanese the hook changes no picture
    pics = K.ENGLISH_PICTURES
    if os.path.isdir(pics) and any(n.lower().endswith(".dds") for n in os.listdir(pics)):
        senv["WCCF_PICTURES_DIR"] = pics
    # the cabinet in the seat1 folder SETUP made, whatever its seat number: the number is only its command line
    p = start(os.path.join("hardware", "debugger.py"), [LIFE, "client", "follow", "arg=%d" % seat_no, "dir=" + seat], "run_seat1.txt", senv)
    roles[p.pid] = "seat 1 launcher" if seat_no == 1 else "seat %d launcher" % seat_no
    found = {}

    def seat_pid():
        try:
            m = re.search(r"launched client_Release\.exe pid (\d+)", open(os.path.join(K.LOGS, "run_seat1.txt")).read())
        except OSError:
            return False
        if m:
            found["pid"] = int(m.group(1))
        return bool(m)
    wait_for("seat %d" % seat_no, seat_pid, 30, p, "run_seat1.txt")
    wait_for("seat %d's window" % seat_no, lambda: K.windows_of(found["pid"]), 120, p, "run_seat1.txt")
    say("  5/6 seat %d (the player cabinet) - window up" % seat_no)
    olog = os.path.join(seat, "wccfpanel.log")
    skip = len(open(olog, encoding="utf-8", errors="replace").read()) if os.path.exists(olog) else 0

    def overlay_up():
        try:
            return "maximized" in open(olog, encoding="utf-8", errors="replace").read()[skip:]
        except OSError:
            return False
    # the game itself loads the overlay: its hook (wccfk.dll) loads WCCF_PANEL 3 s after this window is up.  The
    # game runs without it if it does not come - never a reason to take the game away (2026-10-06)
    try:
        wait_for("the overlay", overlay_up, 60)
        say("  6/6 overlay in seat %d's window" % seat_no)
    except Failed:
        say("  6/6 the overlay did not report its window (seat1\\wccfpanel.log; data\\logs\\hook says if it loaded) - "
            "the game runs; the keyboard works as usual")
    if debug:                               # its own window, minimized, as before
        k = start(os.path.join("hardware", "keyboard.py"), [], None, env, show=SW_SHOWMINNOACTIVE)
    else:
        k = start(os.path.join("hardware", "keyboard.py"), [], "run_keys.txt", env)
    roles[k.pid] = "key driver"
    return found["pid"]


def launch_projector(env, roles):
    """the projector (seat 0) under its launcher, the overlay too in its money-only mode (below in play)"""
    p = start(os.path.join("hardware", "debugger.py"), [LIFE, "client", "follow", "arg=0"], "run_projector.txt",
              dict(env, WCCF_PANEL=PANEL_DLL))
    roles[p.pid] = "projector launcher"
    return p.pid


def play(debug, mode="local", ip=None, seat_no=None, dream=False):
    """mode "local": everything on this PC; "server": the server side only; "remote": the cabinets only, on the
    server at ip - seat_no None: the next free seat from the server's seat desk (2026-10-06), and the projector if this
    PC is the first; 1-8: that seat (the game reads it from the cabinet's settings, SATELLITE_NO -
    docs\\NETWORK-MAP-2010-11.md section 6; the projector is seat 0 and a server has one).  dream (remote only): DREAM
    TEAM - the slot card and the whole catalogue, no sign-in (see the top of this file)"""
    dream = bool(dream) and mode == "remote"
    projector = show = True
    game, seat = setup_state()
    if not game:
        return 2
    running = K.game_processes(game) + kit_pythons()
    known = running_roles()
    busy = not_server_side(running, known) if mode == "remote" else running
    if busy:
        say("Already running (%s) - close the game's window first (a game that is stuck: PLAY.exe stop)." %
            ", ".join(sorted({p[2] for p in busy})))
        return 3
    apply_account_request()                  # SETTINGS' SIGN OUT: before the sign-in below asks
    online = None
    if dream:                                # DREAM TEAM (2026-10-15): no sign-in, no account club - the slot card
        say("DREAM TEAM: your own club card and any card. No wccf.online cards are earned, and in friendlies the "
            "server pairs you only with other DREAM TEAM players (league and cup rounds can still mix).")
    elif mode == "remote":                   # the wccf.online sign-in and the account's own club, before anything
        from online import account, club     # starts (2026-10-14): the token goes to the server's seat desk with the
        online, why = online_club(account.ensure, club.prepare)       # seat request (online\seat.py)
        if not online:                       # never online with the slot card; never locked out either
            if running:                      # a server runs on this PC: the game cannot play beside it here
                say("Online play needs a wccf.online sign-in and your online club (%s). A server runs on this PC, so "
                    "the game cannot play here instead - PLAY.exe stop ends it." % why)
                return 3
            say("Online play needs a wccf.online sign-in and your online club (%s) - playing on this PC instead, with "
                "your own club cards. The next online start tries again." % why)
            return play(debug)
    beside_server = bool(running)            # only "remote" gets here with something running: a server on this PC
    if beside_server:
        os.makedirs(os.path.join(K.LOGS, "hook"), exist_ok=True)     # its logs are open: no rotation
        if read_panel().get("english", "").lower() in K.TEXT_LANGUAGE:
            say("  (the SETTINGS panel's language change waits: the server on this PC uses the same game files)")
    else:
        if not ensure_hook(game, seat):
            return 2
        rotate_logs()
        apply_english_request()
    apply_card_request()                       # the card reader is not running yet, in every mode that gets here
    apply_card_fix()
    if mode != "server":
        apply_board(seat, online)              # ... nor FPR_Emu or the overlay: the club's cards on the table
    env = kit_env(game, online, dream)
    roles = {p[0]: known[p[0]] for p in running if p[0] in known}
    steps = 2 if mode == "server" else 6
    confs = (os.path.join(game, "local", "client_user_option.conf"),
             os.path.join(seat, "local", "client_user_option.conf"))

    def games(name):
        return [p for p in K.game_processes(game) if p[2].lower() == name]

    life = SERVER_LIFE if mode == "server" else LIFE    # a server runs for weeks; a player's game up to 12 hours
    say("Starting WCCF 2010-11 from %s%s" % (game, {"server": " - the server side only",
                                                   "remote": " - the cabinets, on the server at %s" % ip}.get(mode, "")))
    if "scene service" in roles.values():
        say("  1/%d scene service (the server's, already running on this PC)" % steps)
    else:
        p = start(os.path.join("hardware", "scenes.py"), [life + 120, "xscn_watch_log.txt"], "run_scenes.txt", env)
        roles[p.pid] = "scene service"
        time.sleep(2)
        if p.poll() is not None:
            raise Failed("the scene service did not start - see data\\logs\\run_scenes.txt")
        say("  1/%d scene service" % steps)

    if mode == "remote":
        if not server_answers(ip):
            raise Failed("the server at %s does not answer on port %d - is it running there (PLAY.exe server), "
                         "and is that port open to this PC? (PLAY.exe local plays on this PC instead)" %
                         (ip, CONTROL_PORT))
        send_pending_report(env)               # a server answers: the last report it could not take goes now
        seat_no, projector, relay = take_seat(ip, seat_no, env, roles)
        show = read_panel().get("projector", "").lower() != "off"
        port = projector_port(projector, relay, show)
        projector = bool(port)
        for conf in confs:
            set_control_ip(conf, ip)
        # the projector's own settings (the game folder's): control, or the server's projector relay (2026-10-17);
        # the cabinet's keep 20002
        set_conf_value(confs[0], "CONTROL_PORT", port or CONTROL_PORT)
        set_satellite_no(confs[1], seat_no)          # the cabinet's seat (1, or 2-8 for another player's PC)
        # never "WAITING FOR THE PROJECTOR" on a server: its projector is on another PC, or gone (2026-10-06)
        set_conf_value(confs[1], "WAIT_PROJECTOR", 0)
        say("  2/%d server: %s answers on port %d - this PC is seat %d%s" % (
            steps, ip, CONTROL_PORT, seat_no, "" if not projector else " and shows the projector" if port == CONTROL_PORT
            else " and shows the projector through the server's relay (port %d)" % port))
    else:
        seat_no = 1                                  # everything on this PC: seat 1 and the projector
        ctrl_conf = os.path.join(game, "local", "ctrl_user_option.conf")
        if mode == "local":
            for conf in confs:              # after a "remote" run: the cabinets play on this PC again
                set_control_ip(conf, "127.0.0.1")
            set_conf_value(confs[0], "CONTROL_PORT", CONTROL_PORT)  # after an online run through the projector relay
            set_satellite_no(confs[1], 1)            # after a "remote ... seat N" run: seat 1 again
            # no waiting for the projector here either (2026-10-17): it starts first and joins at once, and one
            # closed by the player never holds the next round up (with 1 control starts none without a projector)
            set_conf_value(confs[1], "WAIT_PROJECTOR", 0)
            set_conf_value(ctrl_conf, "WAIT_PROJECTOR", 0)
        else:
            # a server for others: no projector waited for (2026-10-11, the owner: players on the server get only
            # their own game - the seat desk gives no PC the projector).  With 1 control never starts a round until a
            # projector connects (docs\NETWORK-MAP-2010-11.md section 8).  A projector box that joins later shows
            # "Now Synchronizing" until the next round (2026-10-06).
            set_conf_value(ctrl_conf, "WAIT_PROJECTOR", 0)
        p = start(os.path.join("hardware", "debugger.py"), [life + 60, "control", "follow"] + ([] if debug else ["hide"]), "run_server.txt",
                  dict(env, WCCF_WITNESS_DIR=WITNESS) if mode == "server" and witness_ready() else env)
        roles[p.pid] = "server launcher"
        wait_for("the server", lambda: CONTROL_PORT in K.listening_ports() and len(games("match_release.exe")) >= 4,
                 90, p, "run_server.txt")
        ctl = games("control_release.exe")
        if ctl:     # a click in the server's console window would freeze it (text-selection mode): switch that off
            subprocess.run([PY, os.path.join(K.SCRIPTS, "helpers", "console.py"), str(ctl[0][0])], capture_output=True,
                           timeout=15)
            if not debug:       # it starts hidden; a window it shows by itself later is hidden here
                K.hide_windows(ctl[0][0])
        say("  2/%d server: listening on port %d, %d match engines" % (steps, CONTROL_PORT,
                                                                       len(games("match_release.exe"))))
    if mode == "server":
        # the seat desk (2026-10-06): every player's PC that joins gets the next free seat (no projector: 2026-10-11)
        b = start(os.path.join("server", "seat_desk.py"), [life + 60, os.path.join(K.LOGS, "seat_broker.txt")], "run_seat_broker.txt", env)
        time.sleep(1.5)
        if b.poll() is None:
            roles[b.pid] = "seat desk"
            say("     seat desk: TCP 20030 - each player's PC gets the next free seat (its cabinet only, no projector)")
        else:
            say("     the seat desk did not start (data\\logs\\run_seat_broker.txt) - players then give their seat")
        # the match relay (2026-10-06): a match between two players goes through here - home routers block the direct way
        m = start(os.path.join("server", "relay.py"), [life + 60, os.path.join(K.LOGS, "match_relay.txt")], "run_match_relay.txt", env)
        time.sleep(1.0)
        if m.poll() is None:
            roles[m.pid] = "match relay"
            say("     match relay: UDP %d - a match between two players goes through this machine" % RELAY_PORT)
        else:
            say("     the match relay did not start (data\\logs\\run_match_relay.txt) - two players then play the CPU")
        # the projector relay (2026-10-17): control's one projector connection, passed on to every player's projector
        pr = start(os.path.join("server", "projector_relay.py"), [life + 60, os.path.join(K.LOGS, "projector_relay.txt")],
                   "run_projector_relay.txt", env)
        time.sleep(1.0)
        if pr.poll() is None:
            roles[pr.pid] = "projector relay"
            say("     projector relay: TCP %d - each player's PC can show the projector through this machine" %
                PROJECTOR_PORT)
        else:
            say("     the projector relay did not start (data\\logs\\run_projector_relay.txt) - players then see no "
                "projector")
        # the log inbox (2026-10-09): the logs players send with SEND LOGS (SETTINGS) are kept in data\player_logs
        li = start(os.path.join("server", "log_inbox.py"), [life + 60, os.path.join(K.LOGS, "log_inbox.txt")], "run_log_inbox.txt", env)
        time.sleep(1.0)
        if li.poll() is None:
            roles[li.pid] = "log inbox"
            say("     log inbox: TCP 20050 - logs players send from SETTINGS go to data\\player_logs")
        else:
            say("     the log inbox did not start (data\\logs\\run_log_inbox.txt) - SEND LOGS will not reach here")
        if witness_ready():     # a card per finished match (2026-10-14): only a server wccf.online knows
            wt = start(os.path.join("server", "witness.py"), [life + 60, os.path.join(K.LOGS, "witness.txt")],
                       "run_witness.txt", env)
            time.sleep(1.0)
            if wt.poll() is None:
                roles[wt.pid] = "witness"
                say("     witness: each finished match earns its signed-in player a card on wccf.online "
                    "(data\\logs\\witness.txt)")
            else:
                say("     the witness did not start (data\\logs\\run_witness.txt) - finished matches earn no cards")
        write_running(roles, mode, None)
        say("")
        say("Server running. On each player's PC: PLAY.exe remote, then this machine's address - the one their PC")
        say("can reach. This machine must let in TCP ports %d, 20030, 20050 and %d, and UDP %d. PLAY.exe stop ends it." %
            (CONTROL_PORT, PROJECTOR_PORT, RELAY_PORT))
        return 0

    def start_projector(step):
        launch_projector(env, roles)
        say("  %s projector (seat 0) - its window opens in a few seconds" % step)

    # online the projector starts after the cabinet (2026-10-17, match_slot): started first it made slot 0, ran no
    # engine to hold it, and the cabinet's version check took it - stuck at CHECKING M VERSION.  Local keeps the old
    # order: control's 4 engines hold slots 0-3 for good and the projector's own version check runs before the cabinet
    later = projector and mode == "remote"
    if not projector:
        say("  3/6 projector: none on this PC - online, each PC runs only its own cabinet")
    elif later:
        say("  3/6 projector: starts once seat %d has its match slot" % seat_no)
    else:
        start_projector("3/6")

    pid = start_cabinet(debug, env, mode, ip, seat_no, seat, roles)
    if later:
        hook = os.path.join("hook", "mxhook_%d.log" % pid)
        try:
            wait_for("seat %d's match slot" % seat_no, lambda: match_slot(read_log(hook)) is not None, 60)
        except Failed:
            say("     seat %d's match slot not in data\\logs\\%s after 60 s - the projector starts anyway" % (seat_no, hook))
        start_projector("   ")
    # the projector gets the overlay too (2026-10-06), in its money-only mode: its amounts with commas
    # (wccfpanel.c is_projector - no panels, nothing else); its hook (wccfk.dll) loads it (WCCF_PANEL above), and it plays on
    # as before if it does not load (data\logs\wccfpanel_projector.log)

    h = start(os.path.join("helpers", "panel.py"), [LIFE], "run_helper.txt", env)      # the panels' RESTART NOW (from outside the game)
    roles[h.pid] = "panel helper"
    write_running(roles, mode, ip, seat_no, online, dream, {"projector": bool(projector), "show_projector": show})
    say("")
    if mode == "remote":
        say("Playing %son the server at %s%s." % ("DREAM TEAM " if dream else "", ip,
                                                 "" if projector else " as seat %d (no projector on this PC)" % seat_no))
    say("Running. Click the cabinet's window, then play with the keyboard (it works only while a game window is in "
        "front):")
    say("  Enter START (free play - no coin needed)   X decide   C shoot   arrows: tactics")
    say("  I club card in / out   F1 test menu   F11 window size   - or click the buttons around the picture")
    say("First time: put the card in with I, and the game makes your club. It is saved in %s." %
        K.shown(online["card"] if online else CARD))
    say("To finish: let the card come out after a match, then close the cabinet's window - the rest stops with it "
        "(the projector's window can be closed any time; nothing else stops). %s" % (
        "(The key driver's window is minimized.)" if debug else
        "(The key driver runs in the background: its log is data\\logs\\run_keys.txt.)"))
    return 0


def run_started():
    """when this run's card sessions count from: data\\running.json's run_start (its cabinet's start; a projector's
    restart keeps it), or for an older one its write time; None if none"""
    t = running_info().get("run_start")
    if isinstance(t, (int, float)):
        return t
    try:
        return os.path.getmtime(RUNNING)
    except OSError:
        return None


SESSION_WORDS = {"open": "OPEN", "cut": "the last one did not end normally", "closed": "closed", "new": "new card",
                 "none": "no card file", "unreadable": "card file unreadable"}


def console_in():
    """True only for a real console keyboard - not a pipe, a file or NUL (which Windows also calls a terminal, so
    isatty() alone asked the question to a tool on 2026-10-06; harmless - it read "no" - but not exact)"""
    try:
        import ctypes
        import msvcrt
        mode = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(msvcrt.get_osfhandle(sys.stdin.fileno())),
                                                          ctypes.byref(mode)))
    except Exception:
        return False


def ask_yes(question):
    """True only if someone at the stop's window types Y - never a dead end for a person, and never a wait when
    nobody can answer (no console: a tool, a test) - then it is a plain no"""
    try:
        if not sys.stdin or not console_in():
            return False
        return input(question).strip().lower() in ("y", "yes")
    except (EOFError, OSError, KeyboardInterrupt, RuntimeError):
        return False


def club_session():
    """(session state, bad endings) of the club in play: the slot card - or the online club's, while one plays
    (online\\club.py) - or during a manager transfer the new card beside it (2026-10-08): an open session on either
    one is open"""
    online = online_of(running_info())
    card = online["card"] if online else CARD
    since = run_started()
    sess, bad = K.card_session(card, since)
    new_sess, new_bad = K.card_session(os.path.splitext(card)[0] + ".new.bin", since)
    if new_sess == "open" or (new_sess == "cut" and sess != "open"):
        return new_sess, new_bad
    return sess, bad


def stop_guard(force, check, game, seat):
    """The card rule (below), for a stop and for a cabinet restart (2026-10-07): (3, ...) refused - said why - or
    (0, card in?, session state) to go on"""
    seat_up = any(os.path.normcase(os.path.dirname(p[3])) == os.path.normcase(seat)
                  for p in K.game_processes(game) if p[2].lower() == "client_release.exe")
    c = card_in()
    sess, bad = club_session()
    if seat_up and not force and (c is not False or sess == "open"):
        if sess == "open":
            say("A card session is open: a match or Club Make is on, and the game saves your card in the locker room "
                "after the match. Stopping now ends this match without that save, and the card gets a bad ending "
                "(trade rights are lost at 2). If the game is stuck (\"WCCF CONTROL NOT FOUND\"), that match is lost "
                "already and stopping is the way out.")
        else:
            say("%s - the game may be saving it. If you can, press I in the game to take the card out first." % (
                "Your club card is IN the reader" if c else "Cannot tell whether your club card is in"))
        # never a dead end: the person at the STOP window decides, knowing the cost (the player, 2026-10-06: "never put
        # the player in a situation they cant ..."); with nobody to ask it stays running, as before
        if check or not ask_yes("Stop anyway? Type Y and press Enter to stop now - just Enter leaves the game "
                                "running: "):
            say("NOT stopped - the game is still running.%s" % ("" if check else
                " (\"play.py stop force\" stops without asking.)"))
            return 3, c, sess
        say("Stopping, as asked.")
    return 0, c, sess


def stop(force, check=False, keep_server=False):
    """check=True: say what stop would do, and stop nothing (a refusal test must never be a real stop: 2026-10-05
    a stop run as a 'test' closed a game someone was playing - the card had come out since it was last read).
    Refused while the card is in the reader, or while the game has a card session open: it marks one open on the
    card at START and closed at the locker-room save - the card sensor alone reads "out" through a whole match
    (seen 2026-10-06), so the mark is what counts.
    keep_server=True (ended(), 2026-10-08): a server started on this PC with "server" keeps running, and
    data\\running.json keeps its part."""
    game, seat = setup_state()
    if not game:
        return 2
    rc, c, sess = stop_guard(force, check, game, seat)
    if rc:
        return rc
    roles = running_roles() if keep_server else None

    def mine(procs):
        return procs if roles is None else not_server_side(procs, roles)
    ours = mine(kit_pythons())
    if check:
        g = mine(K.game_processes(game))
        say("check only - nothing stopped: stop would end %d kit processes and %d game processes (club card: %s, "
            "session: %s)" % (len(ours), len(g), {True: "in", False: "out", None: "unknown"}[c], SESSION_WORDS[sess])
            if ours or g else "Nothing running.")
        return 0
    for p in ours:               # the launchers first: each takes its game down with it
        K.kill(p[0])
    time.sleep(1.5)
    left = mine(K.game_processes(game))
    for p in left:
        K.kill(p[0])
    time.sleep(1.0)
    still = mine(K.game_processes(game) + kit_pythons())
    if roles is not None:
        write_running({pid: r for pid, r in roles.items() if r in SERVER_ROLES}, "server", None)
    elif os.path.exists(RUNNING):
        os.remove(RUNNING)
    if still:
        say("Still running: %s" % ", ".join("%s %d" % (p[2], p[0]) for p in still))
        return 1
    say("Stopped (%d kit processes, %d game processes)." % (len(ours), len(left)))
    try:                         # the cards on the table kept with their club (formation.py): data\save holds the latest
        from cards import formation
        formation.keep(seat)
    except Exception as ex:
        say("  (the cards on the table were not copied to their club: %s)" % ex)
    return 0


WINDOW_CLOSED = "its window was closed"   # debugger.py's line when it ends a game because its window was closed
CLEAN_EXIT = "process exited, exit code 0x00000000"  # debugger.py's line when a game quit by itself, cleanly: the
                                                     # projector does at a close of its window, before the line above


def closed(text):
    """a launcher's log says its game was closed: the window closed, or the game quit cleanly (2026-10-17)"""
    return WINDOW_CLOSED in text or CLEAN_EXIT in text


def window_launchers(roles):
    """{pid: its log} of the run's game-window launchers (start_cabinet: every seat writes run_seat1.txt)"""
    return {pid: "run_projector.txt" if r == "projector launcher" else "run_seat1.txt" for pid, r in roles.items()
            if r == "projector launcher" or re.fullmatch(r"seat \d+ launcher", r)}


def projector_only(launchers, alive):
    """True when what ended is the run's projector and a cabinet still runs (2026-10-17): the projector's window is
    never a reason to stop - nothing else stops, and it is no crash to report.  Closing the cabinet's own window still
    ends this PC's run, the projector with it"""
    gone = [pid for pid in launchers if pid not in alive]
    return bool(gone) and all(launchers[pid] == "run_projector.txt" for pid in gone) and \
        any(pid in alive for pid in launchers)


def gone_logs(launchers, alive):
    """the logs of the run's game-window launchers that have ended (alive: the kit's Pythons that still run)"""
    return sorted({log for pid, log in launchers.items() if pid not in alive})


def crashed_logs(launchers, alive, read_log):
    """the logs of the launchers that ended WITHOUT their window being closed (a crash), when another game window of
    the run still runs - then nothing may stop (the player, 2026-10-07: "no one cabinet can restart or stop the
    projector"); None when a window was closed, or when no game window is left to keep running.  An empty list: none
    has ended (a hand-run "ended") - nothing stops then either"""
    gone = gone_logs(launchers, alive)
    if any(closed(read_log(log)) for log in gone) or not any(pid in alive for pid in launchers):
        return None
    return gone


def read_log(name):
    try:
        with open(os.path.join(K.LOGS, name), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""                # unreadable counts as no close: the safe side keeps the rest running


REPORT_PENDING = os.path.join(K.DATA, "report.pending")      # a report the server did not take: the next start sends it
CRASH_SIGNS = ("SECOND-chance / FATAL", "STOP: invalid parameter")       # debugger.py's words at a crash


def went_wrong(launcher_logs, read=read_log):
    """Pure (reads through read): why this run went wrong, [] if it did not - a game window that went without being
    closed, a crash the launcher recorded (debugger.py: the report and the memory snapshot), the server link lost
    (wccfpanel.dll's server_link.txt)"""
    why = ["%s: the game window went by itself, not closed" % n for n in launcher_logs if not closed(read(n))]
    why += ["%s: a crash recorded (%s)" % (n, s) for n in sorted(set(launcher_logs) | {"run_server.txt"})
            for s in CRASH_SIGNS if s in read(n)]
    why += ["server_link.txt: %s" % ln.strip() for ln in read("server_link.txt").splitlines() if " LOST " in ln]
    return why


def report_bad_run(server, why, game=None):
    """online, after a run that went wrong: this PC's logs go to the server's log inbox by themselves (the owner,
    2026-10-11: "put something in the server and the game ... like logs so we find out if any issue happened, and
    what the cause is") - what SEND LOGS sends, never the club card, names on this PC replaced, plus the crash
    snapshots and why.  The server out of reach (often the very trouble): data\\report.pending, sent by the next start.
    data\\panel.txt auto_logs=0 turns it off.  Never raises: the end of a run must go on."""
    if not server or not why or read_panel().get("auto_logs") == "0":
        return
    note = "sent by itself at the end of an online run that went wrong:\n" + "\n".join(why) + "\n"
    try:
        from online import send_logs
        blob, _n = send_logs.pack(game=game, note=note)
        ok, what = send_logs.send(server, blob, send_logs.version())
    except Exception as ex:                          # noqa: BLE001 - a report must never break the end of a run
        ok, what = False, repr(ex)
    if ok:
        say("This run went wrong (%s) - its logs went to the server at %s by themselves: code %s." % (why[0], server, what))
        return
    try:
        with open(REPORT_PENDING, "w", encoding="utf-8") as f:
            f.write(server + "\n" + note)
    except OSError:
        pass
    say("This run went wrong (%s) - its logs could not reach the server (%s); the next start sends them." % (why[0], what))


def send_pending_report(env):
    """a report a run could not send (report_bad_run): tried again in the background while the start goes on;
    send_logs.py removes data\\report.pending only once the server took it, so a failed try leaves it for the next"""
    try:
        with open(REPORT_PENDING, encoding="utf-8") as f:
            server = f.readline().strip()
    except OSError:
        return
    if server:
        start(os.path.join("online", "send_logs.py"), [server, "--report", REPORT_PENDING], "run_report.txt", env)


def ended():
    """a game window closed (2026-10-08; there is no STOP now): PLAY.exe's watcher saw one of the run's cabinet and
    projector launchers end - debugger.py ends the game, and itself, when the game's window is closed - and asks
    for the rest to stop: the server, its match engines, the stand-ins, the key driver, the panel helper.  Before, they
    ran on hidden for up to 12 hours.  The projector's window alone stops nothing (2026-10-17, projector_only): exit 3,
    and the watcher goes on watching the cabinet.  A cabinet that played on a server started on
    this PC with "server" leaves that server running for the other players.  A game that went by itself (a crash, no
    close in its log) stops nothing while another game window runs - the projector keeps running (exit 3 too)."""
    game, _seat = setup_state()
    if not game:
        return 2
    info = running_info()
    launchers, alive = window_launchers(running_roles()), set(live_roles(info))
    if projector_only(launchers, alive):
        say("The projector's window has gone: the game plays on without it (closing the cabinet's window ends the run).")
        return 3
    crashed = crashed_logs(launchers, alive, read_log)
    if crashed is not None:
        say("A game window went by itself, not closed (a crash - see data\\logs\\%s): the rest keeps running, the "
            "projector too." % ", ".join(crashed) if crashed else "No game window has ended - nothing stopped.")
        return 3
    server_here = running_info().get("mode") == "remote" and any(
        p[2].lower() == "control_release.exe" for p in K.game_processes(game))
    say("%s - stopping the rest%s." % ("A game window was closed" if any(pid in alive for pid in launchers) else
                                       "No game window is left", " (the server on this PC keeps running)"
                                       if server_here else ""))
    why = went_wrong(gone_logs(launchers, alive))   # not a game the stop is about to end
    r = stop(False, keep_server=server_here)
    if info.get("mode") == "remote":                 # online: the server's people get this PC's side of it
        report_bad_run(info.get("server"), why, game)
    return r


def cabinet_restart_fits():
    """RESTART NOW needs only the cabinet (2026-10-07) when a run with a cabinet is on (data\\running.json), a plain
    start would play the same way - THIS PC, or ONLINE on the same server - and no English switch is asked: the
    projector would come back exactly as it is, so it is kept"""
    info = running_info()
    roles = info.get("processes")
    if info.get("mode") not in ("local", "remote") or not isinstance(roles, dict) or \
            not any(is_cabinet_role(r) for r in roles.values()):
        return False
    panel = read_panel()
    want = panel.get("english", "").lower()
    if want in K.TEXT_LANGUAGE and K.TEXT_LANGUAGE[want] != K.game_language():
        return False
    if panel.get("account", "").lower() == "signout":    # SIGN OUT: the seat lease holds the old sign-in - a full start
        return False
    online = panel.get("play_on", "").lower() == "online"
    if info["mode"] == "remote":               # DREAM TEAM <-> ONLINE: the seat lease and the club change - a full start
        show = panel.get("projector", "").lower() != "off"      # SHOW PROJECTOR changed: a full start (2026-10-17)
        return online and panel.get("server", "") == info.get("server") and \
            (panel.get("online_mode", "").lower() == "dream") == bool(info.get("dream")) and \
            show == info.get("show_projector", show)
    return not online


def restart_cabinet():
    """RESTART NOW for the cabinet only (2026-10-07; the player: "no one cabinet can restart or stop the projector,
    that has to keep running"): seat N's side is stopped by the card rule, the CLUB CARD panel's switch is done, and
    that side starts again.  The projector, the scene service, the seat lease and the panel helper are never touched,
    so the projector stays in step with the server (one that rejoins mid-round waits up to a whole round)."""
    game, seat = setup_state()
    if not game:
        return 2
    rc, _c, _sess = stop_guard(False, False, game, seat)
    if rc:
        return rc
    info = running_info()
    roles = {int(k): v for k, v in (info.get("processes") or {}).items()}
    mode, ip, online, dream = info.get("mode"), info.get("server"), online_of(info), bool(info.get("dream"))
    keep = carried(info)                     # a new run_start: a session the old cabinet had open was cut
    try:
        seat_no = int(info.get("seat", 1))
    except (TypeError, ValueError):
        seat_no = 1
    say("Restarting seat %d's cabinet only - the projector keeps running." % seat_no)
    alive = live_roles(info)
    doomed = [pid for pid, role in roles.items() if is_cabinet_role(role) and pid in alive]
    seat_dir = os.path.normcase(seat)
    clients = {p[0] for p in K.game_processes(game)
               if p[2].lower() == "client_release.exe" and os.path.normcase(os.path.dirname(p[3])) == seat_dir}
    for pid in doomed:                       # the seat launcher takes its cabinet (and its match engines) down with it
        K.kill(pid)
    time.sleep(1.5)

    def seat_side():                         # what is left of the cabinet: its folder's programs and their children
        g = K.game_processes(game)
        mine = {p[0] for p in g if os.path.normcase(os.path.dirname(p[3])) == seat_dir} | clients
        return [p for p in g if p[0] in mine or p[1] in mine]
    for p in seat_side():
        K.kill(p[0])
    time.sleep(1.0)
    for pid in doomed:
        roles.pop(pid, None)
    left = seat_side() + [p for p in kit_pythons() if p[0] in doomed]
    if left:
        write_running(roles, mode, ip, seat_no, online, dream, keep)
        say("Still running: %s - the cabinet was not started again (PLAY.exe stop, then PLAY.exe)." % ", ".join(
            "%s %d" % (p[2], p[0]) for p in left))
        return 1
    apply_card_request()                     # the card reader is stopped: the CLUB CARD panel's switch goes in now
    apply_card_fix()                         # and its CLEAR BAD ENDINGS
    apply_board(seat, online)                # and the new club's cards onto the table, before FPR_Emu and the overlay
    time.sleep(1.0)                          # Windows frees the cabinet's ports and pipes
    start_cabinet(False, kit_env(game, online, dream), mode, ip, seat_no, seat, roles)
    write_running(roles, mode, ip, seat_no, online, dream, keep)
    say("")
    say("Seat %d's cabinet is back; the projector was not touched." % seat_no)
    return 0


def restart_projector(word=None, run_id=None):
    """the online projector, ended and started again (2026-10-17): what the panel helper runs when the projector's link
    to the server is gone for good (helpers\\panel.py ProjectorKeeper - Error 3000, the game never reconnects by itself).
    A fresh projector joins the server's relay again and shows the next phase.  The cabinet, the scene service, the
    seat lease and the panel helper are never touched; the log of the projector before goes to
    run_projector_lost.txt.  Exit 3: no online run with a projector on this PC, another run than run_id (the one the
    helper saw), or - not asked in SETTINGS - a projector the player has closed since: nothing done.  Exit 1: the old
    projector would not end - no second one is started.
    word (SETTINGS' OPEN / CLOSE PROJECTOR, the panel helper): "open" - the same, also for a projector the player
    closed; "close" - the projector ends as if the player closed its window (its log says so: no crash, no report,
    the run goes on); running.json's "projector" stays, so OPEN PROJECTOR can bring it back"""
    game, _seat = setup_state()
    if not game:
        return 2
    info = running_info()
    roles = {int(k): v for k, v in (info.get("processes") or {}).items()}
    old = [pid for pid, r in roles.items() if r == "projector launcher"]
    if info.get("mode") != "remote" or not (old or info.get("projector")):
        say("No online projector in this run (data\\running.json) - nothing done.")
        return 3
    if run_id and info.get("run") != run_id:
        say("The run the projector's restart was for has ended - nothing done.")
        return 3
    live = [pid for pid in old if pid in live_roles(info)]   # its pid may be another program's by now, even a Python's
    if word == "close" and not live:
        say("CLOSE PROJECTOR: no projector runs - nothing done.")
        return 0
    if word is None and (not live or closed(read_log("run_projector.txt"))):
        say("The projector was closed since its restart was planned - not started again.")
        return 3
    say("%s %s; the cabinet is not touched." % (time.strftime("%H:%M:%S"), {
        "open": "OPEN PROJECTOR (SETTINGS) - starting the projector", "close": "CLOSE PROJECTOR (SETTINGS) - closing the "
        "projector"}.get(word, "The projector has lost the server - starting it again")))
    mine = os.path.normcase(os.path.join(game, "client_Release.exe"))
    clients = {p[0] for p in K.game_processes(game) if os.path.normcase(p[3]) == mine}
    for pid in live:                         # its launcher, a debugger: the projector (and its match engines) end with it
        K.kill(pid)
    time.sleep(1.5)

    def left():                              # the projector and its children, its launcher
        return [p for p in K.game_processes(game) if p[0] in clients or p[1] in clients] + \
            [p for p in kit_pythons() if p[0] in live]
    for p in left():
        K.kill(p[0])
    time.sleep(1.0)
    still = left()
    if still:                                # never a second projector beside the first; its role stays
        say("Still running: %s - the projector was not %s (PLAY.exe stop ends the run)." % (", ".join(
            "%s %d" % (p[2], p[0]) for p in still), "closed" if word == "close" else "started again"))
        return 1
    for pid in old:
        roles.pop(pid)
    keep = dict(carried(info), run_start=run_started(), projector=True)   # the card session's start stays
    args = (info["mode"], info.get("server"), info.get("seat", 1), online_of(info), bool(info.get("dream")))
    if word == "close":                      # its log says closed (closed())
        try:
            with open(os.path.join(K.LOGS, "run_projector.txt"), "a", encoding="utf-8") as f:
                f.write("  %s %s - by CLOSE PROJECTOR (SETTINGS)\n" % (time.strftime("%H:%M:%S"), WINDOW_CLOSED))
        except OSError:
            pass
        write_running(roles, *args, keep)
        say("The projector is closed; OPEN PROJECTOR brings it back.")
        return 0
    try:
        os.replace(os.path.join(K.LOGS, "run_projector.txt"), os.path.join(K.LOGS, "run_projector_lost.txt"))
    except OSError:
        pass
    pid = launch_projector(kit_env(game, online_of(info), bool(info.get("dream"))), roles)
    write_running(roles, *args, keep)
    say("The projector is starting again (launcher %d)." % pid)
    return 0


def status():
    game, _seat = setup_state()
    if not game:
        return 2
    roles, info = {}, {}
    try:
        with open(RUNNING, encoding="utf-8") as f:
            info = json.load(f)
        roles = info.get("processes", {})
    except (OSError, ValueError, AttributeError):
        pass
    g, ours = K.game_processes(game), kit_pythons()
    if not g and not ours:
        say("Nothing running.")
        return 0
    if info.get("mode") == "remote":
        say("playing on the server at %s as seat %s" % (info.get("server"), info.get("seat", 1)))
    elif info.get("mode") == "server":
        say("this PC is the server (TCP port %d)" % CONTROL_PORT)
    for p in ours:
        say("  kit   %-28s pid %d" % (roles.get(str(p[0]), "python"), p[0]))
    for p in g:
        say("  game  %-28s pid %d  (%s)" % (p[2], p[0], os.path.basename(os.path.dirname(p[3]))))
    say("club card: %s" % {True: "IN the reader", False: "out", None: "unknown"}[card_in()])
    sess, bad = club_session()
    say("card session: %s%s" % (SESSION_WORDS[sess], "" if bad is None else ", bad endings %d" % bad))
    return 0


def show():
    """show the server's hidden windows again (its console and its settings window); 1 if no server runs here"""
    game, _seat = setup_state()
    if not game:
        return 2
    ctl = [p for p in K.game_processes(game) if p[2].lower() == "control_release.exe"]
    if not ctl:
        say("No server is running on this PC.")
        return 1
    for p in ctl:
        titles = K.show_windows(p[0])
        say("server pid %d: %s" % (p[0], "shown: " + ", ".join('"%s"' % t for t in titles) if titles else
                                   "no hidden window to show"))
    say("To look at, not to click. They are hidden again at the next start.")
    return 0


def play_online(debug, ip, seat_no=None, dream=False):
    """play on the server at ip; when its seat desk wants a wccf.online sign-in or refuses this PC's (SignInRefused),
    stop what was started and play on this PC instead, saying why - never a dead end (2026-10-14).  dream: DREAM TEAM"""
    try:
        return play(debug, "remote", ip, seat_no, dream)
    except SignInRefused as ex:
        detail = str(ex)
        if dream:                                    # DREAM TEAM asks without a sign-in: this server takes signed-in only
            say("The server at %s takes only signed-in players, so DREAM TEAM cannot play there: %s" % (ip, detail))
            say("Playing on this PC instead; ONLINE (not DREAM TEAM) in SETTINGS plays there with your wccf.online "
                "account.")
        else:
            if " again" in detail:                   # the website refused the saved sign-in: a fresh one next start
                from online import account
                account.forget()
            say("The server at %s did not let this PC in: %s" % (ip, detail))
            say("Playing on this PC instead; the next online start asks for a wccf.online sign-in.")
        say("Stopping what was started ...")
        stop(force=True)
        time.sleep(2)                                # Windows frees the ports and pipes
        return play(debug)


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    a = [x.lower() for x in argv]
    try:
        if a[:1] == ["stop"]:
            return stop("force" in a, check="check" in a)
        if a == ["ended"]:
            return ended()
        if a[:1] == ["status"]:
            return status()
        if a == ["show"]:
            return show()
        if a[:1] == ["projector"]:            # the panel helper: lost for good, or SETTINGS' OPEN / CLOSE PROJECTOR;
            words = [x for x in a[1:] if not x.startswith("run=")]       # run=ID: the run it saw
            if words in ([], ["open"], ["close"]):
                return restart_projector((words or [None])[0], next((x[4:] for x in a if x.startswith("run=")), None))
        if a[:1] == ["restart"]:              # RESTART NOW: stop by the card rule (asked during a session), then start
            if a == ["restart"] and cabinet_restart_fits():   # the projector would come back the same: it is kept
                return restart_cabinet()
            say("Restarting WCCF 2010-11, as the SETTINGS panel asked.")
            rc = stop(False)
            if rc != 0:
                return rc
            time.sleep(2)                     # Windows frees the ports and pipes
            return main([x for x in argv if x.lower() != "restart"])
        debug = "debug" in a
        rest = [x for x in a if x != "debug"]
        if not rest:                          # a plain start: what the SETTINGS panel chose
            panel = read_panel()
            if panel.get("play_on", "").lower() == "online":
                # never locked out: the panel that could change it lives inside the game, so a plain start that cannot
                # go online plays on this PC and says why (found 2026-10-06: ONLINE kept with the Paris server off)
                ip = panel.get("server", "")
                if not valid_ipv4(ip):
                    say("The SETTINGS panel says play online, but \"%s\" is not a server address - playing on this "
                        "PC. (In the game: SETTINGS, then type the address again.)" % ip)
                    return play(debug)
                if not server_answers(ip):
                    say("The SETTINGS panel says play online, but the server at %s does not answer - playing on this "
                        "PC instead. (The panel keeps ONLINE for next time; THIS PC there stops this try.)" % ip)
                    return play(debug)
                dream = panel.get("online_mode", "").lower() == "dream"
                say("%s, as the SETTINGS panel chose (PLAY.exe local plays on this PC)." % ("DREAM TEAM online" if dream
                                                                                          else "Online"))
                return play_online(debug, ip, dream=dream)     # the server's seat desk picks the seat
            return play(debug)
        if rest == ["local"]:
            return play(debug)
        if rest == ["server"]:
            return play(debug, "server")
        if rest[0] == "remote":
            words, seat_no = rest[1:], None
            dream = bool(words) and words[-1] == "dream"         # "remote ADDRESS dream": DREAM TEAM
            if dream:
                words = words[:-1]
            if len(words) >= 2 and words[-2] == "seat":          # a second player's PC: "remote ADDRESS seat 2"
                if not (words[-1].isdigit() and 1 <= int(words[-1]) <= 8):
                    say("Seats are 1 to 8, e.g. PLAY.exe remote 192.168.1.20 seat 2 - or leave the seat out and "
                        "the server gives the next free one.")
                    return 2
                seat_no, words = int(words[-1]), words[:-2]
            if len(words) > 1:
                print(__doc__)
                return 2
            s = K.load_settings()
            ip = words[0] if words else s.get("server")
            if not ip:
                say("Which server? PLAY.exe remote, then the server's address (four numbers with dots).")
                return 2
            if not valid_ipv4(ip):
                say("\"%s\" is not an address the game can use: it takes four numbers 0-255 with dots, no names." % ip)
                return 2
            if s.get("server") != ip:
                s["server"] = ip
                K.save_settings(s)
            return play_online(debug, ip, seat_no, dream)   # seat_no None: the server's seat desk picks
        print(__doc__)
        return 2
    except Failed as ex:
        say("FAILED: %s" % ex)
        say("Stopping what was started ...")
        stop(force=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
