# -*- coding: utf-8 -*-
r"""play.py - start (and stop) WCCF 2010-11 on this PC: Sega's server, the projector (the shared big screen) and the
player cabinet (seat 1) with the overlay and your keyboard.  PLAY.exe runs it; run SETUP.exe first.

    python play.py            start everything on this PC - or, when the SETTINGS panel chose ONLINE, the cabinets
                              on its server (as "remote ADDRESS"), and this PC if that server does not answer; it
                              runs up to 12 hours; closing a game window ends it sooner
    python play.py local      everything on this PC, whatever the SETTINGS panel chose
    python play.py server     only the server side (scene service, server, its 4 match engines): for the PC or
                              cloud machine that hosts the game for others - its TCP port 20002 must be open to them;
                              it runs up to 32 days
    python play.py remote ADDRESS
                              only the cabinet on this PC, playing on the server at ADDRESS (four numbers with dots -
                              the game takes no names): the server's seat desk gives this PC the next free seat, and
                              the projector too if no other PC shows it yet (a server without the desk: seat 1 and the
                              projector, as before). The address is remembered, so a later "play.py remote" alone uses
                              it again. "play.py local" puts this PC back.
    python play.py remote ADDRESS seat N
                              seat N (1-8), if it is free there
    python play.py debug      the same with full logs (the card reader then logs every byte, ~60 MB an hour) and
                              every window open (the server's console and settings window, the key driver's);
                              "debug" also goes with server or remote
    python play.py stop       stop everything - refused while your club card is in the reader (the game may be
                              saving it: press I in the game first); "stop force" stops anyway;
                              "stop check" only says what stop would do, and stops nothing
    python play.py ended      what PLAY.exe's watcher runs once a game window is closed: stop the rest (a
                              server started on this PC with "server" stays, for the other players)
    python play.py status     what is running
    python play.py show       show the server's hidden windows again: its console (the round-by-round log) and its
                              settings window - to look at; they are hidden again at the next start
    python play.py restart    what the panels' RESTART NOW runs, through _kit_helper.py, in a window of its own: when a
                              plain start would play the same way (same THIS PC / ONLINE server, no English switch) -
                              a club card switch, say - only the cabinet restarts and the projector keeps running;
                              otherwise stop (the card rule), then a plain start

Order, each step waiting for the one before: scene service -> server (and its 4 match engines) -> projector ->
the cabinet's stand-ins (keychip and network, card reader, I/O board) -> seat 1 -> the overlay -> the key driver ->
the panel helper (_kit_helper.py: RESTART NOW).
Only the game's own windows open (since 2026-10-06): the server's two windows and every script's start hidden,
unless "debug".
The SETTINGS panel in seat 1's window writes data\panel.txt (2026-10-06): "play_on=this_pc" or "play_on=online" with
"server=ADDRESS" - what a plain start does - and "english=on" / "english=off", a request done at the next start
(by english.py, while nothing runs) and then taken out of the file.
"remote" next to a server started on this PC with "server" uses that server's scene service and keeps its logs
(the cabinets' logs of the run before are then not kept); if such a start fails, everything on this PC is stopped,
the server too.
Logs: data\logs\ (the run before: data\logs\previous\; older runs zipped in data\logs\archive\, the oldest dropped
past ARCHIVE_LIMIT); the key driver's is run_keys.txt.
Exit: 0 ok, 1 a step failed, 2 not set up, 3 refused.
"""
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
RELAY_PORT = 20040                                    # UDP, the server's match relay (_relay.py)
SERVER_ROLES = ("scene service", "server launcher", "seat desk", "match relay")
LIFE = 12 * 3600
SERVER_LIFE = 32 * 24 * 3600      # "play.py server" (2026-10-07): a month and a day - a server for others stays up
                                  # all month; a keeper task on that machine restarts it whenever it stops
