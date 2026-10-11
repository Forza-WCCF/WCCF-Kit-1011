# -*- coding: utf-8 -*-
"""test_rotate_logs.py - log rotation never stops a start (A9): a held file in the log folder must not raise
(check.ps1 runs it; scratch folders only, no game). Also checks the normal rotation moves this run's logs aside.
    python source\\test_rotate_logs.py"""
import os
import shutil
import sys
import tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "scripts"))
import kit_common as K  # noqa: E402
import play  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


# 1. normal rotation: this run's logs go into previous\, previous is kept
t = tempfile.mkdtemp(prefix="wccf-logs-")
try:
    K.LOGS = os.path.join(t, "logs")
    os.makedirs(K.LOGS)
    open(os.path.join(K.LOGS, "run_seat1.txt"), "w").write("this run")
    play.rotate_logs()
    check(os.path.isfile(os.path.join(K.LOGS, "previous", "run_seat1.txt")), "this run's log moved to previous\\")
    check(not os.path.isfile(os.path.join(K.LOGS, "run_seat1.txt")), "the current folder is clear for the new run")
finally:
    shutil.rmtree(t, ignore_errors=True)

# 2. a held file: rmtree and move forced to fail - rotate_logs must NOT raise, and the log folder still exists
t = tempfile.mkdtemp(prefix="wccf-logs-")
real_rmtree, real_move = shutil.rmtree, shutil.move
try:
    K.LOGS = os.path.join(t, "logs")
    os.makedirs(os.path.join(K.LOGS, "previous"))
    open(os.path.join(K.LOGS, "previous", "old.txt"), "w").write("held")
    open(os.path.join(K.LOGS, "run_seat1.txt"), "w").write("this run")

    def boom(*a, **k):
        raise OSError("the file is busy")

    shutil.rmtree = boom
    shutil.move = boom
    try:
        play.rotate_logs()                              # must not raise
        check(True, "a held file did not stop the start")
    except Exception as e:  # noqa: BLE001
        check(False, "rotate_logs raised on a held file: %r" % e)
    check(os.path.isdir(K.LOGS), "the log folder still exists after the failure")
finally:
    shutil.rmtree, shutil.move = real_rmtree, real_move
    real_rmtree(t, ignore_errors=True)

n = 4
print("rotate_logs: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
