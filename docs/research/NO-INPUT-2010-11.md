# No input in the middle of a session (WCCF 2010-11, the PC build)

Static analysis of `client_Release.exe` (Rev D, `.work\release1011\cleantest\game\sbwg\extracted\` and seat 1's patched
copy), its decompile (`.work\ghidra_out_1011_classes\client`), the kit's code (`.work\release1011\github\WCCF-Kit`,
branch accounts-signin; the hook, io_board.py, keyboard.py and the panel are unchanged since 000f15f = the tested build
kit-7-test-a2cd0b2) and the logs of three runs of 2026-10-15. Written 2026-10-15.
**Read-only:** nothing was started, no kit or game file was changed, the zipped logs were read in memory. Disassembly
with capstone through `.work\research\player_cards\pe.py`, in inline commands.

**Where the logs are.** `data\logs\previous\` no longer holds case 1: the kit rotated it. Case 1 (run A, 03:01:43 to
04:19:10) is in `kit_user\data\logs\archive\run-2026-10-15_04-19-10.zip`; `previous\` is run B (04:19:51 to 05:09);
`data\logs\` itself is run C (05:35 to 07:04) [V file times and contents].

Tags: **[V]** read in the code or bytes (address given) or in a named log line. **[I]** inferred (the reason is given).
**[A]** not known.

---

## 1. The verdict in plain words

- **The buttons were switched off by Sega's own I/O library inside the game, and they stay off until the game is
  restarted.** At about 04:18:13 the kit's I/O board stand-in (`io_board.py`) stopped answering the game for about
  5 seconds. The game counts every unanswered poll. After 10 in a row it marks the board as broken and from then on
  **never reads the buttons again** in that run. It keeps polling (so the stand-in still sees every poll and every
  press) and keeps lighting the button lamps, but throws the answers away. No message, no crash, no error code.
- **Waiting would not have helped. The player was right.** Nothing in the game clears that mark except starting the game
  again [V, section 3.1]. RESTART NOW was refused during the card session, so the only way out was the close, which
  cost the card a bad ending.
- **The proof is in the I/O board log** (the game's lamp outputs answer each press there). In run A, before 04:18:13,
  120 of 122 SHOOT presses made while the SHOOT lamp was lit were answered in about 60 ms - 100 of 100 in the seven
  earlier waits and 14 of 14 in this wait. After the stall: 52 presses reached the board, 13 of them SHOOT at a lit
  SHOOT lamp, **0 answered**. Screens that close 70-90 ms after SHOOT everywhere else in the run stayed up until their
  own timers ran out [V, section 2].
- **The game itself kept running through the stall** (its card-table polls ran at 93.2 a second, as before) [V].
- **Two later runs show the near misses.** Run B (a stall of about 3.2 s) and run C (about 2.3 s): too few failed polls
  to switch the buttons off, but every press was then answered about 140 ms and about 95 ms later than before, for
  the rest of the run [V the delays; I the cause, section 4].
- **Not the cause:** the wait screen or the server's next round, the empty "Entry / Requests" menu, the cup, the card,
  credits, test mode, the key driver, the panel's windows, the debugger [V, section 8].
- **What made the stand-in stop answering is not in any log** [A]. In two of the three stalls it had just logged a
  lamp change, which means it was writing its log and the outputs file **before** sending its answer [V the order in
  the code; I that a slow file write is what blocked].
- **The fix (section 9), all small:** (1) two bytes in seat 1's exe so failed polls can never switch the buttons off;
  (2) the hook waits for a slow board instead of failing the poll, and drops stale answers; (3) io_board.py answers
  first and writes files after, and logs its own stalls. **Built the same day (kit 7): (1) in memory by the hook,
  (2) the drop only, (3) - and checked in the real game, before and after: section 9.0.**

---

## 2. Case 1, step by step (run A)

I/O board times are seconds since about 03:01:43.9 (matched to the key log: START at 03:02:50 = 66.8, RIGHT at
04:18:18 = 4594.4) [V]. Log = `run_ioboard.txt` in the zip unless named.

| local time | what happened | source |
|---|---|---|
| 04:16:13 / 04:16:18 | the locker-room save kept by wccf.online (version 17); card 2479 HEITINGA given | `run_helper.txt` lines 38-39 [V] |
| 04:16:25 | START (coin 72) | `run_keys.txt` 1843-1844; log line 3031 (4481.4 p1=80) [V] |
| 04:16:25-04:16:41 | the panel: START click, CATALOGUE opened, HEITINGA put on the board, browser closed | `wccfpanel.log` 13334-13342 [V order] |
| 04:16:41.5 | `match_Release.exe 1 0 Match` pid 47252 starts: the wait for the next round | `run_seat1.txt` line 49 (t+4497.8) [V] |
| 04:16:41 to 04:17:58 | management screens; 14 SHOOT presses at a lit SHOOT lamp, all answered (median 58 ms). First: 4497.825 SHOOT, 4497.881 lamps change | lines 3037-3038 and on [V] |
| 04:17:58 to 04:18:18 | no presses; the screens move on by their own timers (the "06" screen closes after 2.37 s, as always) | `run_keys.txt` 1916-1918 [V] |
| about 04:18:13 | last line before the gap: `4589.192 outputs now: 0c 00 e0` | line 3181 [V] |
| about 04:18:13 to 04:18:18 | **the stand-in writes nothing for 5.2 s; the 600 polls of that stretch took 14.39 s instead of 9.36** (lines 3180 and 3230) - the only gap over 2 s in the run | lines 3180-3230 [V] |
| about 04:18:18 | first line after: RIGHT pressed **and** new lamps `3c 00 e0`, in the same poll | lines 3182-3183 [V] |
| 04:18:18 to 04:18:44 | lamps `3c` (LEFT, RIGHT, PRESS, SHOOT lit) for 25.8 s, through 8 SHOOT presses; elsewhere SHOOT ends this screen in 60-90 ms | lines 3183-3253 [V] |
| about 04:18:47 | lamps `06` (SHOOT, KEEPER lit); SHOOT pressed 3 times; the screen stays its full 2.38 s timeout (elsewhere SHOOT ends it in 70-90 ms) | lines 3255-3266 [V] |
| 04:18:22 | START twice (coins 73, 74): no answer | `run_keys.txt` 1936-1941 [V] |
| 04:18:51 to 04:18:53 | lamps `cc 08` (UP, DOWN, PRESS, SHOOT, START lit); presses incl. SHOOT: no answer | lines 3268-3288 [V] |
| (panel) | SETTINGS opened; RESTART NOW refused 8 times "a card session is open"; close warned, then closed | `wccfpanel.log` 13368-13382 [V] |
| 04:19:00-04:19:01 | the game says goodbye to the card table; window closed | `fpr_emu_table0.log` line 2402; `run_seat1.txt` 53 [V] |

**The game process was not frozen during the gap.** `seat1\fpr_emu_table0.log` counts the game's card-table polls:
6000 between 04:16:59.755 and 04:18:04.131 (93.20 a second), then 5237 from 04:18:04.131 to 04:19:00.296 (93.24 a
second) - a 5-second freeze would have cost about 480 polls [V lines 2400-2402; I the arithmetic]. The debugger
printed no slow debug event (max hold 2.7 ms, `run_seat1.txt` line 55) [V].

**The same method on the other runs** (SHOOT pressed while the SHOOT lamp was lit, time to the next lamp change) [V]:

| run | before its stall | the stall (600 polls took) | after it |
|---|---|---|---|
| A (case 1) | 120 of 122 answered, median 60 ms, quickest 23 ms | 14.39 s (5.0 s missing), in a wait | **0 of 13 answered** |
| B (04:19-05:09) | 54 of 54, median 59 ms, quickest 24 ms | 12.45 s (3.1 s missing), about 04:52, in a match | 33 of 33, **median 200 ms, quickest 159 ms** |
| C (05:35-07:04) | 111 of 113, median 61 ms | 11.56 s (2.2 s missing), about 06:52, in a match | 29 of 29, **median 154 ms, quickest 123 ms** |

Run A's two smaller slow stretches (1309-1330 s and 3098-3129 s, during matches) changed nothing: 61 ms, 61 ms, 60 ms
in the three parts of the run [V]. So they were not unanswered polls [I].

---

## 3. How a press reaches a screen

| step | where | what it does | tag |
|---|---|---|---|
| key driver | `code\hardware\keyboard.py` | keys and pads -> `data\_jvs_seat1_input.txt`, only while a game window is in front and the panel's browser is closed (WCCF_TYPING) | [V lines 883-901] |
| board stand-in | `code\hardware\io_board.py` | answers each JVS request on `\\.\pipe\wccf_jvs_seat1` with the file's switch state; logs "inputs now" / "outputs now" | [V] |
| the hook | `source\hook\wccfk.c` | seat 1 opens the board as COM4 (kit patch 0x004D91C9); WriteFile/ReadFile on it go to the pipe | [V lines 800-880] |
| JVS I/O thread | FUN_00838a40 | per request: write FUN_008387b0, read FUN_00838850 (150 ms waits); slot status 4 = answer, 3 = read failed, 2 = write failed; after a failure PurgeComm | [V] |
| JVS library (teaArcade2) | IoThread loop @0x004d94e0 -> FUN_007a4590 -> FUN_007a4350 -> **FUN_007a61a0** per node | reads the last answer into the node: switch bytes, system byte, coin counters | [V] |
| | FUN_007a4590, switch table 0x00AD0A30 | JVS byte 0 -> bits 24-31, byte 1 -> bits 16-23; held / pressed / released per JVS player | [V] |
| | FUN_007a3620 -> FUN_007a6100 | builds and sends the next request: switch read, the 3 lamp bytes, coin read | [V] |
| input object | IoThread DAT_011374cc | ORs the bits into +0x14c/+0x154/+0x15c (P1 +4) under a lock | [V] |
| per frame | FUN_0040a770 -> FUN_004d93b0 | latches them into +0x134 pressed, +0x13c held, +0x144 released | [V] |
| per frame | FUN_004e0610 -> WccfInputBase @0x004e03b0 | the 12 logical buttons; tactics toggle in a match | [V] |
| screens | accessors FUN_004e0170 (pressed), FUN_004e0230 (held), FUN_004e02f0 (released), table 0x009FBD30 | each screen reads the buttons it uses | [V] |

Logical buttons (table 0x009FBD30) [V]: 0 UP, 1 DOWN, 2 LEFT, 3 RIGHT (first JVS player 0x20/0x10/0x08/0x04),
4 PRESS (0x02), 5 DATA (second player byte 1 0x80), 6 START (0x80), 7 SHOOT (0x01), 8 KEEPER (second player
byte 0 0x02), 9 KEY PLAYER (second player byte 1 0x40), 10 SHOOT, 11 KEEPER.

### 3.1 Where the game throws the buttons away: the JVS error mark

FUN_007a61a0, checked in the disassembly [V]:

```
0x007A61B4  call FUN_0082e270          ; the answer to the last request: 0 ok, 1 not yet (loop), else failed
0x007A61C7  add [esi+0x28], 1          ; failed: +1 in this 600-poll window
0x007A61CA  add [esi+0x30], 1          ; failed: +1 in a row
0x007A61D4  cmp [esi+0x28], 0x3C       ; window over and 60 or more failed
0x007A61DA  mov byte [esi+0x34], 1     ;   -> the node is marked broken
0x007A61E1  cmp edi, 0x0A              ; 10 or more failed in a row
0x007A61E6  mov byte [esi+0x34], 1     ;   -> the node is marked broken
0x007A6203  cmp cl, 1 / je 0x007A6371  ; marked: skip reading switches, system byte and coins - every poll from now on
0x007A6218  mov [esi+0x30], eax        ; a good answer resets the in-a-row count (only while not marked)
```

- Only the node's constructor (FUN_007a6010) clears +0x34. The node is built once, when the program starts
  (ClientMain -> FUN_00401530 -> FUN_004e05c0 -> IoThread::IoThread -> FUN_007a4010) [V, every caller found].
- The request with the lamps is still sent every poll (FUN_007a6100 does not look at the mark) [V]. That is why the
  lamps kept changing and the stand-in kept counting polls after 04:18:18 (log lines 3230, 3252, 3254, 3287) [V].
- The only reader of the mark is FUN_007a3780, called only by FUN_004e0a00, which zeroes a node count in a status
  object [V]. No screen or error code reacting to it was found [I].
- A "failed" answer: a read that timed out gives slot status 3 -> FUN_00838610 returns -16 -> counted [V].
- The switch state stays as it was at the last good answer. Here nothing was held at 04:18:13 (no press from
  04:17:58), so the game saw "no button" for good [V the key log; I the frozen value].

**Other conditions that drop buttons**, none of them this bug [V/I]:

| condition | where | why not this bug |
|---|---|---|
| DAT_00aeac72 = 0 (not RingEdge) -> every JVS accessor returns 0 | FUN_004e0170/0230/02f0; set once from the options (WccfUserOption @0x005fc7f0) | fixed for the whole run; input worked for 74 minutes [V] |
| a screen reads only its own buttons and lights only their lamps | the screens; lamp requests DAT_011374e4 | the ignored presses were made at **lit** lamps [V] |
| tactics in toggle mode during a match | WccfInputBase param 1 (DAT_011374cb) | changes how arrows report, drops nothing [V] |

### 3.2 The lamps: the game's own reply, already in the I/O board log

Each poll carries 3 lamp bytes; the stand-in logs every change ("outputs now"). The game rebuilds them every frame
from what the current screen asks for (FUN_004e0710, lamp requests DAT_011374e4, cleared after each frame) [V]:

| lamp | output bit | button (same number in the table above) |
|---|---|---|
| 0, 1, 2, 3 | byte 0: 0x80, 0x40, 0x20, 0x10 | UP, DOWN, LEFT, RIGHT |
| 4 | byte 0: 0x08 | PRESS |
| 5, 6 | byte 1: 0x08 (shared) | DATA, START |
| 7 | byte 0: 0x04 | SHOOT |
| 8 | byte 0: 0x02 | KEEPER |
| 9 / 10 | byte 1: 0x04 / 0x01 | KEY PLAYER / SHOOT |
| flags | byte 2: 0x80 while the card flag DAT_011374df = 1 | - |

[V the table in FUN_004e0710; I that lamp number = button number - the logs agree: SHOOT closes screens lighting
byte 0 0x04, KEEPER closes ones lighting 0x02, UP/DOWN change the lamps on cursor screens, the "continue?" screen
lights byte 1 0x08 just before START (line 3029)].

---

## 4. Why a slow stand-in becomes failed polls (the kit's link)

- **The hook gives up early and never finishes the read.** For the board's overlapped ReadFile, `hook_ReadFile`
  waits up to 120 rounds of `Sleep(1)` for all the bytes, then returns ERROR_IO_PENDING and never completes that read
  [V wccfk.c lines 848-857]. The game then waits 150 ms on the read's event (FUN_00838850), gets a timeout and counts a
  failed poll [V].
- **About 0.37 s per failed poll, so about 3.7 s of silence switches the buttons off.** From runs B and C
  independently: the added delay after each stall = stale answers x 15.6 ms (one poll) -> 9 and 6 answers, and the
  missing poll time then gives 0.36 s and 0.38 s per failed poll [I]. That fits 120 short sleeps plus 150 ms [I].
  Run A: about 5.2 s -> about 14 failed in a row -> marked at the 10th [I]. Run B: about 9 -> one short of the mark.
- **The stale-answer queue (runs B and C).** Every request sent during the stall is answered in a burst afterwards.
  The game reads one answer per poll, so it stays that many answers behind for the rest of the run: about 140 ms (B)
  and 95-125 ms (C) more delay on every button [V the delays; I the queue]. The game's PurgeComm runs only after a
  failed poll, so it never clears that queue [V FUN_00838a40].
- **Why the stand-in could stall the game's polls at all:** io_board.py reads the input file (a file time check on
  every poll), logs every change to two files with a flush, and rewrites `_jvs_seat1_outputs.txt` on every lamp change
  - all **before** it writes the answer [V lines 300-315 and Board.note_outputs]. Run A's stall began right after
  "outputs now: 0c" (line 3181); run C's right after "outputs now: 80 00 e0" (4607.291) [V]. What blocked for seconds
  is [A] (section 10).

---

## 5. The wait before the next match

- **The node:** `wccf::management::ManagementSequenceNode` - start vfunction20 @0x00500f20, every frame vfunction21
  @0x005013e0, end vfunction22 @0x005015c0 [V]. It runs the Team Management screens (ManagementMain; SeqMngTop,
  SeqMngRegister "Entry / Requests", SeqMngInformation and the SeqInfo* messages, team practice) [V class names].
- **What it waits for:** FUN_00500dd0, every frame [V]: it trades "START UP" / "START_UP_OK" with the match program,
  and when the countdown FUN_00408120 is below 1 it sends "GO TO GAME" and moves on; with a client error code
  (DAT_01138390+4 > 0) it goes to "ClientError". [I] the countdown is the kick-off counter the server's next round
  sets (ARRANGE-FIXTURE-2010-11.md 3.1).
- **Buttons:** each screen lights what it takes: SHOOT = OK/next (byte 0 0x04), KEEPER = back (0x02), arrows = cursor,
  START lamp on some screens [V lamps; I names]. Several message screens close by themselves (2.37 s) [V].
- **It takes input normally.** 100 of 100 SHOOT presses at a lit lamp answered in the seven earlier waits of run A,
  14 of 14 in the final wait before the stall [V].
- The picture `.work\shots\waiting_phase_1.png` is this node (run B): "Menu / Entry / Requests" with nothing under it,
  the 次の試合開始まで / お待ちください picture. Why the list is empty is [A]; it is not this bug (run B's input worked
  at those screens).

---

## 6. The kit's own parts

| part | what it does with input | in case 1 | tag |
|---|---|---|---|
| keyboard.py | keys only while a game window is in front; none while the panel's browser sets WCCF_TYPING | every press reached the board | [V] |
| io_board.py | the board; file I/O before each answer | **stopped answering for 5.2 s** | [V] |
| wccfk.c (hook) | the board's COM4 over the pipe; gives up after 120 short sleeps, never completes the read | turns the stall into failed polls | [V code; I effect] |
| wccfpanel.c | its buttons inject keys with SendInput; its browser sets WCCF_TYPING; draws on the game's Present | presses after the browser closed were answered (04:16:41: 56 ms); the panel worked to the end | [V] |
| debugger.py | holds the game during debug events | max 2.7 ms; no slow event | [V] |

Side finding, not this bug: keyboard.py's auto-eject treats output byte 1 bit 0x08 as "the game waits for a card".
In the lamp table that bit is the START/DATA lamp, which management screens light; in run A it took the card out at
03:03:54 on the first management screen (`cc 08 e0` at 130.185, `run_keys.txt` line 30) [V]. Input then worked for 74
minutes with the card out [V], so it is harmless here [I].

---

## 7. The "lag twitch"

- The only stall in the logs is the stand-in's 5.2 s, about 04:18:13 to 04:18:18, 91 s into the wait [V].
- Ruled out as the cause: the start of the match program at 04:16:41 (no slow debug event), the save and upload
  (04:16:10-04:16:28), the panel's NEW CARD and CATALOGUE (closed before 04:16:41) - presses were answered after all
  of them [V].
- What the player saw as the twitch is [A]: the game's picture did not stop (its card-table polls never slowed). The first
  press after 20 quiet seconds fell exactly at the end of the stall (same poll as the new lamps) - either chance or a
  sign that the key driver was stalled too [A].

---

## 8. The candidates, ranked

| # | candidate | for | against | probe next time | fix |
|---|---|---|---|---|---|
| 1 | **the JVS error mark after the stand-in stopped answering** | the mark is in the code (3.1); answers 120/122 -> 0/13 at the stall; game alive; near misses B and C | - | stall lines in io_board.py; the debugger reads the mark (9.4) | 9.1, 9.2, 9.3 |
| 2 | what stalls the stand-in | file I/O before each answer (2 of 3 stalls began at a lamp change); stand-ins are not opted out of Windows throttling | no Windows event at any of the three times [V System, Application, Defender, Storport, NTFS logs] | step timing in io_board.py and keyboard.py | 9.3 |
| 3 | the wait screen or the server's round | the input stopped in a wait | 100/100 and 14/14 answered in waits; stopped 91 s in, at the stall | - | - |
| 4 | after a cup match | case 1 and the tester | B and C stalled mid-match; the mark ignores what screen is up | - | - |
| 5 | the card | card OUT from 03:03:54 | 74 min of input with the card out | - | - |
| 6 | credits / test mode | - | free play; no F1/F2 in the key log | - | - |
| 7 | key driver / panel | - | every press reached the board; panel answered | - | - |
| 8 | the debugger / a frozen game | - | max hold 2.7 ms; card-table polls steady | - | - |

Another player's report (kit 5.5) has the same signature (presses at the board, polling on, no reaction) [V earlier
notes]. The check when that zip is read: one 600-poll interval well over 9.4 s in its `run_ioboard.txt`, and SHOOT at a
lit SHOOT lamp unanswered after it [A until then]. The tester's case has no logs [A].

---

## 9. The fix (proposed below; what was built and checked is 9.0)

### 9.0 Built and checked in the real game (2026-10-15, kit 7)

What was built, against the proposals below:

| proposal | built | where |
|---|---|---|
| 9.1 the two bytes | **in memory at the game's start, not in the exe**: the hook writes 00 over both `01`s in client_Release.exe, only if both places hold Sega's exact bytes (else it changes nothing and says so). Why not PATCHES: seat 1's exe has an English copy whose hash setup.py checks, so a new PATCHED_CLIENT would have refused every English player's update | `source\hook\jvs.h` jvs_unlatch, `wccfk.c` install_jvs_unlatch; log line "JVS: failed polls can no longer switch the buttons off" |
| 9.2 drop stale answers | yes: before each request on the JVS port, the bytes waiting are read and dropped (logged, the first 5 times then every 100th) | `jvs.h` jvs_drop, `wccfk.c` hook_WriteFile |
| 9.2 wait by time instead of 120 sleeps | **not built**: with the mark off and stale answers dropped, a failed poll costs only that poll; a longer wait would hold the game's JVS thread | - |
| 9.3 io_board.py answers first | yes, further: the answering thread never touches the disk (the input file is read by its own thread, the log and the outputs file written by another); high priority, Windows' throttling off; moments over 250 ms logged as SLOW | `code\hardware\io_board.py` |
| 9.3 keyboard.py stall line | not built | - |
| 9.5 test switch in io_board.py | not needed: the live test freezes the stand-in from outside (NtSuspendProcess) | - |

The checks:
- `source\test_jvs.c` (11 checks): the mark switched off only on Sega's bytes and never half; stale answers dropped from
  a real named pipe, the next answer read whole.
- `source\test_io_board.py` (15 checks): the real io_board.main() on a real pipe while a write of the outputs file
  hangs 2 s - every answer still went out at once; **the old io_board.py held one answer 2,003 ms** under the same test.
- **The real game** (local, a test kit, the card out). A probe read the game's memory (the error-mark code, the JVS
  node `[[0x00BF24F4]]` +0x28/+0x30/+0x34, the held buttons `[0x011374CC]+0x13C`), wrote DOWN into the key driver's file
  and froze the stand-in [V, each line printed by the probe]:

| | the old hook (as kit 6) | the new hook |
|---|---|---|
| the running game's code at 0x007A61DA / 0x007A61E6 | c6 46 34 01 / c6 46 34 01 | c6 46 34 00 / c6 46 34 00 |
| one 6 s stall | 16 failed polls in a row, **mark 1**, the count stuck at 17; **DOWN never reached the game again** | 16 in a row, mark 0, the count back to 0; DOWN reached the game |
| 5 stalls of 2.5 s, each ended 30 ms after the game sent a new poll | DOWN reached the game 26 ms before, then **147, 246, 392, 451, 559 ms** after each - the lasting delay of runs B and C, growing | 56 ms before, then 54, 42, 33, 47, 58 ms; the hook dropped 119 bytes (7 answers) of late answers each time |
| 6 stalls of 2.5 s ended at random moments | 30-54 ms after each (the game's own purge cleaned up) | 38-68 ms after each |

The stand-in logged each stall, e.g. "SLOW (1 so far): 17 requests were waiting - nothing was read for 6017 ms".
Still [A]: what stalled the stand-in on 2026-10-15 (the SLOW lines will say next time: a slow read of the input file,
a slow write, or the process not running).

### 9.1 Seat 1's exe: the mark can never be set (2 bytes)

Two lines for `code\setup.py` PATCHES, then a new PATCHED_CLIENT hash ("15 changes" becomes 17) [V bytes `c6 46 34 01`
at both places in Sega's exe and in seat 1's copy]:

```
(0x007A61DD, 0x3A55DD, "01", "00", "JVS: 60 failed polls in a window no longer switch the buttons off"),
(0x007A61E9, 0x3A55E9, "01", "00", "JVS: 10 failed polls in a row no longer switch the buttons off"),
```

Effect: after any stall the first good answer brings the buttons back [I from 3.1]. Risk: low. A board that is
really dead keeps the last switch state, as now, with no error screen - there was none before either [I].

### 9.2 The hook (`source\hook\wccfk.c`, about 10 lines)

- In `hook_WriteFile`, for a JVS port: before writing a request, read and drop any bytes waiting in the pipe. They
  can only be answers to requests the game gave up on; FUN_00838a40 always writes one request, then reads its answer
  [I]. Removes the lasting delay of runs B and C. Count the dropped bytes for the log.
- In `hook_ReadFile` (overlapped, JVS): wait by time, not by 120 sleeps - for example up to 2 s once the board has an
  address (keep the short wait before: a reset gets no answer) - and count each read left pending. Then a slow board
  is a slow poll, not a failed one: the game's poll loop just waits (FUN_00838610 returns "not yet" while the read is
  in progress) [V]. Risk: during a long stall the game's JVS thread waits up to the limit; the lamps stop changing for
  that long [I].

### 9.3 io_board.py (and the same care in keyboard.py)

- Answer first: build the answer from what is in memory and write it, then do the logging and the outputs file. Read
  the input file in a small thread, not on every poll. About 20 lines.
- Log its own stalls: when an answer goes out more than 250 ms after its request, one line with the time and the step
  it was in (and whether requests were waiting, which tells "the board was late" from "the game was quiet").
- Opt the stand-ins out of Windows' throttling and raise io_board.py's priority, as the debugger already does for the
  game (`debugger.full_speed`; move it to kit_common to reuse it) [I that it helps; A whether throttling was involved].
- keyboard.py's 10 ms key loop also reads the outputs file every 0.1 s: give it the same stall line [I].

### 9.4 Probes (prove it next time)

1. The check used here needs no new logging: in `run_ioboard.txt`, SHOOT presses (p1 bit 0x01 rising) while the last
   "outputs now" had byte 0 bit 0x04, and the time to the next "outputs now". About 60 ms = fine; 120-200 ms = a stale
   queue; none answered = the mark. A 600-poll interval over about 10 s = the stand-in answered late.
2. The stall lines of 9.3.
3. The debugger already reads the game's memory: once a second read the node's mark and counts - node =
   [[0x00BF24F4]], mark byte +0x34, in-a-row +0x30, window +0x28 - and print a line when they change [I the pointer
   chain from FUN_007a4010 / FUN_007a44a0; verify once on a live game].

### 9.5 Test plan (cleantest only)

A test-only switch in io_board.py (a file beside it makes it sleep 6 s once). Before the fix: a wait screen stops
answering SHOOT and the debugger probe shows the mark at 1. After 9.1 + 9.2: the screen answers again within a poll
or two of the stall's end, with the usual delay (check 1 of 9.4). Then CI's tests, the patched-exe hash, and one full
online session.

---

## 10. Open questions

| question | status | next step |
|---|---|---|
| What stalled the stand-in for 5.2 s (and 3.2 s, 2.3 s)? | [A] - no Windows event at the three times; two began at a lamp-file write | the stall lines (9.3) |
| Was the key driver stalled at the same time? | [A] | its stall line |
| Exact cost of one failed poll (0.37 s, threshold about 3.7 s) | [I] from runs B and C | the hook's pending count (9.2) |
| The other player's kit 5.5 report: the same cause? | [I] consistent | read its `run_ioboard.txt` with check 1 |
| The node pointer chain for the probe | [I] | read it once on a live game |
| What the zeroed node count (FUN_004e0a00) is used for | [A] | not needed for the fix |
| Why the Entry / Requests list was empty in the picture | [A] | separate (ARRANGE-FIXTURE 3.1, RG_LIST) |

---

## 11. Sources

- Logs, run A: `.work\release1011\cleantest\kit_user\data\logs\archive\run-2026-10-15_04-19-10.zip` (run_ioboard.txt,
  run_keys.txt, run_seat1.txt, run_helper.txt, run_scenes.txt, _dbg_client_seat1.txt, hook\mxhook_75220.log,
  hook\mxhook_47252.log); run B: `...\data\logs\previous\`; run C: `...\data\logs\`.
- `.work\release1011\cleantest\game\sbwg\seat1\wccfpanel.log` lines 13332-13382; `fpr_emu_table0.log` lines 2398-2403.
- `.work\shots\waiting_phase_1.png`.
- Decompile `.work\ghidra_out_1011_classes\client`: FUN_007a61a0, FUN_007a6100, FUN_007a6010, FUN_007a4010,
  FUN_007a4590, FUN_007a4350, FUN_007a3780, FUN_004e0a00, FUN_0082e270, FUN_00838610, FUN_00838850, FUN_008387b0,
  FUN_00838a40, wccf::io::IoThread @0x004d9050 / @0x004d94e0, FUN_004d93b0, FUN_004e0610, FUN_004e0710,
  WccfInputBase @0x004e03b0, FUN_004e0170/0230/02f0, FUN_0040a770, ManagementSequenceNode @0x00500f20 / 0x005013e0 /
  0x005015c0, FUN_00500dd0, FUN_00408120. Disassembly 0x007A61A0-0x007A6230; tables 0x009FBD30, 0x00AD0A30.
- Kit: `source\hook\wccfk.c` (hook_WriteFile, hook_ReadFile, hook_PurgeComm), `code\hardware\io_board.py`,
  `code\hardware\keyboard.py`, `code\hardware\debugger.py`, `source\panel\wccfpanel.c`, `code\setup.py` (PATCHES).
- Earlier notes: `.work\input_mapping.md`, `.work\jvs_init_debug.md`, `docs\research\ARRANGE-FIXTURE-2010-11.md`.
- Windows event logs (System, Application, Defender, Storport, NTFS, Kernel-PnP, Resource-Exhaustion) around
  04:18, 04:52 and 06:52 of 2026-10-15: no events.
