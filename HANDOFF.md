# WCCF 2010-11 kit - root HANDOFF

The front door for a developer. (Players read `README.txt`.) Each folder has its own `HANDOFF.md`; this is the root.

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
| `languages\` | one folder per language - `languages\english\`: the English translation tables (text + fingerprints of Sega's files; no Sega file) |
| `python\` | an embedded Python so players install nothing |
| `code\` | the kit's Python. At the top, the four a person runs or everything shares: `play.py` (start/stop), `setup.py`, `english.py`, `kit_common.py`. Then `cards\` (club cards, the catalogue), `hardware\` (the cabinet's parts, faked on a PC), `online\` (joining a server), `server\` (running one for others), `helpers\` (the panel's helper, sound, the hook's name in the game) |
| `source\` | the source of every compiled program, the build/check/package scripts, and the tests |
| `data\` | the player's own: settings, keys, the club card and other clubs, logs, runtime state |

## How a start works (the short version)

`PLAY.exe` -> `code\play.py`. It starts, in order: the scene service, the server or an online seat, the
projector, the cabinet's stand-ins (keychip, card reader, I/O board), the cabinet (`client_Release.exe`) with the
hook and the panel, and the key driver. The game loads the hook (`programs\wccfk.dll`, placed in the game's folder
by SETUP, which also renames the game's import to it) - the hook stands in for the cabinet hardware and loads the
panel. Closing the game window ends the whole run.

## The redesign

A full clean-up is underway. The plan, the target layout, and the one-by-one worklist are in
`docs\REDESIGN.md`. Read it before working on the redesign. The audit that started it is at
`.work\audit\KIT-AUDIT.md` (outside the repo).

## The rules that do not bend

- The repo is the source of the shipped kit; CI builds it; a release is cut only after a real-game test.
- Never break what players and the live server are running. Big moves land whole, never half.
- `data\` is the player's - UPDATE never writes it.
