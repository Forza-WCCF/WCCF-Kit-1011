# docs\ - notes for the people who work on the kit

Not in the players' ZIP (`.gitattributes`).

| File | What it does |
|---|---|
| `REDESIGN.md` | the kit 6 redesign: the plan, the target folders, and the worklist with what was done and how it was checked |
| `research\CLUB-CARD-2010-11.md` | how the club card is built, read and saved, as found in the game |
| `research\CONTRACT-END-2010-11.md` | what happens when a manager's contract ends (the manager transfer) |
| `research\FREE-PLAY-2010-11.md` | how free play works in the game |
| `research\NO-INPUT-2010-11.md` | why the buttons stopped mid-session (Sega's JVS error mark after a stalled I/O board stand-in), the fix kit 7 built, and its before/after check in the real game (9.0) |
| `research\PVP-CONNECTION-2010-11.md` | the opponent match's socket lifecycle, relay routing, independent game failure reasons, regression coverage and remaining protocol limits |
| `website\wccfgame.php` | wccf.online's own card code (its MyBB plugin), as it runs there: sign-in codes, the starter 11, the card draw and its odds, owned cards, the club card checks - for reading; `code\server\card_bank.py` is the same rules for any server, and `source\test_card_bank.py` checks both read the club data at the same places. Copied from the website at each change, never edited here |

## Careful
- The research notes cite old paths and line numbers as they were when written (`.work\...`, `mxhook.c`): history,
  not a map of the kit today.
