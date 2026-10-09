# Changelog

Community tools for WCCF 2010-11 (Rev D): a launcher, stand-ins for the cabinet's hardware and an on-screen panel, so
your own copy's server, projector and player cabinet run on one Windows PC - and online play on a shared server. The
game is not included. Newest first; each date is the day that kit was built.

## Unreleased

### Added
- SETUP.exe is a window: the game folder (BROWSE, or drag it onto the window or onto SETUP.exe) with SET UP /
  REPAIR and UNDO SETUP; GAME LANGUAGE, ENGLISH or JAPANESE (what ENGLISH.exe did); and UPDATE, the kit's releases
  and test builds on GitHub. UPDATE downloads the one you pick and copies it over the kit folder - data\ (club
  cards, keys, settings, logs) is never written, nothing is copied while the game runs - removes the files the old
  kit had and the new one does not, then offers setup again (and the English, if it is on). The scripts' output shows
  in the window. Its words are English, or Italian or Japanese when Windows is.
- PLAY.exe says when a newer kit is out, and SETUP.exe marks it "(newer)" and says so: a release only, never a test
  build. PLAY asks GitHub while the game starts and waits at most 3 s more for the answer.
- The kit ZIP holds version.txt (which kit it is) and files.txt (every file it ships), for UPDATE.
- When a contract ends, the game's own manager transfer works: put the card in again after the last match, and the
  card reader stand-in puts a blank new card beside it, as if two cards were stacked on the arcade's reader. The game
  moves the manager (name, salary, level, record, titles, division) to the new card and you make a new club in Club
  Make. At the next start the new club is in the slot and the old card goes to YOUR CARDS as "CLUB - transferred"
  (the game will not play it again: no PLAY THIS CLUB for it). The CLUB CARD panel says when a contract has ended.
- A player card after each match, as the cabinet's dispenser gave one (a test): when a match ends with its
  locker-room save, a window shows a card drawn from the catalogue - 2.5 % a card better than white and black
  (RARE, LEGEND, ALL TIME LEGEND), else 70 % white (REGULAR) and 30 % black (SPECIAL). Only shown: nothing is added
  to the club card. A click on it shuts it; it shuts itself after 20 s.
- CATALOGUE: the search takes several words, and a card must match each one: a name, club, country or season
  (`milan 2004`), a line (`fw`) or a role (`dmf`: cards rated 8 or more in it). `brazil fw`, `italy cb`.
- CATALOGUE: the card's pane lists the three roles the card suits best, out of 10 (`ROLES  DMF 10  CMF 7  CVR 5`):
  the game's own numbers (the player record's first 16 hidden values); the role names are inferred from the players
  rated 10 in each.
- FORMATION BOARD: resting the mouse on a card on the table (the big card) also shows its name, line, total and roles.
- Logs: older runs are no longer deleted. `data\logs\previous` is still the run before; the runs before it are
  zipped into `data\logs\archive` (about the last 200 MB, the oldest go first).
- Free play: the game's own FREE PLAY is switched on in seat 1, so no coin is needed anywhere - including the
  two-choice screen after a cup match that PRESS / SHOOT decide, where START's coin did not help. The key driver
  still puts a coin in on START, in case the panel is not loaded.
- SETTINGS > LOGS: SEND LOGS (click twice) sends this game's logs to the server you play on and shows a short code
  to post in Discord with what went wrong. Never the club card; the Windows user name and PC name are taken out.
- The kit's version (`KIT 5.5`) at the top right of the game, under the ping meter when online -
  `version.txt` in the kit (`kit-5.5`), written when the kit ZIP is made.
- Server: a box that only shows the projector (a stream box) can be kept out of the game until a player is in it -
  put its address in `data\hold_projector.txt`. The seat desk then holds that address off TCP 20002 with a Windows
  firewall rule and lifts it as soon as a player joins; "HOLD" tells the box whether it is held. On the shared server,
  runs where the stream box was the first in let almost no players in afterwards (6 runs); runs a player joined first
  let everyone in (3 runs). Other servers: no file, nothing changes.
- Server: the log inbox (`scripts\_log_inbox.py`, TCP 20050) keeps those logs in `data\player_logs`: at most 8 MB
  an upload, 6 an hour from one address, 1 GB in all (the oldest go). A server must now let in TCP 20050 too.

### Changed
- The panel is loaded by the game itself: the kit's winmm.dll, which the game already loads, loads wccfpanel.dll
  3 s after the window is up, for seat 1 and the projector. overlay\inject.exe, which wrote it into the running game
  from outside (VirtualAllocEx + CreateRemoteThread, a method antivirus programs watch for), is gone; an update
  removes it.
