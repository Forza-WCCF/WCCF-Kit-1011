# -*- coding: utf-8 -*-
"""The actual cabinet-start path sets the match wait before launching any process.

Uses scratch cabinet settings and stops at the first process launch: no game, real
settings, hardware helpers or network connection is started. Covers UPDATE without
SETUP, online restart and returning from online to local play.
"""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "code"))
import play  # noqa: E402
import setup  # noqa: E402

fails, checks = [], 0


def check(ok, message):
    global checks
    checks += 1
    if not ok:
        fails.append(message)
        print("FAILED: " + message)


class BeforeLaunch(Exception):
    pass


with tempfile.TemporaryDirectory(prefix="wccf-match-wait-") as temp:
    seat = Path(temp) / "seat1"
    (seat / "local").mkdir(parents=True)
    conf = seat / "local/client_user_option.conf"
    original_start = play.start
    observed = []

    def intercept(*args, **kwargs):
        observed.append(conf.read_bytes())
        raise BeforeLaunch

    play.start = intercept
    try:
        for newline in (b"\r\n", b"\n"):
            # An existing installation has the same hook and skips SETUP: a missing
            # match-wait option must still be supplied by the real start path.
            original = newline.join((b"# personal comment", b"CONTROL_IP=203.0.113.1",
                                     b"SATELLITE_NO=2", b"CUSTOM=keep", b""))
            conf.write_bytes(original)
            for mode, expected in (("remote", 60), ("remote", 60), ("local", 6), ("remote", 60)):
                before_count = len(observed)
                with contextlib.redirect_stdout(io.StringIO()):
                    try:
                        play.start_cabinet(False, {}, mode, "203.0.113.1", 2, str(seat), {})
                    except BeforeLaunch:
                        pass
                raw = conf.read_bytes()
                expected_line = b"TIMEOUT_P2P=" + str(expected).encode("ascii")
                check(len(observed) == before_count + 1 and observed[-1] == raw and
                      raw.splitlines().count(expected_line) == 1,
                      "%s: wait %d set before the first process launch (%r)" % (mode, expected, newline))
                check(raw.replace(expected_line + newline, b"") == original,
                      "%s: unrelated settings and line endings preserved" % mode)
                if mode == "remote" and before_count % 4 == 1:
                    check(raw == observed[-2], "online cabinet restart leaves the same effective settings")
        check(b"TIMEOUT_P2P=6\r\n" in setup.CONF_SEAT1.encode("ascii"),
              "SETUP's cabinet template explicitly retains the local game's original wait")
    finally:
        play.start = original_start

print("match patience: %d of %d checks passed" % (checks - len(fails), checks))
sys.exit(bool(fails))
