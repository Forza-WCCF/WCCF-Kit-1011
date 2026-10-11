# languages\ - the game in other languages

One folder per language. Nothing of Sega's is in here: only text, and fingerprints of Sega's files.

| Folder | What is in it |
|---|---|
| `english\` | the English (SETUP.exe's ENGLISH) |

## How a language gets into the game
`code\english.py` builds the game's text on the player's PC from THEIR game files and these tables, checks every line,
backs Sega's files up in `data\english_backup\`, then swaps the new files in - one file at a time, whole.

## Careful
- peakx's Italian (pull request #30) goes in as `languages\italian\` when it is reworked for the new folders.
