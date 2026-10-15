# source\hook\ - the kit's hook inside the game (programs\wccfk.dll)

The game's programs load this DLL because setup.py renames their import of `WINMM.dll` to `wccfk.dll`
(`code\helpers\hook.py`). Inside the game it stands in for the cabinet's hardware.

| File | What it does |
|---|---|
| `wccfk.c` | the hook: the cabinet's serial ports become the card reader's and I/O board's named pipes, the RingEdge memory, the network address the game expects; answers the server's start of logowin.exe; loads the panel (`WCCF_PANEL`) once the game's window is up; on the server (control): whole messages, and with `WCCF_WITNESS_DIR` the witness - ENTRY SVR (a session's start), TEAM DATA (each match's start, a played-on one too) and TEAM DATA RSLT (its end) kept for wccf.online, each message name a player sends said in the log as "match flow" |
| `winmm_fwd.h` | passes the game's three timer functions on to Windows' own winmm |
| `wholemsg.h` | the server's whole messages: what players send to control_Release (port 20002) is kept and handed over only as whole batches; bytes that cannot be a batch are skipped, nobody is cut (`WCCF_WHOLEMSG=0` turns it off) |
| `test_wholemsg.c` | not shipped: 18 checks of `wholemsg.h` - a batch split at every byte waits, garbage is skipped, the crash's wild length is refused (check.ps1 runs it) |
| `jvs.h` | the I/O board's guards (2026-10-15, "no input"): in client_Release.exe Sega's error mark (10 failed polls in a row = the buttons never read again that run) is switched off at start, only on Sega's exact bytes; before each new request, late answers still waiting on the pipe are dropped. Why: `docs\research\NO-INPUT-2010-11.md` |
| `test_jvs.c` | not shipped: `jvs.h` on its own - the mark off only on Sega's bytes and never half, late answers dropped from a real named pipe (check.ps1 runs it) |

## Careful
- Keep the log line `mxhook attached` (it was named mxhook.c): setup.py recognises its own hook by it.
- The JVS mark patch changes the game's code in memory only (never the exe on disk): seat 1's exe and its English copy
  keep their checked hashes. Its log line ("JVS: failed polls can no longer switch the buttons off") is in each
  client's `data\logs\hook\mxhook_<pid>.log`.
- The name `wccfk.dll` must stay at most 9 characters: setup overwrites `WINMM.dll` in the game's import in place.
- The whole-messages change (#35) removes the most likely cause of the server crash (Sega's code for joining a message
  that arrived in pieces); the crash was never made to happen on purpose, so it is not a proven fix. The server's
  keeper (restart within a minute) stays the safety net.
