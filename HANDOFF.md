# WCCF 2010-11 kit - root HANDOFF

The front door for a developer. (Players read `README.txt`.) Each folder has its own `HANDOFF.md`, naming every file
in it - `source\test_handoffs.py` (check.ps1) fails when one does not. The HANDOFFs are in git, not in the players'
ZIP (`.gitattributes`). `programs\` and `data\` are made on the player's PC, so they are described here instead.

## What the kit is

Community tools that make a player's own copy of WCCF 2010-11 (Rev D) - a 2010 Sega arcade football game, 32-bit
Windows programs `client_Release.exe` (cabinet / projector), `control_Release.exe` (server), `match_Release.exe`
(match engine) - run on one Windows PC, and play online on a shared server. The kit stands in for the arcade
cabinet's hardware, starts everything, draws the panels around the game, and connects players. **None of Sega's
files ship.** SETUP builds whatever it needs from the player's own copy of the game.

## The folders (each has its own HANDOFF.md)

| Folder | What it holds |
|---|---|
| `PLAY.exe` `SETUP.exe` | the launchers (Rust). PLAY starts/stops the game; SETUP sets up the game folder, language, and kit updates |
| `programs\` | the compiled programs: the in-game hook (`wccfk.dll`), the panel (`wccfpanel.dll`) and the card-table helper (`FPR_Emu.exe`) |
| `art\` | the panel's picture (`skin.tex`) |
| `data\cache\` | the catalogue + card pictures SETUP makes from the player's own game (made again if deleted) |
| `data\bank\` | a hosting PC's own card bank (`code\server\card_bank.py`): its accounts, owned cards and club cards (sqlite; passwords and tokens hashed) and the server's name + secret for its witness. Never sent with SEND LOGS |
| `data\accounts\` | this PC's sign-in to each other server's card bank, one file each (wccf.online's stays `data\account.json`); the online clubs are in `data\save\online\` beside it, one folder per bank |
| `data\keeper\` | the host's keeper (`PLAY.exe keeper on`, `code\server\keeper.ps1`): its log, `server.wanted` while this PC hosts, the logs of each crash |
| `data\dumps\` | memory snapshots of crashes (debugger.py; newest 5 lean + 5 full) - the lean ones go with SEND LOGS and the automatic report |
| `languages\` | one folder per language - `languages\english\`: the English translation tables (text + fingerprints of Sega's files; no Sega file) |
| `python\` | an embedded Python so players install nothing |
| `code\` | the kit's Python. At the top, the four a person runs or everything shares: `play.py` (start/stop), `setup.py`, `english.py`, `kit_common.py`. Then `cards\` (club cards, the catalogue), `hardware\` (the cabinet's parts, faked on a PC), `online\` (joining a server), `server\` (running one for others), `helpers\` (the panel's helper, sound, the hook's name in the game) |
| `source\` | the source of every compiled program (`hook\`, `panel\`, `card_table\`, `launcher\`), the build/check/package scripts, the tests, and wccf.online's own card code for reading (`website\`) |
| `data\` | the player's own: settings, keys, the club card and other clubs, logs, runtime state, `cache\`, `english_backup\` (Sega's original files while English is on - never a cache) |
| `docs\` | the redesign's plan and the research notes - not in the players' ZIP |

## How a start works (the short version)

`PLAY.exe` -> `code\play.py`. It starts, in order: the scene service, the server or an online seat, the
projector, the cabinet's stand-ins (keychip, card reader, I/O board), the cabinet (`client_Release.exe`) with the
hook and the panel, and the key driver. The game loads the hook (`programs\wccfk.dll`, placed in the game's folder
by SETUP, which also renames the game's import to it) - the hook stands in for the cabinet hardware and loads the
panel. Closing the cabinet's window ends the whole run; closing the projector's stops nothing else. Online, a
projector that lost the server is started again by the panel helper (`helpers\panel.py` ProjectorKeeper, `play.py
projector`), and SETTINGS' OPEN / CLOSE PROJECTOR asks the helper for `play.py projector open|close`. Stops, the end
of a run, RESTART NOW's cabinet restart and the projector's restarts take `data\run.lock` in turn: each reads
`data\running.json`, ends or starts programs and writes it back alone.

## The redesign

A full clean-up is underway. The plan, the target layout, and the one-by-one worklist are in
`docs\REDESIGN.md`. Read it before working on the redesign. The audit that started it is at
`.work\audit\KIT-AUDIT.md` (outside the repo).

## The rules that do not bend

- The repo is the source of the shipped kit; CI builds it; a release is cut only after a real-game test.
- Never break what players and the live server are running. Big moves land whole, never half.
- `data\` is the player's - UPDATE never writes it.
