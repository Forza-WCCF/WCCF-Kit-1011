# WCCF 2010-11 - coins, credits and free play (read-only research)

Written 2026-10-09. Nothing was run, started or changed. Sources: Sega's client (client_Release.exe: the projector's copy and three seat 1 copies, the same bytes at the
addresses used here), its Ghidra decompile, `control_Release.exe`, `testmode_Release.exe`, this kit's source and one
kit hook log.

Tags: **[V]** read by me (address, decompile line, file line). **[I]** inferred (from what is said). **[A]** not known.

---

## 1. The short answer

- **Credits are counted on the cabinet only** (seat 1, `client_Release.exe`), by Sega's arcade library **amCredit** linked
  into the game. The server does not count coins or charge anything [V, 2].
- **Every play costs 1 credit** [V]. How many coins make 1 credit depends on which branch the game took at start-up
  (1 coin = 1 credit, or Sega's Japanese table where one COIN 1 press counts as 5 coins) [V both branches; which one runs
  on seat 1: A]. Either way one coin is at least one credit [I].
- **A built-in FREE PLAY exists**: byte 2 of amCredit's 16-byte coin setting [V]. On a real cabinet that setting is
  stored in the cabinet's settings chip (EEPROM) and set from the system test menu [I]. The game's own test program
  `testmode_Release.exe` has no FREE PLAY or coin-setting menu [V].
- **The kit cannot switch it on with a file today**: seat 1 never reaches the settings chip (the kit does not emulate
  it), so the game starts from blank settings each time and FREE PLAY is off [I, strong; 3.3].
- **The projector is already free**: with `IS_RINGEDGE=0` the game's free-play test always answers yes [V].
- **Where START-adds-a-coin is not enough**: one screen only - a two-choice screen after a match, decided with PRESS or
  SHOOT, not START [V code]; it appears only when the WCCF Cup data asks for it [I]. Every normal gate (new club card,
  club card check, CONTINUE) is decided by START, so the driver's coin covers it [V].
- **Recommendation**: set amCredit's own FREE PLAY byte in memory from the overlay (`wccfpanel.dll`), the way the
  dispenser fix already patches seat 1: one data byte, `0x00CD0F9A = 1`, after amCredit has started, guarded by a code
  check. No game code changes, no file changes. Then the COIN button can go; keep the driver's FREE_PLAY as the
  fallback for when the overlay does not load (section 5).

---

## 2. How the game counts coins and credits (question 1)

### 2.1 Who counts

- The cabinet. amCredit ("amCredit Ver.1.08 Build:Oct 18 2011", string in client, control and testmode [V]) is driven
  by teaArcade2's `JvsManager`: `initCredit` `FUN_007a3c10@0x007a3c10`, `getCreditString` `FUN_007a3830`,
  `getCreditStatus` `FUN_007a3880`, `isCreditEnough` (check + take) `FUN_007a38e0` [V: their error texts name them,
  all_client.c:1498673-1498785].
- Coins arrive from the JVS I/O board's coin counters: `FUN_0082caa0` -> `FUN_0082c820` (per coin slot, multiplier) ->
  `FUN_0082c4b0` (coins -> credits) [V all_client.c:1699181-1699468, 1698865-1699047]. In the kit those counters come
  from `_keys_seat1.py`'s `coin1=N` line through the I/O board stand-in [V `_keys_seat1.py:314-332`].
- The server (`control_Release.exe`) has no coin logic of its own: its only coin/credit strings are the same shared
  library texts plus the WCCF Cup option line (2.4) [V string scan]. It knows the bookkeeping message name
  `SLS_SVR_BOOK` [V string]; what it does with it is [A] (the cabinet sends coin and credit counters in it - see
  `docs\research\CARD-DISPENSER-2010-11.md` 2.7).

### 2.2 amCredit's state (client addresses)

| Address | What | Tag |
|---|---|---|
| `0x00CD0F90` | 1 = amCredit started (`FUN_0082c240` sets it last) | [V all_client.c:1698834, 1698852] |
| `0x00CD0F98` .. `0x00CD0FA7` | the 16-byte coin setting in use (copied in by `FUN_0082c240`) | [V :1698780-1698786] |
| `0x00CD0FA8` + 2*player | credits (byte) and leftover coins (byte) per player | [V `FUN_0082bdf0`, `FUN_0082c4b0`] |
| `0x00CD0FB8` .. | bookkeeping counters (coins per slot, totals) | [V `FUN_0082c820`, :1699247-1699253] |
| `0x00CD123C` / `123D` / `123E` | credit cap / service-credit cap / player count | [V :1698660-1698664] |

