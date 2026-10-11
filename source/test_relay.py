# -*- coding: utf-8 -*-
"""test_relay.py - the match relay's seat-ownership rule (A6): a live seat cannot be taken over by another address,
so no one can hijack a player's match by sending "WRL1R" + a seat (check.ps1 runs it; no sockets, no game).
    python source\\test_relay.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import _relay as R  # noqa: E402

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

n = 10
print("relay: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
