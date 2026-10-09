# The WCCF 2010-11 club card ("card management")

> Research notes from the maintainers' workspace, shared here on 2026-10-09 so the club card work is not done
> twice (for 2010-11 and later versions). Paths under `.work\` are research tools and card samples that are not
> in this repository. Player names and the personal data of real cards are left out.

Static analysis of `client_Release.exe` (WCCF 2010-11, the RingEdge PC build) plus the card files, the game's own
backup memory, and the card-reader log that the kit kept for the first club. **Read-only:** nothing was started, and
no card, kit or game file was written. All card work was done on copies in `.work\research\club_card\samples\`.

Provenance marks: **[V]** read in the code (function and address given) or proved on a sample (named).
**[I]** inferred (the reason is given). **[A]** unknown.

Samples (copies; this report names them by these short names):

| name | what it is | original |
|---|---|---|
| s1 | test club アアア after a locker-room save; the screenshot `.work\shots\remote_seat1_d.png` shows this state | `.work\release1011\cleantest\kit_user\data\save\seat1_club.bin` (as it was when copied; see s1b) |
| s1b | the same file copied again later: a later session had started on it | same path |
| s2a | the player's club, written at a session START, then cut by the server freeze | `seat1_club.bin` in the control3000 crash folder under `.work\release1011\crash_logs\` |
| s2b | the player's club after the restart and a later session | `WCCF-2010-11-kit\data\save\seat1_club.bin` |
| s3 | old test club ＡＡＡＡ (once showed "did not end normally") | `WCCF-2010-11-kit\data\save\seat1_club.AAAA-test.bin` |
| s4 | the first club ever made (東京ＳＣ) | `.work\cards1011\seat1_club.bin` |

Sections 1-8 are the ones asked for. Section 9 (the private server) was added on request, so Open questions and
Sources are sections 10 and 11.

---

## 1. Summary in plain words

- The club card keeps your whole career in one block of data. The card holds it **twice**: copy A and copy B.
  Each copy ends with a check number. The game reads copy A. If A is damaged, it reads copy B. If both are
  damaged, it refuses the card.
- I can now read **every** value on the card. That covers the names, salary, money, the league table and all 16 players
  with their growth, plus the safety flags. There are 429 named values in all.
- I checked it against the test club's locker-room screen. The card says 2nd Division, 3rd Leg, 1st place,
  W2 L0 D1, manager アアア, salary $99,200. It also gives shirt 16 to Flamini and shirt 33 to T. Silva, as on the screen.
- The salary is stored in hundreds of dollars: 992 on the card is $99,200 on the screen.
- **When the game writes the card:**
  - at Club Make;
  - at every START (it switches the "improper flag" ON);
  - after every match, in the locker room (results saved, flag OFF, one use counted);
  - when you choose to play on (flag ON again);
  - game over writes nothing.
- If the game dies while the flag is ON, the next START adds 1 to the "improper count". Then you see "This Club
  Card did not end normally last time".
- **Penalties.** From a count of 2, any trades you have left are taken. At every 5th count (5, 10, 15 ...):
  - the salary drops by $500,000, which in practice means **$0**;
  - the contract loses 5 matches;
  - prize money drops by 250,000, in practice **to 0**;
  - both current win streaks go to 0;
  - World Trophy points drop.

  The first club's reader log shows both penalty rounds happening, at count 5 and at count 10.
- **The player's real club:**
  - improper count 1, flag off;
  - salary $98,500;
  - 10 wins in a row, and 1st in the 2nd Division after 5 legs.

  No penalty has hit it. Four more cut sessions would reach count 5, the big penalty.
- The game also keeps a copy of the last saved card in its own memory file (`mxsram.bin`), stored twice. Your
  club is in there, identical to your card file. Every kit card has the same identity, so this backup cannot tell
  one club from another.
- The kit's card file is safe against a cut in the middle of a save. The game writes copy A completely before copy
  B, so one good copy always survives (with the new reader that saves the file in one step).
- The new tool `decode_club_card.py` reads a card file without changing it and prints all of this. To use it, copy
  your card first while no session is open, then decode the copy. In PowerShell, from the WCCF folder:

  ```
  Copy-Item "WCCF-2010-11-kit\data\save\seat1_club.bin" ".work\research\club_card\my_card.bin"
  python ".work\research\club_card\decode_club_card.py" ".work\research\club_card\my_card.bin"
  ```

---

## 2. Block map

The card is 256 blocks of 16 bytes. The kit's card file is a 16-byte header followed by those 256 blocks
(4,112 bytes) [V `_icc_reader.py` Card.load/image].

**Kit file header** [V `_icc_reader.py`]: bytes 0-3 = UID (`DE AD BE EF`); byte 4 = the 'P' Card Status byte
(`0x18`); bytes 5-6 = the block-5 use counter, little-endian; bytes 7-15 = zero. The counter lives only in the
header: block 5 in the file stays zero.

| block(s) | holds | samples | source |
|---|---|---|---|
| 0 | manufacturer/UID block, read once per detection | `DE AD BE EF 22 18 02 00` + 8 zero bytes on every card | [V notes 3.4; all samples] |
| 1-3 | unused (never addressed) | zero | [V samples; I notes] |
| 4 | signature: bytes 8-11 = `95 71 66 40` (LE `0x40667195`). The game **requires a write here to fail** | as stated | [V notes 3.4; log: every detection starts with a 'U' to block 4] |
| 5 | value counter, only through 'I' commands (kept in the file header) | 0xFFF4-0xFFF8 | [V notes, `_icc_reader.py`] |
| 6 | bytes 12-15 big-endian serial, must be >= 10,000,000 | 10,000,001 on every card | [V notes; samples] |
| 7 | binding: a copy of block 0, written once when a blank card is first seen | equals block 0 on all samples | [V notes; log: 'U' to block 7 only at new-card detection] |
| 8-112 | **copy A**: 1,676-byte payload + 4-byte checksum (block 112 bytes 12-15) | | [V FUN_004d7d20, FUN_004d7bb0] |
| 113-217 | **copy B**: the same 1,680 bytes (checksum at block 217 bytes 12-15) | identical to A on all samples | [V FUN_004d7d20; samples] |
| 218-255 | unused | zero | [V samples; notes: highest block used is 217] |

**Inside one copy** (payload byte p sits in block 8 + p div 16, byte p mod 16; add 105 for copy B) [V layout from
FUN_00422210, sizes from the descriptor tables, total checked = 0x68C]:

| group | payload bytes | size | copy A from-to | contents |
|---|---|---|---|---|
| SystemInfo | 0-72 | 73 | block 8 byte 0 - block 12 byte 8 | version, dates, IDs, trades, WAN flag (68 records) |
| UserInfo | 73-75 | 3 | block 12 bytes 9-11 | improper flag and counts, unsent plays (7 records) |
| Coach | 76-323 | 248 | block 12 byte 12 - block 28 byte 3 | manager: name, salary, contract, records (250 records) |
| Club | 324-835 | 512 | block 28 byte 4 - block 60 byte 3 | club: name, money, league, streaks, tactics, flags (773 records) |
| Player x16 | 836-1459 | 39 each | block 60 byte 4 - block 99 byte 3 | one record per registered player (60 records each) |
| Title x30 | 1460-1609 | 5 each | block 99 byte 4 - block 108 byte 9 | per-competition W/D/L/titles (6 records each) |
| Etc | 1610-1675 | 66 | block 108 byte 10 - block 112 byte 11 | World Trophy points, version-up flag, spares (63 records) |
| checksum | 1676-1679 | 4 | block 112 bytes 12-15 | LE32 = sum + 1 |

Every group happens to fill whole bytes (584, 24, 1984, 4096, 312, 40 and 528 bits), so there are no padding bits
[V arithmetic on the tables]. Three more groups exist in memory but are **never stored**: NoSaveCoach,
NoSaveClub (1,502 records), NoSavePlayer [V FUN_00422210 skips cases 3-5].

---

## 3. Field map

**How the payload is coded** [V]:
- Each value is an unsigned number of a fixed bit width. Bits are read MSB first (FUN_00424260); writing is the
  same in reverse (FUN_004241e0), clamped to the width.
- Field order and widths come from 0xDC-byte descriptors in the exe, one table per group (vfunction2 gives the
  table, vfunction3 the record count, e.g. Club: `0x00B13FB0`, 0x305 records). Each record holds:
  - +0x00 the name;
  - +0x40 a Japanese description (the game looks fields up by this text, FUN_00421a40);
  - +0xC0 the array length;
  - +0xC4 1 = settable by the game's setter;
  - +0xCC max, +0xD0 min, +0xD4 default;
  - +0xD8 the bit width.
- When the game sets a value it clamps it to min-max (FUN_00422900). When it **reads** the card it does not clamp
  (FUN_00424260 reads raw bits).
- Text fields are 56-byte arrays of Shift-JIS (cp932) bytes, NUL-terminated. Full-width, half-width kana and plain
  ASCII all occur (a club name typed in plain ASCII).

The complete list (all 429 named fields with widths, min, max, default and offsets) is in
`.work\research\club_card\schema.tsv` and `club_card_schema.py`. The table below covers everything the brief asked
for. "bit" = position in the payload, MSB first. Sample values are listed s1 / s2a / s2b / s3 / s4. Dates are not
printed, as this report carries none.

| field (group) | bit; copy A place | bits | encoding and meaning | samples | tag |
|---|---|---|---|---|---|
| SYSTEM_VERSION (Sys) | 0; block 8 bytes 0-3 | 32 | card format version (big-endian when read as bytes). Values 1-4 are refused (error 4): this is the old notes' "block 8 bytes 0-3 must not be 1-4" | 5 on all | [V samples; notes 3.4] |
| SYSTEM_LAST_PLAY_DAY (Sys) | 32; block 8 byte 4 | 25 | last play day, a 6-digit YYMMDD number, local time. Written at each locker room (FUN_005ec6e0 -> FUN_004eb870 -> FUN_00411f00 `_localtime64_s`) | dates | [V code; V s1 equals the save's day; V log replay: +1 day at a locker room after midnight] |
| SYSTEM_COACH_ID (Sys) | 57; block 8 byte 7 bit 1 | 16x8 | the 16-byte manager ID the server matches (NETWORK_ID). Bytes 8-11 = SYSTEM_COACH_ENTRY_TIME and bytes 12-15 = SYSTEM_CARD_ID, both big-endian. Bytes 0-7 = `00 00 00 00 3a 3a 00 00` on every card | e.g. s2b (left out here) | [V samples for bytes 8-15; A bytes 0-7] |
| SYSTEM_NETWORK_CARD_ID (Sys) | 185 | 32 | card ID given by the server in a NETWORK_ID reply | 0 on all | [V FUN_00408b90] |
| SYSTEM_NETWORK_COACH_ID (Sys) | 217 | 32 | manager ID given by the server in a NETWORK_ID reply | 0 on all | [V FUN_00408b90] |
| SYSTEM_CARD_ID (Sys) | 263; block 10 byte 0 bit 7 | 32 | card ID, equal to the block-6 serial | 10,000,001 on all | [V samples; I origin] |
| SYSTEM_COACH_ENTRY_TIME (Sys) | 295 | 32 | card creation time, a month-day-hour-minute-second number (max in table 1231235959) | dates | [I format; samples agree with the founding day] |
| SYSTEM_SHOP_ID (Sys) | 327 | 16 | shop of creation; filled after a valid NETWORK_ID if still 0 | 0 on all | [V FUN_00408b90] |
| SYSTEM_MACHINE_SERIAL_NO (Sys) | 343 | 12x8 | ASCII serial of the cabinet that made the card | "Default::" on all | [V samples] |
| CLUB_TRADE_RIGHT_NUM (Sys) | 503; block 11 byte 14 bit 7 | 2 | times trade rights were granted (max 3) | 0 on all | [V name; I meaning] |
| CLUB_TRADE_REMAINDER_NUM (Sys) | 505; block 11 byte 15 bit 1 | 2 | **trades left** (max 2). Set to 0 by the penalty at count 2+ | 0 on all | [V FUN_005e4ef0] |
| other trade fields (Sys) | 249-262, 439-502 | | CLUB_TRADE_CR_NUM_1/2, CLUB_TRADE_STATUS_1/2, CLUB_TRADE_IC_ID_1/2 (source card IDs), CLUB_TRADE_REFUSE | 0 | [V names] |
| USER_WT_POINT_TRANSMISSION_FLAG (Sys) | 567 | 1 | when 1, the locker room skips its save (FUN_005e5170) | 0 on all | [V code; A when it is set] |
| USER_WAN_INJUSTICE_FLAG (Sys) | 579; block 12 byte 8 bit 3 | 1 | "WAN cut" flag (WAN抜きフラグ); see section 5 | 0 on all | [V code] |
| USER_FAILURE_TRANSMISSION_PLAY_NUM (User) | 587; block 12 byte 9 bit 3 | 8 | **unsent plays**: +1 at the end of every match (FUN_005ec760, called from ClientGameSequenceNode::vfunction22), set to 0 only by a valid NETWORK_ID reply | 6 / 9 / 10 / 7 / 8 | [V code; V replay: +1 per match] |
| USER_INJUSTICE_FLAG (User) | 595; **block 12 byte 10, mask 0x10** (copy B: block 117) | 1 | the **improper flag** 不正フラグ: 1 from START to the locker room | 0 / 1 / 0 / 0 / 1 (s1b: 1) | [V code; 6 card versions; replay] |
| USER_INJUSTICE_NUM (User) | 596; block 12 bytes 10-11 | 7 | **improper count** 不正回数 (max 127) | 3 / 0 / 1 / 3 / 10 | [V] |
| USER_WAN_INJUSTICE_NUM (User) | 603 | 5 | WAN-cut count | 0 on all | [V FUN_005e4cd0] |
| COACH_NAME (Coach) | 608; block 12 byte 12 | 56x8 | **manager name**, Shift-JIS | アアア / (name) / (name) / アアア / アイイシ | [V s1 = screen] |
| COACH_NAME_READ (Coach) | 1056; block 16 byte 4 | 56x8 | name reading, half-width katakana; some readings contain `'` | ｱｱｱ' / (reading) / ... | [V samples; A the `'`] |
| COACH_BIRTHDAY (Coach) | 1504 | 25 | YYYYMMDD (the same value on all of one player's clubs) | dates | [I] |
| COACH_SALARY (Coach) | 1529; block 19 byte 15 bit 1 | 20 | **annual salary in units of $100** (default 500 = $50,000; max 999,999) | 992 / 870 / 985 / 787 / 0 | [V s1: 992 = "$99200" on screen] |
| COACH_LAST_TERM (Coach) | 1576; block 20 byte 5 | 8 | **contract: matches left** (default 100, max 150), -1 per match. At 0 the card's use counter is set to 1 (last use) | 94 / 91 / 90 / 93 / 82 | [V FUN_005dd1b0; replay] |
| COACH_LEVEL, COACH_LEVEL_TITLE, COACH_TYPE (Coach) | 1585, 1590, 1596 | 5, 6, 4 | manager level (max 17), title, type | level 0 on all | [V names] |
| COACH_OFFENCE ... COACH_LINE_DEFENCE (Coach) | 1609-1808 | 20x10 | manager style values (default 245) | | [V names] |
| COACH_TOTAL_WIN/DRAW/LOSE_NUM (Coach) | 1809 / 1826 / 1843 | 17 each | manager career W / D / L | 5-1-0 / 9-0-0 / 10-0-0 / 6-1-0 / 7-0-1 | [V samples agree with club records] |
| COACH_TOTAL_CHAMPIONSHIP_NUM (Coach) | 1860 | 30x10 | per-competition titles by name, but every card holds the same 7, 7, 8, 9 at indexes 9, 15, 16, 27 | same on all | [A meaning] |
| COACH_MAX_OFFICIAL_SERIES_WIN (Coach) | 2176 | 8 | best official win streak | 2 / 4 / 5 / 4 / 3 | [V] |
| CLUB_NAME (Club) | 2592; block 28 byte 4 | 56x8 | **club name**, Shift-JIS or ASCII | アアアア / (club name) / ... / ＡＡＡＡ / 東京ＳＣ | [V] |
| CLUB_NAME_CALL (Club) | 3040; block 31 byte 12 | 56x8 | club name reading | (reading) ... | [V] |
| CLUB_FOUNDATION (Club) | 3488 | 25 | founding day, YYYYMMDD | dates | [I] |
| CLUB_STADIUM_NAME (Club) | 3536 | 5 | stadium name **index** (s1's screen says "Otsu Ground") | 20 / 15 / 15 / 5 / 0 | [I index; A the list] |
| CLUB_SUPPORTER_NUM (Club) | 3568 | 17 | supporters (min 1,000, default 3,000). The screen's "10960 fans" is the match attendance line (`GAM_OPENING_status_0008` "%d fans"), not this value | 2268 / 3053 / 2703 / 1237 / 3757 | [V name; I attendance] |
| CLUB_GET_PRIZE (Club) | 3596 | 24 | prize money (unit unknown); -250,000 per 5th improper | 8961 / 11951 / 12990 / 7793 / 1721 | [V code; A unit] |
| CLUB_FINANCIAL_POITN (Club) | 3620 | 24 | finance points (default 25,000) | 26259 / ... | [V name] |
| CLUB_NEW_ENTRY_PLAYER_NUM (Club) | 4626 | 6 | newly registered players, recounted at each save (FUN_005dcba0) | 21 / 16 / 16 / 16 / 16 | [V code] |
| CLUB_HOMETOWN_REGION/COUNTRY/CITY (Club) | 5112 / 5115 / 5123 | 3 / 8 / 11 | hometown | | [V names] |
| CLUB_LAST_GAME_RESULT / TITLE (Club) | 5294 / 5298 | 4 / 5 | last result; last competition (14 = Regular League) | title 14 on s1-s3, 17 on s4 | [I 14 = RL, from Title[14]] |
| CLUB_RECORD_WIN/DRAW/LOSE (Club) | 5439 / 5447 / 5455 | 8 each | club all-match W / D / L | 5-1-0 / 9-0-0 / 10-0-0 / 6-1-0 / 7-0-1 | [V] |
| CLUB_RECORD_SERIES_WIN (Club) | 5463 | 8 | **current win streak**; reset by a 5th-count penalty | 2 / 9 / 10 / 0 / 1 | [V code; replay] |
| CLUB_RECORD_MAX_SERIES_WIN (Club) | 5479 | 8 | best win streak (not reset) | 3 / 9 / 10 / 6 / 6 | [V] |
| CLUB_RECORD_OFFICIAL_SERIES_WIN (Club) | 5495 | 8 | **current official win streak**; reset by the penalty | 2 / 4 / 5 / 0 / 0 | [V code; replay] |
| CLUB_RL_WIN / DRAW / LOSE (Club) | 5587 / 5591 / 5595; block 51 bytes 10-11 | 4 each | **Regular League W / D / L** this season | s1: 2 / 1 / 0 | [V s1 = "W2 L0 D1"] |
| CLUB_RL_SECTION (Club) | 5599 | 4 | **league leg** just played | s1: 3 | [V s1 = "3rd Leg"] |
| CLUB_RL_GET_GOAL / LOSE_GOAL (Club) | 5603 / 5609 | 6 each | league goals for / against | s1: 8 / 1 | [V] |
| CLUB_RL_LAST_RANK (Club) | 5619 | 4 | **league position, 0 = 1st**; CLUB_RL_BEFORE_LAST_RANK (5615) = the leg before | 0 / 0 / 0 / 0 / 2 | [V s1 0 = "1位"; I 0-based from s4 = computed 3rd] |
| CLUB_RL_IMAGINE_POINT / GOAL_POINT / GOAL_LOST_POINT (Club) | 5629 / 5669 / 5725 | 8x5, 8x7, 8x7 | the 8-team league table. **Entry 0 is the club itself**, entries 1-7 the other teams | s1 points 7,5,5,2,2,0,5,4 | [I: entry 0 equals the club's own record on all 5 cards] |
| CLUB_RL_START / SUCCESSION / PRESENT_DIVISION (Club) | 5781 / 5784 / 5787 | 3 each | **division** (default 2, max 4) | 2 on all | [V s1 2 = "2nd Division"] |
| CLUB_MATCHING_PARAMETER (Club) | 6066 | 14 | matchmaking value, rewritten at each save (FUN_005e7a20) | 3508 / ... | [V code] |
| other Club fields | | | stadium/clubhouse parts, uniforms and emblem, sponsors, offers, captain, key player, tactics, CPU settings, 120 player-pair link values, about 30 "information" flags | | [V names, schema.tsv] |
| **Player[i]** (i = 0-15) | 6688 + 312i; payload byte 836 + 39i | 312 per player | per-player record (below) | | [V] |
| PLAYER_CARD_NO | +0 | 14 | the **player card number** (key into the game's player list; names come from `.work\playercards1011\catalogue.tsv`) | s1 P7 = 3735 FLAMINI, P15 = 3731 T.SILVA | [V s1: back numbers 16 and 33 = the shirts on the screen] |
| PLAYER_OFFICIAL_GOAL / ASSIST | +14 / +26 | 12 each | official goals / assists | | [V] |
| PLAYER_PARTICIPATE_NUM | +38 | 8 | appearances | | [V] |
| PLAYER_INJURY_PART / DEGREE / HEALING | +47 / +50 / +52 | 3 / 2 / 6 | injury | s1 P3 = 1/1/0 | [V names] |
| PLAYER_BACK_NUMBER | +58 | 7 | shirt number in this club | | [V screen] |
| PLAYER_CONDITION / TEAM_ACCUMULATE_FATIGUE | +65 / +68 | 3 / 8 | condition 0-5 (default 2), fatigue | | [V names] |
| PLAYER_MASTERY and MASTERY_*_NUM | +80; +87 to +116 | 7; 6x5 | **growth**: familiarity (習熟度) and training count per skill | | [V names] |
| PLAYER_ABILITY_UP_1-3, STYLE, FK/CK/PK, KEYPLAYER_EXP, FAVOR, RESPECT, 13 DISSATISFACTION fields, 7 OPINION fields | +118-+306 | | growth bursts, kicker roles, mood and the coach's ratings | | [V names] |
| (no player contract, no player level) | | | the schema has **no** per-player contract or level field. The only contract is the manager's (COACH_LAST_TERM) | | [V schema] |
| **Title[k]** (k = 0-29) | payload byte 1460 + 5k | 40 per title | TITLE_PARTICIPATE_NUM, TOTAL_WIN, DRAW, LOSE (8 bits each), TOTAL_CHAMPIONSHIP (7), DUMMY (1) | Title[14] = the Regular League | [V: equals CLUB_RL_W/D/L on all cards; A the other k; Title[28] and [29] hold values that do not fit a record] |
| CLUB_WT_POINT_MAX / CLUB_WT_POINT (Etc) | 12880 / 12900 | 20 each | World Trophy points | 0 on all | [V names] |
| CLUB_WT_THIS_TITLE_POINT (Etc) | 12923 | 17 | this tournament's WT points; -5,000 per 5th improper | 0 | [V code] |
| CLUB_WT_SUCCESSION_CHAMPION_NUM (Etc) | 13000 | 5 | consecutive WT titles; reset by the penalty | 0 | [V code] |
| VERUP_FLAG1011 (Etc) | 13035 | 1 | 2010-11 version-up flag (default 1) | 1 on all | [V] |

**What the screen showed for s1, and where each value is** [V s1 against `.work\shots\remote_seat1_d.png`]:

| screen | card |
|---|---|
| Regular League, 2nd Division | CLUB_RL_PRESENT_DIVISION = 2 |
| 3rd Leg | CLUB_RL_SECTION = 3 |
| 1位 (1st) | CLUB_RL_LAST_RANK = 0; computed table: 7 points, no team above |
| W2 L0 D1 | CLUB_RL_WIN 2, CLUB_RL_LOSE 0, CLUB_RL_DRAW 1 (Title[14] the same) |
| manager アアア | COACH_NAME = `83 41 83 41 83 41` (Shift-JIS) at block 12 bytes 12-15 + block 13 bytes 0-1 |
| Annual Salary $99200 | COACH_SALARY = 992 |
| T.SILVA 33, FLAMINI 16 (shirts) | Player[15] card 3731 back 33; Player[7] card 3735 back 16 |
| Matches $15100, Titles $000 | **not found as stored values** [A]. A guess: "Matches" is the salary raise from this match (151, so 841 before). Raises of 143-162 per win appear in the log replay, the same size [I, unchecked] |
| Otsu Ground | CLUB_STADIUM_NAME = 20 [I index] |
| 10960 fans | match attendance, not stored [I] |

---

## 4. Checksums and copies

**Algorithm** [V FUN_004d7b70, FUN_004d7d20, FUN_004d7bb0]:
- sum = the 32-bit wrapping sum of the 419 (0x1A3) little-endian dwords of the payload (bytes 0-1675 of the copy);
- stored = the LE32 at payload byte 1676 (block 112 bytes 12-15 for A, block 217 bytes 12-15 for B);
- **the game writes stored = sum + 1** and **accepts stored == sum or sum + 1**.

**Recomputed on every sample** [V `blocks.py`, decoder]: all five cards and s1b have good copies with
stored = sum + 1, and copy A byte-identical to copy B. s1b's sum is s1's + 0x00100000, exactly the flag bit's weight
in its dword:

| sample | sum | stored |
|---|---|---|
| s1 | 0x0D489CCC | 0x0D489CCD |
| s2a | 0x00A2772F | 0x00A27730 |
| s2b | 0xE47543D3 | 0xE47543D4 |
| s3 | 0xED55E63C | 0xED55E63D |
| s4 | 0x3DA97807 | 0x3DA97808 |

**How the game picks a copy** [V FUN_004d7bb0, accessor FUN_004d7530]:
1. Counter 0xFFFF (new card): no check at all.
2. If either copy is all zeros (sum 0 and stored 0): refuse (detection error 0xA).
3. If copy A passes: read copy A. Copy B is not compared with A. A good-but-different copy B is ignored
   (test card `copies_differ.bin`).
4. If A fails and B passes: card+0x1A6C = 1 and copy B is read (test card `copyA_corrupt.bin`).
5. Both fail: detection error 0xA (`mov [0x011374a8], 0xA` at 0x004d649d) [V].

**Copy B is made by copying A**: FUN_004d7d20 builds 0xD20 bytes, writes the checksum at 0x68C, then copies the
first 0x690 bytes over the second [V]. So after every game save both copies are identical.

---

## 5. When and how it is written

### 5.1 The save path [V]
Every write goes through **FUN_005dcc70**, which serializes the parameters (FUN_00422440) and calls FUN_004d8c90.
That calls FUN_004d7d20, which:
- builds copy A + checksum + copy B;
- stores a backup in battery memory (FUN_004d76f0 -> FUN_004f18d0 -> FUN_004f1920 "writeRegionBuSram");
- posts **job 5**.

Job 5 (FUN_004d7e00 -> FUN_004d71f0) then:
1. re-selects the card;
2. sends one **'U'** per block **only for blocks that differ** from what it last read, in **ascending order 8 -> 217**
   (so all of copy A before copy B), 6 tries each plus up to 10 retries;
3. **reads everything back** (14 x 'R', 15 blocks each) and compares;
4. clears "write pending" if all matched.

Save failures are logged as event 0x138D (fewer than half written) or 0x138E (read-back mismatch). FUN_005dcc70
also refreshes the 16 PLAYER_CARD_NO values and CLUB_MATCHING_PARAMETER from the cards on the table (FUN_005e7a20)
before every save [V].

### 5.2 The moments

| moment | code | what changes | reader commands seen in the log | use counter |
|---|---|---|---|---|
| **New card detected** | FUN_004d6c40 (notes 3.4) | block 7 := block 0; blocks 8-217 zeroed | U4 (must fail), I0, U7, 14 R, **14 S**, 14 R | stays 0xFFFF |
| **Club Make** | club_make::SaveNewClubDataNode::vfunction21 @0x0045d7a0 | the whole new club; improper flag = 1 | **I by 1 first**, then 138 U, then 14 R | 0xFFFF -> 0xFFFE |
| **Session START** (Team IC Card Check) | TeamCardCheckSequenceNode::vfunction21 -> FUN_005740e0 -> FUN_005e4cd0 (improper check, penalties) -> FUN_005dcd40 (flag = 1, WAN flag = 0) -> FUN_005dcc70 | flag 0 -> 1; plus count/penalty fields when the last session was cut | **4 U: blocks 12, 112, 117, 217** (flag byte + both checksums), then 14 R | none |
| **Locker room** (after each match) | LockerRoomSequenceNode::vfunction20 @0x005d1ff0: FUN_005ec6e0 (play day, WAN flag, **flag = 0**) -> FUN_005e5340/FUN_005e5410 -> FUN_005dcc70 -> FUN_005dd1b0 | results, money, players, flag 1 -> 0, last-play day | about 106-138 U, 14 R, then **I by 1** | -1 |
| **Play on** (continue) | LockerRoomSequenceNode::vfunction22 -> FUN_005e77b0 -> FUN_005e4cd0 (does nothing the second time) -> FUN_005dcd40 | flag 0 -> 1 | 4 U (12, 112, 117, 217), 14 R | none |
| **Game over** | LockerRoomSequenceNode::vfunction22 without continue | **nothing** | none | none |
| **Detection of an existing card** (each card loading; in the log about every 35 s while a card sat on the reader between sessions) | FUN_004d6060 / FUN_004d6c40 | nothing | U4 (must fail), I0 (reads the counter), 14 R | none |

Sources for the reader commands: `.work\_icc_seat1_log.txt` (the 51 MB reader log of the session that made the first
club), summarised by `icclog_order.py` and replayed by `icclog_replay.py` [V]. Typical full sessions from that log:

```
new card + Club Make + 1st match:  U4 I0 U7 Rx14 Sx14 Rx14 I1 Ux138 Rx14 Ux106 Rx14 I1
session with play-on:              U4 I0 Rx14 Ux4 Rx14 Ux112 Rx14 I1 Ux4 Rx14 Ux124 Rx14 I1
session after a cut + penalty:     U4 I0 Rx14 Ux10 Rx14 Ux134 Rx14 I1
```

**The once-per-session guard** [V]: FUN_005e4cd0 runs once (DAT_011376ff). AdvertiseSequenceNode::vfunction20
(attract) and FUN_005e6060 reset it.

**The WAN flag** (WAN抜きフラグ) [V] is set in two ways:
- at every locker room, FUN_005e4bd0 first clears it, then sets it to (network object +0x568 == 2). +0x568 is
  copied from a received message in FUN_004e7c80;
- FUN_005d3920 runs every frame in the locker room (called from LockerRoomSequenceNode::vfunction21 @0x005d35cb).
  It reads the network object's +0x500, the result of the server's NETWORK_ID reply: FUN_00408b90 writes 1 =
  accepted and 2 = rejected, and each ENTRY SVR or play-data send resets it to 0.
  - With 1 it clears USER_WT_POINT_TRANSMISSION_FLAG, saves (FUN_005dcdc0) and decrements (FUN_005dd1b0).
  - With 2 it sets **the WAN flag to 1** and saves, and logs event 0x7EC.
  - Both only act when the node's +0xFC is set; when that happens is [A]. My guess: the case where the normal
    locker-room save was skipped because USER_WT_POINT_TRANSMISSION_FLAG was 1 [I].

At START, a set WAN flag adds 1 to USER_WAN_INJUSTICE_NUM **and** 1 to USER_INJUSTICE_NUM (with penalties), then
clears [V FUN_005e4cd0 @0x005e4d8b-0x005e4ddb]. What +0x568 = 2 means on the server side is [A]. With the kit's
server, no NETWORK_ID reply arrives (unsent plays keep rising), so neither path has fired on any sample (WAN flag 0
everywhere) [V].

**The use counter** (header bytes 5-6 = block 5) [V]:
- 0xFFFF = a new card (Club Make follows);
- **-1 at Club Make**, before the write: job 2 posted by FUN_005dd1b0, seen in the log as I by 1 ahead of the 138
  U. Job 5's own "new card" decrement then does not fire, because the counter is no longer 0xFFFF.
- **-1 at each locker room**, after the write and read-back.
- set to **1** (job 3) when the manager's contract COACH_LAST_TERM has reached 0 (FUN_005dd1b0 @0x005dd20a).
- At detection, 1 = error 7 (last use, the game goes on) and 0 = error 8 (used up) [notes 3.3].

Checked on all samples: decrements = 1 (Club Make) + matches played, and COACH_LAST_TERM = 100 - matches
(- 10 for s4's two penalties):
- s1: 0xFFF8 = 1 + 6, term 94;
- s2a: 0xFFF5 = 1 + 9, term 91;
- s2b: 0xFFF4 = 1 + 10, term 90;
- s3: 0xFFF7 = 1 + 7, term 93;
- s4: 0xFFF6 = 1 + 8, term 92 - 10 = 82.

### 5.3 What the commands look like [V notes section 2; log]
Host frame: `[cmd, cmd, len, data, BCC]`. BCC is the XOR of the bytes before it, every 0x10 is doubled, and the
frame ends `10 03`.

- **'U' write one block**: `55 55 12` + block (LE16) + 16 data bytes + BCC + `10 03`. Reply status 0 = written
  (block 4 must answer non-zero). From the log:
  ```
  1065.870    CMD 55 ?  len 18 data [0c 00 00 00 39 d0 00 00 00 00 20 00 10 00 83 41 83 43]  bcc ok
  1065.890    -> REPLY st=0 55 00 00 55 10 03
  ```
- **'S' write 15 blocks**: `53 53 F3` + start (LE16) + `0F` + 240 bytes. Used **only** to zero a new card
  (14 frames, starts 8, 23, ... 203) [V log].
- **'I' decrement block 5**: `49 49 04 05 00` + amount (LE16). The reply data is the new value:
  ```
  1065.110    CMD 49 ?  len 4 data [05 00 01 00]  bcc ok
  1065.134    -> REPLY st=0 49 00 04 fe ff 00 00 4c 10 03
  ```
- **'R' read 15 blocks**: 14 of them read blocks 8-217 (detection and every read-back).

### 5.4 What goes to the server [V]
- **ENTRY SVR** (FUN_0044ba20), from CardArrangeSequenceNode::vfunction20 (each session) and
  club_make::SeqContractPlayer::vfunction2 (Club Make). It carries a 16-character text and a 16-bit value from the
  cabinet's server settings (+0x52A, +0x53A: meaning [A]), 7 x NO_SAVE_CLUB_MATCHING_HISTORY, the two WT ranking
  values, and **the full 1,676-byte serialized card payload**.
- **Play data** after each locker-room save (FUN_0044bbd0 -> FUN_004509b0): the full payload again, plus the four
  WT point fields.
- **Improper count report** (FUN_00446cf0) when the count rises at START, and FUN_00446d60 after a penalty, both
  only if a server link exists (DAT_01137388).
- **NETWORK_ID reply** (FUN_00408b90): see section 9.5.

---

## 6. What a session changes (the diffs)

### 6.1 s2a -> s2b (the player's club: the cut session, then the restart session) [V decoder `--diff`]
- **Header use counter 0xFFF5 -> 0xFFF4**: exactly one locker-room save happened in between.
- **136 blocks differ, 68 in each copy, and copy B's set = copy A's + 105**: blocks 12, 20, 22, 25, 35-43, 45-68,
  70-98, 103, 112 and their copy-B twins. The 0x10 bit of block 12 byte 10 is the flag.
- **231 fields differ.** The ones that tell the story:

```
USER_INJUSTICE_FLAG              1 -> 0     (s2a was written at START; s2b after a locker room)
USER_INJUSTICE_NUM               0 -> 1     (the restart's START counted the cut session)
USER_FAILURE_TRANSMISSION_PLAY_NUM 9 -> 10  (one more match not confirmed by a server)
COACH_SALARY                     870 -> 985 (= $87,000 -> $98,500)
COACH_LAST_TERM                  91 -> 90   (contract: one match used)
COACH_TOTAL_WIN_NUM              9 -> 10;  CLUB_RECORD_WIN 9 -> 10;  CLUB_RL_WIN 4 -> 5;  CLUB_RL_SECTION 4 -> 5
CLUB_RL_GET_GOAL / LOSE_GOAL     11 -> 15 / 1 -> 2   (a 4-1 league win)
CLUB_RECORD_SERIES_WIN           9 -> 10;  CLUB_RECORD_OFFICIAL_SERIES_WIN 4 -> 5
CLUB_GET_PRIZE 11951 -> 12990;  CLUB_FINANCIAL_POITN 18425 -> 17501;  CLUB_SUPPORTER_NUM 3053 -> 2703
CLUB_RL_IMAGINE_POINT            12,6,7,1,6,4,6,4 -> 15,9,7,4,6,7,6,4   (entry 0 = the club, +3)
Player[0-15]: appearances, fatigue, condition, key-player experience, respect, dissatisfaction, the coach's ratings
Title[14].TITLE_TOTAL_WIN_NUM    4 -> 5
```

No penalty was applied: count 1 is below both the trade threshold (2) and the period (5) [V]. Full list:
`.work\research\club_card\output\diff_s2a_s2b.txt`.

### 6.2 s1 -> s1b (a later session started on the test club) [V]
Only USER_INJUSTICE_FLAG 0 -> 1, in blocks 12, 112, 117 and 217. This is the session-start save seen on a real card.

### 6.3 The first club's whole life, replayed from the reader log [V `icclog_replay.py`]
Every 'S'/'U'/'I' in `.work\_icc_seat1_log.txt` was applied to an empty card in order. The card was decoded after
each burst. **The final replayed blocks 8-217 equal s4 byte for byte, and the replayed counter 0xFFF6 equals s4's
header.** The key steps (t = seconds on the log's own clock, which restarts at a reader restart):

```
#43  Club Make      I1 + 138 U   flag 0->1, salary 500, term 100, supporters 3000         counter 0xFFFE
#44  locker room    I1 + 106 U   flag 1->0, salary 500->496, term 100->99, RL lose 0->1    counter 0xFFFD
#75  START          4 U          flag 0->1                     (then the session was cut)
#79  START          4 U          count 0->1                    (cut again; and again:)
#81, #83, #85       4 U each     count 1->2, 2->3, 3->4
#87  START          6 U          count 4->5, SALARY 496->0, TERM 99->94      <- 1st penalty
#88  locker room    I1 + 112 U   flag 1->0, salary 0->157, prize 0->1096, streak 0->1     counter 0xFFFC
#89  play on        4 U          flag 0->1
#96  locker room                 last-play day +1 (after midnight), salary 319->462
#108 START          16 U         count 7->8, Card Arrange: new-entry players 11->16
#113 START          10 U         count 9->10, SALARY 462->0, TERM 88->83, PRIZE 9394->0,
                                  win streak 6->0, official streak 3->0            <- 2nd penalty
#114 locker room    I1 + 134 U   flag 1->0, prize 0->1721                                  counter 0xFFF6
#116 START          4 U          flag 0->1   (s4 was left here: flag 1, count 10)
```

---

## 7. Damage handling and penalties

### 7.1 Damage, by case [V unless marked]
| case | what the game does | where |
|---|---|---|
| copy A bad, B good | reads B; the next save rewrites A, since its blocks differ from what was read [I] | FUN_004d7bb0, FUN_004d7530, FUN_004d71f0 |
| both copies bad | detection error 0xA -> FUN_004d8a80 returns 5 -> "ICCardError" [I from FUN_004d8a80 with IS_RINGEDGE on] | 0x004d649d |
| a copy all zeros (sum 0, stored 0) | error 0xA, even if the other copy is good | FUN_004d7bb0 |
| copies differ, both valid | copy A wins silently | FUN_004d7bb0 |
| blank card (counter 0xFFFF) | no checksum check; block 7 written, data zeroed, Club Make | notes 3.4; log |
| counter low byte 0 / 1 | error 8 (used up) / error 7 (last use, soft) | notes 3.3 |
| SYSTEM_VERSION 1-4 | error 4 | notes 3.4 + this map |
| block 7 != block 0 | error 6 (anti-copy) | notes 3.4 |
| a save that cannot finish (card gone) | "write pending" stays; when the interface is destroyed the image goes to the battery backup (the slot with the same block 0, or the oldest by last-play day) | ~IccInterface @0x004d5d46 -> FUN_004d76f0(...,1) |
| **improper flag or WAN flag = 1 at insert** | message **SYS_GAME_warning_0001** "This Club Card did not end normally last time. Its data may not be saved correctly. Also, any entry for a data match will be cancelled." | condition 0x004ee140 (flag or WAN flag), in the message table record at 0x00AF4D58 (code 0xC06) |

**A cut in the middle of a save** [I, from the write order in FUN_004d71f0 and the copy choice in FUN_004d7bb0]:
- The game writes copy A's changed blocks in ascending order and ends copy A with its checksum (block 112), before
  it touches copy B.
- Cut while copy A is half written: A fails its checksum, and copy B (the previous save) is read.
- Cut while copy B is being written: copy A is already complete and is read.
- So a valid card survives either way. A cut during a locker-room save can still lose that match: if B is read,
  it holds the START image with the flag at 1, so the next START counts a cut.
- This needs the card **file** to stay whole. The new reader replaces the file in one step after each block; the old
  one rewrote it in place and could leave an empty file (memory note `wccf-1011-card-session-safety`).

How the message link was settled: the message table has 0x140-byte records with the condition function as the
**last** field (+0x13C). This was proved on the four card-dispenser records: each condition tests the code of the
record it closes (0x004edfc0 tests 0xC1B, the code of SYS_DIS_error_0001; and so on). So 0x004ee140 belongs to
SYS_GAME_warning_0001, not to the next record's "This cabinet is offline" [V].

**Game backup (battery memory)** [V code; offsets V on copies]:
- FUN_004d76f0 keeps 10 slots of 0xFB0 bytes: +9 = the card's block 0 (the key), +0x19 = copy A as saved. A normal
  save always uses **slot 0**.
- In `mxsram.bin` the area starts at **0x4C00** (4 bytes + "GWBS", slot 0 at 0x4C08), with a full mirror at
  **0xEA00**.
- The dev install's `seat1\mxsram.bin` holds the player's club, identical to s2b's copy A, in both
  areas. `seat1_dev_backup\mxsram.bin` holds s4.
- Staff "Club Card Recovery Mode" (ICCardBackUpSequenceNode; texts SYS_SYS_warning_0021-0028) writes a slot back
  onto a card whose block 0 matches (FUN_004d7830 / FUN_004d7940).
- **Kit caveat** [I]: every kit card has the same block 0, UID, serial and SYSTEM_CARD_ID. So recovery would
  restore the last club saved on that seat onto any card.

### 7.2 Penalties [V FUN_005e4cd0, FUN_005e4ef0, FUN_005e4e00; V replay]
At START (once per session), if USER_INJUSTICE_FLAG = 1, the game does this:
1. count + 1;
2. reports it to the server if linked;
3. runs **FUN_005e4ef0(count)**;
4. clears the flag.

Then the session-start save sets the flag to 1 again. The same happens for the WAN flag, which also bumps the WAN
count. FUN_005e4ef0:
- **if count is a multiple of 5** (the period, default 5):
  - **COACH_SALARY - 5,000** (stored units, i.e. **$500,000 on screen**; floor 0, so in practice $0);
  - **COACH_LAST_TERM - 5** (only if above 0; floor 1);
  - **CLUB_GET_PRIZE - 250,000** (floor 0);
  - **CLUB_RECORD_SERIES_WIN = 0** and **CLUB_RECORD_OFFICIAL_SERIES_WIN = 0** (the best-ever streaks stay);
  - **CLUB_WT_THIS_TITLE_POINT - 5,000** (floor 1 if it was above 0);
  - **CLUB_WT_SUCCESSION_CHAMPION_NUM = 0**;
  - then a warning is shown (FUN_004ec560), most likely SYS_SYS_warning_0041 "...a penalty was applied to some
    play data" [I].
- **if count >= 2** (the threshold, default 2) **and trades are left**: **CLUB_TRADE_REMAINDER_NUM = 0**
  (SYS_SYS_warning_0043, loss of trade rights [I]).

Seen live (replay #87 and #113): salary 496 -> 0 and 462 -> 0, term 99 -> 94 and 88 -> 83, prize 9394 -> 0,
streaks 6 -> 0 and 3 -> 0.

**Where the amounts come from** [V cabinet side; I server side]:
- FUN_005e4e00 loads them from the network-settings object (FUN_00407870) at +0x575 term, +0x576 period,
  +0x578 salary, +0x57C prize, +0x580 WT, +0x59E trade threshold. If the period or threshold is below 1 it uses 5
  and 2.
- control_Release.exe initialises a settings block at 0x00405da0 with exactly 5, 5, 5000, 250000, 5000 and 2 at
  offsets +1, +2, +4, +8, +0xC, +0x2A. Those are the cabinet offsets minus 0x574.
- So the penalty amounts are **control-server settings sent to the cabinet**, in the message GAME_CTRL [V]:
  control fills its game-server block (`+0x638`) with these defaults at start-up (FUN_0043bf00 → FUN_00405da0, at
  0x0043bf5f) and sends it to each cabinet at INIT (FUN_00434450); the cabinet stores it at `+0x574` (FUN_00409bc0).
  A game server's server-info reply would replace them. Traced in `ALLNET-ONLINE-2010-11.md`, section 4.2.

---

## 8. The decoder and its output on each sample

**File:** `.work\research\club_card\decode_club_card.py`, with its data table `club_card_schema.py` beside it
(generated from the exe by `make_schema_module.py`).
- **Read-only:** the card is opened `rb`, read in one go and closed.
- **Exit codes:** 0 = the game would accept the card; 1 = the game would refuse it (or `--diff` found
  differences); 2 = the file cannot be read.

Modes:
- summary (default);
- `--all` (every field off its default; add `--defaults` for all);
- `--json`;
- `--diff OTHER`;
- `--copy A|B`;
- `--verify-schema` (re-reads the 7 descriptor tables from the exe and compares);
- `--sram MXSRAM` (lists the game's backup slots);
- `--redact-dates` (used for this report).

**Tests run** [V]:
- `--verify-schema`: "429 fields ... IDENTICAL".
- Hostile cards built in `tests\` by `make_test_cards.py`, with results:

| test card | exit | result |
|---|---|---|
| empty | 2 | cannot read |
| 100 bytes | 2 | cannot read |
| 4,113 bytes | 2 | cannot read |
| bare 4,096-byte dump | 0 | decoded |
| blank new card | 0 | "new card: checksums are not checked" |
| copy A corrupt | 0 | reads copy B |
| both corrupt | 1 | REFUSED 0xA |
| copy B zeroed | 1 | REFUSED 0xA |
| version 3 | 1 | FAIL error 4 |
| block 7 changed | 1 | FAIL error 6 |
| counter 0xFF00 | 1 | FAIL error 8 |
| status 0x20 | 1 | FAIL error 5 |
| copies differ, both valid | 0 | reads A |

- Every sample decoded twice gave identical output.
- The original card files still equal the copies, except s1's original, which a later session rewrote after I
  copied it (that later state is s1b; I never opened any original for writing).
- **Not tested:** cards written by anything other than this build; a bit-level fuzz of the payload.

Outputs below are verbatim, with `--redact-dates`. Full outputs, including `--all`, are in
`.work\research\club_card\output\`.

**s1 (test club アアア, locker-room save, the screenshot state)**
```
CARD FILE  samples/s1_test_aaa_locker.bin
header     uid deadbeef  Card Status 0x18  use counter 0xFFF8  padding zero: True

CHECKS (the reader-level checks the game makes at detection)
  Card Status byte                   0x18         ok   must not be 0x20 (else error 5)
  block 4 signature                  0x40667195   ok   must be 0x40667195 (else error 4/5)
  block 6 serial                     10000001     ok   must be >= 10,000,000 (else error 4)
  use counter (block 5)              0xFFF8       ok   in use; 7 decrements since new
  block 7 == block 0                 True         ok   anti-copy binding (else error 6)
  SYSTEM_VERSION (block 8 bytes 0-3) 5            ok   1-4 are refused (error 4)

CHECKSUMS  (sum of 419 little-endian dwords; the game stores sum+1 and accepts sum or sum+1)
  copy A (blocks 8-112)    sum 0x0D489CCC stored 0x0D489CCD  GOOD (sum+1: written by the game)
  copy B (blocks 113-217)  sum 0x0D489CCC stored 0x0D489CCD  GOOD (sum+1: written by the game)
  copy A == copy B: True
  verdict: copy A is good: the game reads copy A
  OVERALL: the game would accept this card
  decoded: copy A

CLUB
  manager            アアア   (reading ｱｱｱ')
  club               アアアア   (reading ｱ'ｱｱｱ)
  founded            [date]   card made [date]   last played [date]
  card version       5
  Regular League     division 2, leg 3: W2 L0 D1, goals 8-1, 7 points, position 1 (computed), 1 (stored rank+1)
  all matches        manager W5 D1 L0; club W5 D1 L0; win streak 2 (best 3); official streak 2
  annual salary      992  (= $99,200 on screen)
  prize money        8961   finance points 26259   supporters 2268
  contract left      94 matches   manager level 0   stadium name index 20
  trades             rights 0, remaining 0

SESSION SAFETY
  improper flag      0  (closed: last write was a locker-room save or a game-over state)
  improper count     3  (penalties: trade rights at 2+, money/contract/streaks at every 5th)
  WAN flag / count   0 / 0
  unsent plays       6  (matches since the server last confirmed this card)
  network IDs        manager 0  card 0   card id 10000001   shop id 0
  coach id (server key) (16 bytes, left out here)

SQUAD (16 registered players)
  #   card   name                   pos back apps goals asst cond fatigue mastery injury
  0   3691   BENAGLIO               GK  1    4    0     0    4    109     16      -
  1   2562   SAMUEL                 DF  25   4    0     0    4    155     15      -
  2   9928   KOEMAN                 DF  12   4    0     0    3    78      15      -
  3   2416   HYYPIA                 DF  4    0    0     0    1    0       11      1/1/0
  4   9798   GULLIT                 MF  10   4    0     0    3    72      8       -
  5   3762   CORDOBA                DF  2    0    0     0    0    0       15      -
  6   2610   DIARRA                 MF  6    4    0     1    2    76      11      -
  7   3735   FLAMINI                MF  16   3    0     0    1    16      19      -
  8   3637   OWEN                   FW  7    4    1     0    3    135     26      -
  9   9799   CRUIJFF                FW  14   4    3     0    4    36      8       -
  10  9859   KRASIC                 MF  27   4    2     0    3    84      11      -
  11  9731   ADEBAYOR               FW  13   2    4     0    0    60      19      -
  12  9795   VAN BASTEN             FW  9    4    0     2    3    80      17      -
  13  3312   MARADONA               FW  15   4    0     4    3    44      8       -
  14  2608   PEPE                   DF  3    3    0     0    4    72      11      -
  15  3731   T.SILVA                DF  33   1    0     0    1    0       12      -
```

**s2b (the player's club, after the restart; this is the card in the installed kit)**
```
CARD FILE  samples/s2b_after_restart.bin
header     uid deadbeef  Card Status 0x18  use counter 0xFFF4  padding zero: True

CHECKS (the reader-level checks the game makes at detection)
  Card Status byte                   0x18         ok   must not be 0x20 (else error 5)
  block 4 signature                  0x40667195   ok   must be 0x40667195 (else error 4/5)
  block 6 serial                     10000001     ok   must be >= 10,000,000 (else error 4)
  use counter (block 5)              0xFFF4       ok   in use; 11 decrements since new
  block 7 == block 0                 True         ok   anti-copy binding (else error 6)
  SYSTEM_VERSION (block 8 bytes 0-3) 5            ok   1-4 are refused (error 4)

CHECKSUMS  (sum of 419 little-endian dwords; the game stores sum+1 and accepts sum or sum+1)
  copy A (blocks 8-112)    sum 0xE47543D3 stored 0xE47543D4  GOOD (sum+1: written by the game)
  copy B (blocks 113-217)  sum 0xE47543D3 stored 0xE47543D4  GOOD (sum+1: written by the game)
  copy A == copy B: True
  verdict: copy A is good: the game reads copy A
  OVERALL: the game would accept this card
  decoded: copy A

CLUB
  manager            (the player's name)   (reading: its kana)
  club               (the player's club name)   (reading: its kana)
  founded            [date]   card made [date]   last played [date]
  card version       5
  Regular League     division 2, leg 5: W5 L0 D0, goals 15-2, 15 points, position 1 (computed), 1 (stored rank+1)
  all matches        manager W10 D0 L0; club W10 D0 L0; win streak 10 (best 10); official streak 5
  annual salary      985  (= $98,500 on screen)
  prize money        12990   finance points 17501   supporters 2703
  contract left      90 matches   manager level 0   stadium name index 15
  trades             rights 0, remaining 0

SESSION SAFETY
  improper flag      0  (closed: last write was a locker-room save or a game-over state)
  improper count     1  (penalties: trade rights at 2+, money/contract/streaks at every 5th)
  WAN flag / count   0 / 0
  unsent plays       10  (matches since the server last confirmed this card)
  network IDs        manager 0  card 0   card id 10000001   shop id 0
  coach id (server key) (16 bytes, left out here)

SQUAD (16 registered players)
  #   card   name                   pos back apps goals asst cond fatigue mastery injury
  0   9810   VÍTOR BAÍA             GK  1    5    0     0    2    40      24      -
  1   9793   F.DE BOER              DF  4    5    0     0    3    84      24      -
  2   2224   CANNAVARO              DF  5    4    0     0    2    36      24      -
  3   3289   FERDINAND              DF  12   3    0     0    2    0       24      1/1/0
  4   3293   GERRARD                MF  15   4    0     0    2    20      29      -
  5   9922   CANTONA                FW  7    5    1     2    3    45      25      -
  6   2229   BALLACK                MF  13   2    1     0    1    0       25      -
  7   2206   KAKÁ                   MF  22   5    0     1    3    60      24      -
  8   2236   PELÉ                   FW  17   5    4     3    4    60      24      -
  9   3988   MESSI                  FW  18   4    1     0    2    24      24      -
  10  3301   CRISTIANO RONALDO      FW  16   5    6     2    2    88      24      -
  11  9795   VAN BASTEN             FW  9    3    2     0    3    16      24      -
  12  1334   VIEIRA                 MF  14   5    0     0    2    57      24      -
  13  9798   GULLIT                 MF  10   3    0     0    1    12      24      -
  14  9797   RIJKAARD               MF  8    4    0     0    4    16      24      -
  15  1781   MALDINI                DF  3    3    0     0    3    48      24      -
```

**s2a (the player's club, written at a START, then cut)** (the CHECKS and the squad are as for s2b; the rows that differ:)
```
header     uid deadbeef  Card Status 0x18  use counter 0xFFF5  padding zero: True
  use counter (block 5)              0xFFF5       ok   in use; 10 decrements since new
  copy A (blocks 8-112)    sum 0x00A2772F stored 0x00A27730  GOOD (sum+1: written by the game)
  copy B (blocks 113-217)  sum 0x00A2772F stored 0x00A27730  GOOD (sum+1: written by the game)
  OVERALL: the game would accept this card
  Regular League     division 2, leg 4: W4 L0 D0, goals 11-1, 12 points, position 1 (computed), 1 (stored rank+1)
  all matches        manager W9 D0 L0; club W9 D0 L0; win streak 9 (best 9); official streak 4
  annual salary      870  (= $87,000 on screen)
  prize money        11951   finance points 18425   supporters 3053
  contract left      91 matches   manager level 0   stadium name index 15
  improper flag      1  (a session is open, or the last one did not end normally)
  improper count     0  (penalties: trade rights at 2+, money/contract/streaks at every 5th)
  unsent plays       9  (matches since the server last confirmed this card)
```

**s3 (old test club ＡＡＡＡ)**
```
header     uid deadbeef  Card Status 0x18  use counter 0xFFF7  padding zero: True
  use counter (block 5)              0xFFF7       ok   in use; 8 decrements since new
  copy A (blocks 8-112)    sum 0xED55E63C stored 0xED55E63D  GOOD (sum+1: written by the game)
  copy B (blocks 113-217)  sum 0xED55E63C stored 0xED55E63D  GOOD (sum+1: written by the game)
  OVERALL: the game would accept this card
  manager            アアア   (reading ｱｱ'ｱｱｱｱ)
  club               ＡＡＡＡ   (reading ｴｰｴ'ｰｴｰｴｰｱ)
  Regular League     division 2, leg 5: W4 L0 D1, goals 10-0, 13 points, position 1 (computed), 1 (stored rank+1)
  all matches        manager W6 D1 L0; club W6 D1 L0; win streak 0 (best 6); official streak 0
  annual salary      787  (= $78,700 on screen)
  prize money        7793   finance points 18996   supporters 1237
  contract left      93 matches   manager level 0   stadium name index 5
  improper flag      0  (closed: last write was a locker-room save or a game-over state)
  improper count     3  (penalties: trade rights at 2+, money/contract/streaks at every 5th)
  unsent plays       7  (matches since the server last confirmed this card)
  (squad: the same 16 players as the player's club, earlier in their growth)
```

**s4 (first club 東京ＳＣ: improper count 10, two penalties)**
```
header     uid deadbeef  Card Status 0x18  use counter 0xFFF6  padding zero: True
  use counter (block 5)              0xFFF6       ok   in use; 9 decrements since new
  copy A (blocks 8-112)    sum 0x3DA97807 stored 0x3DA97808  GOOD (sum+1: written by the game)
  copy B (blocks 113-217)  sum 0x3DA97807 stored 0x3DA97808  GOOD (sum+1: written by the game)
  OVERALL: the game would accept this card
  manager            アイイシ   (reading ｱ'ｲｲｼ)
  club               東京ＳＣ   (reading ﾄｳ'ｷｮｳｴｽｼｰ)
  Regular League     division 2, leg 3: W2 L1 D0, goals 8-2, 6 points, position 3 (computed), 3 (stored rank+1)
  all matches        manager W7 D0 L1; club W7 D0 L1; win streak 1 (best 6); official streak 0
  annual salary      0  (= $0 on screen)
  prize money        1721   finance points 25647   supporters 3757
  contract left      82 matches   manager level 0   stadium name index 0
  improper flag      1  (a session is open, or the last one did not end normally)
  improper count     10  (penalties: trade rights at 2+, money/contract/streaks at every 5th)
  unsent plays       8  (matches since the server last confirmed this card)
  squad: BUFFON, NESTA, MALDINI, STAM, CAFU, SEEDORF, ABBIATI, PIRLO, KAKÀ, SHEVCHENKO, RONALDO, ROBINHO,
         INZAGHI, RUI COSTA, GATTUSO, COLOCCINI
```

**`--sram` on the copy of the dev install's mxsram.bin**
```
SRAM samples/mxsram_revd_seat1.bin (2097152 bytes)
  area at 0x04C00  header 92 ce 0f 8b 47 57 42 53
    slot 0  key deadbeef221802000000000000000000  checksum GOOD  manager (name)  club (club name)  last played [date]  improper flag 0 count 1
  area at 0x0EA00  header 92 ce 0f 8b 47 57 42 53
    slot 0  key deadbeef221802000000000000000000  checksum GOOD  manager (name)  club (club name)  last played [date]  improper flag 0 count 1
```

---

## 9. The club card on a private server (wccf.online)

Marked **DESIGN** where it is a proposal. The facts it rests on are tagged as elsewhere.

### 9.1 What exists today [V]
- `_icc_reader.py` keeps the card in memory and answers the game's commands. After every 'U', 'S' and non-zero
  'I' it rewrites the card file. The new reader does this as temp file + flush + replace.
- The reader cannot see the game's intent, only its commands. But the saves have clear shapes (section 5.2), and
  the reader holds the decoded state:
  - **session start / play on** = 4 U (blocks 12, 112, 117, 217) + 14 R;
  - **locker room** = about 100+ U + 14 R + I by 1;
  - **Club Make** = I by 1 + about 138 U + 14 R.
- The **improper flag is one bit**: block 12 byte 10, mask 0x10, in the reader's own memory. 1 = a session is
  open.

### 9.2 The card on the server, tied to the account (DESIGN)
1. **Load before the game reads.** At kit start (PLAY), the launcher signs in to wccf.online and downloads the
   account's card image (4,112 bytes) into the local card file. Then the reader starts. The game reads the card
   at its first detection.
2. **Save after every completed save, not every block.** A save is complete when a run of 'U's is followed by the
   game's 14 'R' read-back. Also upload after every 'I' by 1 (the use counter). Upload the whole image with:
   - the account;
   - a local sequence number;
   - the hash of the previous image;
   - the decoded flag and count (for the server's own view).

   The server keeps **every version**, so it can always roll back.
3. **Both the START save and the locker-room save matter.** The START upload (flag 1) tells the server "a session is
   open on PC X". The locker-room upload (flag 0) closes it. The server should refuse to hand the same card to a
   second PC while a session is open.
4. **The same bit fixes the kit's STOP guard.** `play.py stop check` can ask the reader "is block 12 byte 10 bit
   0x10 set?" instead of the card sensor, which reads "out" mid-match (memory note).

### 9.3 What the server may change, and what it must never touch (DESIGN on [V] rules)
**May change**, between sessions only and within each field's min-max:
- names: COACH_NAME, CLUB_NAME and readings; Shift-JIS, at most 55 bytes + NUL;
- money: COACH_SALARY (units of $100), CLUB_GET_PRIZE, CLUB_FINANCIAL_POITN, CLUB_SUPPORTER_NUM;
- contract COACH_LAST_TERM (keeps a card alive: at 0 the counter is set to "last use");
- league state, records, titles;
- player growth: PLAYER_MASTERY, OPINION_*, ABILITY_UP_*;
- shirt numbers;
- trades: CLUB_TRADE_RIGHT_NUM, CLUB_TRADE_REMAINDER_NUM;
- improper count and flag (forgiveness, section 9.5).

Note: **PLAYER_CARD_NO is overwritten from the cards on the table at every save** (FUN_005e7a20 inside
FUN_005dcc70) [V]. A squad change made on the server lasts only until the next save, unless the table matches.

**Must never touch:**

| what | why |
|---|---|
| blocks 0, 4, 6, 7 of an existing card | identity, the must-fail signature, serial, anti-copy binding (block 7 must equal block 0) [V] |
| the use counter, except on purpose | 0xFFFF makes the game zero the card and start Club Make; 0 = used up [V] |
| SYSTEM_VERSION | must stay 5; 1-4 are refused [V] |
| SYSTEM_COACH_ID | the key the game matches NETWORK_ID replies against [V] |
| the checksum words | always recomputed, never edited [V] |
| copy B on its own | must be byte-identical to A, as the game writes it [V] |
| values outside min-max | the game clamps when it sets a value but **not** when it reads the card [V FUN_00424260]; an out-of-range value reaches the game unchecked [I] |
| any edit while the game holds the card | the game rewrites only the blocks **it** changed, plus its own checksum. A server edit underneath leaves mixed blocks under a checksum that fits neither, and the card is refused (error 0xA) [I from FUN_004d71f0 + FUN_004d7bb0] |

The penalty amounts look like a **server** setting (control's block at 0x00405da0, section 7.2) [I]. A private
server could probably tune or switch off the penalties there rather than editing cards. Test that before relying on
it (section 10).

### 9.4 Keeping the copies consistent when the server edits (DESIGN)
1. Take the copy the game would read (the decoder's verdict).
2. Decode, change the fields, re-encode the 1,676 bytes: same group order, MSB first, no padding.
3. checksum = (sum of the 419 LE dwords + 1) mod 2^32. Copy A = payload + checksum; copy B = the same 1,680 bytes.
4. Check with `decode_club_card.py --diff` against the old image:
   - both copies GOOD and A == B;
   - only the intended fields changed;
   - OVERALL accept.
5. Store the new version, keep the old one, and deliver it only at the next kit start.

An encoder is **not built**. The decoder's layout (`LAYOUT` in `decode_club_card.py`) is the basis for one.

### 9.5 Offline play and network drops (the improper-flag rules applied)
**The game's rules** [V]:
- The flag is 1 from START to the locker room. Anything that ends the game in between (crash, kill, restart,
  power cut, Error 3000 + restart) leaves it at 1.
- The next START adds 1, and penalties follow at count 2 (trades) and every 5th.
- Online today, a lost link to control means Error 3000 and a restart (`docs\NETWORK-MAP-2010-11.md` section 8)
  [cited], so **a drop mid-session is a cut**.
- A vanished player-vs-player opponent instead turns into a CPU match, saved normally (same source) [I].

**With a server card** (DESIGN):
1. **The local card is the truth during a session; the server is a mirror.** If the locker-room upload fails, keep
   it queued and send it later in order.
2. **Never let an older server image replace a newer local one.** Example: the server holds the flag-1 START image
   and the local card has the flag-0 locker-room image. Loading the server copy would create a false improper
   count. Use the sequence numbers.
3. **A real cut stays a cut.** If the PC dies mid-session, the server holds the START image (flag 1). The next load
   counts the cut, which is Sega's rule against pulling the plug.
4. **Forgiveness is a policy choice for the server's owner.** If the server itself caused the cut (its own crash or restart,
   logged while a session was open), it can clear the flag on the stored image before the next load. That is done
   between sessions, with the checksum recomputed. The match is still lost; the penalty is avoided.
5. **Offline play:** allowed on the local cache, marked unsynced, uploaded on reconnect. If another PC played the
   same card meanwhile, refuse the upload and ask the server's owner. Never merge two careers.

### 9.6 What Sega's own protocol already gives the server [V], and the account link (DESIGN)
- **ENTRY SVR** (each session at Card Arrange, and at Club Make): the **full card payload**, plus the matching
  history and WT ranks (section 5.4). The server sees the whole club before each session.
- **Play data** after each locker room: the full payload again.
- **Improper count** reports (FUN_00446cf0) and penalty notices (FUN_00446d60).
- **NETWORK_ID** (control -> cabinet, FUN_00408b90) brings a 16-byte ID plus two 32-bit numbers. If the 16 bytes
  equal the card's SYSTEM_COACH_ID and both numbers are non-zero, the cabinet:
  - writes them into SYSTEM_NETWORK_COACH_ID and SYSTEM_NETWORK_CARD_ID;
  - sets USER_FAILURE_TRANSMISSION_PLAY_NUM to 0;
  - fills SYSTEM_SHOP_ID if empty;
  - stores all of these at its next save.

  On a mismatch it marks the reply **rejected** (network object +0x500 = 2) [V]. That probably shows "Club Card
  data is invalid. Server authentication failed." [I]. **Warning:** a rejection seen in the locker room makes
  FUN_005d3920 set the WAN flag and save. The next START then counts it as an improper session [V code chain, not
  seen live; gated by the node's +0xFC, see section 5.2]. A private server must never answer NETWORK_ID with an ID
  that does not match the card.
- **Account link** (DESIGN):
  1. Key each club by SYSTEM_COACH_ID. It differs per club in our samples, because it carries the creation time.
  2. On the first ENTRY SVR from a signed-in kit, bind that key to the account.
  3. Answer NETWORK_ID with (account number, card number). From then on, every payload the cabinet sends carries
     the account number inside the card. The "unsent plays" count also stops climbing.
- **Caveat** [I]: every kit card shares card ID 10,000,001, UID `DE AD BE EF` and the same block 0. Cards issued by
  the server should get their own UID, block 0 (= block 7) and block-6 serial when they are created. Then
  SYSTEM_CARD_ID and the battery backups are unique too.

---

## 10. Open questions (each with the read or test that settles it)

1. **"Matches $15100" and "Titles $000"** on the locker-room screen are not stored values. Settle: decode the card
   before and after one match and photograph that locker room. If Matches = (salary after - salary before) x 100,
   the inference holds.
2. **Stadium name list**: is CLUB_STADIUM_NAME 20 "Otsu Ground"? Settle: find the name list (game text or sprites)
   that the stadium screen draws from, and check index 15 against the player's stadium name.
3. **Attendance** ("10960 fans"): how it follows from CLUB_SUPPORTER_NUM. Settle: log both over a few matches.
4. **COACH_TOTAL_CHAMPIONSHIP_NUM and Title[28], Title[29]** hold values that do not fit, and they are the same on
   every card. Settle: read the code that writes these fields (FUN_00421a40 callers with their descriptions), or
   decode a card straight after Club Make.
5. **Units** of CLUB_GET_PRIZE and CLUB_FINANCIAL_POITN. Settle: find the screen that shows them and compare with a
   decoded card.
6. **The penalty settings path**: which message copies control's block into the cabinet at +0x574? Settle: find the
   cabinet handler that copies 0x38 bytes into the FUN_00407870 object. Or, on a test kit with a throwaway club,
   change control's default and watch one penalty.
7. **The clean-test SRAM** has an initialised but empty backup area (`--sram` on its copy). Settle: compare that
   mxsram.bin before and after one locker-room save, and read that kit's hook log.
8. **The `'` in name readings** (ｱｱｱ', ﾄｳ'ｷｮｳ...). Settle: make a test club with a known reading, then decode.
9. **Repeated detection** about every 35 s while a card sits on the reader between sessions. Settle: reader log with
   the attract screens recorded alongside.
10. **USER_WT_POINT_TRANSMISSION_FLAG** (when 1 the locker room skips its save): who sets it? Settle: xref the
    description string 0x00a356c4 (writers besides FUN_005dcdc0).
11. **SYSTEM_COACH_ENTRY_TIME format** [I]: make a club and compare the value with the clock at Club Make.
12. **ENTRY SVR's 16-character text and 16-bit value** (+0x52A, +0x53A of the settings object). Settle: capture one
    ENTRY SVR at control.
13. **Effects of a high "unsent plays" count**: only one other reader was found (FUN_005deb10, a copy between
    parameter sets). Settle: xref 0x009e42d0 further.
14. **The WAN flag's triggers**: when the locker-room node's +0xFC gate is set (FUN_005d3920), and what the
    server-supplied +0x568 = 2 means (written in FUN_004e7c80). Settle: xref the writers of +0xFC in the
    LockerRoomSequenceNode functions, and capture the message FUN_004e7c80 parses at control. Live, use the two-seat
    online test from the network map, with a throwaway club.

---

## 11. Sources

**Code** (`.work\ghidra_out_1011_classes\client\`, addresses as `FUN_xxxxxxxx`; plus disassembly via
`.work\_disasm.py`):
- **Payload:** FUN_00422210 (parse; jump table 0x0042241c), FUN_00422440 (serialize), FUN_00422120 (size),
  FUN_00424130/FUN_00424260 (bit reader), FUN_004240d0/FUN_004241e0 (bit writer), FUN_00424190 (bytes per group),
  FUN_00422b70 (object slots), FUN_004220b0 (16 players, 30 titles).
- **Groups:** common::parameter::*ParameterBase::vfunction2/3/4.
- **Field access:** FUN_00421a40 (lookup by description), FUN_00422900 (set with clamp), FUN_005dd240 / FUN_005dd300.
- **Checksums and saving:** FUN_004d7b70, FUN_004d7bb0, FUN_004d7530, FUN_004d7d20, FUN_004d7e00, FUN_004d71f0,
  FUN_004d76f0, FUN_004d7680, FUN_004d7830, FUN_004d7940, FUN_004f18d0, FUN_004f1920, FUN_004d8b60, FUN_004d8c90,
  FUN_004d8a80; detection result at 0x004d6441-0x004d64c2.
- **Moments:** FUN_005dcc70, FUN_005dcd40, FUN_005dd1b0 (disassembly 0x005dd1b0-0x005dd22f), FUN_005740e0,
  TeamCardCheckSequenceNode::vfunction21, FUN_005e4cd0 (disassembly 0x005e4cd0), FUN_005e4ef0, FUN_005e4e00,
  FUN_005e4b80, FUN_005e4c80, FUN_005e4b30, FUN_005e4c30, FUN_005e4bd0, FUN_005ec6e0, FUN_004eb870, FUN_00411f00,
  game::LockerRoomSequenceNode::vfunction20/22, FUN_005e77b0, FUN_005e5170, FUN_005e51c0, FUN_005e5410,
  FUN_005e7a20, FUN_005dcba0, FUN_005d3920, FUN_005ec760, club_make::SaveNewClubDataNode::vfunction21,
  FUN_005e6060, AdvertiseSequenceNode::vfunction20.
- **Did-not-end check:** 0x004ee140 (not indexed by Ghidra; disassembly) and the message table records at
  0x00AF2F54-0x00AF4E94.
- **Server:** FUN_0044ba20 (ENTRY SVR), CardArrangeSequenceNode::vfunction20, club_make::SeqContractPlayer::vfunction2,
  FUN_0044bbd0, FUN_004509b0, FUN_00408b90 (NETWORK_ID, called from FUN_00407050), FUN_005d3920 (locker-room
  reply handling, called from LockerRoomSequenceNode::vfunction21 @0x005d35cb), FUN_004e7c80 (+0x568),
  FUN_00407870, FUN_00406920, FUN_00409c30; control_Release.exe 0x00405da0.
- **Backup:** ICCardBackUpSequenceNode::vfunction20/21, FUN_0040bf40.
- **Strings:** resolved from `client_Release.exe` with `.work\research\club_card\jstr.py` (Shift-JIS descriptions),
  `peek.py`, `msgtable.py`, `xref.py`.

**Data:**
- the samples in the table at the top;
- `.work\shots\remote_seat1_d.png`;
- `.work\_icc_seat1_log.txt` (reader log of the first club);
- mxsram copies (`seat1\` beside the game folder, `seat1_dev_backup\`, `.work\release1011\cleantest\game\seat1\`);
- `.work\playercards1011\catalogue.tsv`;
- `.work\release1011\kit\english\screen_text.tsv` (message texts);
- `.work\release1011\kit\source\mxhook\mxhook.c` (lines 157-307: `\\.\mxsram` -> `mxsram.bin` in the working
  folder).

**Tools written for this** (all in `.work\research\club_card\`):
- the deliverable: `decode_club_card.py` + `club_card_schema.py` (from `make_schema_module.py`);
- schema work: `schema.py`, `schema_dump.py` -> `schema.tsv`, `explore.py`, `compare.py`, `blocks.py`,
  `field_positions.py`, `catalogue_check.py`;
- exe access: `pe.py`, `peek.py`, `jstr.py`, `xref.py`, `msgtable.py`;
- backups: `sram_scan.py`, `sram_find.py`;
- reader log: `icclog_writes.py`, `icclog_order.py`, `icclog_replay.py`, `icclog_excerpt.py`;
- tests: `make_test_cards.py` -> `tests\`;
- results: `output\`.

**Where this disagrees with or sharpens earlier notes:**
- `docs\NETWORK-MAP-2010-11.md` section 8:
  - It said "the player's real club ... improper count is most likely 0 [I]; the agent guessed 1". **The card reads 1**
    (s2b) [V]. The cut session at s2a was counted at the restart.
  - "Salary -5,000": the amount is in the card's units of $100, so it is **-$500,000 on screen**. In practice the
    salary becomes $0 (seen twice in the replay) [V].
  - "Every win streak reset": precisely the **current** club streak and the **current** official streak (plus
    consecutive WT titles). The best-ever streaks are kept [V].
  - "The server writes a network manager ID + card ID": the **cabinet** writes them, and only when control's
    NETWORK_ID reply carries the card's own 16-byte manager ID. It also resets the unsent-plays count and fills the
    shop ID [V FUN_00408b90].
  - "The last-played date is local YYMMDD": confirmed, and it is written at the **locker room** (FUN_005ec6e0), not
    at START [V].
- `.work\icc_protocol_notes.md`:
  - Section 4: "block8[0..3] big-endian not in 1..4: purpose unknown". It is **SYSTEM_VERSION**, the first payload
    field (5 on every card) [V].
  - Section 4: "Not mapped: which parameter sits at which bit offset". Now mapped, all 429 fields [V].
  - Section 3.6: "If the counter was 0xFFFF it then sends I Decrement 1". True in code, but at Club Make the
    decrement already came **before** the write (FUN_005dd1b0, job 2). That rule therefore did not fire. Net: one
    decrement [V log + code order].
- Memory note `wccf-1011-card-session-safety.md`: its five write moments and "game over writes nothing" are
  confirmed in code and in the reader log [V]. Its "salary -5,000" needs the same precision as above.
