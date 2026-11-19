# code\helpers\ - small helpers the rest of the kit uses

| File | What it does |
|---|---|
| `panel.py` | the panel's helper: does what the in-game panels ask for and cannot do from inside the game - RESTART NOW, the CLUB CARD view, SEND LOGS, the starting volumes, and online each save of the club card to wccf.online - and of the new card a manager transfer puts beside it, so the card its first match earns is shown - then the cards on the table (seat 1 beside WCCF_GAME's folder) for the account's profile, and online brings the projector back when it has lost the server (play.py projector; never one the player closed) and does SETTINGS' OPEN / CLOSE PROJECTOR (a press during a restart waits for it) (play.py starts it) |
| `sound.py` | the game's starting volumes - the projector muted, seat 1 very low - set once each, then left to the Volume Mixer |
| `console.py` | switches off QuickEdit in a console window: a click there would freeze the program writing to it (it froze the server once) |
| `hook.py` | renames the game programs' import of `WINMM.dll` to the kit's own `wccfk.dll`, and back (setup.py, english.py) - the antivirus fix |
| `defender.py` | setup's Windows Defender step: with the player's Yes to Windows' own prompt, the game's folders (extracted\, seat1\, misc\ - never one above) are left out of Defender's scans, so its machine learning cannot delete the changed game program as a "trojan" (it did, 2026-11-18); undo puts them back; `data\defender.json` remembers; nothing is asked where Defender is not the antivirus (or under Wine) |

## Careful
- `panel.py` takes `data\` and `PLAY.exe` from `kit_common` - play.py starts it with neither, so that is what runs.
- `hook.py` is a pure byte swap and must stay reversible: `setup.py undo` gives back Sega's exact files.
  `source\test_patch_hook_import.py` covers it.
- `defender.py` never asks Windows anything in a test: `source\test_defender.py` sets its `runner` to a stand-in.
  Its undo touches only the folders of the game being undone (test_setup_state undoes a scratch game).
