# source\ - how every program is made, and the checks

The source of every compiled program the kit ships, the scripts that build, check and package the kit, and the tests.

| File | What it does |
|---|---|
| `README.txt` | how each program is built, command by command |
| `build.ps1` | builds every program into its place: the C programs (32-bit, Microsoft's compiler) and the launchers (Rust) |
| `check.ps1` | every check that needs no game - CI runs it on every push; run it after any change |
| `package.ps1` | makes the kit ZIP the way players get it, in `dist\` |
| `test_card_fix.py` | a missing club-card helper file never stops a start |
| `test_ended.py` | play.py's choice when a game window's launcher ends (a closed window stops the rest) |
| `test_handoffs.py` | every folder has a HANDOFF.md that names every file in it |
| `test_hold_projector.py` | the seat desk keeps the projector box out of the game until a player is in it |
| `test_icc_reader.py` | the card reader's saving and recovery (a busy file never half-writes the card) |
| `test_imports.py` | every file in `code\` imports the way the launchers run it |
| `test_log_archive.py` | the run before last is zipped into the archive, never just deleted |
| `test_old_layout.py` | a kit updated from before kit 6 is tidied: old folders, catalogue moved |
| `test_patch_hook_import.py` | the game's import renamed to `wccfk.dll` and back (the antivirus fix) |
| `test_relay.py` | a live seat cannot be taken over by another address |
| `test_rotate_logs.py` | a log file held open never stops a start |
| `test_seat_desk_game.py` | the seat desk never gives a seat that is in the game |
| `test_seat_lease.py` | the seat lease reconnects and asks for the same seat after a break |
| `test_send_logs.py` | SEND LOGS packs and sends, the inbox keeps, and both refuse what they must |
| `test_setup_state.py` | what a start needs; a game an older kit set up is set up once |
| `test_take_seat.py` | the seat an online PC takes from the seat desk's answer |
| `test_wallet_transferred.py` | after a manager transfer the old card shows as transferred |

| Folder | What is in it |
|---|---|
| `hook\` | the kit's hook in the game (`programs\wccfk.dll`) |
| `panel\` | the panel around the game (`programs\wccfpanel.dll`) |
| `card_table\` | the card-table helper (`programs\FPR_Emu.exe`) |
| `launcher\` | PLAY.exe and SETUP.exe (Rust) |
| `build\` | made by build.ps1 - the compiler's leftovers and the test game window; not in git |

## Careful
- Rust (`cargo`) is not installed on Ali's PC: the launchers are built and checked only by CI.
