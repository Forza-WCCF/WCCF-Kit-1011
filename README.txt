WCCF 2010-11 (Rev D) on a PC - the kit
======================================

WHAT IT IS
  Community-made tools for your own copy of WCCF 2010-11 (Rev D): a launcher, stand-ins for the cabinet's hardware
  and an in-game panel, so the game's server, the projector (the shared big screen) and a player cabinet (seat 1)
  run on one Windows PC. The game itself is not part of the kit. Around seat 1's picture there is a panel with
  the cabinet's buttons, a FORMATION BOARD for your cards (drag to move, drop on another card to swap, right-click
  to take a card off), a CATALOGUE of all 3,909 player cards (search, position, rarity, country and club filters,
  sort, a slider per stat, a stats pane; a click puts the card on your table), KEYS, where you choose your own keys
  or a game controller's buttons, SETTINGS, and CLUB CARD, your club card and your other clubs.
  The kit holds none of Sega's files. Everything that comes from the game is made by setup from YOUR copy.

NEW IN KIT 5.5
  - Free play: the game's own FREE PLAY is on, so you never need a coin - not even on the screen after a cup match.
    The COIN and BACK buttons are gone, and DATA and CARD are full width.
  - When your contract ends, put the card in again after the last match: the game moves your manager to a new card
    and you make a new club. The old card is kept in YOUR CARDS as "transferred".
  - SETUP.exe is a window: your game folder, the game's language (English or Japanese - ENGLISH.exe is gone), and
    UPDATE, which updates the kit for you from now on (your clubs, keys and settings are never touched). PLAY.exe
    tells you when a newer kit is out.
  - Antivirus: the panel now loads from inside the game itself. overlay\inject.exe is gone - it is what Windows
    Defender blocked on one player's PC.
  - After each match, a player card is shown as the cabinet's dispenser gave one - only shown, nothing is added to
    your club card.
  - CATALOGUE: search with several words (milan 2004, brazil fw); each card's pane shows the roles it suits best.
    On the FORMATION BOARD a card shows big after the mouse rests on it 3 s.
  - The kit's version (KIT 5.5) is at the top right of the game. SETTINGS > LOGS > SEND LOGS sends your logs (never
    your club card) to the server you play on and shows a code: post the code in Discord with what went wrong.
  - Online: no more two players on one seat after a server restart (the second one was never let in), and the
    shared server notices when it stops letting players in and restarts by itself.
  - Fixed: on a PC left on for more than 24 days, the "You are owed N Player Card(s)" fix did not run.
  - Updating from 5.4: unzip this kit over the old folder, then open SETUP.exe and SET UP / REPAIR (and English if
    you use it). Next time, SETUP's UPDATE does it for you.