The 16-byte coin setting, as amCredit checks it (`FUN_0082bd00@0x0082bd00`, all_client.c:1697965) and uses it:

| Byte | Meaning (Sega's usual COIN ASSIGNMENTS names) | Allowed | Evidence |
|---|---|---|---|
| 0 | coin chute type: 0 common, 1 individual | 0-1 | 0 -> every player uses credit slot 0 (`FUN_0082bdf0`) [V; name I] |
| 1 | service type | 0-1 | used with byte 0 for service credits (`FUN_0082c6a0`) [V; name I] |
| **2** | **FREE PLAY** | 0-1 | 1 -> credit check always "enough", nothing taken, coins not turned into credits, credit text NULL [V 3.1] |
| 3, 4 | coin chute 1 / 2 multiplier | 1-9 | `FUN_0082c820` :1699235-1699243 [V; name I] |
| 5 | bonus adder (0 = none) | 0, 2-9 | `FUN_0082c4b0` :1698907-1698913 [V; name I] |
| 6 | coins per credit | 1-9 | `FUN_0082c4b0` :1698973-1698981 [V] |
| 7-14 | game cost (credits) for play kind 0-7 | 1-9 | `FUN_0082bdf0` reads byte 7+kind [V] |

### 2.3 What the coin setting is on seat 1

`FUN_004f2040@0x004f2040` (run once at start-up from `FUN_00401530` via `FUN_004f1fd0` [V callers]) builds it:
- Only with `IS_RINGEDGE=1` (`DAT_00aeac72`) [V :394790].
- It starts from the game's copy at `0x00BF2038` (= `FUN_007a2ed0()` + 0x28 [V 0x007a3a6c-0x007a3a73]).
- If `FUN_00406900()` is true (`*DAT_0113751c != 0` and `+0x10 == 0`; what it means is [A]) it overwrites the copy with
  Sega's fixed setting **but keeps byte 2 (FREE PLAY) as stored** [V :394844-394852]: common chute, COIN 1 x5,
  COIN 2 x1, bonus adder 5 (or a bonus table), 3 coins per credit, every play 1 credit. Then a bonus table is chosen
  from the game's SPECIAL CREDIT mode 1-8 [V :395020-395134]. The tables match `testmode_Release.exe`'s texts exactly
  ("MODE_1: 3 COINS 1 CREDIT / 5 COINS 2 CREDITS / 10 COINS 5 CREDITS" ... MODE_5 with 5 coins = 3 credits)
  [V: table {0,0,0,0,1,0,0,0,0,4} gives 3->1, 5->2, 10->5; strings at testmode file offset 0x204168].
- Otherwise the copy is passed as it is; on seat 1 it is all zeros (3.3), which amCredit rejects, so it uses its own
  default: common chute, x1, no bonus, **1 coin = 1 credit, every play 1 credit, FREE PLAY 0**
  [V `FUN_0082c240` :1698764-1698786 with `FUN_0082bd00`].
- So: **1 credit per play** in both branches [V]. One COIN 1 press = 1 credit (default) or 5 coins -> 2 credits with the
  bonus (Sega's branch) [I from the arithmetic]. Which branch seat 1 takes: [A]. The credit cap is 24 [V
  `FUN_007a3c10(0x18, 9, 1, 1, 0, 0)` at :394856 and the callback 0x007a3a50, which skips the region adjustment when
  the 4th argument is 1].
- Play kinds: kind 0 = starting a game (new card or club card check), kind 1 = CONTINUE [V: the EDX value at each
  `FUN_004f2410` call, section 4].

### 2.4 Where the credit count is kept

In amCredit's RAM (`0x00CD0FA8`) [V]. At start it is filled from the game's backup buffer `0x00BF2098` (backup record
7) [V 0x007a3ad0-0x007a3ae7 pushes `FUN_007a2ed0()+0x88`; `FUN_0082c240` copies it at :1698820]. On seat 1 that
buffer is never loaded (3.3), so **credits start at 0 at every launch** [I].

---

## 3. Built-in FREE PLAY (question 2)

### 3.1 What it does in the code [V]

With byte 2 of the setting = 1 (`0x00CD0F9A` live):
- `getCreditString` -> amCredit `0x0082BFE0` returns NULL (`cmp byte [0x00cd0f9a], 0 / jne -> return 0`)
  [V disassembly 0x0082bfed-0x0082bff3]. The game's own free-play test `FUN_004f24e0` answers **yes** when that string is
  NULL [V 0x004f2531-0x004f2548].
- `FUN_0082bdf0` (status) returns 2 = enough; `FUN_0082be60` (take) returns 1 and takes nothing [V :1698143, :1698196].
- `FUN_0082c4b0` ignores coins; `FUN_0082c6a0` ignores service credits [V :1698899, :1699076]. The bookkeeping coin
  counters in `FUN_0082c820` still count [V :1699245-1699255].
- The credit display: `FUN_004f2560` returns 1 (free) and `FUN_0047af10` draws its state-1 picture instead of the coin
  or credit picture [V :218599-218633]; what state 1 shows on screen is [A] (probably "FREE PLAY", like the older game's
  attract screen, CONTEXT-HANDOFF.md:776 - the other game, analogy only).

### 3.2 Where Sega keeps it and who sets it

- In amBackup **record 1**: settings chip (EEPROM, region 0) at offset 0x20, 32 bytes with a CRC, mirror at 0x220
  [V record table `0x009CB300`: region 0, offset 0x20, size 0x20, CRC on, mirror 0x220; region 0 = 4 KB, read/write
  functions `0x008311a0` / `0x008312e0` next to `amEepromInit`]. The setting starts 8 bytes into the record (buffer
  `0x00BF2030`, setting at `0x00BF2038`), so FREE PLAY is chip byte 0x2A (mirror 0x22A) [I from those V numbers].
- `testmode_Release.exe` has no FREE PLAY, COIN ASSIGNMENTS or GAME COST item [V: no such text in ASCII, Shift-JIS or
  UTF-16; its menus are INPUT/MONITOR/OUTPUT TEST, GAME ASSIGNMENTS (CABINET TYPE, ADVERTISE SOUND, SATELLITE
  ARRANGEMENT, SPECIAL CREDIT), BOOKKEEPING, BACKUP/HDD CLEAR, NETWORK, IC CARD, CAMERA, CLOSE SETTING, ALL.Net -
  strings at file offsets 0x202d6c-0x204f04]. So on a real cabinet FREE PLAY is set in the RingEdge system's own test
  menu, outside these programs [I].
- No config key: the option files (`local\client_user_option.conf`, `ctrl_user_option.conf`, `mxGetHwInfo.ini`) have
  none [V], and the client's option names have none (CARD-DISPENSER-2010-11.md 2.2, about 80 names checked there) [V
  there].

