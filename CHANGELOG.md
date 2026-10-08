# Changelog

The WCCF 2010-11 (Rev D) kit: Sega's server, the projector and a player cabinet on one Windows PC, with an
on-screen panel - and online play on a shared server. Newest first; each date is the day that kit was built.

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
- The first kits: `SETUP.bat` and `PLAY.bat` run Sega's server, the projector and seat 1 on one PC, with the
  on-screen panel - cabinet buttons, a formation board and a catalogue of all 3,909 cards. No fixed paths: unzip
  anywhere.
- English (`ENGLISH.bat`), a 2-minute entry window and a smoother projector.
