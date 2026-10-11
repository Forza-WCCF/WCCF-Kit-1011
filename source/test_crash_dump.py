# -*- coding: utf-8 -*-
"""test_crash_dump.py - a crash leaves its memory snapshots (debugger.py write_dumps, 2026-10-11): source\\build\\crashme.exe
(a write to address 0, 32-bit like the game) runs as the "client" under the real debugger.py from a scratch folder;
data\\dumps must get a lean and a full snapshot, both real minidumps, and the launcher's report must name them.
check.ps1 runs it after build.ps1; nothing of the game runs.
    python source\\test_crash_dump.py"""
import os
import shutil
import subprocess
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print("  %s  %s%s" % ("PASS" if ok else "FAIL", name, ("  - " + detail) if detail else ""))


tmp = tempfile.mkdtemp(prefix="crashdump_")
try:
    game, logs = os.path.join(tmp, "game"), os.path.join(tmp, "data", "logs")
    os.makedirs(game)
    os.makedirs(logs)
    shutil.copy(os.path.join(KIT, "source", "build", "crashme.exe"), os.path.join(game, "client_Release.exe"))
    env = dict(os.environ, WCCF_LOGS=logs, WCCF_GAME=game)
    r = subprocess.run([sys.executable, "-B", os.path.join(KIT, "code", "hardware", "debugger.py"), "30", "client",
                        "nomaps", "dir=" + game], env=env, capture_output=True, text=True, timeout=60)
    out = r.stdout + r.stderr
    dumps = os.path.join(tmp, "data", "dumps")
    names = sorted(os.listdir(dumps)) if os.path.isdir(dumps) else []
    check("the crash is reported as fatal", "SECOND-chance / FATAL" in out, out[-300:])
    check("the report names the snapshots", "memory snapshot (fatal exception 0xC0000005" in out, out[-300:])
    check("data\\dumps has one lean and one full snapshot", [n.rsplit("_", 1)[1] for n in names] == ["full.dmp", "lean.dmp"],
          str(names))
    heads = [open(os.path.join(dumps, n), "rb").read(4) for n in names]
    check("both are real minidumps (MDMP)", heads == [b"MDMP", b"MDMP"], str(heads))
    sizes = [os.path.getsize(os.path.join(dumps, n)) for n in names]
    check("the full one holds more than the lean one", len(sizes) == 2 and sizes[0] > sizes[1], str(sizes))
    check("the launcher ends with an error (the program crashed)", r.returncode == 1, str(r.returncode))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("crash snapshots: %d/%d checks passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
