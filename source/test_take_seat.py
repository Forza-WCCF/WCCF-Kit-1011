# -*- coding: utf-8 -*-
"""test_take_seat.py - play._seat_decision: the seat an online PC takes from the seat desk's answer (check.ps1 runs
it; nothing live). A4: only "no broker" falls back to seat 1; full / taken / refused / no answer STOP, so two PCs
never land on seat 1.
    python source\\test_take_seat.py"""
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, "code"))
import play  # noqa: E402

fails = []


def check(cond, what):
    if not cond:
        fails.append(what)
        print("FAILED: " + what)


def dec(got, seat=None, ip="20.0.0.1"):
    return play._seat_decision(got, seat, ip)


# a real seat is used as given, projector flag carried
check(dec({"seat": 3, "projector": 0}) == ("seat", 3, False), "a given seat is used, no projector")
check(dec({"seat": 1, "projector": 1}) == ("seat", 1, True), "seat 1 with the projector")

# no broker = a server without a seat desk: seat 1 + projector, or the asked-for seat
check(dec({"error": "no broker", "detail": "refused"}, None) == ("no_broker", 1, True), "no broker -> seat 1 + projector")
check(dec({"error": "no broker"}, 5) == ("no_broker", 5, False), "no broker with a seat asked -> that seat, no projector")

# every other answer must STOP (raise), never fall back to seat 1 (the two-on-one bug)
for bad in ({"error": "no answer", "detail": "slow"}, {"error": "full"}, {"error": "taken"},
            {"error": "refused", "detail": "?"}, {}, {"detail": "garbage"}):
    try:
        dec(bad, 2)
        check(False, "a %r answer must stop, not take a seat" % bad)
    except play.Failed:
        pass

# the stop messages name the real trouble
try:
    dec({"error": "full"}, None)
except play.Failed as e:
    check("full" in str(e), "the 'full' message says full")
try:
    dec({"error": "no answer", "detail": "slow"}, None)
except play.Failed as e:
    check("did not answer" in str(e) and "local" in str(e), "the 'no answer' message says so and offers local play")

# a seat desk that wants a wccf.online sign-in, or refused this PC's (2026-10-14): SignInRefused, with the desk's
# own words - play.play_online then plays on this PC and says why
try:
    dec({"error": "signin", "detail": "ERR sign in: this server needs a wccf.online account"})
    check(False, "a sign-in refusal must raise SignInRefused")
except play.SignInRefused as e:
    check("needs a wccf.online account" in str(e), "a sign-in refusal keeps the desk's words for the player")
check(issubclass(play.SignInRefused, play.Failed), "SignInRefused is still a Failed (old handlers keep working)")

n = 12
print("take_seat: %d of %d checks passed" % (n - len(fails), n))
sys.exit(1 if fails else 0)