- The formation board shows a card big after the mouse rests on it 3 s (was 8 s).
- The BACK button is gone: it pressed nothing, and in the game the blue KEEPER button goes back.
- The COIN button is gone: play is free (above). KEYS still lists COIN, for a key or a real coin switch.

### Removed
- ENGLISH.exe: SETUP.exe's GAME LANGUAGE does the same. SETUP.exe removes it, and the .bat files of kits before 5.4.

### Fixed
- The key driver could end when its input file stayed busy (an antivirus scan, for one): every key and controller
  button dead, the last one held, the game going on by itself. A possible cause of the freeze reported in team
  training and the locker room (not confirmed). It now tries again on its next round; if it ever stops anyway,
  `data\logs\keys_crash.txt` says why.
- On a PC that had been on for more than 24.8 days without a restart, the card dispenser fix ("You are owed N
  Player Card(s)" kept at 0) never ran, nor did the player card after a match: their once-a-second / every-2-s
  timers started from 0 and never came round. They now count from the moment they start.
- Server (seat desk): after a server restart, a game that rejoined by itself kept its old seat while the desk thought
  that seat was free, and gave it to the next player - who was never let in (seen on the shared server: 4 tries in 12
  minutes). The desk now reads who is in the game and never gives a seat, or the projector, that another PC is
  using; the same PC can take its seat back.

## Kit 5.4 - 2026-10-09

### Added
- CLUB CARD: CLEAR BAD ENDINGS (click twice) sets the card's bad endings back to 0 at a restart, after a backup.
  Trade rights or money the game already took stay as they are. If it cannot be done, the kit says so and the game
  starts anyway. `scripts\edit_club_card.py` changes any other field.
- CATALOGUE: COUNTRY and CLUB filters (top right of the catalogue): a list of every country or club, A to Z, with
  its number of cards; typing narrows it, ANY clears it. On the card under the mouse, SAME CLUB and SAME COUNTRY
  show its clubmates or countrymen (a second click clears). The stats pane now shows the card's country too.
- Hosting a server: when the crash guard cannot catch a crash, `data\logs\run_server.txt` now says why
  (`MSGPARSE guard stepped aside: ...`, with what it found) - please share that line.

### Changed
- The README, the GitHub page and SETUP's messages speak of your own copy of the game: the kit does not include the
  game, and no longer names any download of it.
- `PLAY`, `SETUP` and `ENGLISH` are programs (`.exe`, written in Rust: `source\launcher`) instead of `.bat` files,
  used the same way. Updating from an earlier kit: delete the old `.bat` files.
- Quitting is closing the game's window. `STOP` is gone: closing seat 1's (or the projector's) window ends the game
  and everything the kit started with it. During a match the first close only warns (the card would get a bad
  ending); a second close within 8 seconds quits anyway. A hosted server (`PLAY.exe server`, no window) and a stuck
  game: `PLAY.exe stop`. A game window that goes by itself (a crash, not a close) stops nothing else while another
  game window runs: the projector keeps running (`data\logs\run_ended.txt` says so).

### Fixed
- Closing the game's window left the game itself running without a window, and with it the server, its match
  engines and the kit's helpers, hidden, for up to 12 hours. Now everything stops (`data\logs\run_ended.txt`). A
  server started on the same PC with `PLAY.exe server` keeps running for the other players.

### For developers
- The kit is built from this repository's source by GitHub Actions (`.github\workflows\kit.yml`): every push and pull
  request builds every program (`source\build.ps1`), runs the checks that need no game (`source\check.ps1`) and packs
  the kit zip (`source\package.ps1`); a `kit-*` tag drafts a release with it. Git holds the source, not the built
  programs.
- `source\package.ps1` reads the kit zip back and fails unless every program is in it (`PLAY.exe`, `SETUP.exe`,
  `ENGLISH.exe`, `bin\`, `overlay\` and `python\python.exe`). A `kit-5.4` tag makes `WCCF-2010-11-kit-5.4.zip`.
  A run's download on GitHub is that ZIP itself, no longer a ZIP around it, and CI checks the downloaded file too.
- Test builds for players: Actions > Kit > Run workflow with a tag like `kit-5.4-test1` publishes a pre-release with
  the ZIP (a public download).
- A `kit-*` tag's draft release carries its notes (`.github\release-notes.md` and the kit's CHANGELOG section); it is
  refused when CHANGELOG.md's newest heading is not that kit.
  Without pushing a tag: Actions > Kit > Run workflow on main with the tag (`kit-5.4`) under "release" - CI makes
  the tag on main's commit once every check has passed, and drafts the same release.

## Kit 5.3 - 2026-10-08

### Fixed
- Hosting a server: the crash guard added in 5.2 only caught one form of the "WCCF CONTROL NOT FOUND" (Error 3000)
  message-handling crash (an out-of-bounds read). A live crash showed the same bad message can also blow up in a
  memcpy (an out-of-bounds write) a bit deeper in the same code. The guard now catches **any** fault that happens
  while that message-reassembly function is running and drops the one bad message, so the server keeps going. For
  hosts only; players who just join need nothing. (Sega's server can crash in other, unrelated ways too - this
  covers the common message-handling one; keep a way to restart the server if it ever stops.)

## Kit 5.2 - 2026-10-08

### Fixed
- Hosting a server (`PLAY.bat server`) survives a rare crash. The server could drop with "WCCF CONTROL NOT FOUND"
  (Error 3000) on every cabinet at once while players were setting up a match - an out-of-bounds read in its
  message handling. A guard now catches that exact fault, drops the one bad message, and the server keeps running.
  On by default when hosting; players who only join a server never saw this and need nothing.

## Kit 5.1 - 2026-10-08

### Fixed
- The formation board could hold another club's cards after you switched clubs. Each club card now keeps its own
  board: the table you set up moves with the card (a `.board` folder beside the card file). Switch clubs in CLUB
  CARD and the table you left for that club comes back; a club played for the first time gets its squad laid out
  in a 4-4-2 with the substitutes on the bench. A table that belongs to no card is kept in
  `data\save\boards_unknown`, never thrown away.
- YOUR CARDS: with more clubs than fit, the rest could not be chosen. They are now in pages (`< PREV`, `NEXT >`, or
  the mouse wheel).

## Kit 5 - 2026-10-07

### Added
- Ping meter when you play online: bars and "80 ms" at the top right, above the game - green under 100 ms,
  yellow under 200, red above. It is your trip to the server; against another player, theirs adds to it.

### Changed
- Switching club cards (and RESTART NOW, when the server and the language stay the same) restarts only your
  cabinet: the projector keeps running and never has to sync again.
- Hosting a server (`PLAY.bat server`): it runs for 32 days instead of 12 hours, and waits for a projector to join
  before its first round.

### Fixed
- English: Prize Money on the fan event and golden age (all titles won) screens is one amount with commas -
  `$5,431,900`, not `$5 million$431900`.
- English: Team Training's "They're giving 110% out there" showed a junk number; it now reads "They're giving their
  all out there". Run `ENGLISH.bat` again after updating.

## Kit 4 - 2026-10-06

### Added
- Game controllers in KEYS: a USB encoder under real cabinet buttons, an arcade stick or a gamepad.
- SETTINGS: this PC or online, English or Japanese, RESTART NOW; the view CABINET or COMPACT (the game larger, no
  cabinet buttons).
- CLUB CARD: your club as the game reads it, its card health and backups; more than one club (YOUR CARDS).
- Online with others: SETTINGS > ONLINE and a server's address. Each PC that joins gets the next free seat by
  itself, the first one also the projector, and a match between two players goes through the server - nothing
  else to install.

### Changed
- Only two windows (the projector and seat 1); the projector starts muted and seat 1 quiet.
- Your card is saved safely, with backups; STOP asks before cutting a match.
- Each button's whole picture is clickable, rim and shadow too.

### Fixed
- English: money in dollars with commas on seat 1 and the projector (`$3,982,700`); the result screen's stats and
  goal minutes; the projector's "League"; "Contract: 88"; the shop's name ("Local Shop").

## Kit 3 - 2026-10-05

### Added
- KEYS, right of START: pick your own key for every cabinet button; it works at once (saved in `data\keys.txt`).

### Fixed
- Seat 1 closing at the start of a match: the game hit a text it could not format; now it shows the text and goes
  on.
- No more "You are owed N Player Card(s)": a PC has no card dispenser, so the kit tells the game nothing is owed.
- English: the license date reads like 2026/10/5 (it was in Japanese).

## Kits 1 and 2 - 2026-10-05
- The first kits: `SETUP.bat` and `PLAY.bat` start your own copy's server, projector and seat 1 on one PC, with the
  on-screen panel - cabinet buttons, a formation board and a catalogue of all 3,909 cards. No fixed paths: unzip
  anywhere.
- English (`ENGLISH.bat`), a 2-minute entry window and a smoother projector.
