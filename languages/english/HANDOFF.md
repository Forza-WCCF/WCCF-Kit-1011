# languages\english\ - the game's English

`code\english.py` reads these four tables.

| File | What it does |
|---|---|
| `screen_text.tsv` | the kit's own translation of the screen text, line by line, keyed by Sega's ids |
| `sega_rstring.tsv` | Sega's own European English from the older WCCF, used where the Japanese is the same |
| `cpu_names.tsv` | the CPU teams' names |
| `exe_text.tsv` | text inside the game's programs: the "Next match" ticker, dates, money, the shop's name |
| `pictures.tsv` | writing inside the game's pictures - the six team stats round the hexagon, OK / BACK: each picture by Sega's fingerprint, each word's box and the word (an Italian column too); ENGLISH redraws them and adds them at the end of `data\wccf_data.xaf` (peakx, #29) |

## Careful
- Country and prefecture names stay in Japanese on purpose: the game finds its weather table by them, and English
  ones crashed the server.
- `pictures.tsv` is NOT USED by default (`english.py` PICTURES, off): with the redrawn pictures in the game's archive
  the game gave the club card straight back instead of reading it (2026-10-11, a real start on the test game - English
  text alone read the card, Japanese read it, English with the pictures did not, every try). `WCCF_PICTURES=1` turns
  it on to test a fix; the pictures are added at the archive's end and JAPANESE cuts them away again. The likely
  place to look: the club screen loads the hexagon picture (`SCM_Parameta*.dds`) right after a card read.
