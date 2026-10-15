# code\hardware\ - the arcade cabinet's parts, faked on a PC

A real WCCF cabinet has a card reader, buttons on an I/O board, and Sega's background services. On a PC these
programs stand in for them; play.py starts each one (data\running.json lists them while the game runs).

| File | What it does |
|---|---|
| `card_reader.py` | the club-card reader: hands the card file to the game over a named pipe, and saves what the game writes - never in place, with backups |
| `io_board.py` | the I/O board (JVS): turns the key driver's file `data\_jvs_seat1_input.txt` into the game's buttons; writes the game's outputs (the card ejector) beside it. Since 2026-10-15 the thread that answers the game never touches the disk (the input file is read, and the log and outputs file written, by threads of their own), it runs at high priority out of Windows' throttling, and moments over 250 ms are logged as `SLOW` - a 5 s stall here once cost the buttons for the rest of a run (`docs\research\NO-INPUT-2010-11.md`) |
| `keyboard.py` | the key driver: your keyboard and controllers become the cabinet's buttons (keys from `data\keys.txt`, the KEYS panel); takes the card out when the game ejects it |
| `scenes.py` | the scene service (xscnWatch): loads the game's scene files when it asks |
| `network.py` | the arcade's background services (keychip and network): answers the game's questions |
| `debugger.py` | starts one of the game's programs (server, projector, seat 1) with the shared memory in place, ends it when its window closes, and guards the server against a known crash; at any crash it prints where and writes two memory snapshots to `data\dumps` (lean + full, newest 5 each) |

## Careful
- `keyboard.py`'s `LIVE`, the outputs file `io_board.py` writes beside it, and play.py's `KEYS_INPUT` must name the
  same files in `data\`: play's stop guard reads whether the card is in from there. check.ps1 asserts it.
- `debugger.py` prints the line play.py looks for when a window was closed (`test_ended.py`).
- The live Azure server still runs these under their kit 5 names (`_debug_launch.py` ...): see `code\server\HANDOFF.md`.
- Verified 2026-10-11 in a real start of CI's kit: every one started from here, and the card went in and out.
