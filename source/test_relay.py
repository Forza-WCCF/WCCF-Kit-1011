# -*- coding: utf-8 -*-
"""test_relay.py - the match relay's seat-ownership rule (A6): a live seat cannot be taken over by another address,
so no one can hijack a player's match by sending "WRL1R" + a seat - while the same public address on a new port takes
its seat at once (2026-10-15) (check.ps1 runs it; no sockets, no game).
    python source\\test_relay.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
from server import relay as R  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


OWNER = ("1.1.1.1", 20001)
ATTACKER = ("9.9.9.9", 40000)
FORGET = R.FORGET

seats, rejects = {}, {}

# the owner claims seat 3 at t=0
check(R.claim(seats, 3, OWNER, 0.0, rejects) is True, "the first address gets the seat")
check(seats[3][0] == OWNER, "the owner is recorded")

# the owner keeps refreshing - always allowed
check(R.claim(seats, 3, OWNER, 5.0, rejects) is True, "the owner refreshes its own seat")

# a different address claiming the LIVE seat is rejected, and does not change the owner
check(R.claim(seats, 3, ATTACKER, 6.0, rejects) is False, "a stranger cannot take a live seat")
check(seats[3][0] == OWNER, "a rejected claim leaves the owner unchanged")
check(rejects.get(3) == 1, "the rejection is counted")

# the attacker trying again is still rejected while the owner is active
check(R.claim(seats, 3, ATTACKER, 10.0, rejects) is False, "still rejected while the owner is active")
check(rejects.get(3) == 2, "each rejection counts")

# once the owner has been quiet longer than FORGET, a new address may take the seat (a changed public address)
check(R.claim(seats, 3, ATTACKER, 6.0 + FORGET + 1, rejects) is True, "a forgotten seat is free for a new address")
check(seats[3][0] == ATTACKER, "the new address now owns the seat")

# a different seat is independent
check(R.claim(seats, 5, OWNER, 100.0, rejects) is True, "another seat is unaffected")

# 2026-10-15 on the live server: a player's seat said hello from one port, then his match data came from another port
# of the SAME public address - 92 packets rejected in 30 s, and both games fell back to a CPU match. Now: at once.
seats, rejects = {}, {}
HOME_A, HOME_B = ("163.5.171.50", 7411), ("163.5.171.50", 17389)
check(R.claim(seats, 2, HOME_A, 0.0, rejects) is True, "a hello takes the free seat")
check(R.claim(seats, 2, HOME_B, 0.4, rejects, data=True) is True,
      "the same public address on a new port: its match data is taken at once")
check(seats[2][0] == HOME_B and not rejects, "... the seat moves to the port that plays, nothing rejected")
check(R.claim(seats, 2, HOME_A, 3.0, rejects) is True and seats[2][0] == HOME_B,
      "a hello from the other port while the match plays: the seat stays on the port that plays")
check(R.claim(seats, 2, HOME_B, 3.1, rejects, data=True) is True and seats[2][0] == HOME_B, "the playing port goes on")
check(R.claim(seats, 2, ATTACKER, 3.2, rejects, data=True) is False and seats[2][0] == HOME_B,
      "another public address is still refused (A6)")
check(R.claim(seats, 2, HOME_A, 9.1, rejects) is True and seats[2][0] == HOME_B,
      "a data pause longer than five seconds does not let an old socket's hello steal the live route")
check(seats[2][1] == 3.1, "an ignored hello does not refresh the selected socket's lifetime")
check(R.claim(seats, 2, HOME_A, 3.1 + FORGET + 1, rejects) is True and seats[2][0] == HOME_A,
      "after the selected socket expires, a hello can take the seat again")

n = 19
print("relay: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
