# source\panel\ - the panel around the game (programs\wccfpanel.dll)

The hook loads the panel into seat 1's window (and into the projector, for its money display). It draws with the
game's own Direct3D 9, so it lives inside the game's window.

| File | What it does |
|---|---|
| `wccfpanel.c` | the panel: TACTICS, FORMATION, SETTINGS (SHOW PROJECTOR, OPEN / CLOSE PROJECTOR, GRAPHICS beside the VIEW heading), CLUB CARD, CATALOGUE and KEYS; the projector's money; the online match relay's client side; guards for the game (a bad `%` in its text, the card dispenser's debt); the server link watched all the time (`data\logs\server_link.txt`: UP / LOST, dated; nothing after the player's own close); settings self-tests also verify projector and graphics choices survive one another's saves |
| `fakegame.c` | not shipped: a stand-in game window, so the panel's self-tests run without the game (check.ps1); it can hold a TCP link like the game's (`connect:PORT`, `disconnect`) |

## Careful
- The match relay tracks socket lifetimes through the checked Rev D sendto/recvfrom/closesocket imports. Only the
  current data socket sends a keepalive; peer mappings belong to that socket generation. Relay diagnostics queue
  outside the game thread and include guarded read-only game reason/progress snapshots. The expanded relay
  self-test uses real local sockets, including handle reuse, truncation, MSG_PEEK and concurrent operations.
- The panel finds its picture and catalogue through `WCCF_SKIN`, `WCCF_CATALOGUE`, `WCCF_CARDS` (play.py), and
  `version.txt` and `data\` one folder above itself.
- Its key rules must equal `code\hardware\keyboard.py` (allowed keys, controller words), and its "is a card session
  open" rule must equal `kit_common.card_session` - both are written in two languages, keep them equal.