### 3.3 Why the kit cannot set it with a file today [I, strong]

- The settings chip is opened through Windows' device-setup calls (`SetupDiGetClassDevsA` on Sega's SMBus driver GUID,
  then `CreateFileA`) [V all_client.c:1706526-1706588]. The kit's hook does not provide that device [V
  `source\mxhook\mxhook.c:174-182`: only mxsram, columba and the serial ports], and seat 1's hook log shows no
  `CreateFileA` of any device [V `WCCF-2010-11-kit\data\logs\hook\mxhook_45620.log`: no such line]. So `amEepromInit`
  fails [I].
- When it fails, the backup load `FUN_007a2f00` is skipped (it runs only if the chip and SRAM both started) and the
  game's buffer at `0x00BF2010` stays zeroed [V :1498126, :1498140-1498142]. FREE PLAY is therefore 0 on every start
  [V given the failure].
- (An older note says the game's settings chip "reads/writes a FILE" - CONTEXT-HANDOFF.md:15195. The `eeprom%d.bin` /
  `busram%d.bin` files are teaArcade2's own game regions, `FUN_004f1690`, not amBackup's record 1 [V :393661, :393723].)
- To use Sega's switch from a file, the hook would have to emulate the SMBus device (GUID, four IOCTLs) and the kit
  would ship a chip image with record 1 and its CRC. That also makes the game load every other chip record (region,
  serial, network settings) for the first time - unknown side effects [I]. Not the least invasive route.

### 3.4 The server's FREEPLAY switch (WCCF Cup only)

