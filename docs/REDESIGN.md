# Kit redesign - the plan (started 2026-10-11)

Ali, 2026-10-11: "i want to redesign the whole kit, it feels so messy and unclean ... definitely new folder
layout, and in each folder there should be an accompanying handoff file ... lets get to work one by one, and fix
all the issues."

This file is the blueprint and the worklist. It is the durable record every session reads before touching the
redesign. Grounded in the audit at `.work\audit\KIT-AUDIT.md` (read-only, commit f89eebe); findings are referenced
by their audit tags (A1, B3, D10 ...).

## The rules this redesign runs under

- **Never break what players and the server run.** The GitHub repo is the source; CI must stay green; a release is
  cut only after a real-game test. The physical folder move is "stop the world" - it must not land half-done.
- **One thing at a time, each its own small PR/commit, tests passing before the next** (bunyan marsus).
- **Every behaviour is kept** unless it is dead code (audit section E) - the move merges duplicates, it does not
  drop features.
- **A 9-year-old must be able to figure it out** (Ali, 2026-10-11: "i want the organization to be so simple a 9
  year old can figure it out naming wise, and structure wise"). Plain-English folder and file names, no jargon;
  the structure obvious at a glance. Applies to the folder move (Phase 3). Draft plain names (Ali reviews before
  the move):
  - `programs\` (the compiled helpers - was `bin\`), `art\` (skin + English words - was `assets\`), `python\`,
    `code\` (the kit's Python, one job per file - was `kit\`), `data\` (your club cards, keys, settings, logs - kept;
    everyone knows "data"). Inside `code\`: plain names like `paths.py files.py settings.py running.py` (what is
    running - was `procs`), `cards\ game\ online\ server\ setup\ hardware\` (the cabinet stand-ins - was `standins`).
  - The hook DLL is `wccfk.dll` for now (must be <= 9 chars to rename in place, and not a Windows name); a clearer
    name is open for Ali.
- **Each folder gets a `HANDOFF.md`** (Ali's ask): what the folder is, one line per file, what depends on it, what
  is fragile. Root `HANDOFF.md` is the kit's front door for a developer. (Open question for Ali: whether the
  HANDOFF files ship in the player ZIP or are kept out by `.gitattributes` like `docs\`. Default: keep them in the
  repo, out of the ZIP.)

## Coordination

Ali's order (2026-10-11): "we can rework peakx's work and make it better, and make it work with the new design,
this is not a question its an order." So the redesign is NOT blocked on the 7 open PRs (#28-#35). peakx's content
(English, Italian translations) is kept and folded into the new `assets\english\` layout; the plumbing PRs
(settings, CI, winmm version info) are reworked onto the new design. The redesign proceeds at full speed.

Still true and non-negotiable: **never break what players and the live server run.** Work stays incremental (one
module/fix at a time, CI green, real-game test before any release) - that is a safety rule, not a coordination one.
We start with the most dangerous player bugs (A1-A9) because a half-fixed card bug can destroy a player's club card.

## Target layout (from the audit's F4, refined as we go)

```
WCCF-2010-11-kit\                     what a player unzips
  PLAY.exe  SETUP.exe
  README.txt  CHANGELOG.md  version.txt  files.txt  HANDOFF.md
  bin\                                every compiled program, each with version info
    winmm.dll  (-> kit-named hook, B item 4 / Defender fix)   device stand-ins, serial bridge, network, logowin, panel loader
    wccfpanel.dll                     the in-game panel (moved here from overlay\)
    FPR_Emu.exe                       the card-table helper
  assets\
    skin.tex                          the panel's art (from overlay\)
    english\*.tsv                     the translation tables (from english\)
  python\                             embedded Python + Pillow (unchanged)
  kit\                                the Python code, one job per module
    paths.py                          every folder, file name, port, limit (D13, D14)
    files.py                          write-a-file-whole (one retry rule, D10), read key=value, read JSON
    procs.py                          find/stop programs by full path, a program's windows (D8, D9)
    settings.py                       ONE settings file + request files (D3)
    card\     format.py schema.py store.py decode.py edit.py wallet.py boards.py view.py   (D1, D2, D5)
    run\      play.py cabinet.py game.py server_guard.py gamemem.py logs.py                (B3, A3, A4, A9, D20)
    standins\ keychip.py card_reader.py io_board.py scenes.py keys.py helper.py sound.py
    online\   seat_lease.py send_logs.py                                                    (A5)
    server\   seat_desk.py relay.py log_inbox.py                                            (A6)
    setup\    setup.py patches.py catalogue.py english.py                                   (D16)
  data\                               the player's own; never shipped, never written by UPDATE
    settings.txt  keys.txt
    save\                             club card, other clubs, backups, tables
    logs\                             every log of the kit
    run\                              running.json, lease, key-driver files, view, requests - safe to delete (F3)
    cache\                            catalogue.tsv, cards\, english_backup\ - made by SETUP
source\  tests\                       in the repo only
```

`wccfpanel.c` (6,069 lines) splits into files compiled into the same DLL: hook, draw, board, catalogue, keys,
settings, clubcard, deal, net, money, gamefix.

## The worklist - one by one

Status: [ ] not started  [~] in progress  [x] done (PR #)

### Phase 1 - player safety, in the current files (no file move, conflict-free)
- [x] A1  wrong-size card no longer locks the player out: a NEW card is served, the bad file kept as .bad (`open_card`). Still to do: name the log in play.py's failure, keep refusal lines in a real log (play.py side)
- [x] A2  card save never writes in place; keeps the newest image in memory and retries (`_flush`, `retry_saves`) + `source\test_icc_reader.py` (14 checks) - the reader's first test
- [x] A3  no 12-hour kill: player `LIFE` is now a 32-day backstop; a run ends when its window closes (watch.rs). play.py docstring updated
- [x] A4  seat fallback only on "no broker" (`_seat_decision`, tested); waits 25 s (> the lease's 16 s worst case); the lease pid is tracked at once so a stop always cleans it up. `source\test_take_seat.py` (10 checks)
- [x] A5  the seat lease reconnects and re-claims its seat (WANT SEAT n) after any break; retries through a desk restart. `source\test_seat_lease.py` (4 checks, a fake desk)
- [~] A6  the relay now rejects a seat claim from a different address while the owner is live (`claim`, `source\test_relay.py`, 10 checks) - stops internet hijacking of a live match. THE FULL desk-issued token (also covers the pre-match race and two-behind-one-router) is deferred to the online\ rebuild: it needs the desk, the lease, the overlay (C) and a coordinated client update
- [x] A7  the panel's close warning AND the RESTART gate now check BOTH cards (`any_session_open` in wccfpanel.c), matching play.club_session - no silent bad ending on the manager-transfer club. Panel DLL builds clean; CI runs the panel self-test. (The RESTART hint text at line ~3656 and the club-switch at ~4257 still read the slot card only - fold into D5, one session rule; the panel session logic still has no unit test - G)
- [x] A8  SW1/SW2 have no default key (both the Python driver ACTIONS and the C KEYS panel g_kact set to 0); KEYS can still give one. Key self-test 96/96 + a new A8 check; panel DLL builds clean
- [x] A9  log rotation never stops a start: a busy `previous` is set aside with a timestamp, a busy current log is left in place (`rotate_logs`). `source\test_rotate_logs.py` (4 checks)
- [~] A10 smaller lock-outs: [x] catalogue-missing no longer blocks a start (`setup_state`, `source\test_setup_state.py`). Left: the 17th club (wccfpanel.c panel reads <=16 clubs), SEND LOGS to the right server (folds into D3), UPDATE SHA-256 check (Rust launcher), the projector-box hold-file edge (server)

### Phase 2 - cheap antivirus wins (small, mostly conflict-free)
- [x] B2e removed the screenshot-to-disk dumps (wccfpanel_frame.bmp, wccfpanel_atlas.bmp); B9 removed the dead tasklist in _xscn_watch.py; B11 added overlay\inject.exe + bin\logowin.exe to SETUP's LEGACY cleanup. Panel builds clean. LEFT: B2a (Present/Reset trampoline execute-only, not RWX)
- [ ] B1g version info in winmm.dll / wccfpanel.dll / FPR_Emu.exe (build.ps1 + package.ps1 check) - may already be in flight
- [ ] B3  run cabinets and the projector without the debugger; keep it for control only
- [x] B(4) stop impersonating winmm - the hook ships as `wccfk.dll` and SETUP renames the game's import to it. DONE and proven: `patch_hook_import.py` (pure reversible swap, `normalized()`); `winmm_fwd.h` 3 forwarders to real winmm; `build.ps1`/`package.ps1` ship `bin\wccfk.dll`; `setup.py` (norm_sha fingerprints, rename client/control/match, place wccfk.dll, undo un-renames, drop winmm_orig); `english.py` (hook preserved through on/off, backups in Sega WINMM space). Tests: `test_patch_hook_import.py` 12 (CI, synthetic PE); local proofs on the REAL Sega exes: `prove_on_real_exes.py`, `prove_setup_rename.py`, `prove_english_hook.py` all GREEN. STILL TO DO before a kit ships: a real game START (test kit `play.py local`, then Ali's kit) confirming the renamed exes launch + Defender clean. (Note: the redesign's mxhook lacks the whole-messages server fix - merge that in when redesign lands.)

### Phase 3 - the physical move  (IN PROGRESS, one folder per commit, CI-green each)
- [x] `scripts\` -> `code\` (commit d4025f6, CI green): Rust launchers, check.ps1, every test, docs updated; kit_common uses __file__ so no path constant changed.
- [x] `bin\` -> `programs\` (commit 175014c, CI green): the hook + card-table helper build there; build.ps1/package.ps1/kit.yml/.gitignore follow; kit_common constant is PROGRAMS. The PANEL still builds to overlay\ (moves in the overlay step).
- [x] `overlay\` split (commits 2561229, 39623e7, 172f419; CI green). VERIFIED BY A REAL START: CI's kit ZIP laid over the test kit (a hand-unzip over 5.x), `code\setup.py` (catalogue + 3927 pictures moved, old scripts\ bin\ overlay\ removed), `code\play.py local`: seat 1 loaded wccfk.dll + programs\wccfpanel.dll, panel log "skin ...\art\skin.tex", "catalogue ...\data\cache\catalogue.tsv - 3909 cards", card pictures on the board. That run also found python313._pth still saying ..\scripts (fixed; check.ps1 now imports through the _pth alone) and old scripts\ never emptying (runtime files; fixed). Notes from the build: panel -> `programs\wccfpanel.dll`, skin -> `art\skin.tex`, catalogue + cards -> `data\cache\`. The panel finds them through WCCF_SKIN / WCCF_CATALOGUE / WCCF_CARDS (play.py `kit_env`), else beside itself (`our_file`; its version.txt and data\ stay one folder up - same depth). `setup.tidy_old_layout` moves an older kit's catalogue + cards and removes its scripts\ bin\ overlay\ leftovers (`source\test_old_layout.py`, 7). check.ps1 passes locally incl. the panel self-test (86) from programs\. LEFT: CI, and a REAL GAME START on the test kit (panel draws its skin + catalogue from the new places; its log line names both paths).
- [x] A kit unzipped by hand, or updated with "set up" declined, still had 5.x's winmm.dll in the GAME folder: `play.ensure_hook` (fresh starts only - nothing running) runs setup.py once when the game or seat1\ has no wccfk.dll, then starts; if setup fails it stops and names SETUP.exe. test_setup_state.py 8 (checked to fail when the check is broken). VERIFIED: CI's kit 62b99a9 over the test kit with seat1\wccfk.dll removed - play.py local ran setup once (hook back, old english\ removed) and started 6/6; seat 1 loaded wccfk.dll + programs\wccfpanel.dll.
- [x] `english\` -> `languages\english\` (Ali's choice 2026-10-11, over art\english\: one folder for every language - peakx's #30 adds italian\, which goes to languages\italian\ when reworked). english.py ENG = K.LANGUAGES\english; tidy_old_layout removes an old english\'s copies (test_old_layout 8). VERIFIED: CI's kit (62b99a9) over the test kit; english.py check built 7178 lines with the old english\ already removed.
- [x] `data\`: NOT regrouped into own\ / run\ - a played kit's data\ is already plain (save\ logs\ english_backup\ cache\ + 4 small files, seen in Ali's kit 2026-10-11); moving running.json / english_backup would touch the panel (C), SETUP (Rust) and every old kit's files for no clearer result. english_backup is Sega's original files, not a cache: it stays. DONE instead: nothing is written into code\ any more - the key driver's live files (_jvs_seat1_input/outputs.txt) are in data\ (_keys_seat1.RUN, play.KEYS_INPUT); check.ps1 asserts play.py, the key driver and the I/O board name the same file (play's stop guard reads the card state from it) - checked to fail on the old path
- [x] `code\` in plain folders with plain names (Ali chose "folders + plain names" over folders-only or flat): top = play.py setup.py english.py kit_common.py; `cards\` catalogue formation view wallet decode edit schema codes unpack; `hardware\` card_reader io_board keyboard scenes network debugger; `online\` seat send_logs; `server\` seat_desk relay log_inbox; `helpers\` panel sound console hook (commits 9044fb2 1064660 35f77c9 b5834d5 60683ab). Folders are plain Python folders (`from cards import wallet`), found through python313._pth. Caught on the way: three files that found the kit as "N folders up from this file" (send_logs, the key driver, the panel helper - the last two in every real run); old scripts\ now recognised by the 27 names kits 5-5.5.1 shipped. New guard: `source\test_imports.py` (every file imports through the _pth; every import line incl. inside functions resolves; no bad escapes). Proven equal to before the move: catalogue + 3927 pictures byte for byte, the decoder's JSON on a real card. Log file names unchanged (the server's tools read them). VERIFIED with CI's kit (dd23fbc, ZIP af17138) laid over the test kit: all 9 roles alive, each from its new path (hardware\scenes, debugger x3, network, card_reader, io_board, keyboard; helpers\panel); the key driver's live files in data\, nothing written into code\; the full card cycle - I = in (the stop guard refused to stop), the game read the club, the game ejected it (auto-eject) = out, session closed. (This also verifies the earlier live-files move, 0089fda.)
- [ ] THE SERVER'S NEXT UPDATE: Azure runs the kit 5 file names (_seat_broker.py, _relay.py, _log_inbox.py, _debug_launch.py ...) and its keeper may name them - check the keeper and its tasks before putting kit 6 there; never while players are on.
- [x] `source\` folders named for what they build: `hook\` (mxhook.c -> wccfk.c), `panel\`, `card_table\` (7d9d3f6). The hook still logs "mxhook attached" (setup recognises it) and names its logs mxhook_*.log.
- [x] A HANDOFF.md in every folder (16 + the root; e9a9cdb): one plain line, one line per file, what is fragile. `source\test_handoffs.py` fails when a folder has none or a file has no line (checked). In git, out of the players' ZIP (`.gitattributes`).
- [x] Test builds say which kit they lead to: `KIT 6-test-<commit>` (kit.yml `$next = '6'` - Ali: "not 5.6 but kit 6"); a release tagged kit-6 says `KIT 6`. release.rs reads it as a test build of 6 (tests in CI). a77cd41.
- [x] peakx's six open PRs reworked onto the redesign (his commits replayed, his authorship kept): #28 English full names + last 22 lines, #29 English in the game's pictures, #30 ITALIANO (languages\italian\), #31 version information in wccfk.dll / FPR_Emu.exe / wccfpanel.dll (paths mapped to programs\, the hook's description and the card table's corrected), #32 crates cached in CI + server checks side by side (checked: a failing one still fails the run, by name), #34 the version beside the SETTINGS title. Adapted: english.py reads languages\<folder>\ and imports cards.catalogue / cards.unpack; his tests put code\ on the path. On the way my CHANGELOG resolver dropped ten of our entries (#29) - restored verbatim (f30dd37), the resolver now refuses loose lines on either side. Checked: check.ps1 all green; english.py check builds 7200 lines + 11 pictures in English and in Italian on a real game. His PRs on GitHub stay open until Ali decides how to close them.
- [x] REAL START with CI's kit (kit-6-test-a2a79ec): the label reads KIT 6-test-a2a79ec. #29's pictures BROKE THE CARD: with them in the archive the game gave the club card straight back, every try (Ali saw it too: "when i click on card it doesnt take the card in"). Bisected on the test game: Japanese - card read; English text without the pictures - card read, club screen in English; English with the pictures - card refused. So english.py's PICTURES is off by default (WCCF_PICTURES=1 to test a fix; test_english_pictures asserts the default); CHANGELOG/README/HANDOFFs say the pictures stay Japanese. No public kit ever held them (no tag contains #29). For peakx: the club screen loads SCM_Parameta*.dds right after the read.
- [x] The server fix (#35, whole messages) merged into source\hook\ (0c9dfde): wholemsg.h + test_wholemsg.c moved in by git, build.ps1 builds the test, check.ps1 runs it (18/18). REAL TEST on this PC with the merged hook: the server's hook log "whole messages: ON"; split_sender.py's 10 batches cut into pieces - 10 given whole after 160 waits, exactly 37 bytes of garbage skipped, the sender stayed connected, the server and both cabinets kept running (same numbers as the PR's own test). Still: the crash was never reproduced - the likely cause removed, not a proven fix; the keeper stays the net.
- [ ] THE SERVER ON KIT 6 (Ali: "the server needs to also have the latest kit"). Read-only survey (`.work\azure_vm_kit6_survey.ps1`, `azure_vm_keeper_names.ps1`): the server runs kit 5 in C:\wccf1011\kit (scripts\, bin\), the game in C:\wccf1011\game with winmm.dll 55342F6B (the whole-messages build); 0 players at 07:43 UTC. Names that must change: keeper.ps1 line 41 `kit\scripts\play.py` -> `kit\code\play.py`, and the task "WCCF 2010-11 server" (`kit\scripts\play.py server`). Everything else the keeper reads keeps its name in kit 6 (kit\data\logs, seat_broker.txt, _dbg_control.txt, kit\data\hold_projector.txt). Steps, on Ali's word, with nobody connected checked in the same command: keeper.pause; stop the server; back up kit\, keeper.ps1 and the task; unzip kit 6 over kit\ (data\ kept); code\setup.py on the game (wccfk.dll + the import rename + the old-layout tidy; English stays on); Defender scan there; keeper.ps1 line 41 + the task to code\; remove keeper.pause; start; check "whole messages: ON", the seat desk, relay and inbox running, a real join.
- [ ] RELEASE: Cargo.toml (and Cargo.lock's own entry) to 6.0.0 - the programs' version information and SETUP read it; tag kit-6
- [ ] merge the duplicates (D1-D22), split wccfpanel.c - after kit 6

### Phase 3 (old notes)
- [ ] paths.py, files.py, procs.py, settings.py - the shared foundation; switch call sites one by one
- [ ] card\ modules; merge the duplicate readers/savers (D1, D2); parity test for the C decoder (D4)
- [ ] run\, standins\, online\, server\, setup\ - move and merge
- [ ] data\ split (own / run / cache); runtime files out of code\ and seat1\ (F3)
- [ ] assets\, bin\ consolidation; the HANDOFF.md in every folder
- [ ] split wccfpanel.c
- [ ] the missing tests (audit G): the card reader, the session rule, the lease, the relay, keys parity

### Phase 4 - the contradictions and dead code (fold into the steps above where they live)
- C1-C13 (stale docs/comments), E (dead code) - removed as each file is touched.

## Progress log (newest first)
- 2026-10-11  A1 + A2 done: the card reader never writes the card in place and never locks the player out on a bad
  card; `source\test_icc_reader.py` (14 checks) added to check.ps1 - the reader's first test.
- 2026-10-11 06:11  branch `redesign` cut off main; this plan + root HANDOFF written. Phase 1 next.
