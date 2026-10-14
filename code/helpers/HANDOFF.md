# code\helpers\ - small helpers the rest of the kit uses

| File | What it does |
|---|---|
| `panel.py` | the panel's helper: does what the in-game panels ask for and cannot do from inside the game - RESTART NOW, the CLUB CARD view, SEND LOGS, the starting volumes, and online each save of the club card to wccf.online (play.py starts it) |
| `sound.py` | the game's starting volumes - the projector muted, seat 1 very low - set once each, then left to the Volume Mixer |
| `console.py` | switches off QuickEdit in a console window: a click there would freeze the program writing to it (it froze the server once) |
| `hook.py` | renames the game programs' import of `WINMM.dll` to the kit's own `wccfk.dll`, and back (setup.py, english.py) - the antivirus fix |

## Careful
- `panel.py` takes `data\` and `PLAY.exe` from `kit_common` - play.py starts it with neither, so that is what runs.
- `hook.py` is a pure byte swap and must stay reversible: `setup.py undo` gives back Sega's exact files.
  `source\test_patch_hook_import.py` covers it.
