# languages\italian\ - the game in Italian (peakx, #30)

SETUP.exe's ITALIANO (`code\english.py on it`). Each line comes from here first, then from the English - never
Japanese.

| File | What it does |
|---|---|
| `screen_text.tsv` | the kit's own Italian of the screen text, keyed by Sega's ids |
| `sega_rstring.tsv` | Sega's own Italian from the older European WCCF, used where the Japanese is the same |

## Careful
- Players', CPU teams' and supporters' names stay as in the English (the game puts a nickname's adjective first,
  which Italian cannot follow). The pictures' Italian is the second column of `languages\english\pictures.tsv`.
- `source\test_italian_tables.py` checks each Italian line keeps the same printf and colour codes as the English line
  of that key, in the game's font (a stray `%` shows junk or stops the game); `english.py` checks against the game's
  own Japanese at "on".