- Control's operator window has "FREEPLAY MODE" and "PLAYER CARD PAYOUT" switches [V UTF-16 dialog strings at file
  offset 0x2cb9ac, 0x2cba34]; entering cup mode logs "WCCFCUP MODE OPTION : Payout(%d), FreePlay(%d), regulation(%d),
  NextSeat(%d)" [V `FUN_00450e70`, 0x004511a8].
- The cabinet honours it: `FUN_004f24e0`'s first test is cup flag `S+5` and cup byte `T+0xA` (from the WCCFCUP_INFO
  packet) [V 0x004f24e0-0x004f252a; packet mapping V in CARD-DISPENSER-2010-11.md 2.2].
- But it only counts while the server is in **WCCF Cup mode**, which turns the cabinets' attract screen into the cup
  screen ("ClientWccfcup", `AdvertiseSequenceNode::vfunction21` [V classes:2265-2267]) - a tournament, not normal play.
  Not usable for everyday free play [I].

---

## 4. Every place the game asks for credit (question 3)

All direct callers were listed from the binary (`pe.py callers`) and match the decompile [V]: the free-play test
`0x004f24e0` (7 callers), status `0x007a3880` (6), take `0x004f2410` (4).

| Screen (node) | Button that decides | Credit check | Take | START-adds-a-coin enough? |
|---|---|---|---|---|
| New (blank) club card: `ICCardNewSequenceNode::vfunction21@0x005736a0` -> "Club Make" | START (button table entry 6 = player 1 byte 0 0x80 [V table `0x009FBD30`]) | free, or status kind 0 = enough, checked at the START press [V 0x005737f4-0x00573813] | kind 0 (`xor edx,edx` 0x0057381b) [V] | **Yes**: the driver's coin reaches the game 0.15 s before START [I]. Without credit START does nothing and the timer ends in "ICCardTimeOut" [V :584143] |
| Club card check: `FUN_005740e0` (TeamCardCheck) -> "Card Arrange" / "Club Make" | START (entry 6, 0x0057424b) [V] | every frame: no credit = START ignored, ends in "ICCardTimeOut" [V :585120-585126, :585210-585216] | kind 0 after the card animation (0x005742d3) [V] | **Yes** [I] |
| After a match, CONTINUE: `game::LockerRoomSequenceNode::vfunction21@0x005d2eb0` case 1 | START (entry 6, 0x005d316b) [V] | free, or status kind 1 = enough [V 0x005d3149-0x005d3160] | kind 1 (`mov edx, esi`, 0x005d317f) [V] | **Yes** [I]; otherwise "Game Over" when the window closes [V :697610-697612] |
| Two-choice screen after a match: `FUN_006f3690` (sub-step 4 of `FUN_006f35e0`) | LEFT/RIGHT choose (entries 2/3), **PRESS or SHOOT** decide (entries 4/7) [V 0x006f369f-0x006f3755] | choice 1 needs free, or status kind 1 = enough [V 0x006f376f-0x006f3790]; without it the press does nothing | later, in the locker room case 4, kind 1 with no check (0x005d33b5) [V] - harmless: with no credit nothing is taken [V `FUN_007a38e0`] | **No** - START is not the decide button. Reached only when `+0x144 == 2`, set from the cup struct `T+0x10 == 1` (locker room case 3, :697702-697732) [V], so WCCF Cup only [I]. Workaround today: press START once (adds a coin), then PRESS |
| Card purchase / dispenser | - | none [V CARD-DISPENSER-2010-11.md 2.2: nothing on that path looks at credits] | - | not needed |
| Attract screen | inserting the club card starts, not START [V `AdvertiseSequenceNode::vfunction21`: the card bit held -> next node] | none | - | not needed |
| Credit display (`FUN_0047af10`) | - | status only, for the picture | - | - |

Notes:
- `FUN_004f2410` (take) skips the take only for the cup's free play, otherwise asks amCredit [V :395240-395278]; with
  amCredit's FREE PLAY on, amCredit takes nothing [V 3.1]. Its return value is ignored by all four callers [V].
- The 0.15 s ordering (coin before START) is a timing assumption, not a guarantee [I]; if the coin is late, that START
  press is ignored, the coin stays as a credit and the next START works [I].

---

## 5. Recommendation (question 4)

### 5.1 The change: switch amCredit's own FREE PLAY on in memory, from `wccfpanel.dll`