PY = sys.executable
ICC_PIPE, JVS_PIPE = r"\\.\pipe\wccf_icc_seat1", r"\\.\pipe\wccf_jvs_seat1"
KEYS_INPUT = os.path.join(K.SCRIPTS, "_jvs_seat1_input.txt")     # _keys_seat1.py writes it beside itself
CARD = os.path.join(K.SAVE, "seat1_club.bin")
RUNNING = os.path.join(K.DATA, "running.json")
PANEL = os.path.join(K.DATA, "panel.txt")         # the SETTINGS panel's choices (wccfpanel.dll writes it)
CREATE_NEW_CONSOLE = 0x10
SW_HIDE, SW_SHOWMINNOACTIVE = 0, 7


class Failed(Exception):
    pass


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


def kit_env(game):
    """what every program of a run gets: this PC's environment without an earlier run's MXHOOK_ / WCCF settings, and
    where the game and the logs are"""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("MXHOOK_", "WCCF"))}
    env.update(WCCF_GAME=game, WCCF_LOGS=K.LOGS, MXHOOK_LOG_DIR=os.path.join(K.LOGS, "hook"))
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
    os.makedirs(K.LOGS, exist_ok=True)
    prev = os.path.join(K.LOGS, "previous")
    if os.path.isdir(prev):
        try:
            archive_run(prev, os.path.join(K.LOGS, "archive"))
        except (OSError, zipfile.BadZipFile) as ex:     # never a reason not to start: the old run's logs just go
            say("  logs: the run before last not archived (%s)" % ex)
        shutil.rmtree(prev)
    names = [n for n in os.listdir(K.LOGS) if n not in ("previous", "archive")]
    if names:
        os.makedirs(prev)
        for n in names:
            shutil.move(os.path.join(K.LOGS, n), os.path.join(prev, n))
    os.makedirs(os.path.join(K.LOGS, "hook"), exist_ok=True)


def setup_state():
    game = K.find_game(K.load_settings().get("game"))
    seat = K.seat_dir(game) if game else None
    if (not game or not os.path.isfile(os.path.join(seat, ".wccf-kit"))
            or not os.path.isfile(os.path.join(K.OVERLAY, "catalogue.tsv"))):
        say("Not set up yet - run SETUP.exe first.")
        return None, None
    return game, seat


