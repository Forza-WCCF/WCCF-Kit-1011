# languages\english\ - the game's English

`code\english.py` reads these four tables.

| File | What it does |
|---|---|
| `screen_text.tsv` | the kit's own translation of the screen text, line by line, keyed by Sega's ids |
| `sega_rstring.tsv` | Sega's own European English from the older WCCF, used where the Japanese is the same |
| `cpu_names.tsv` | the CPU teams' names |
| `exe_text.tsv` | text inside the game's programs: the "Next match" ticker, dates, money, the shop's name |

## Careful
- Country and prefecture names stay in Japanese on purpose: the game finds its weather table by them, and English
  ones crashed the server.
- Text drawn as a picture (for example "insert your club team card" at the start) is not in these tables.
