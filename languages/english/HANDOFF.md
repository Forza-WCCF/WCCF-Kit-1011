# languages\english\ - the game's English

`code\english.py` reads these four tables.

| File | What it does |
|---|---|
| `screen_text.tsv` | the kit's own translation of the screen text, line by line, keyed by Sega's ids |
| `sega_rstring.tsv` | Sega's own European English from the older WCCF, used where the Japanese is the same |
| `cpu_names.tsv` | the CPU teams' names |
| `exe_text.tsv` | text inside the game's programs: the "Next match" ticker, dates, money, the shop's name |
| `pictures.tsv` | writing inside the game's pictures - the six team stats round the hexagon, OK / BACK, the bar's "please wait for the next match": each picture by Sega's fingerprint, each word's box and the word (an Italian column too). `how`: `archive` = ENGLISH redraws it and adds it at the end of `data\wccf_data.xaf` (peakx, #29 - off, below); `memory` = redrawn as the same kind and size of picture into `data\english_pictures\`, which seat 1's hook hands the game as it loads Sega's (2026-10-15, on). `art`: a file here holding our English lettering (only inside the row's boxes), laid into Sega's picture instead of drawing the words in Arial Bold - English only, Italian draws its own words |
| `pictures_SCM_Parameta_max.png` | the English lettering of the six team stats round the hexagon (seat 1's row): OFFENCE, TACKLING, SPEED, POWER, CONTROL, DEFENCE - our words only, each in its box, nothing of Sega's. Made 2026-10-16 with Codex's image tool from Sega's picture (enlarged on black), then made Sega's size, the alpha taken from the brightness, only the boxes kept and the colours matched to Sega's measured cream and gold; every word within half a pixel of Sega's centre |
| `pictures_MNG_Base_MenuTex.png` | the same for the management menu's button names: OK and BACK beside Sega's own KEY (under Manager License), in Sega's thin white letters at KEY's height, OK moved 2 px to its box's centre |

## Careful
- Country and prefecture names stay in Japanese on purpose: the game finds its weather table by them, and English
  ones crashed the server.
- The `memory` rows never touch the archive, so the card problem below cannot come from them; the wait line was seen in
  English in the real game with a club card read in the same session (2026-10-15). A row could move from `archive` to
  `memory` - each needs that check with a card before it ships. 2026-10-16: the hexagon's seat-1 row moved and the
  menu's OK / BACK was added (both `memory`, with `art`); their check with a card is the real game on that branch.
- A word box must hold ALL of Sega's word, its faintest edge too: the menu's first boxes, measured where the writing
  was bright, left a dot of 決定 and 戻る beside OK and BACK. Measure at alpha 1 and over.
- `pictures.tsv`'s `archive` rows are NOT USED by default (`english.py` PICTURES, off): with the redrawn pictures in the game's archive
  the game gave the club card straight back instead of reading it (2026-10-11, a real start on the test game - English
  text alone read the card, Japanese read it, English with the pictures did not, every try). `WCCF_PICTURES=1` turns
  it on to test a fix; the pictures are added at the archive's end and JAPANESE cuts them away again. The likely
  place to look: the club screen loads the hexagon picture (`SCM_Parameta*.dds`) right after a card read.
