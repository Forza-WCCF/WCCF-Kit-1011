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
- Text drawn as a picture is changed only where `pictures.tsv` lists it (for example "insert your club team card" at
  the start stays Japanese). The pictures are written into the game's 1.4 GB archive (added at its end, JAPANESE cuts
  them away again): peakx's note says "not yet seen in a running game" - check that in a real start before a release.
