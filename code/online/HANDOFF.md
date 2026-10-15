# code\online\ - joining someone else's server

| File | What it does |
|---|---|
| `account.py` | this PC's wccf.online sign-in, the way a TV signs in: a code shown (PLAY window + a small Windows box), the page opened in the browser, the player approves there; the token kept in `data\account.json`. play.py runs it before joining a server; no sign-in = play.py plays on this PC instead. `signout()` (SETTINGS' SIGN OUT, via play.py at the next start): the website refuses the token from then on, then it is forgotten here |
| `club.py` | your online club: signed in, a PC plays online with the account's own club card (`data\save\online\u<account>\club.bin`), not the slot card; the cards the account owns on wccf.online (a new account gets 11 white ones) make the CATALOGUE (`data\cache\catalogue_online.tsv`) and, for a club not made yet, the table; the list is kept for when the website is down. The club card is kept on wccf.online: before each online start `sync()` makes this PC's card the same as the website's (a new club starts on a blank card with an id of its own; this PC's newer save goes up; the website's newer one wins, this PC's copy kept in `backup\`), and `upload()` sends each save (the panel helper calls it after the locker-room save; a used-up card is not sent). After 100 matches the game's manager transfer makes a new card (`club.new.bin`); the website takes it once the old contract has ended, and `ready()` puts the old card in `transferred\` at the next start - played through in the real game 2026-10-15 |
| `seat.py` | this PC's seat on a server: asks the server's seat desk for a seat and holds it while the game runs; after a break it reconnects and asks for the same seat; signed in, every request carries the token, and online the club card's id (`CARD c`) so the server tells two players in one house apart |
| `send_logs.py` | SEND LOGS (SETTINGS panel): this kit's logs in one ZIP, sent to a server's log inbox - never the club card, and names on this PC are replaced; also the newest lean crash snapshots and a report.txt; play.py uses it to send a run that went wrong by itself |

## Careful
- `seat.py` writes its answer once, for play.py; play.py only falls back to seat 1 when a server has no seat desk at
  all (`test_take_seat.py`, `test_seat_lease.py`).
- The sign-in token is a password: only `account.py` and `seat.py` read `data\account.json`; never print it, log
  it, put it on a command line or in SEND LOGS (`send_logs.files()` names what it packs - keep it that way). A desk
  refusal ("ERR sign in ...") becomes play.py's `SignInRefused`: it plays on this PC and says why
  (`test_account.py`, `test_seat_desk_signin.py`).
- The online club never touches the slot card or YOUR CARDS: play.py passes its card as `WCCF_CLUB_CARD` (the card
  reader, the panel, its helper) and records it in `data\running.json` for a stop and a cabinet restart. Anything
  wrong in `club.prepare()` plays with the slot card, as before (`test_online_club.py`).
