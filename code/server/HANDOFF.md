# code\server\ - running a server for other players

play.py starts these when this PC is the server (`play.py server`).

| File | What it does |
|---|---|
| `seat_desk.py` | hands out seats to the PCs that join (TCP 20030); never seat 0 (the server runs with WAIT_PROJECTOR=0) - a PC that says `RELAY` is told the projector relay's port (`SEAT n PROJECTOR 20031`) and shows the projector through it; checks a PC's wccf.online sign-in with the website (`WANT ... TOKEN t`) and remembers its account - optional until `data\require_signin.txt` exists, then needed; kit 7 also says which club card it plays (`CARD c`), kept in the lease for the witness |
| `projector_relay.py` | the projector on every player's PC (TCP 20031, 2026-10-17): holds control's one projector connection (seat 0), opened once a player is in the game, and passes what control sends to every projector PC; answers each projector's INIT itself, keeps control's seat alive, sends control each REQ_* once (one per name on its way, the rest wait for its reply) and every reply to all, gives a late joiner what it missed (TO MATCH INI before the frames), sheds a slow projector's oldest frames (then a finished match's INI) and cuts only one that takes nothing for 100 s, has 4 MiB waiting, sends bytes that are no batch or over 1,000 messages a second (a burst over 100 a second is dropped, not cut); drops what an older session with control passes on |
| `relay.py` | passes match traffic between two players' PCs (UDP 20040) - home routers block the direct way; a live seat belongs to the address that holds it |
| `log_inbox.py` | keeps the logs players send with SEND LOGS (TCP 20050), in `data\player_logs` |
| `witness.py` | a card per finished match (phase 3): only on a server wccf.online knows (`data\server_name.txt` + `data\server_secret.txt`, never in git or SEND LOGS); the hook in control keeps each cabinet's club data at a session's start, at each match's start (TEAM DATA, a match played on too) and after a match in `data\witness\`, the seat desk's `data\leases.json` says whose it was (two signed-in players at one address: the club card's id in the message names the seat), and this tells the website with the server's secret - the website gives the card |

## Careful
- The live Azure server runs kit 5's copies under their OLD names (`_seat_broker.py`, `_relay.py`, `_log_inbox.py`,
  `_debug_launch.py`). Its next update must account for the new names - check its keeper and tasks first, and never
  while players are on.
- Their log files keep their names (`seat_broker.txt`, `match_relay.txt`, `log_inbox.txt`): the server's own tools
  read those.
