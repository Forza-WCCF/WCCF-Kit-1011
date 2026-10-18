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
| `pictures.h` | English pictures (2026-10-15): with `WCCF_PICTURES_DIR` (play.py, seat 1, only while `data\english_pictures\` has some) the hook loads english.py's pictures, each named by Sega's picture (size + FNV-1a 64), and hooks D3DX's `D3DXCreateTextureFromFileInMemoryEx`: when the game hands over exactly that Sega picture it gets the English one; refused by D3DX = Sega's own. The game's files are never changed |
| `patience.h` | the link to the server waits out an internet outage (2026-10-16, GROPS's Error 3000 mid-match): TCP_MAXRT 100 s on the game's link at both ends (the game's connect, the server's accept), the game's "30 s without CONTROL_STATE = Error 3000" raised to 120 s (client_Release.exe 0x004072F4) and the server's "cut a seat after 12 missed KEEP_ALIVE ticks, TRUNCATION at 11" raised to 40 / 39 (control_Release.exe 0x0042CDB8, 0x0042CE16); the projector's own 30 s timer raised to 120 s as well (2026-10-17, client_Release.exe 0x00600FCF, checked with its neighbours from 0x00600FCC) - in memory, only on Sega's exact bytes. Measured on the kit: `.work\research\link_patience\` (outside the repo) |
| `test_patience.c` | not shipped: `patience.h` on its own - each limit raised only on Sega's exact bytes and never half, Windows takes the waiting time on a real socket (check.ps1 runs it) |
| `test_pictures.c` | not shipped: `pictures.h` on its own - the fingerprint against FNV's published values (english.py's is checked against the same), names, a folder with good and bad files, only Sega's exact bytes swapped (check.ps1 runs it) |

## Careful
- Keep the log line `mxhook attached` (it was named mxhook.c): setup.py recognises its own hook by it.
- The JVS mark patch changes the game's code in memory only (never the exe on disk): seat 1's exe and its English copy
  keep their checked hashes. Its log line ("JVS: failed polls can no longer switch the buttons off") is in each
  client's `data\logs\hook\mxhook_<pid>.log`.
- The name `wccfk.dll` must stay at most 9 characters: setup overwrites `WINMM.dll` in the game's import in place.
- The whole-messages change (#35) removes the most likely cause of the server crash (Sega's code for joining a message
  that arrived in pieces); the crash was never made to happen on purpose, so it is not a proven fix. The server's
  keeper (restart within a minute) stays the safety net.
