# source\ - how every program is made, and the checks

The source of every compiled program the kit ships, the scripts that build, check and package the kit, and the tests.

| File | What it does |
|---|---|
| `README.txt` | how each program is built, command by command |
| `build.ps1` | builds every program into its place: the C programs (32-bit, Microsoft's compiler) and the launchers (Rust) |
| `check.ps1` | every check that needs no game - CI runs it on every push; run it after any change |
| `crashme.c` | not shipped: a program that crashes at once, for `test_crash_dump.py` (built into `build\`) |
| `package.ps1` | makes the kit ZIP the way players get it, in `dist\` |
| `test_account.py` | the wccf.online sign-in against a fake website: a code, the approval, the token saved and never printed, reused, replaced when refused, the website down; seat.py's TOKEN suffix |
| `test_card_fix.py` | a missing club-card helper file never stops a start |
| `test_crash_dump.py` | a crash leaves a lean and a full memory snapshot in `data\dumps` (crashme.exe under the real launcher) |
| `test_ended.py` | play.py's choice when a game window's launcher ends (a closed cabinet window stops the rest, the projector's alone stops nothing), and when a run went wrong (the automatic report) |
| `test_projector_keeper.py` | the panel helper's rule for the online projector (helpers\panel.py keep_projector): a lost link restarts it after 10 / 30 / 60 s, at most 3 times until a link holds 10 min; a projector whose window the player closed is never brought back |
| `test_projector_restart.py` | play.py's projector restart, OPEN and CLOSE against a scratch running.json and stand-in processes: the card session's start stays, a reused pid is never ended, no second projector beside one that will not end, a projector the player closed is not reopened by the automatic restart; projector and cabinet restarts wait for a stop under the run lock, then leave an ended or replaced run alone; a normal or legacy cabinet restart keeps the projector |
| `test_english_pictures.py` | English writing in the game's pictures: added at the archive's end, taken back out byte for byte (peakx, #29); the "memory" pictures: the fingerprint (FNV-1a 64's published values), the DXT5 writer, the wait line drawn as Sega's kind and size of picture with its mirror, the archive untouched, the folder on and off |
| `test_graphics_env.py` | SETTINGS > GRAPHICS' NEXT START rows: panel.txt's `msaa=` / `shadows=` / `motion_blur=` reach the hook as `WCCF_MSAA` / `WCCF_SHADOWS` / `WCCF_MOTION_BLUR`, valid values only (no `resolution=`) |
| `test_handoffs.py` | every folder has a HANDOFF.md that names every file in it |
| `test_hold_projector.py` | the seat desk keeps the projector box out of the game until a player is in it |
| `test_icc_reader.py` | the card reader's saving and recovery (a busy file never half-writes the card) |
| `test_imports.py` | every file in `code\` imports the way the launchers run it |
| `test_italian_tables.py` | the Italian keeps every printf and colour code of the English, in the game's font (peakx, #30) |
| `test_link_close.py` | the panel's server link watch: a link lost while the game runs is written LOST (the automatic report), the link the game drops after the player closed it is not (fakegame.exe and a listener on 127.0.0.1:20002) |
| `test_log_archive.py` | the run before last is zipped into the archive, never just deleted |
| `test_old_layout.py` | a kit updated from before kit 6 is tidied: old folders, catalogue moved |
| `test_patch_hook_import.py` | the game's import renamed to `wccfk.dll` and back (the antivirus fix) |
| `test_projector_relay.py` | the projector relay between a fake control and fake projectors: INIT answered by the relay, control reached only once a player is in and with 8 seats, a KEEP_ALIVE per CONTROL_STATE, a request sent once and its reply to all, a late joiner's replay in control's order (INI before frames), a stalled projector shed without slowing the other, a stuck one cut, a bad message cut, control let go with the last projector; bad batches, floods, a control that reads nothing, stale sessions, leave/join and connect races, same-name requests, the replay's order, a new match's INI (2026-10-17 review) |
| `test_relay.py` | a live seat cannot be taken over by another address; the same address on a new port takes its seat at once |
| `test_io_board.py` | the I/O board stand-in on a real pipe, the test in the game's place: while a write of the outputs file hangs 2 s every answer still goes out at once (the old stand-in held one for 2,003 ms), a key press reaches the answers, a held-up answer with requests waiting is logged SLOW, the last line is written before it ends |
| `test_server_conf.py` | the server's settings file: the random-pairing line (`MATCHING_PARA_FM1`) with a value that pairs any two real clubs and never a DREAM TEAM club with one, an older kit's file (kit 7's FM1=20000 too, also with play.py's `WAIT_PROJECTOR`) replaced without a copy, a hand edit kept |
| `test_dream_team.py` | DREAM TEAM: the panel's DREAM TEAM and `remote ADDRESS dream` start it, its programs get `WCCF_DREAM_TEAM=1`, its seat request carries no sign-in even on a signed-in PC, running.json says so, RESTART NOW keeps the cabinet alone only while DREAM TEAM stays DREAM TEAM |
| `test_rotate_logs.py` | a log file held open never stops a start |
| `test_seat_desk_game.py` | the seat desk never gives a seat that is in the game; the RELAY word gets the projector relay's port |
| `test_online_club.py` | the online club: the owned cards make the CATALOGUE (only those, each once), the list kept for when the website is down, refused / unknown / empty answers play with the slot card, a new club's cards laid out on the table, formation finds the online board, play.py's run record and environment carry it |
| `test_seat_desk_signin.py` | the seat desk with the wccf.online sign-in: optional or needed (data\require_signin.txt), a good / refused token, the website down, seat.py signed in, an older desk that does not know TOKEN (seat.py asks again without it), no token in the log |
| `test_seat_lease.py` | the seat lease reconnects and asks for the same seat after a break |
| `test_send_logs.py` | SEND LOGS packs and sends, the inbox keeps, and both refuse what they must |
| `test_setup_state.py` | what a start needs; a game an older kit set up is set up once |
| `test_setup_kit_english.py` | SETUP on a game another copy of the kit made English: the kit's English or Italian found in client_Release.exe, so SETUP says so instead of "not Rev D" |
| `test_witness.py` | the server's witness (a card per finished match): who sat where (leases.json, a seat freed a moment ago, one address with two accounts), what goes to the website (a session's start, each match's start, its end), refusals, out of reach and tried again, files to done\ and never sent twice, the secret in no line, no secret = not started |
| `test_take_seat.py` | the seat an online PC takes from the seat desk's answer, and where its projector connects (control, the server's projector relay, or none) |
| `test_wallet_transferred.py` | after a manager transfer the old card shows as transferred |
| `test_club_links.py` | the club card's links reach the CLUB CARD view (from 151, the game's pair order), for the FORMATION board's lines |

| Folder | What is in it |
|---|---|
| `hook\` | the kit's hook in the game (`programs\wccfk.dll`) |
| `panel\` | the panel around the game (`programs\wccfpanel.dll`) |
| `card_table\` | the card-table helper (`programs\FPR_Emu.exe`) |
| `launcher\` | PLAY.exe and SETUP.exe (Rust) |
| `build\` | made by build.ps1 - the compiler's leftovers and the test game window; not in git |

## Careful
- Rust (`cargo`) is not installed on Ali's PC: the launchers are built and checked only by CI.
