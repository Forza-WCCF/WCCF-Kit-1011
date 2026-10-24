# source\website\ - wccf.online's own card code (for reading)

The community server's players sign in and earn cards on wccf.online. Its code is here so anyone can read how it
works (the owner, 2026-10-23: "the kit should have all the code"). The kit never runs it: a server someone hosts
uses `code\server\card_bank.py`, the same rules for any server.

| File | What it does |
|---|---|
| `wccfgame.php` | wccf.online's MyBB plugin, as it runs there: sign-in codes, the starter 11, the card draw and its odds, owned cards, the club card checks |

## Careful
- Copied from the website's plugin at each change, never edited here.
- Before each copy, check it holds no secret: today only hashes of two random secrets and the server's public
  address.
- `source\test_card_bank.py` checks that this file and `card_bank.py` read the club data at the same places.
