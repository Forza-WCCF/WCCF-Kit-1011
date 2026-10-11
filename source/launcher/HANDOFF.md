# source\launcher\ - PLAY.exe and SETUP.exe (Rust)

The two programs a player double-clicks. They run the kit's Python (`code\play.py`, `code\setup.py`,
`code\english.py`) and show what it says.

| File | What it does |
|---|---|
| `Cargo.toml` | the project: both programs and the crates they use |
| `Cargo.lock` | every crate pinned to one version |
| `build.rs` | puts Windows version information into both programs (Defender trusts a named program more) and SETUP's look |
| `rust-toolchain.toml` | the Rust version, pinned |
| `rustfmt.toml` | how the code is formatted (`cargo fmt --check` in CI) |
| `.cargo\config.toml` | the C runtime linked in, so players need nothing installed |
| `src\lib.rs` | what both share: the kit's folder, running a `code\` script with the kit's Python |
| `src\release.rs` | the kit's releases on GitHub: SETUP's UPDATE lists them, PLAY says when a newer one is out |
| `src\watch.rs` | PLAY's watcher: closing the game's window stops the rest of the run |
| `src\bin\play.rs` | PLAY.exe: starts the game (`code\play.py` with PLAY's arguments) |
| `src\bin\setup\main.rs` | SETUP.exe's window: the game folder (set up / undo), the language, updates |
| `src\bin\setup\text.rs` | SETUP's words, in English, Italian or Japanese (from Windows' language) |

## Careful
- Rust is not installed on Ali's PC: CI builds and checks these (fmt, clippy with warnings as errors, tests). A
  comment at the end of a list entry can fail `cargo fmt --check` - put such comments above the entries.
- `release.rs` reads `version.txt`: a release is `kit-6`, a test build `kit-6-test-<commit>`; its tests cover both.
