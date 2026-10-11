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
- [ ] A10 the smaller lock-outs (catalogue-missing start, 17th club, SEND LOGS address, UPDATE SHA check, hold-file)

### Phase 2 - cheap antivirus wins (small, mostly conflict-free)
- [ ] B2e remove the screenshot-to-disk dumps; B9 remove the dead tasklist; B2a trampoline execute-only; B11 add the two flagged names to LEGACY
- [ ] B1g version info in winmm.dll / wccfpanel.dll / FPR_Emu.exe (build.ps1 + package.ps1 check) - may already be in flight
- [ ] B3  run cabinets and the projector without the debugger; keep it for control only
- [ ] B(4) stop impersonating winmm: ship the hook as wccfk.dll, patch the import in the game exes (DESIGN at `.work\research\mxrename\DESIGN.md`, mechanism already proven)

### Phase 3 - the physical move
- [ ] paths.py, files.py, procs.py, settings.py - the shared foundation; switch call sites one by one
- [ ] card\ modules; merge the duplicate readers/savers (D1, D2); parity test for the C decoder (D4)
- [ ] run\, standins\, online\, server\, setup\ - move and merge
- [ ] data\ split (own / run / cache); runtime files out of scripts\ and seat1\ (F3)
- [ ] assets\, bin\ consolidation; the HANDOFF.md in every folder
- [ ] split wccfpanel.c
- [ ] the missing tests (audit G): the card reader, the session rule, the lease, the relay, keys parity

### Phase 4 - the contradictions and dead code (fold into the steps above where they live)
- C1-C13 (stale docs/comments), E (dead code) - removed as each file is touched.

## Progress log (newest first)
- 2026-10-11  A1 + A2 done: the card reader never writes the card in place and never locks the player out on a bad
  card; `source\test_icc_reader.py` (14 checks) added to check.ps1 - the reader's first test.
- 2026-10-11 06:11  branch `redesign` cut off main; this plan + root HANDOFF written. Phase 1 next.
