# source\hook\ - the kit's hook inside the game (programs\wccfk.dll)

The game's programs load this DLL because setup.py renames their import of `WINMM.dll` to `wccfk.dll`
(`code\helpers\hook.py`). Inside the game it stands in for the cabinet's hardware.

| File | What it does |
|---|---|
| `wccfk.c` | the hook: the cabinet's serial ports become the card reader's and I/O board's named pipes, the RingEdge memory, the network address the game expects; answers the server's start of logowin.exe; loads the panel (`WCCF_PANEL`) once the game's window is up |
| `winmm_fwd.h` | passes the game's three timer functions on to Windows' own winmm |

## Careful
- Keep the log line `mxhook attached` (it was named mxhook.c): setup.py recognises its own hook by it.
- The name `wccfk.dll` must stay at most 9 characters: setup overwrites `WINMM.dll` in the game's import in place.
- Pull request #35 (the server only ever sees whole messages from players) runs on the Azure server but is NOT in
  this file yet: it goes in before kit 6 is released.