def write_running(roles, mode, ip, seat_no=1):
    with open(RUNNING, "w", encoding="utf-8") as f:
        json.dump({"started": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode, "server": ip, "seat": seat_no,
                   "processes": roles}, f, indent=1)


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
    """the SETTINGS panel's "english=on" / "english=off": done now, before anything starts (english.py refuses while
    the game runs), then taken out of the file - a request, not a lasting setting, so ENGLISH.exe still works"""
    want = read_panel().get("english", "").lower()
    if want not in ("on", "off"):
        return
    if (want == "on") != K.english_on():
        say("  the game's text %s, as the SETTINGS panel asked - this takes a moment ..." % (
            "into English" if want == "on" else "back to Sega's Japanese"))
        try:            # english.py swaps each file in one step, so even a stop half way leaves every file in place
            r = subprocess.run([PY, os.path.join(K.SCRIPTS, "english.py"), want], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
            lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
            why = "" if r.returncode == 0 else (lines[-1] if lines else "english.py exit %d" % r.returncode)
        except (OSError, subprocess.TimeoutExpired) as ex:
            why = "it did not finish: %s" % ex
        if why:
            say("  the text could not be switched (%s) - the game starts as it is" % why)
        else:
            say("  done: the game's text is %s" % ("English" if want == "on" else "Sega's Japanese"))
    drop_panel_line("english")


def apply_card_request():
    """the CLUB CARD panel's "card=FILE" / "card=new" (2026-10-06): which club card goes into the slot, done now while
    nothing runs (club_wallet.switch: two renames, no card ever overwritten), then taken out of the file - only
    after the switch, so one stopped half way is finished at the next start.  Anything wrong: said, and the game
    starts with the card that is in the slot (never locked out).  First, a finished manager transfer is put away
    (club_wallet.finish_transfer, 2026-10-08): the new club into the slot, the old card to your cards."""
    try:
        import club_wallet
        _done, what = club_wallet.finish_transfer()
    except Exception as ex:                    # e.g. a card file held by another program: both stay, said
        what = "the manager transfer could not be finished now (%s) - both cards stay where they are" % ex
    if what:
        say("  club card: %s" % what)
    want = read_panel().get("card", "")
    if not want:
        return
    try:
        import club_wallet
        done, what = club_wallet.switch(want)
    except Exception as ex:                    # e.g. a card file held by another program: the slot stays as it is
        done, what = False, "the switch could not be done (%s) - the card in the slot stays" % ex
    say("  club card: %s" % what)
    drop_panel_line("card")


def apply_card_fix():
    """the CLUB CARD panel's "card_fix=bad_endings" (2026-10-08): the slot card's bad endings back to 0
    (edit_club_card.clear_bad_endings: the game's own checks, the old card into data\\save\\backup first), done now
    while the card reader is not running, then taken out of the file.  Anything wrong: said, and the card stays as it
    was (never a reason not to start)."""
    want = read_panel().get("card_fix", "").lower()
    if not want:
        return
    if want == "bad_endings":
        try:
            import edit_club_card
            what = edit_club_card.clear_bad_endings(CARD)
        except Exception as ex:
            what = "the bad endings were not cleared (%s) - the card stays as it was" % ex
        say("  club card: %s" % what)
    drop_panel_line("card_fix")


def apply_board(seat):
    """the cards on the table follow the club card in the slot (boards.py, 2026-10-08: the player saw another club's
    formation on the board) - done while nothing reads the table: the card reader, FPR_Emu and the overlay start after
    this.  Anything wrong: said, and the table stays as it is (never a reason not to start)."""
    try:
        import boards
        for what in boards.sync(seat):
            say("  table: %s" % what)
    except Exception as ex:
        say("  table: left as it is (%s)" % ex)


def take_seat(ip, seat_no, env, roles):
    """remote mode (2026-10-06): this PC's seat on the server at ip, from the server's seat desk (_seat_broker.py,
    TCP 20030) through _seat_lease.py, which keeps holding it while the game runs; seat_no None = the next free seat.
    Returns (seat, projector?).  A server without the desk: seat_no or 1, the projector with seat 1 - as before."""
    out = os.path.join(K.DATA, "seat_lease.json")
    if os.path.exists(out):
        os.remove(out)
    p = start("_seat_lease.py", [ip, out, LIFE] + ([] if seat_no is None else [seat_no]), "run_seat_lease.txt", env)
    end = time.time() + 15
    while time.time() < end and not os.path.exists(out):
        time.sleep(0.2)
    try:
        with open(out, encoding="utf-8") as f:
            got = json.load(f)
    except (OSError, ValueError):
        got = {"error": "no answer", "detail": "the seat lease wrote nothing in 15 s"}
    if "seat" in got:
        roles[p.pid] = "seat lease"
        return int(got["seat"]), bool(got.get("projector"))
    err = got.get("error")
    if err == "full":
        raise Failed("the server at %s is full: 8 cabinets play there now" % ip)
    if err == "taken":
        raise Failed("seat %d is taken on the server at %s - leave the seat number out to get the next free one" %
                     (seat_no, ip))
    seat_no = seat_no or 1
    say("  (the server has no seat desk - %s: seat %d%s, as before)" % (got.get("detail") or err, seat_no,
                                                                        " with the projector" if seat_no == 1 else ""))
    return seat_no, seat_no == 1


def start_cabinet(debug, env, mode, ip, seat_no, seat, roles):
    """steps 4-6 of a start, then the key driver: seat N's own side - the keychip / network, card reader and I/O board
    stand-ins, the cabinet (the seat1 folder) with its overlay - each new process into roles.  A cabinet restart
    (2026-10-07) runs only this: the projector, the scene service, the seat lease and the panel helper keep running."""
    p = start("_ringedge_services.py", [LIFE, "ringedge_log.txt"], "run_ringedge.txt", env)
    roles[p.pid] = "keychip / network stand-in"
    import club_wallet                         # its NEW: room for a second card, for a manager transfer (2026-10-08)
    p = start("_icc_reader.py", [ICC_PIPE, LIFE, "icc_log.txt" if debug else "NUL", CARD, club_wallet.NEW],
              "run_cardreader.txt", env, quiet=not debug)
    roles[p.pid] = "card reader stand-in"
    p = start("_jvs_board.py", [JVS_PIPE, LIFE, "jvs_log.txt", KEYS_INPUT], "run_ioboard.txt", env)
    roles[p.pid] = "I/O board stand-in"
    wait_for("the cabinet's stand-ins", lambda: {40100, 40102, 40106} <= K.listening_ports() and
             {"wccf_icc_seat1", "wccf_jvs_seat1"} <= K.pipes(), 20)
    say("  4/6 cabinet stand-ins: keychip/network, card reader (card file data\\save\\seat1_club.bin), I/O board")

    senv = dict(env, MXHOOK_RINGEDGE="1",
                MXHOOK_COM="COM3=%s;COM1=%s;mxjvs=%s;COM4=%s" % (ICC_PIPE, ICC_PIPE, JVS_PIPE, JVS_PIPE))
    if mode == "remote":    # a match against another player goes through the server's relay (wccfpanel.dll, 2026-10-06)
        senv.update(WCCF_RELAY="%s:%d" % (ip, RELAY_PORT), WCCF_SEAT=str(seat_no))
    if debug:
        senv["MXHOOK_VERBOSE"] = "1"
    # the cabinet in the seat1 folder SETUP made, whatever its seat number: the number is only its command line
    p = start("_debug_launch.py", [LIFE, "client", "follow", "arg=%d" % seat_no, "dir=" + seat], "run_seat1.txt", senv)
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
    time.sleep(3)
    olog = os.path.join(seat, "wccfpanel.log")
    skip = len(open(olog, encoding="utf-8", errors="replace").read()) if os.path.exists(olog) else 0
    try:
        r = subprocess.run([os.path.join(K.OVERLAY, "inject.exe"), str(found["pid"]),
                            os.path.join(K.OVERLAY, "wccfpanel.dll")], capture_output=True, text=True, timeout=60)
        why = "" if r.returncode == 0 else (r.stdout.strip() or r.stderr.strip() or "exit %d" % r.returncode)
    except (OSError, subprocess.TimeoutExpired) as ex:
        why = str(ex)

    def overlay_up():
        try:
            return "maximized" in open(olog, encoding="utf-8", errors="replace").read()[skip:]
        except OSError:
            return False
    if why:     # the game runs without the overlay - never a reason to take the game away (2026-10-06)
        say("  6/6 the overlay did not load (%s) - the game runs without its panels; the keyboard works as usual" %
            why)
    else:
        try:
            wait_for("the overlay", overlay_up, 60)
            say("  6/6 overlay in seat %d's window" % seat_no)
        except Failed:
            say("  6/6 overlay loaded (it did not report its window yet - see seat1\\wccfpanel.log)")
    if debug:                               # its own window, minimized, as before
        k = start("_keys_seat1.py", [], None, env, show=SW_SHOWMINNOACTIVE)
    else:
        k = start("_keys_seat1.py", [], "run_keys.txt", env)
    roles[k.pid] = "key driver"


def play(debug, mode="local", ip=None, seat_no=None):
    """mode "local": everything on this PC; "server": the server side only; "remote": the cabinets only, on the
    server at ip - seat_no None: the next free seat from the server's seat desk (2026-10-06), and the projector if this
    PC is the first; 1-8: that seat (the game reads it from the cabinet's settings, SATELLITE_NO -
    docs\\NETWORK-MAP-2010-11.md section 6; the projector is seat 0 and a server has one)"""
    projector = True
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
    beside_server = bool(running)            # only "remote" gets here with something running: a server on this PC
    if beside_server:
        os.makedirs(os.path.join(K.LOGS, "hook"), exist_ok=True)     # its logs are open: no rotation
        if read_panel().get("english", "").lower() in ("on", "off"):
            say("  (the SETTINGS panel's English change waits: the server on this PC uses the same game files)")
    else:
        rotate_logs()
        apply_english_request()
    apply_card_request()                       # the card reader is not running yet, in every mode that gets here
    apply_card_fix()
    if mode != "server":
        apply_board(seat)                      # ... nor FPR_Emu or the overlay: the slot club's cards on the table
    env = kit_env(game)
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
        p = start("_xscn_watch.py", [life + 120, "xscn_watch_log.txt"], "run_scenes.txt", env)
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
        seat_no, projector = take_seat(ip, seat_no, env, roles)
        for conf in confs:
            set_control_ip(conf, ip)
        set_satellite_no(confs[1], seat_no)          # the cabinet's seat (1, or 2-8 for another player's PC)
        # never "WAITING FOR THE PROJECTOR" on a server: its projector is on another PC, or gone (2026-10-06)
        set_conf_value(confs[1], "WAIT_PROJECTOR", 0)
        say("  2/%d server: %s answers on port %d - this PC is seat %d%s" % (
            steps, ip, CONTROL_PORT, seat_no, " and shows the projector" if projector else ""))
    else:
        seat_no = 1                                  # everything on this PC: seat 1 and the projector
        ctrl_conf = os.path.join(game, "local", "ctrl_user_option.conf")
        if mode == "local":
            for conf in confs:              # after a "remote" run: the cabinets play on this PC again
                set_control_ip(conf, "127.0.0.1")
            set_satellite_no(confs[1], 1)            # after a "remote ... seat N" run: seat 1 again
            set_conf_value(confs[1], "WAIT_PROJECTOR", 1)    # the game's own way, with its projector right here
            set_conf_value(ctrl_conf, "WAIT_PROJECTOR", 1)
        else:
            # a server for others: the game's own way - it waits for the first projector before its first round, so
            # the projector starts in step (2026-10-06: with 0 the rounds started at once and a projector joining a
            # minute later sat on "Now Synchronizing" until the next round).  A projector that leaves later is
            # dropped like any seat and the matches go on (docs\NETWORK-MAP-2010-11.md section 8); the seat desk
            # gives the projector to the first PC that joins.
            set_conf_value(ctrl_conf, "WAIT_PROJECTOR", 1)
        p = start("_debug_launch.py", [life + 60, "control", "follow"] + ([] if debug else ["hide"]), "run_server.txt",
                  env)
        roles[p.pid] = "server launcher"
        wait_for("the server", lambda: CONTROL_PORT in K.listening_ports() and len(games("match_release.exe")) >= 4,
                 90, p, "run_server.txt")
        ctl = games("control_release.exe")
        if ctl:     # a click in the server's console window would freeze it (text-selection mode): switch that off
            subprocess.run([PY, os.path.join(K.SCRIPTS, "_no_quickedit.py"), str(ctl[0][0])], capture_output=True,
                           timeout=15)
            if not debug:       # it starts hidden; a window it shows by itself later is hidden here
                K.hide_windows(ctl[0][0])
        say("  2/%d server: listening on port %d, %d match engines" % (steps, CONTROL_PORT,
                                                                       len(games("match_release.exe"))))
    if mode == "server":
        # the seat desk (2026-10-06): every player's PC that joins gets the next free seat, the first the projector
        b = start("_seat_broker.py", [life + 60, os.path.join(K.LOGS, "seat_broker.txt")], "run_seat_broker.txt", env)
        time.sleep(1.5)
        if b.poll() is None:
            roles[b.pid] = "seat desk"
            say("     seat desk: TCP 20030 - each player's PC gets the next free seat, the first also the projector")
        else:
            say("     the seat desk did not start (data\\logs\\run_seat_broker.txt) - players then give their seat")
        # the match relay (2026-10-06): a match between two players goes through here - home routers block the direct way
        m = start("_relay.py", [life + 60, os.path.join(K.LOGS, "match_relay.txt")], "run_match_relay.txt", env)
        time.sleep(1.0)
        if m.poll() is None:
            roles[m.pid] = "match relay"
            say("     match relay: UDP %d - a match between two players goes through this machine" % RELAY_PORT)
        else:
            say("     the match relay did not start (data\\logs\\run_match_relay.txt) - two players then play the CPU")
        write_running(roles, mode, None)
        say("")
        say("Server running. On each player's PC: PLAY.exe remote, then this machine's address - the one their PC")
        say("can reach. This machine must let in TCP ports %d and 20030, and UDP %d. PLAY.exe stop ends it." % (
            CONTROL_PORT, RELAY_PORT))
        return 0

    if projector:
        p = start("_debug_launch.py", [LIFE, "client", "follow", "arg=0"], "run_projector.txt", env)
        roles[p.pid] = "projector launcher"
        say("  3/6 projector (seat 0) - its window opens in a few seconds")
    else:
        say("  3/6 projector: none on this PC - the server's projector is on the seat 1 PC")

    start_cabinet(debug, env, mode, ip, seat_no, seat, roles)
    # the projector gets the overlay too (2026-10-06), in its money-only mode: its amounts with commas
    # (wccfpanel.c is_projector - no panels, nothing else); it plays on as before if it does not load
    if projector:
        try:
            m = re.search(r"launched client_Release\.exe pid (\d+)",
                          open(os.path.join(K.LOGS, "run_projector.txt")).read())
            r = subprocess.run([os.path.join(K.OVERLAY, "inject.exe"), m.group(1),
                                os.path.join(K.OVERLAY, "wccfpanel.dll")], capture_output=True, text=True,
                               timeout=60) if m else None
            pwhy = "its process was not found" if not m else "" if r.returncode == 0 else (
                r.stdout.strip() or r.stderr.strip() or "exit %d" % r.returncode)
        except (OSError, subprocess.TimeoutExpired) as ex:
            pwhy = str(ex)
        say("       projector: amounts with commas" if not pwhy else
            "       projector: its amounts stay without commas (%s)" % pwhy)

    h = start("_kit_helper.py", [LIFE], "run_helper.txt", env)      # the panels' RESTART NOW (from outside the game)
    roles[h.pid] = "panel helper"
    write_running(roles, mode, ip, seat_no)
    say("")
    if mode == "remote":
        say("Playing on the server at %s%s." % (ip, "" if projector else " as seat %d (no projector on this PC)" % seat_no))
    say("Running. Click the cabinet's window, then play with the keyboard (it works only while a game window is in "
        "front):")
    say("  Enter START (free play: it puts a coin in for you)   X decide   C shoot   arrows: tactics")
    say("  I club card in / out   5 coin   F1 test menu   F11 window size   - or click the buttons around the picture")
    say("First time: put the card in with I, and the game makes your club. It is saved in data\\save\\seat1_club.bin.")
    say("To finish: let the card come out after a match, then close the game's window - the rest stops with it. %s" % (
        "(The key driver's window is minimized.)" if debug else
        "(The key driver runs in the background: its log is data\\logs\\run_keys.txt.)"))
    return 0


def run_started():
    """when this run started: data\\running.json's write time (written once, when everything was up); None if none"""
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
    """(session state, bad endings) of the club in play: the slot card, or during a manager transfer the new card
    beside it (2026-10-08) - an open session on either one is open"""
    import club_wallet
    since = run_started()
    sess, bad = K.card_session(CARD, since)
    new_sess, new_bad = K.card_session(club_wallet.NEW, since)
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
    try:                         # the cards on the table kept with their club (boards.py): data\save holds the latest
        import boards
        boards.keep(seat)
    except Exception as ex:
        say("  (the cards on the table were not copied to their club: %s)" % ex)
    return 0


WINDOW_CLOSED = "its window was closed"   # _debug_launch.py's line when it ends a game because its window was closed


def window_launchers(roles):
    """{pid: its log} of the run's game-window launchers (start_cabinet: every seat writes run_seat1.txt)"""
    return {pid: "run_projector.txt" if r == "projector launcher" else "run_seat1.txt" for pid, r in roles.items()
            if r == "projector launcher" or re.fullmatch(r"seat \d+ launcher", r)}


def crashed_logs(launchers, alive, read_log):
    """the logs of the launchers that ended WITHOUT their window being closed (a crash), when another game window of
    the run still runs - then nothing may stop (the player, 2026-10-07: "no one cabinet can restart or stop the
    projector"); None when a window was closed, or when no game window is left to keep running.  An empty list: none
    has ended (a hand-run "ended") - nothing stops then either"""
    gone = sorted({log for pid, log in launchers.items() if pid not in alive})
    if any(WINDOW_CLOSED in read_log(log) for log in gone) or not any(pid in alive for pid in launchers):
        return None
    return gone


def read_log(name):
    try:
        with open(os.path.join(K.LOGS, name), encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""                # unreadable counts as no close: the safe side keeps the rest running


def ended():
    """a game window closed (2026-10-08; there is no STOP now): PLAY.exe's watcher saw one of the run's cabinet and
    projector launchers end - _debug_launch.py ends the game, and itself, when the game's window is closed - and asks
    for the rest to stop: the server, its match engines, the stand-ins, the key driver, the panel helper.  Before, they
    ran on hidden for up to 12 hours.  The card rule still holds for a cabinet that still runs (the projector closed
    during a match: refused, exit 3, and the watcher goes on watching).  A cabinet that played on a server started on
    this PC with "server" leaves that server running for the other players.  A game that went by itself (a crash, no
    close in its log) stops nothing while another game window runs - the projector keeps running (exit 3 too)."""
    game, _seat = setup_state()
    if not game:
        return 2
    launchers, alive = window_launchers(running_roles()), {p[0] for p in kit_pythons()}
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
    return stop(False, keep_server=server_here)


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
    if want in ("on", "off") and (want == "on") != K.english_on():
        return False
    online = panel.get("play_on", "").lower() == "online"
    if info["mode"] == "remote":
        return online and panel.get("server", "") == info.get("server")
    return not online


def restart_cabinet():
    """RESTART NOW for the cabinet only (2026-10-07; the player: "no one cabinet can restart or stop the projector,
    that has to keep running"): seat N's side is stopped by the card rule, the CLUB CARD panel's switch is done, and
    that side starts again.  The projector, the scene service, the seat lease and the panel helper are never touched,
    so the projector stays in step with the server (one that rejoins mid-round waits up to a whole round)."""
    game, seat = setup_state()
    if not game:
        return 2
    info = running_info()
    roles = {int(k): v for k, v in (info.get("processes") or {}).items()}
    mode, ip = info.get("mode"), info.get("server")
    try:
        seat_no = int(info.get("seat", 1))
    except (TypeError, ValueError):
        seat_no = 1
    rc, _c, _sess = stop_guard(False, False, game, seat)
    if rc:
        return rc
    say("Restarting seat %d's cabinet only - the projector keeps running." % seat_no)
    alive = {p[0] for p in kit_pythons()}
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
        write_running(roles, mode, ip, seat_no)
        say("Still running: %s - the cabinet was not started again (PLAY.exe stop, then PLAY.exe)." % ", ".join(
            "%s %d" % (p[2], p[0]) for p in left))
        return 1
    apply_card_request()                     # the card reader is stopped: the CLUB CARD panel's switch goes in now
    apply_card_fix()                         # and its CLEAR BAD ENDINGS
    apply_board(seat)                        # and the new club's cards onto the table, before FPR_Emu and the overlay
    time.sleep(1.0)                          # Windows frees the cabinet's ports and pipes
    start_cabinet(False, kit_env(game), mode, ip, seat_no, seat, roles)
    write_running(roles, mode, ip, seat_no)
    say("")
    say("Seat %d's cabinet is back; the projector was not touched." % seat_no)
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
                say("Online, as the SETTINGS panel chose (PLAY.exe local plays on this PC).")
                return play(debug, "remote", ip)              # the server's seat desk picks the seat
            return play(debug)
        if rest == ["local"]:
            return play(debug)
        if rest == ["server"]:
            return play(debug, "server")
        if rest[0] == "remote":
            words, seat_no = rest[1:], None
            if len(words) >= 2 and words[-2] == "seat":          # a second player's PC: "remote ADDRESS seat 2"
                if not (words[-1].isdigit() and 1 <= int(words[-1]) <= 8):
                    say("Seats are 1 to 8, e.g. PLAY.exe remote 192.168.1.20 seat 2 - seat 1 is the PC that also "
                        "shows the projector, so every other PC takes its own seat from 2 up.")
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
            return play(debug, "remote", ip, seat_no)       # seat_no None: the server's seat desk picks
        print(__doc__)
        return 2
    except Failed as ex:
        say("FAILED: %s" % ex)
        say("Stopping what was started ...")
        stop(force=True)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