NEW IN KIT 5.4
  - Closing the game's window quits the game, cleanly, every time: the game and everything the kit started with it
    (the server, its match engines, the kit's helpers) stop by themselves. Before, the game and its helpers ran on
    hidden in the background. There is no STOP any more. During a match the first close only warns you (it would
    cost your card a bad ending); close again within 8 seconds to quit anyway. A game that crashes stops nothing
    else: the projector keeps running.
  - CLUB CARD: CLEAR BAD ENDINGS (click twice) sets the card's bad endings back to 0 at a restart.
  - CATALOGUE: COUNTRY and CLUB (top right) - pick from a list of every country or club with its number of cards
    (type to narrow it); on the card under the mouse, SAME CLUB and SAME COUNTRY show its clubmates or countrymen.
  - Hosting a server: when the crash guard cannot catch a crash, data\logs\run_server.txt now says why
    ("MSGPARSE guard stepped aside: ...") - please share that line.
  - PLAY, SETUP and ENGLISH are programs (.exe) instead of .bat files; they are used the same way.
    Updating: delete the old PLAY.bat, STOP.bat, SETUP.bat and ENGLISH.bat.

NEW IN KIT 5.3
  - Hosting a server (PLAY.exe server) is sturdier against a crash. The server could drop with "WCCF CONTROL NOT
    FOUND" (Error 3000) on every cabinet at once while players were setting up a match - a bad message from a
    connection. A guard now catches that message-handling crash (in its two forms) and drops the one bad message so
    the server keeps running. On by default when you host. This is ONLY for people who HOST a server; if you just
    join one, you never saw this and need nothing. (Note: Sega's server can crash other ways too; this covers the
    common one. Keep a way to restart it if it ever stops.)

NEW IN KIT 5.1
  - Each club card keeps its own formation board: the table you set up moves with the card. Switch clubs in CLUB
    CARD and the table you left for that club comes back; a club played for the first time gets its squad laid out
    in a 4-4-2 with the substitutes on the bench. The board lives beside the card file (a .board folder) and moves
    with it. A table that belongs to no card is kept in data\save\boards_unknown, never thrown away.
  - YOUR CARDS shows every club you have: when they do not all fit, they are in pages (< PREV, NEXT >, or the
    mouse wheel).

NEW IN KIT 5
  - A ping meter when you play online: bars and "80 ms" at the top right, above the game - green under 100 ms,
    yellow under 200, red above. It is your trip to the server; against another player, theirs adds to it.
  - Switching club cards restarts only your cabinet: the projector keeps running and never has to sync again.
  - English: Prize Money on the fan event and golden age (all titles won) screens is one amount with commas
    ($5,431,900 - it read "$5 million$431900"); Team Training's "They're giving their all out there" (it showed a
    junk number). Choose English again after updating (SETUP.exe, "Game language").
  - Hosting a server (PLAY.exe server): it runs for 32 days instead of 12 hours, and waits for a projector to join
    before its first round.

