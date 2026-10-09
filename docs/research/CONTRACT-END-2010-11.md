# When the manager's contract runs out (WCCF 2010-11, the PC build)

> Research notes from the maintainers' workspace, shared here on 2026-10-09 so the club card work is not done
> twice (for 2010-11 and later versions). Paths under `.work\` are research tools and card samples that are not
> in this repository. Player names and the personal data of real cards are left out.

Static analysis of `client_Release.exe` (Rev D), the kit's scripts and the earlier research docs, written 2026-10-08.
**Read-only:** nothing was started, no kit or game file was written, and no player's card was opened. The only card
data quoted is from the copies already in `CLUB-CARD-2010-11.md` (its sample names s1-s4 are used here).

"Contract" here means the **manager's contract on the club card** (`COACH_LAST_TERM`), not the retired browser
project in `rebuild\`.

Tags: **[V]** read in the code or bytes (address given) or in a named file. **[I]** inferred (the reason is given).
**[A]** not known.

---

## 1. The verdict in plain words

- **At 0 the club ends. The game has no way to keep playing that club.** After the match that takes the contract to
  0, the locker room saves the club as usual, then marks the card "last use". The next time that card goes in, the
  game shows *"Contract ended on this Club Card. Insert it with a new Club Card to transfer manager data."*, offers no
  START, and after the countdown says *"Time's up. Club Card discharged."* The club's data is still on the card,
  unchanged.
- **The new-card step is real, but it moves the MANAGER, not the club.** You insert the expired card and a blank card
  **stacked together**. The game copies the manager (name, salary, level, career record, titles, histories), the
  league division, and the growth of players who have a "mentor/disciple" bond, onto the new card. Then you build a
  **new club** in Club Make (home town, name, kit, emblem, squad). The old card's counter is set to 0 and it can never
  be played again. The club itself (its name, money, squad, league table, records) does **not** move.
- **The kit cannot do that transfer today.** Its card reader stand-in holds one card only.
- **So "add a new card and keep the club" is not something the game does.** The smallest way to get it is a kit tool
  that **renews the contract on the card file** between sessions: set the matches left back up (the game allows up to
  150) and refresh the card's use counter. The club stays exactly as it is. The plan is in section 6.
- The contract can also grow in play: sponsor missions and a few other events add matches (section 3.5).
- A second limit exists: the card's **use counter** wears out after about 253 locker-room saves, contract or not.
  Then the card shows the same "Contract ended" screen (section 3.4).

---

## 2. The two numbers that decide it

| number | where | what it does | tag |
|---|---|---|---|
| **COACH_LAST_TERM** (監督任期残り), "matches left" | payload byte 197 of each copy = block 20 byte 5 (copy A), block 125 byte 5 (copy B); a whole byte, 8 bits | default 100, max 150. -1 at the end of every match. The game reads it as "contract ended" when it is 0 | [V schema.tsv: Coach group byte 76 + bit 968 = payload bit 1576 = byte 197; FUN_005edea0] |
| **use counter** (block 5) | the kit's card file header, bytes 5-6 | 0xFFFF = blank card. -1 at Club Make and at each locker-room save. The game looks only at the **low byte**: 0xFF = new, 2-0xFE = normal, **1 = last use ("expired")**, **0 = used up ("transferred")** | [V FUN_004d74f0 returns the counter `& 0xFF`; FUN_004d6c40 count = V & 0xFF (icc_protocol_notes 3.4)] |

The game decides the card's state in **FUN_004d8a80** @0x004d8a80 [V disassembly 0x004d8a80-0x004d8b5a]:

| returns | when | meaning |
|---|---|---|
| 0 | primary card's counter low byte = 0xFF | new card |
| 1 | otherwise | normal club card |
| 2 | detection error 7 (counter 1), **or contract = 0**, or counter 0 on the primary | **contract ended** |
| 3 | two cards seen (+0x3848 = 2) and a two-card state (+0x3858 > 0) | **transfer** (old + new card) |
| 4 | detection error 8 (counter 0) | **already transferred** |
| 5 | detection failed (with IS_RINGEDGE on) | card error |

---

## 3. The path after 0

### 3.1 How the contract moves before it reaches 0

- **-1 per match**: FUN_005edea0, called at the end of each match from `game::ClientGameSequenceNode::vfunction22`
  @0x005CD63A, does `if (term > 0) term = term - 1` in memory [V FUN_005edea0 lines 43-59]. The locker room then
  saves it. In an "event" mode (an object at `[DAT_0113751c+8]` with byte +5 = 1) the contract does not move [V; I that
  this is the WCCF Cup].
- **Penalty**: at every 5th improper count, -5, but never below 1, so a penalty alone never ends a contract [cited
  `CLUB-CARD-2010-11.md` 7.2].
- **Resign** (`MAN_Regist_message_0004` "You can resign before your contract ends."): offered when the contract is above
  1, the club has played more than 19 matches, the manager has not resigned already, and no event mode is on [V
  FUN_005d9940: term > 1, NO_SAVE_CLUB_GAME_NUM > 0x13, COACH_RESIGN != 1]. Saying yes runs
  `SeqMngRegResign::vfunction3` → FUN_00556bd0 → FUN_005570b0 → **FUN_005dd060**, which sets **COACH_LAST_TERM = 1**
  and **COACH_RESIGN = 1** [V FUN_005dd060 @0x005dd060-0x005dd093: `FUN_00422900(1,0,0)` on both]. The texts:
  "Resign from this club?", "If you resign, this Club Card can no longer be used.", "To transfer your data, you'll need
  a new Club Card.", "I'll process your resignation. Make the last one count." [V screen_text.tsv MAN_RETIRE_*; FUN_00556de0
  holds MAN_RETIRE_message_0000].
- **Accepting another club's offer** ("Taking a new offer means you resign. Unlike a normal resignation, your manager
  skills carry over better.") runs FUN_00536cc0: CLUB_OFFER_ACCEPT, CLUB_RL_SUCCESSION_DIVISION (the next club's
  division) and **COACH_LAST_TERM = 1** [V FUN_00536cc0 @0x00536e16; jstr on its fields].
- So the last match comes from one of three things: the count running down, a resignation, or an accepted offer.
  All three end the same way.

### 3.2 The final match and its locker room

| step | code | what the player sees | card reader | tag |
|---|---|---|---|---|
| before the match | management info, FUN_0052d940 | *"Your contract's final match is here."* and one of five lines about how the team did (INF_TERM_message_0000-0005) | none | [V the text is referenced only in FUN_0052d940; A the exact condition] |
| match end | FUN_005edea0 | - | none | term 1 → 0 in memory [V] |
| locker room, on entry | `LockerRoomSequenceNode::vfunction20` @0x005d2479-0x005d24ad | - | - | a node flag (data +4) starts at 1 and is cleared when COACH_LAST_TERM = 0 [V] |
| locker room save | same function @0x005d2734-0x005d2742: FUN_005e5410, **FUN_005dcc70** (save), then **FUN_005dd1b0** | - | the normal save: about 100-140 'U', 14 'R' | [V] |
| "last use" | **FUN_005dd1b0** @0x005dd20a: term ≤ 0 and counter low byte > 1 → FUN_004d8f90 → **job 3** | - | **'I' by (low byte - 1)**: the counter's low byte becomes 1 (in the kit, e.g. 0xFFF0 → 0xFF01) | [V FUN_005dd1b0; IccInterface::vfunction2 case 3; I the kit value, from `_icc_reader.py` 'I' handling] |
| contract-end screen | `LockerRoomSequenceNode::vfunction21` state 6 @0x005d34d4: flag 0 → state 7 → FUN_006f4c10 / FUN_006f5cc0 → FUN_006f6010 | the contract-end results: **Prize Money, Previous (starting salary), Last Pay** (the kit's money map D11), and *"Well done in your final match."* plus a line such as *"Sadly, the match was lost. Move on and go for wins with a new team."* (INF_TERML_message_0000-0009) | none | [V call chain; V FUN_006f6010 holds INF_TERML_message_0000; V `MONEY-2010-11.md` D11 = FUN_006f4c10] |
| end | state 7 → 8 → "Game Over" | Game Over | none | [V states 7 and 8 exit only to state 8 or "Game Over"; I that no play-on is offered] |

Normal matches (term > 0) instead post **job 2**, 'I' by 1 [V FUN_005dd1b0 @0x005dd21a-0x005dd22a].

### 3.3 The next session, with the expired card alone

| step | code | what the player sees | card reader | tag |
|---|---|---|---|---|
| detection | FUN_004d6060 / FUN_004d6c40 | - | the usual existing-card reads: 'U' 4 (must fail), 'I' by 0 (reads the counter: low byte 1), 'T' 8, 'T' 0, 'T' 7, 14 'R', 'E' | [V; read order from icc_protocol_notes 3.3-3.4] |
| the card is an "old card" | FUN_004d6c40: count 1 → old-card slot (+0x3850), two-card state +0x3858 = 2, **not** made primary | - | - | [V FUN_004d6c40 C lines 105-111] |
| verdict | FUN_004d6060 @0x004d6441-0x004d6450: one card, checksums good → **error 7** (bad → error 0xA) | - | - | [V] |
| load | FUN_004d8b60 accepts error 7 and loads the club | - | - | [V] |
| IC CARD LOADING | FUN_00572c70: FUN_004d8a80 = 2 → result 1 | - | - | [V] |
| Team IC Card Check | `TeamCardCheckSequenceNode::vfunction20` @0x005743d0, case 2 | the manager card window with ***"Contract ended on this Club Card. Insert it with a new Club Card to transfer manager data."*** (MAN_DATA_message_0001); status 1 to FUN_00576ab0 | none | [V; I that status 1 draws the header "Expired" (MAN_DATA_header_0001)] |
| no START | FUN_005740e0 starts a session only for result 1 or 3 (or 2/4 in the event mode) | START does nothing | none | [V FUN_005740e0 C line 56] |
| timeout | FUN_005740e0: countdown < 0 → FUN_004d8ee0(1) (the card interface is closed) → "ICCardTimeOut" | ***"Time's up. Club Card discharged."*** (SYS_SYS_warning_0006) | none; nothing is written to the card | [V; text from the kit's `english\sega_rstring.tsv`; I "nothing written", from the paths: no save is reached] |

The card is not changed by this session, so the club stays readable on it [I from the code paths above].

The messages with "expired" in their wording (SYS_SYS_warning_0007 "Contract expired. Insert old and new cards
together...", 0009 "Club Card has expired. You cannot use an expired Club Card at this time.") are not shown on this
path: 0009's condition needs the event mode (FUN_004ed4f0), and 0007 has no condition of its own (the stub
`FprInterface::vfunction17`) and no code was found raising it [V message table at 0x00AE8000-0x00B00000, record = id
text, code at +0xC, condition at +0x13C].

### 3.4 Other cases

- **Counter worn out with contract left.** FUN_005dd1b0 decrements while the low byte is above 1 [V], so after Club
  Make (0xFF → 0xFE) and 253 more locker-room saves the low byte reaches 1. The next detection gives error 7, and
  FUN_004d8a80 returns 2: the same "Contract ended" screen with matches still left [I from the code; never seen live].
  From the s2b sample (counter 0xFFF4) that is 243 more matches away [V arithmetic on that copy; A where the card is
  now].
- **Contract 0 but counter still above 1** (not something the game makes itself): FUN_004d8a80 returns 2, and
  FUN_005dd130 at Team IC Card Check posts job 3, making the counter 1 [V FUN_005dd130; TeamCardCheck vfunction20
  @0x005748ac].
- **A card already transferred** (counter 0): one card, count 0 → two-card state 3 → **error 8** [V FUN_004d6060
  @0x004d6407]. FUN_004d8a80 returns 4: *"Data transferred from this Club Card. You can't play with this Club Card."*
  (MAN_DATA_message_0002), and the system message ***"Error 5110 Manager data has already been transferred from this
  Club Card."*** (SYS_SYS_warning_0010, condition 0x004ED550: error 8) [V]. Whether it then goes through Team IC Card
  Check or straight to ICCardError (FUN_00572c70 sends any raised system code to ICCardError) is [A].

### 3.5 Can the contract be renewed?

Yes, but only by events in play, and only while it is above 0 [V for the writers below; A for the amounts]:
- **FUN_005379c0** (from `SeqInfoMission::vfunction2`, the sponsor mission info) and **FUN_00537fe0** (from
  `SeqInfoNote` and `SeqInfoGoldenAge`): `COACH_LAST_TERM = term + NO_SAVE_CLUB_RENEW_CONTRACT_NUM`, shown as
  "Matches left: %d" and "Contract +%d matches" [V; INF_CONTRACT_contents_0000/0001].
- The texts *"Contract extended by %d matches."* (FUN_0052f1c0) and *"This win also completed the sponsor's task. Your
  contract is extended by %d matches."* (FUN_0052ebc0) [V].
- The setter clamps at 150 [cited `CLUB-CARD-2010-11.md` 3: FUN_00422900 clamps to min-max].
- Who sets NO_SAVE_CLUB_RENEW_CONTRACT_NUM, and to what, was not found: the only four references read it [V xref
  0x00A253E8; A the writer].
- The card also has COACH_LEVEL_CONTRACT_NUM (renewals, max 5) and COACH_LEVEL_CONTRACT_PASS (matches since one, max
  25) [V names in schema.tsv; A their use].
- Once the counter is at 1 nothing in the game can restart that card: no session can begin (3.3).

---

## 4. The new-card transfer (Sega's flow)

Sega's word is 継承, "succession": the manager's abilities are inherited by a new card. The Japanese warning says to
insert the old and new cards "２枚重ねて" (two cards stacked) [V `.work\translation\english_test\main_screens_jp.tsv`,
SYS_SYS_warning_0007].

### 4.1 What the reader must see

Both cards must be on the reader when IC CARD LOADING starts: the game detects cards only then
[cited icc_protocol_notes 3.2]. Detection reads slot 0, halts it ('E'), then reads slot 1, which is the second card
answering the next Request [V FUN_004d6060 loop, C lines 89-116].

| card | its counter | what FUN_004d6c40 does | tag |
|---|---|---|---|
| expired card | low byte 1 | becomes the **old card** (+0x3850), state +0x3858 = 2, never primary; its block 7 must equal its block 0 | [V] |
| blank card | 0xFFFF | becomes the **primary**: 'U' 7 := block 0, then blocks 8-217 zeroed with 14 'S' | [V; notes 3.4] |
| a transferred card | low byte 0 | old card, state 3 | [V] |
| any other club card | 2-0xFE | primary; a second primary gives **error 9** | [V] |

The two-card verdict [V FUN_004d6060 @0x004d62f0-0x004d6353]: state 1 → error 4 (state 1 is never written in this
build, so the old 2005-06 carry-over path is dead [V FUN_004d6c40 writes only 2 and 3; FUN_004d6060 writes 0]);
primary not blank, or state 0 or 3 → **error 9**, shown as ***"Error 5113 Do not insert 2 or more cards. Transferring
manager data needs an expired card and a new card."*** (SYS_SYS_warning_0013, condition 0x004ED620) [V]. Otherwise the
cards are ready and FUN_004d8a80 returns 3.

### 4.2 The screens

| step | code | what the player sees | tag |
|---|---|---|---|
| IC CARD LOADING | FUN_00572c70: result = 2 - (state != 1) → 1 | - | [V] |
| Team IC Card Check | vfunction20 case 3 | ***"Transfer data to sign a contract."*** (MAN_DATA_message_0003), status 2 | [V; I header "Transferable"] |
| START | FUN_005740e0: FUN_004d8a80 = 3 → **"Club Make"** (not "Card Arrange") | Club Make | [V] |
| Club Make | FUN_0045bde0: transfer → FUN_005dce10 (`ParameterClient::succeedSaveData()`), then the sequence starts at step 5 instead of 0 | the licence steps (name, birthday) are skipped; the contract steps follow: home town, club name, uniform, emblem, players | [V call and the 5/0; I which steps, from the creation order in `SeqClubMakeMain::vfunction2`: LicenceTop, LicenceName, LicenceBirthday, LicenceEnd, ContractTop, ContractHome, ContractClubName, ContractUniform, ContractEmblem, ContractPlayer, ContractEnd] |
| WCCF Cup | condition 0x004ED660: FUN_004d8a80 = 3 in the event mode | *"You cannot transfer manager data during the WCCF Cup."* | [V] |

The English in `SYS_SYS_caution_0008` (*"Insert this Club Card together with a new one to transfer your manager
data. [Manager] %s [Club] %s"*) is drawn only when the system code is 0xBCD (SYS_SYS_warning_0008, Error 5109), whose
condition at 0x004ED4B0 always returns 0 and which no code raises [V: `xor al, al` before both returns; xref finds
0xBCD only in ICCardError's compare]. So that screen is not reachable in this build [I].

### 4.3 What is copied to the new card

FUN_005dce10 reads the old card into parameter set 3 (FUN_004d7530, the copy the game trusts) and copies into set 2,
the new club, only when the two-card state is 2 [V]. Fields by function (read with `jstr.py --from-c`):

| function | fields | tag |
|---|---|---|
| FUN_005dddd0 (runs first) | the new card's own SYSTEM_CARD_ID, SYSTEM_COACH_ENTRY_TIME, SYSTEM_SHOP_ID, SYSTEM_MACHINE_SERIAL_NO, SYSTEM_COACH_ID | [V fields; I it writes fresh values] |
| FUN_005de670 | **SYSTEM_COACH_ID (16 bytes) and SYSTEM_NETWORK_COACH_ID copied from the old card**, so the manager keeps the server key; data-match and ranking weeks, ranking No.1 counts, location-test flags, match-offer default; SYSTEM_VERSION and last play day set fresh | [V read in full] |
| FUN_005def80 | manager name, reading, birthday; **salary** (also into COACH_SUCCESSION_SALARY); **succession count + 1**; level, title, career W/D/L, titles, Regular League count, best official streak, level/title/league histories, the 2005-06 fields, sponsor, downloaded uniforms, reserves | [V fields; V the salary and the +1 at C lines 96-160] |
| FUN_005decf0 | the new club's start and current division = the old card's **CLUB_RL_SUCCESSION_DIVISION**; data-match weeks; NO_SAVE_CLUB_COACH_SUCCESSION = 1 | [V read in full] |
| FUN_005e08f0 | for each of the 16 players whose **PLAYER_MASTER_DISCIPLE** (選手師弟関係) is set: card number, mastery, growth bursts, style, key-player experience, favour, respect, dissatisfaction count, training counts, and the partnership values between such players | [V read in full; I "mentor/disciple" is the meaning] |
| FUN_005deb10, FUN_005e10c0, FUN_005e11d0, FUN_005e80f0, FUN_005e16e0 | camera, data display and friend-list types, unsent plays; Title records; WT ranking No.1 counts, WT/JWC champion wins, the manager's training slots, downloaded comic kit, CPU win; meet-participation flag | [V fields touched; I copied, from the same pattern as above, not read in full] |

**Not copied**: the club name and reading, emblem, uniform, stadium, home town, money (prize money, finance points),
supporters, the squad (apart from bonded players), league table and position, club records and streaks, trades,
tactics, and COACH_LAST_TERM (so the new contract starts at the default 100) [I: none of these is in the copy
functions' field lists; Club Make builds them].

### 4.4 What happens to the old card, and in what order

1. Leaving Club Make, `ClubMakeSequenceNode::vfunction22` → FUN_0045bfa0 → **FUN_005dd0b0** [V]:
   - serialises the new club (FUN_00422440) and passes it to **FUN_004d7580**, which puts it in the **new** card's
     staging buffer with its checksum and keeps a battery backup **keyed by the old card's block 0** [V FUN_004d7580:
     primary slot +0x384c for the buffer, +0x3850 + 0x18 for the key];
   - posts **job 4**: select the old card, **'I' by its whole counter word**, so its counter becomes **0** [V
     IccInterface::vfunction2 case 4]. **No data blocks of the old card are written**: its club stays on it intact
     [V: job 4 sends only 'I'].
2. `SaveNewClubDataNode::vfunction21` waits ("Wait for Succeeded ...") while DAT_011374c7 is set; after 300 frames, or
   if DAT_011374c0 is set, it raises an error [V]. Then the same save as a normal Club Make: improper flag on, job 2 on
   the new card ('I' by 1: 0xFFFF → 0xFFFE), FUN_005efb20(1), FUN_005dcc70 (job 5: about 138 'U', 14 'R') [V].
3. Failure texts: *"Error 3084 / 3085 Could not write the manager data transfer. Club Card discharged. ... In card
   recovery mode, insert together the two Club Cards used for the transfer."* (SYS_SYS_warning_0037/0038, codes
   0xC0C/0xC0D) [V texts and codes; A which failure raises which].

**The old card is killed before the new one is written** (step 1 before step 2) [V order]. A crash between the two
leaves a dead old card and a blank-looking new one. The old club's data is still on the old card [V], so it is
recoverable by resetting its counter [I].

### 4.5 What control (Sega's server) sees

- **ENTRY SVR** is sent at Club Make (`SeqContractPlayer`) and before every match (Card Arrange), carrying the whole
  serialised club, so control receives the new club with the **old** SYSTEM_COACH_ID [cited `ALLNET-ONLINE-2010-11.md`
  4.3; V FUN_005de670 for the copied ID].
- **In the kit, control records nothing and refuses nothing**: it never forwards entries to a game server
  (IS_RINGEDGE = 0, no GAME_SVR_ENTRY), no NETWORK_ID comes back, and the card check (GMSVR_RANK) is not even sent for
  cards whose network IDs are 0, which is every kit card [cited ALLNET 4.3, 4.4].
- **Collisions**: every kit card has UID `DE AD BE EF`, the same block 0 and serial 10,000,001 [cited `CLUB-CARD`
  7.1, 9.6]. Nothing on the server side keys on those today [I]. Inside the game they do matter for a two-card
  transfer: the presence poll re-selects each card by UID, and the battery backup keys by block 0, so two cards with
  the same UID and block 0 cannot be told apart [I from FUN_004d6a90 and FUN_004d76f0 as described in the notes].
- With a real game server, the new card would come with the same manager key and a new card ID. control logs
  "AlreadyIssue" / "MultiIdErr" by what the server answers [cited ALLNET 4.3]; what Sega's server did is [A].

---

## 5. The kit today

- **The card reader stand-in** (`.work\_icc_reader.py`, staged unchanged into `kit\scripts\`) [V]:
  - one `Card`, loaded **once** when the reader starts, from `data\save\seat1_club.bin`;
  - always "present"; it ignores the card sensor. After 'E' (Halt) the next Request answers "no card" until 'N', so
    the game always sees **exactly one card**;
  - after every 'U', 'S' and non-zero 'I' it rewrites the **whole** file from memory (temp file, flush, replace); the
    first save after 60 s of quiet copies the file on disk into `data\save\backup\` first;
  - job 3 and job 4 decrements work as plain 'I' amounts: an expired card's header would read 0xFF01, a transferred
    one 0x0000 [V the 'I' code; I values].
- **play.py** starts the reader with that one file (line 412) and runs `apply_card_request()` before the reader
  starts, which carries out the CLUB CARD panel's `card=FILE` / `card=new` through `club_wallet.switch()`: two renames,
  no card overwritten [V play.py 346-360, 497, 795; club_wallet.py].
- **The CLUB CARD panel** (`.work\wccfpanel\wccfpanel.c`, view written by `club_view.py`) shows "CONTRACT N matches
  left", yellow at 10 or fewer [V club_view.py 162-163]. It checks the counter only for 0xFFFF [V line 146]: an
  expired card shows "CONTRACT 0 matches left" and no word "expired", and the panel does not show the counter's
  remaining life [I]. A card with counter 0 is shown as "the game would refuse this card" [I from the decoder's error-8
  test].
- **What would happen today when the contract ends:**
  - the game shows the expired screen and times out, every session [V 3.3];
  - **NEW CLUB CARD** in the panel moves the expired club into `cards\` and puts a blank in the slot. With one card
    on the reader the game makes a **new manager licence and a new club**; nothing is transferred [V switch(); I the
    game path: one blank card → ICCardNew → Club Make from step 0];
  - the old card stays in `cards\`, expired, with its club intact, but cannot be played [I].
- **A second card in the middle of a session:**
  - the game would never see it: detection runs only at IC CARD LOADING, and the reader has one card [V];
  - replacing `seat1_club.bin` while the reader runs: the reader's next save writes its own in-memory card over the
    new file [V save()]. The replaced file survives only in `backup\`, if that save was the first after 60 s of quiet
    [I];
  - the card sensor (key I) going out and in changes nothing in the reader [V]; in the game, pulling the card
    mid-match has no visible effect through the reader [cited notes 3.5].

---

## 6. The plan (written before the choice was made; plan B was built afterwards)

### 6.1 The choice

| | A. Renew the contract (keep the club) | B. Sega's transfer (keep the manager) |
|---|---|---|
| what the player keeps | everything: the same club, squad, money, league | manager name, salary, level, records, titles, division, bonded players' growth |
| what the player loses | nothing | the club; the old card can never be played again |
| size of the change | one function in `club_wallet.py`, a request word in `play.py`, a line in `club_view.py`, later a panel button | a second card in the reader, a second card file, new requests, a panel button |
| authentic | no (the kit edits the card) | yes |

The player first asked to keep the club, so this report plans A in full and lists B in 6.4. **Decided afterwards: B, Sega's own transfer** - when a contract ends you put in a new card, as on the arcade. The code shared with this report does B; plan A was not built.

### 6.2 Plan A: "RENEW CONTRACT", in place, between sessions

Files and changes:

1. **`.work\release1011\kit\scripts\club_wallet.py`**: add `renew(slot=SLOT, term=100)`, run only where `switch()`
   runs (before the card reader starts):
   - refuse when the file is missing, the wrong size, a blank card (0xFFFF), or the game would refuse it
     (`decode_club_card.game_choice`);
   - copy the card file into `data\save\backup\` under a new name before anything (never into `cards\`: a second
     playable copy of the same club would make two careers with one manager key);
   - take the copy the game reads; set payload byte 197 (COACH_LAST_TERM) to `term` (1-150);
   - recompute the checksum (sum of the 419 little-endian dwords, + 1) and write the same 1,680 bytes to copy A
     (blocks 8-112) and copy B (blocks 113-217);
   - if the counter's low byte is below a threshold (say 20), set the header counter to **0xFFFE**; never 0xFFFF
     (that makes the game wipe the card and start Club Make);
   - touch nothing else: blocks 0-7, the improper flag and count, the IDs, SYSTEM_VERSION;
   - write by temp file, flush, replace (the reader's own pattern);
   - read it back: the decoder must accept it, A must equal B, and a field diff against the backup must show only
     COACH_LAST_TERM (and the counter). On any failure, put the backup back and say so.
2. **`.work\release1011\kit\scripts\play.py`**: in `apply_card_request()`, accept `card=renew` and call
   `club_wallet.renew()` at the same safe moment as a switch.
3. **`.work\release1011\kit\scripts\club_view.py`**: a state for "contract ended" (term 0 or counter low byte ≤ 1)
   and for "transferred" (counter low byte 0), and a row "card life: N matches" (counter low byte - 1).
4. **Later, `.work\wccfpanel\wccfpanel.c`**: a RENEW CONTRACT button in the CLUB CARD panel, armed by a first click
   like NEW CLUB CARD, writing `card=renew` and asking for RESTART NOW. This needs the DLL rebuilt, its SHA-256 in
   `stage_kit.py`, and `fstest_clubcard` again. Until then the request line can be written by hand or by a
   `play.py renew` command.
5. **A check left behind**: `club_wallet_renew_test.py` beside it, running the cases in 6.5 T1 on generated cards.

Open choices (not decided here): the new term (100 is the game's default, 150 its maximum); whether
a resignation (COACH_RESIGN = 1, CLUB_OFFER_ACCEPT) is undone too; whether `play.py` renews by itself at a start when
the term is low, so the player never sees the end screen.

### 6.3 Risks, biggest first

1. **Editing the card while the reader or the game holds it.** The reader would write its memory over the edit, or
   the game would rewrite only its own changed blocks under a checksum that fits neither, and refuse the card
   (error 0xA) [cited `CLUB-CARD` 9.3]. Guard: renew only in `apply_card_request()`, before the reader starts, and
   refuse when any kit process runs.
2. **Losing the club through a bad write.** Guards: the backup first, the read-back and diff, the automatic restore,
   and never a counter of 0xFFFF.
3. **The player's own card last.** Every test runs on copies and on the test kit; the player's real card only
   with the player's word.
4. **Older copies of the club elsewhere**: the game's battery backup (`mxsram.bin`) keeps the last saved image keyed
   by block 0; staff Club Card Recovery Mode could write that older image back [I]. Only if that menu is used.
5. **Unknown side effects** of raising the term on events that look at it (sponsor offers, contract renewals, the
   "final match" message) [A], and of leaving COACH_RESIGN at 1 after a resignation [A].

### 6.4 Plan B, Sega's transfer (the one chosen and built)

- `_icc_reader.py`: a second card with its **own** UID, block 0 (= its block 7) and serial; Request / Anticoll /
  Select / Halt routed by the selected card; 'R', 'T', 'U', 'S', 'I' on the selected card; each card saved to its own
  file.
- `play.py` / `club_wallet.py`: a `transfer=FILE` request that puts the expired card and a fresh blank on the reader
  at the next start, and afterwards makes the new card the slot card and moves the old one (counter 0) to `cards\`.
- Risk: Sega's order kills the old card before the new one is written (4.4). The reader's backup holds the old card,
  and its club data is untouched, so it can be revived [I].

### 6.5 Test plan (copies and the test kit `.work\release1011\cleantest\kit_user` only)

- **T1, no game running**: copy `kit_user\data\save\cards\AAAA.bin` and `Rosso.bin` into a scratch folder. Renew them;
  check with `decode_club_card.py --diff` that only the contract (and the counter) changed. Hostile cases: an empty
  file, 100 bytes, 4,113 bytes, both copies bad, a blank card (0xFFFF), counter 0, term already 150, a read-only
  file, renewing twice, and killing the tool between the temp file and the replace (the original must be intact).
- **T2, the final match** (the test kit with `play.py local`, at a time the player agrees, never the player's own kit): use the tool with
  `term=1` on a copy, put it in kit_user's slot through the wallet, play one match. Expect the "final match" message,
  the contract-end screen (Prize Money, Previous, Last Pay), Game Over, the reader log showing a counter decrement to
  0x??01, and the decoded card with term 0.
- **T3, the expired card**: insert it again. Expect "Contract ended on this Club Card...", no START, then "Time's up.
  Club Card discharged.", and the same file hash before and after.
- **T4, the renewal**: with everything stopped, renew that card; play one match. Expect it accepted, term 99, the
  counter one lower, the improper flag closed, and only the match's own changes in the diff.
- **T5, the wallet round trip**: switch to another test card and back; the renewed card is still accepted.
- **T6 (only for plan B)**: two test cards on the two-card reader; check 4.1-4.4 step by step.

---

## 7. Open questions

| # | question | tag | settles it |
|---|---|---|---|
| 1 | When exactly the "Your contract's final match is here." message shows (term 1?) | [A] | T2 screenshot; or read FUN_0052d760's caller condition |
| 2 | That the last locker room offers no play-on | [I] | T2 |
| 3 | A card with counter 0: Team IC Card Check or straight to ICCardError | [A] | a copy with counter 0x0000 on the test kit |
| 4 | The size of in-game contract extensions (writer of NO_SAVE_CLUB_RENEW_CONTRACT_NUM not found) | [A] | find the setter that passes the field in a register; or watch a sponsor mission |
| 5 | The 253-save card life | [I] | a copy with counter 0xFF02 and term above 0: after one match it should show "Contract ended" |
| 6 | Whether a resignation must be undone (COACH_RESIGN, CLUB_OFFER_ACCEPT) when renewing | [A] | read FUN_005de110 and FUN_005e0170, which read both |
| 7 | Which Club Make steps a transfer skips (step 5 = home town?) | [I] | read `SeqClubMakeMain` state handling, or T6 |
| 8 | What FUN_00576ab0's status 0-3 draws ("Active / Expired / Transferred / Transferable"?) | [I] | T3 screenshot |
| 9 | What Sega's server did with a transferred manager | [A] | no server to ask; only matters for a future private server |
| 10 | Where the player's real card stands now (term, counter) | [A] | his own decode, when he chooses (not read for this map) |

---

## 8. Sources

- **Code** (`.work\ghidra_out_1011_classes\client\`, plus `.work\_disasm.py` on `client_Release.exe`):
  FUN_005dd1b0, FUN_005dd130, FUN_005dd060, FUN_005dd0b0, FUN_005edea0, FUN_004d8a80, FUN_004d74f0, FUN_004d8f90,
  FUN_004d8fb0, FUN_004d7580, FUN_004d7530, FUN_004d8b60, FUN_004d6060 (0x004d6300-0x004d64c2), FUN_004d6c40,
  FUN_004d5dc0, FUN_004d8ee0, `wccf::io::IccInterface::vfunction2`, FUN_00572c70, `ICCardLoadingSequenceNode::vfunction21`,
  `ICCardNewSequenceNode::vfunction20/21`, `ICCardErrorSequenceNode::vfunction20`, `ICCardTimeOutSequenceNode::vfunction20`,
  `TeamCardCheckSequenceNode::vfunction20/21`, FUN_005740e0, FUN_00574bc0, `game::LockerRoomSequenceNode::vfunction20`
  (0x005d2460-0x005d2760) and `vfunction21` (0x005d2eb0-0x005d3600), FUN_006f5cc0 → FUN_006f6010,
  `club_make::SaveNewClubDataNode::vfunction21`, FUN_0045bde0, FUN_0045bfa0, FUN_0045c390, `SeqClubMakeMain::vfunction2`,
  FUN_005dce10, FUN_005db4c0, FUN_005dddd0, FUN_005de670, FUN_005deb10, FUN_005decf0, FUN_005def80, FUN_005e08f0,
  FUN_005e10c0, FUN_005e11d0, FUN_005e80f0, FUN_005e16e0, FUN_005d9940, FUN_00536cc0, FUN_005379c0, FUN_00537fe0;
  message conditions 0x004ED4B0-0x004ED700.
- **Tools** (`.work\research\club_card\`, run read-only): `xref.py`, `jstr.py`, `pe.py`; the message-table walk was
  an inline script, nothing saved.
- **Data**: `.work\research\club_card\schema.tsv`; `.work\release1011\kit\english\screen_text.tsv` and
  `sega_rstring.tsv`; `.work\translation\english_test\main_screens_jp.tsv`.
- **Kit**: `.work\_icc_reader.py`, `.work\release1011\stage_kit.py`, `kit\scripts\play.py`, `club_wallet.py`,
  `club_view.py`, `kit_common.py`, `english.py`; `.work\wccfpanel\wccfpanel.c` (searched, not read in full).
- **Docs**: `CLUB-CARD-2010-11.md` (field map, penalties, save path), `ALLNET-ONLINE-2010-11.md` 4.2-4.4,
  `MONEY-2010-11.md` D11, `.work\icc_protocol_notes.md` 3-4.

**Where this sharpens earlier notes:**
- `icc_protocol_notes.md` 10 said the two-card transfer was "traced only far enough to note errors 8/9 and job 4".
  Sections 4.1-4.4 above trace it through Club Make. Job 4 writes only the counter; the new club goes to the new card
  by the normal save.
- `CLUB-CARD-2010-11.md` 9.3 lists COACH_LAST_TERM as a field a server may change "to keep a card alive". Add: the
  counter's low byte must also stay at 2 or above, or the card shows "Contract ended" with matches left (3.4).
