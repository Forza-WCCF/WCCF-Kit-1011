# code\ - the kit's own programs, written in Python

PLAY.exe and SETUP.exe run the files here with the kit's own Python (`python\python.exe`). That Python finds this
folder through `python\python313._pth` - the only place that names it.

| File | What it does |
|---|---|
| `play.py` | starts and stops the game: the server, the projector, seat 1 and every stand-in (PLAY.exe runs it) |
| `setup.py` | sets the game folder up for the kit, repairs it, and undoes it (SETUP.exe runs it) |
| `english.py` | puts the game's English in place, or Sega's Japanese back (SETUP.exe's ENGLISH / JAPANESE); also draws the "memory" pictures into `data\english_pictures\` (the bar's "please wait for the next match"), which seat 1's hook hands the game as it loads Sega's (`source\hook\pictures.h`) |
| `kit_common.py` | what everything shares: the kit's folders (`K.KIT`, `K.DATA`, `K.CACHE` ...), the settings file, the game folder |

| Folder | What is in it |
|---|---|
| `cards\` | club cards and the card catalogue |
| `hardware\` | the arcade cabinet's parts, faked on a PC |
| `online\` | joining someone else's server |
| `server\` | running a server for other players |
| `helpers\` | small helpers: the panel's helper, the starting volumes, the console, the hook's name in the game |

## Careful
- Import across folders by folder name: `from cards import wallet`. The folders are plain Python folders.
- Never find the kit by counting folders up from a file - use `kit_common` (`K.KIT`, `K.DATA` ...). Three files did,
  and pointed at the wrong place when they moved one folder deeper (2026-10-11).
- Nothing is written into `code\` while the kit runs: live files go to `data\`.
- After any change run `source\check.ps1`: `source\test_imports.py` imports every file here the way the launchers
  do, and checks every import line, also the ones inside functions.
