# source\card_table\ - the card-table helper (programs\FPR_Emu.exe)

On a real cabinet the player lays their cards on a table that reads them. This program answers the game's questions
about that table.

| File | What it does |
|---|---|
| `fpr_emu.c` | answers the game's card-table polls with the cards listed in `seat1\fpr_table0.txt` (laid out by `code\cards\formation.py`); setup.py copies it into the game's `misc\FlatPanelReader_Emulator\exe\` |
