# code\online\ - joining someone else's server

| File | What it does |
|---|---|
| `account.py` | this PC's wccf.online sign-in, the way a TV signs in: a code shown (PLAY window + a small Windows box), the page opened in the browser, the player approves there; the token kept in `data\account.json`. play.py runs it before joining a server; nothing fatal - no sign-in plays on |
| `seat.py` | this PC's seat on a server: asks the server's seat desk for a seat and holds it while the game runs; after a break it reconnects and asks for the same seat; signed in, every request carries the token |
| `send_logs.py` | SEND LOGS (SETTINGS panel): this kit's logs in one ZIP, sent to a server's log inbox - never the club card, and names on this PC are replaced; also the newest lean crash snapshots and a report.txt; play.py uses it to send a run that went wrong by itself |

## Careful
- `seat.py` writes its answer once, for play.py; play.py only falls back to seat 1 when a server has no seat desk at
  all (`test_take_seat.py`, `test_seat_lease.py`).
- The sign-in token is a password: only `account.py` and `seat.py` read `data\account.json`; never print it, log
  it, put it on a command line or in SEND LOGS (`send_logs.files()` names what it packs - keep it that way). A desk
  refusal ("ERR sign in ...") becomes play.py's `SignInRefused`: it plays on this PC and says why
  (`test_account.py`, `test_seat_desk_signin.py`).