NEW IN KIT 4
  - Game controllers in KEYS: a USB encoder under real cabinet buttons, an arcade stick or a gamepad.
  - SETTINGS: this PC or online, English or Japanese, restart; VIEW: the CABINET layout or COMPACT (the game larger,
    no cabinet buttons). CLUB CARD: your club as the game reads it, and more than one club (YOUR CARDS).
  - Only two windows (projector and seat 1); the projector starts muted and seat 1 quiet.
  - Your card is saved safely, with backups; closing the game during a match asks first.
  - Each button's whole picture is clickable, rim and shadow too.
  - English: money in dollars, with commas on seat 1 and the projector ($3,982,700); the result screen's stats and
    goal minutes; the projector's "League"; "Contract: 88"; the shop's name.
  - Online with others (SETTINGS > ONLINE and a server's address): each PC that joins gets the next free seat by
    itself, the first one also the projector, and a match between two players goes through the server - nothing
    else to install.

YOU NEED
  - Windows 10 or 11, 64-bit, with the game on an NTFS drive (normal for C: and D:)
  - your own copy of the game, Rev D, as a folder of files: the game folder is the one that holds
    client_Release.exe, control_Release.exe and match_Release.exe. Setup checks that it is Rev D.
  - DirectX 9: Microsoft's "DirectX End-User Runtime (June 2010)". Setup tells you if it is missing.
  Nothing else: Python is inside the kit.

SETUP (once)
  1. Unzip this kit into a folder of its own. Keep the game in a folder of its own too (e.g. D:\Games\WCCF).
     Plain paths are safest: the game has trouble with non-English letters in folder names.
  2. Drag the game folder onto SETUP.exe. Or open SETUP.exe, pick the game folder (BROWSE, or drag it into the
     window) and click SET UP / REPAIR.
  3. Setup checks that your copy is Rev D, makes the changes listed under WHAT SETUP CHANGES, then makes the card
     catalogue and the card pictures from your files (about a minute); what it does shows in SETUP's window.
     Running it again checks and repairs.
  SETUP.exe is one window for the rest too: GAME LANGUAGE (see ENGLISH), UNDO SETUP, and UPDATE. Its own words are
  in English, or in Italian or Japanese when Windows is.
  Updating: PLAY.exe says when a newer kit is out (a release, never a test build), and so does SETUP.exe, which marks
  it "(newer)". Close the game, open SETUP.exe: under UPDATE it lists the kit's releases and test builds on GitHub
  ("What's new" opens one's page). Pick one, UPDATE: it is downloaded and put into this folder - data\ (your club,
  your other clubs, settings, keys, catalogue, logs) stays as it is - and the files the old kit had and the new one
  does not are removed. Then SETUP offers to set up the game folder again, and the English with it if you use English.
  A server settings file you edited by hand is kept as .before-kit. By hand, or from Kit 5.4 and older: unzip the new
  kit over the old folder, then open SETUP.exe (it removes the old .bat files and ENGLISH.exe), SET UP / REPAIR, and
  ENGLISH if you use English.

PLAY
  PLAY.exe starts everything in about 30 seconds: the server, the projector's window, seat 1's window with the
  panel, and the key driver. Only two windows open, the projector's and seat 1's: the server and the kit's helpers
  run in the background ("PLAY.exe show" shows the server's console and settings window; "PLAY.exe debug" opens
  every window and keeps full logs).
  Sound: the projector starts muted and seat 1 at 4% of the PC's volume, so the same sounds do not play twice and
  nothing is loud at the start. Windows' Volume Mixer changes either while you play; the next start sets them again.
  The game runs in rounds, like an arcade: an entry window, then the matches. The kit keeps each entry window open
  for 2 minutes (the game's own 40 seconds were too short for a seat that had just started, which then waited a
  whole 12-minute round, the projector meanwhile on "Now Synchronizing"). Put your card in soon after starting
  and you play in the first round. To change the 2 minutes: FIX_REST_ENTRY_TIME in
  local\ctrl_user_option.conf in the game folder (seconds).
  Click seat 1's window, then:
      I       club card in / out (with a new card the game makes your club: manager license, club name)
      Enter   START (play is free: the game's own FREE PLAY is switched on - no coin needed)
      X       decide          C   shoot          arrows   tactics
      F1      test menu       F11 window size
  or click the buttons around the picture. Keys only count while a game window is in front.
  Your own keys: the KEYS button (right of START) lists every cabinet button with a KEY box and a CONTROLLER box.
  Click a KEY box, press the key you want; a key another button already has swaps over. Esc, F10, F11, Alt and the
  Windows keys stay free.
  A game controller: click a CONTROLLER box, then press a button or move the stick or d-pad. It works with a USB
  encoder under real cabinet buttons that shows up as a game controller, an arcade stick or a gamepad; under RESET,
  CONTROLLERS shows what Windows sees and what is pressed right now. Right-click a CONTROLLER box to clear it. Keys
  and controller work together. An encoder that types keys (a "keyboard encoder") goes in the KEY boxes.
  Every change works at once and is kept in data\keys.txt (RESET, or deleting that file, gives the keys above back
  and clears the controller).
  Your club is saved in data\save\seat1_club.bin. Back it up.
  The kit's version (KIT 5.5 ...) is at the top right of the game, under the ping when you play online: give it
  when you report a problem.

SETTINGS (left side, under CARD)
  NOW: the link to the server, your card's session, its bad endings, its last save and backup, the game's text.
  NEXT START: THIS PC (everything on this PC) or ONLINE with a server's address (the cabinets on this PC play on
  that server), and ENGLISH or JAPANESE (does what SETUP.exe's GAME LANGUAGE does, at the next start). They are kept in
  data\panel.txt. RESTART NOW (click it twice) starts the game again with them - not during a match. When the
  server and the language stay the same, only your cabinet restarts and the projector keeps running.
  VIEW, changes at once: LAYOUT CABINET (the cabinet's buttons around the game) or COMPACT (the game larger,
  without them - your keys or controller press them; SETTINGS and CLUB CARD move under CATALOGUE and KEYS).
  LOGS: SEND LOGS (click twice) sends this game's logs to the server you play on (the address under PLAY ON) -
  never your club card, and your Windows user name and PC name are taken out of them. You get a short code: post
  it in Discord with what went wrong.

CLUB CARD (left side, under SETTINGS)
  Your club card as the game reads it: club, manager, contract, league, prize money; the card's health (a session
  open or closed, bad endings, its two saved copies, backups); the squad (a name in red is injured). It follows
  each save of the card.
  YOUR CARDS - more than one club: NEW CLUB CARD puts this club aside and a blank card in the slot; put it in (I)
  and the game makes a new club. PLAY THIS CLUB puts that club back in the slot. Click twice; each switch restarts
  your cabinet (about a minute) while the projector keeps running, never during a match, and no card is ever
  deleted. The clubs put aside are in
  data\save\cards.
  CLEAR BAD ENDINGS (under CARD HEALTH, while the card has a bad ending or its last session was cut): click twice,
  and the game restarts with the card's bad endings back to 0 (the old card goes to data\save\backup first). Not
  during a match. Trade rights or money the game already took for them stay as they are.
  Any other field of the card: python\python.exe scripts\edit_club_card.py data\save\seat1_club.bin --help
  (close the game first; it shows what it would change and writes only with --write).

QUIT
  After a match the card comes out by itself (or press I). Then close the game's window (its X, or Alt+F4): the game
  ends, and everything the kit started with it stops too - the projector, the server, its match engines and the
  kit's helpers (data\logs\run_ended.txt says what was stopped). Closing the projector's window does the same.
  During a match (the game marks a card session open from START to the locker-room save) closing seat 1's window
  would end that match without its save, and the card gets a "bad ending" (trade rights are lost at 2). So the first
  close only shows a warning over the game; close again within 8 seconds to quit anyway. (Closing the projector's
  window during a match leaves seat 1 playing; close seat 1 after the match.)
  A server started with "PLAY.exe server" has no window: "PLAY.exe stop" ends it. A cabinet that played on it from
  this same PC leaves it running for the other players when its window closes.
  A game window that goes by itself (a crash, not a close) stops nothing else: the projector keeps running. Its log
  says what happened (data\logs\run_seat1.txt or run_projector.txt); "PLAY.exe stop" ends the rest.
  A game that is stuck (no window to close, or it will not close): "PLAY.exe stop force".

ONLINE (play with others on one server)
  One PC hosts: "PLAY.exe server" starts only the server, in the background - no game window opens, and the
  window that started it closes by itself after 30 seconds while the server keeps running ("PLAY.exe stop" ends
  it). That PC must let in TCP ports 20002, 20030 and 20050 and UDP 20040; at home behind a router, forward those
  ports to it. Logs that players send with SEND LOGS are kept there in data\player_logs. Each player: "PLAY.exe remote" and the server's address (e.g. PLAY.exe remote 192.168.1.20), or ONLINE
  in SETTINGS. The first PC to join also shows the projector. The PC that hosts can play too: "PLAY.exe remote"
  with its own local address (ipconfig shows it).

ENGLISH (optional)
  ENGLISH (in SETUP.exe, GAME LANGUAGE) puts the game into English: about 7,200 lines of screen text, the players'
  names (Sega's own Latin spelling, e.g. M.DIARRA) and skill names, the CPU teams' names, the projector's "Next match"
  ticker, the dates on seat 1 (e.g. 2026/10/5 on the manager license), money in dollars, and the shop's name on the
  projector's awards ("Local Shop" - also inside the server program, the only change ENGLISH makes to it).
  Awards the game saved before English was on keep the names they were saved with (e.g. the CPU's Best Eleven
  team, in Japanese, on the projector's MVP and Best Eleven awards).
  With English on, the panel also writes money as one amount with commas ($3,982,700) on seat 1 and the projector.
  Four rare screens still show it in two pieces ("$2 million$299000"): a fan event, a golden age, a financial
  crisis and the end of a contract.
  It is built on your PC from your own game files and every line is checked; the kit holds only the English text.
  Sega's files are kept in data\english_backup, and JAPANESE puts them back. Close the game first.
  Still Japanese: country and prefecture names (the game finds its weather table by them, and English ones crash
  the server), the network-ranking areas, and writing that is part of a picture (logos, some titles and buttons).
  The English comes from this kit's translation, from Sega's own English that the game files already hold, and
  from Sega's European English of the older WCCF (lines with the same Japanese).

WHAT SETUP CHANGES   (UNDO SETUP in SETUP.exe takes all of it back out)
  game folder     adds winmm.dll (the kit's hook) and winmm_orig.dll (a copy of your Windows' own winmm.dll)
                  (the hook also keeps the server from starting Sega's logowin.exe, which opens a white window
                  over the whole screen; a kit that had put a stand-in in its place puts Sega's back)
                  adds local\client_user_option.conf (projector) and local\ctrl_user_option.conf (server)
  beside it       seat1\   the player cabinet: links to the game folder's files and folders, its own copy of
                           client_Release.exe with 15 changes (checked byte for byte), its own settings
                  misc\FlatPanelReader_Emulator\exe\FPR_Emu.exe   the card-table helper the game starts
  Nothing else on the PC is changed.

GOOD TO KNOW
  - Your club card is saved safely: each save goes to a temporary file first and replaces the card in one step, so
    a crash or a power cut cannot leave a broken card. Before the first save of each session the card is copied to
    data\save\backup (the newest 20 are kept; CLUB CARD lists them). To go back to one: close the game, then copy it
    over data\save\seat1_club.bin.
  - Windows may ask whether control_Release.exe may use the network: either answer works, everything stays on
    this PC.
  - Antivirus programs may dislike bin\winmm.dll (it sits between the game and Windows; it also loads the panel into
    the game). Its source code is in source\.
  - One copy at a time on a PC.
  - If both pictures freeze while the sound goes on, Windows took the graphics device away from the game
    (a display change, Ctrl+Alt+Del, an administrator prompt ...). The game cannot recover from that:
    close its window (or PLAY.exe stop force), then PLAY.exe.
  - Logs are in data\logs ("PLAY.exe debug" keeps more; the card reader's full log grows about 60 MB an hour).
    If a game window closes by itself, its log (run_seat1.txt, run_projector.txt or run_server.txt) says how,
    and for the game's own "invalid parameter" stop it names the function that caused it - share that log.
    The previous run's logs are in data\logs\previous; older runs are zipped in data\logs\archive (about the
    last 200 MB of them, the oldest go first).
  - Seat 1 used to close itself at the start of some matches: the game draws a text it cannot format (a stray %).
    The panel now catches that one case: the text is shown as it is, the game goes on, and the text is written to
    seat1\wccfpanel.log (beside the game folder) as a "badfmt:" line - please share that line.
  - The arcade printed the player cards you earn from a dispenser. There is none here, so the game counted every
    card as owed ("You are owed N Player Card(s)"). The panel now tells the game nothing is owed.
  - The game is in Japanese; SETUP.exe's ENGLISH translates most of it (see ENGLISH).
  - Windows 11 slows the timers of a program whose window is minimized or covered, and the server's window starts
    minimized: its loop then ran too slowly for the projector's live matches, which stuttered. The kit tells
    Windows not to slow any of the game's programs (data\logs\run_server.txt: "Windows' throttling off").
  - The game draws 30 pictures a second, as the arcade did, and syncs them to the screen only when the main monitor
    runs at exactly 60 Hz. On other refresh rates movement can look slightly uneven; a screen at 60 or 120 Hz shows
    it evenly.

FOLDERS
  bin\       winmm.dll (the hook), FPR_Emu.exe (card-table helper)
  overlay\   wccfpanel.dll (the panel; the game's winmm.dll loads it into seat 1, and into the projector for its money
             with commas only), skin.tex (its picture);
             setup adds catalogue.tsv and cards\
  scripts\   setup, play, english, the card maker, the launcher, and stand-ins for the arcade's hardware
             (keychip and network, card reader, I/O board, scene service) and the key driver
  english\   the kit's English: screen_text.tsv (the translation), sega_rstring.tsv (Sega's European English),
             cpu_names.tsv (team names), exe_text.tsv (the ticker, the dates, money, the shop's name) - text and
             fingerprints only
  source\    the source of every program in bin\ and overlay\ (C) and of PLAY and SETUP.exe (Rust,
             source\launcher) - source\README.txt: how they were built
  python\    Python 3.13 (python.org's embeddable build) with Pillow
  data\      made on your PC: settings (panel.txt), your club card (save\, with backup\ and your other clubs in
             cards\), your keys (keys.txt), logs