The game's own setting, set live instead of through the missing settings chip. One data byte; no game code changes.

- Only in `client_Release.exe` (as `dispenser_install` does, `source\overlay\wccfpanel.c:5738-5754`).
- Code check first: the 19 bytes at `0x0082BFE0` must be
  `33 C0 39 05 90 0F CD 00 75 03 C2 04 00 38 05 9A 0F CD 00` [V, identical in all three seat 1 copies checked]. They
  prove that `0x00CD0F90` is amCredit's "started" flag and `0x00CD0F9A` its FREE PLAY byte.
- Wait until `*(DWORD *)0x00CD0F90 == 1` (amCredit started; it starts once, at program start [V `FUN_00401530` ->
  `FUN_004f1fd0` -> `FUN_004f2040`; `FUN_0082c240` returns early if already started, :1698646]), then write
  `*(BYTE *)0x00CD0F9A = 1`. Nothing else writes that byte after start [V: every code reference to `0x00CD0F98`-`9A`
  is a read except in `FUN_0082c240` (start); the only other writer is the memset in `FUN_0082bc30`, called only from
  JvsManager's shutdown `FUN_007a4260`]. Re-asserting it on the existing 2 s tick covers a restart of amCredit anyway.
- Effect [V 3.1]: every gate in section 4 passes, including the PRESS/SHOOT cup screen; no credit is ever taken; coins
  are ignored (only the bookkeeping counter moves); the credit display shows its free-play state. The projector needs
  nothing (already free, 1).

### 5.2 After it is in

- The on-screen COIN button can be removed: coins do nothing in free play [V `FUN_0082c4b0`].
- Keep `FREE_PLAY = True` in `_keys_seat1.py` as the fallback: if the overlay fails to load (play.py lets the game run
  without it), START-adds-a-coin still opens every normal gate [V section 4]; in free play its coins are harmless [V].
  Its docstring line "the game's own FREE PLAY setting (not found yet)" can then be corrected.

### 5.3 Alternatives, smaller or larger

| Option | What | Why not first |
|---|---|---|
| Patch the game's free-play test | `0x004F24E0` -> `B0 01 C3` (always yes) | A code patch; credits still counted and taken when present. Works, but changes code where a data byte does the job |
| Emulate the settings chip | SMBus device in mxhook + a chip image with FREE PLAY and CRC | Truly "Sega's setting from a file", but large, and wakes up every other chip record (3.3) |
| WCCF Cup FREEPLAY on the server | control's switch | Only in cup mode (3.4) |
| Driver only (today) | START-adds-a-coin | Fails on the cup two-choice screen (PRESS/SHOOT); depends on 0.15 s ordering |

### 5.4 Side effects to expect [I unless marked]

- Server: nothing charges; control has no coin logic (2.1). The bookkeeping report `SLS_SVR_BOOK` will show 0 coin
  credits (it carries the counters [V CARD-DISPENSER-2010-11.md 2.7]).
- ALL.Net billing calls (`alpbExStartCredit` etc.) exist in the library [V strings]; whether WCCF calls them per play is
  [A]; the kit runs with `ALLNET_AUTH=0` [V `scripts\setup.py:66`].
- Two JVS output bits (`DAT_011374e8 |= 0x18`) are requested differently in free play (`FUN_004049d0` :18912-18916,
  `FUN_004f23a0` :395169-395177) [V]; probably the coin lock-out coils [I from the test menu's COIN LOCKOUT 1/2 items];
  the I/O board stand-in only logs outputs [V CARD-DISPENSER-2010-11.md 2.1].

---

## 6. What I could not determine

1. Which coin branch seat 1 takes at start (`FUN_00406900`'s meaning), so 1 or 2 credits per COIN press [A].
2. What the free-play credit picture shows (`FUN_0047b040`, state 1) [A] - one look at seat 1 after the change settles it.
3. That the two-choice screen (`FUN_006f3690`) is WCCF Cup only [I]: what `T+0x10` holds outside a cup is [A].
4. That `amEepromInit` fails on seat 1 [I, strong]: the game's own log line ("amEepromInit() is failed") is not in any
   kit log; a breakpoint or a read of `0x00BF2038` / `0x00CD0F98` in the running seat 1 would prove it.
5. Whether the 0.15 s coin-before-START ordering ever loses a press [A].
6. Not tested: the recommended write. It is a design from the code, not a run.
