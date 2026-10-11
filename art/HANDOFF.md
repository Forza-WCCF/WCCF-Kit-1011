# art\ - the panel's picture

| File | What it does |
|---|---|
| `skin.tex` | the whole panel around the game (TACTICS, FORMATION, the buttons) as one picture: 1728x1080, BGRA. Rendered from the project's skin page; there is no source for it here |

## Careful
- The panel (`programs\wccfpanel.dll`) is told where it is (`WCCF_SKIN`, set by play.py). The button positions in
  `source\panel\wccfpanel.c` must match where they are drawn in this picture.
