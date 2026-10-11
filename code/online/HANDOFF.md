# code\online\ - joining someone else's server

| File | What it does |
|---|---|
| `seat.py` | this PC's seat on a server: asks the server's seat desk for a seat and holds it while the game runs; after a break it reconnects and asks for the same seat |
| `send_logs.py` | SEND LOGS (SETTINGS panel): this kit's logs in one ZIP, sent to a server's log inbox - never the club card, and names on this PC are replaced |

## Careful
- `seat.py` writes its answer once, for play.py; play.py only falls back to seat 1 when a server has no seat desk at
  all (`test_take_seat.py`, `test_seat_lease.py`).
