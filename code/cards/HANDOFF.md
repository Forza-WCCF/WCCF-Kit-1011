# code\cards\ - club cards and the card catalogue

Everything that reads, shows, changes or lists the club card (the player's save, `data\save\seat1_club.bin`) and the
catalogue of every player card.

| File | What it does |
|---|---|
| `catalogue.py` | makes the CATALOGUE (`data\cache\catalogue.tsv` and a picture per card) from the player's own game files - only reads the game (setup.py runs it) |
| `formation.py` | every club card keeps its own cards on the table (the FORMATION board); play.py lays the slot card's table out at a start and keeps it at a stop (the online club's board too: `online\u<account>\club.board`) |
| `view.py` | writes `data\club_view.txt`, the club card as the game reads it, for the CLUB CARD panel and the FORMATION board's link lines - read-only (the panel's helper runs it when the card changes) |
| `wallet.py` | your other club cards (`data\save\cards\`) and the card in the slot: switching cards, and a manager transfer's second card |
| `decode.py` | reads a club card file and checks it the way the game does - read-only; also a command-line tool |
| `edit.py` | changes fields on a club card with the game's own checks, a backup first (CLEAR BAD ENDINGS uses it; also a command-line tool) |
| `schema.py` | the card's field table - GENERATED from `client_Release.exe` by a research tool; never edit it by hand |
| `codes.py` | club, nationality and season names - worked out by people, kept apart from what is decoded |
| `unpack.py` | unpacks the game's compressed pictures (YS) for `catalogue.py` |

## Careful
- The club card is the player's save. Only `edit.py` (with its checks and backup) and `wallet.py` (renames, never a
  copy over a card) change card files; everything else only reads them.
- `decode.py`, `edit.py` and `schema.py` must agree with the game's own format; `test_card_fix.py`,
  `test_wallet_transferred.py` and `edit.py --self-test` (check.ps1) cover them.
- Moved here on 2026-10-11 the catalogue maker and the decoder gave the same results as before, byte for byte.
