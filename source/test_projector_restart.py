# -*- coding: utf-8 -*-
"""test_projector_restart.py - play.py's projector restart, OPEN and CLOSE (restart_projector) against a scratch
running.json and stand-in processes (check.ps1 runs it; nothing starts, nothing is ended): the card session's start
stays, a pid Windows gave to another of the kit's Pythons is never ended, an old projector that will not end gets no
second one beside it, an automatic restart leaves a projector the player closed alone, and a restart waits for a stop
under the run lock - then finds the run gone and starts nothing. The cabinet's restart likewise leaves a stopped
or replaced run alone, including when it waited behind a stop; a normal cabinet restart still keeps the projector.
    python source\\test_projector_restart.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import play  # noqa: E402

K = play.K
T = tempfile.mkdtemp(prefix="wccf-projrestart-")
fails, n = [], 0


def check(cond, what):
    global n
    n += 1
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


GAME = os.path.join(T, "extracted")
PY = os.path.join(T, "python.exe")
play.RUNNING, play.LOCK, K.LOGS = os.path.join(T, "running.json"), os.path.join(T, "run.lock"), T
play.setup_state = lambda: (GAME, os.path.join(T, "seat1"))
play.kit_env = lambda *a: {}
play.time.sleep = lambda s: None
py, born, games, kills, launched, stubborn = {}, {}, [], [], [], set()   # py: the kit's Pythons that run {pid: start}
play.kit_pythons = lambda: [(pid, 1, "python.exe", PY) for pid in py]
K.started = lambda pid: py.get(pid)
K.game_processes = lambda game: list(games)


def kill(pid):
    kills.append(pid)
    if pid in stubborn:
        return False
    py.pop(pid, None)
    games[:] = [p for p in games if p[0] != pid]
    return True


def launch(env, roles):
    launched.append(1)
    roles[900] = "projector launcher"
    return 900


K.kill, play.launch_projector = kill, launch
START = time.time() - 600                          # the run (its cabinet) started 10 minutes ago


def run(alive=True, log=""):
    """a fresh online run: seat 1's launcher 10, the projector's launcher 12 and its game 50"""
    py.clear(), games.clear(), kills.clear(), launched.clear(), stubborn.clear()
    py.update({10: 1000, 12: 1200})
    if alive:
        games.append((50, 12, "client_Release.exe", os.path.join(GAME, "client_Release.exe")))
    else:
        py.pop(12)
    play.write_running({10: "seat 1 launcher", 12: "projector launcher"}, "remote", "1.2.3.4", 1, None, False,
                       {"run": "r1", "run_start": START, "projector": True, "show_projector": True})
    with open(os.path.join(T, "run_projector.txt"), "w", encoding="utf-8") as f:
        f.write(log)


def info():
    with open(play.RUNNING, encoding="utf-8") as f:
        return json.load(f)


try:
    # H1: a projector's restart keeps the card session's start - in the file and its write time (the panel's)
    run()
    check(play.run_started() == START and abs(os.path.getmtime(play.RUNNING) - START) < 1, "the run's start is written")
    check(play.restart_projector("open", "r1") == 0 and launched, "OPEN: a fresh projector")
    check(play.run_started() == START and abs(os.path.getmtime(play.RUNNING) - START) < 1 and info()["run"] == "r1",
          "... the card session's start and the run stay (an open session stays open)")
    check(info()["processes"] == {"10": "seat 1 launcher", "900": "projector launcher"} and info()["born"]["10"] == 1000,
          "... the cabinet's role and start kept, the old projector's gone")

    # H9: the old launcher's pid now another of the kit's Pythons (another start): never ended
    run()
    py[12] = 7777                                  # pid 12 is a cabinet helper by now
    games.clear()
    check(play.restart_projector("close", "r1") == 0 and kills == [], "CLOSE: a reused pid is not the projector")
    run()
    py[12] = 7777
    check(play.restart_projector("open", "r1") == 0 and 12 not in kills and launched, "OPEN: only a new one starts")

    # CLOSE: the projector ends, OPEN stays on offer without a live pid role
    run()
    check(play.restart_projector("close", "r1") == 0 and sorted(kills) == [12, 50], "CLOSE: its launcher and game end")
    check(info()["projector"] is True and "12" not in info()["processes"] and info()["run_start"] == START,
          "... running.json says a projector can come back, keeps no pid for it and keeps the run's start")
    check(play.restart_projector("open", "r1") == 0 and launched, "OPEN after CLOSE")

    # M8: an old projector that will not end: no second one, its role stays
    run()
    stubborn.update({12, 50})
    check(play.restart_projector("open", "r1") == 1 and not launched, "kill failed: no second projector")
    check("12" in info()["processes"], "... and its role stays")

    # M5: the automatic restart finds the projector closed by the player since it was planned: nothing
    run(alive=False)
    check(play.restart_projector(None, "r1") == 3 and not launched and not kills, "closed (gone): not reopened")
    run(log="  t+ 61.0s %s\n" % play.WINDOW_CLOSED)
    check(play.restart_projector(None, "r1") == 3 and not launched and not kills, "closed (its log): not reopened")
    run()
    check(play.restart_projector(None, "r1") == 0 and launched, "lost the server, still open: restarted")

    # H2: a restart for another run, or a run gone, does nothing; a stop holding the lock is waited for
    run()
    check(play.main(["projector", "run=r0"]) == 3 and not launched and not kills, "another run's restart: nothing")
    run()
    held = os.path.join(T, "held")
    stopper = subprocess.Popen([sys.executable, "-c", (
        "import os, sys, time; sys.path.insert(0, %r); import play; play.LOCK = %r\n"
        "with play.run_lock():\n"
        "    open(%r, 'w').close(); time.sleep(2); os.remove(%r)\n") % (
        os.path.join(KIT, "code"), play.LOCK, held, play.RUNNING)], creationflags=subprocess.CREATE_NO_WINDOW)
    end = time.time() + 30
    while not os.path.exists(held) and time.time() < end:
        time.sleep(0.05)
    t0 = time.time()
    rc = play.restart_projector(None, "r1")
    stopper.wait()
    check(time.time() - t0 > 1 and rc == 3 and not launched and not kills and not os.path.exists(play.RUNNING),
          "a stop under the run lock: the restart waits, then finds the run gone and starts nothing (%r)" % rc)

    # The cabinet uses the same lock: a stop can finish after its card guard, before it reads the run again.
    # Every process operation is still a stand-in, also when the regression starts an unwanted cabinet.
    cabinet_starts = []

    def cabinet(debug, env, mode, ip, seat_no, seat, roles):
        cabinet_starts.append((mode, ip, seat_no))
        py[901] = 9010
        roles[901] = "seat %d launcher" % seat_no

    play.start_cabinet = cabinet
    play.stop_guard = lambda *a: (0, False, "closed")
    play.apply_card_request = play.apply_card_fix = lambda: None
    play.apply_board = lambda *a: None

    for replacement in (None, "r2"):
        run()
        cabinet_starts.clear()
        held = os.path.join(T, "cabinet-held")
        if os.path.exists(held):
            os.remove(held)
        stopper = subprocess.Popen([sys.executable, "-c", (
            "import json, os, sys, time; sys.path.insert(0, %r); import play; play.LOCK = %r\n"
            "with play.run_lock():\n"
            "    open(%r, 'w').close(); time.sleep(2)\n"
            "    path, replacement = %r, %r\n"
            "    if replacement is None:\n"
            "        os.remove(path)\n"
            "    else:\n"
            "        with open(path, encoding='utf-8') as f: info = json.load(f)\n"
            "        info['run'] = replacement\n"
            "        with open(path, 'w', encoding='utf-8') as f: json.dump(info, f)\n") % (
            os.path.join(KIT, "code"), play.LOCK, held, play.RUNNING, replacement)],
            creationflags=subprocess.CREATE_NO_WINDOW)
        end = time.time() + 30
        while not os.path.exists(held) and time.time() < end:
            time.sleep(0.05)
        check(os.path.exists(held), "cabinet race: the simulated stop holds the real lock")
        t0 = time.time()
        rc = play.restart_cabinet()
        stopper.wait(timeout=10)
        check(stopper.returncode == 0 and time.time() - t0 > 1 and rc == 3 and not cabinet_starts and not kills,
              "cabinet restart waits, then leaves a %s run alone" % ("stopped" if replacement is None else "replaced"))
        check((not os.path.exists(play.RUNNING)) if replacement is None else info().get("run") == replacement,
              "cabinet restart never rewrites the stopped or replaced run")

    run()
    cabinet_starts.clear()
    check(play.restart_cabinet() == 0 and cabinet_starts == [("remote", "1.2.3.4", 1)] and kills == [10],
          "a normal restart starts the cabinet once and keeps the projector")
    check(info()["run"] == "r1" and info()["processes"] == {"12": "projector launcher", "901": "seat 1 launcher"},
          "a normal cabinet restart preserves the run and projector roles")

    run()
    cabinet_starts.clear()
    legacy = info()
    legacy.pop("run")
    with open(play.RUNNING, "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    check(play.restart_cabinet() == 0 and cabinet_starts == [("remote", "1.2.3.4", 1)],
          "a legacy run without an id can still restart its cabinet")
finally:
    shutil.rmtree(T, ignore_errors=True)

print("projector restart: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
