The source of every program the kit ships, and how each is built.  The kit ZIP carries the built programs; git
holds only their source (2026-10-08).  From a git checkout, build them all into their places with:

    powershell -ExecutionPolicy Bypass -File source\build.ps1     the C programs (32-bit, MSVC) and the launchers (Rust)
    powershell -ExecutionPolicy Bypass -File source\check.ps1     the checks that need no game (scripts, key driver, panel)
    powershell -ExecutionPolicy Bypass -File source\package.ps1   the kit ZIP in dist\, as players get it

Needs Visual Studio 2022 (or its Build Tools) with "Desktop development with C++", and rustup.  CI
(.github\workflows\kit.yml) runs the same three on every push and pull request; a tag kit-* also gets a draft
release with the ZIP.  The commands each program is built with, for the record (build.ps1 adds /Brepro, so the same
source gives the same file, and keeps the compiler's leftovers in source\build\):

The C source of every program the kit ships. Each was built with Microsoft's C compiler for 32-bit x86
(Visual Studio Build Tools, "vcvarsall.bat x86"), the runtime linked in (/MT), so no Visual C++ runtime is needed.

  bin\winmm.dll        mxhook\mxhook.c (+ winmm_fwd.h: forwards all 192 winmm functions to winmm_orig.dll)
                       cl /nologo /LD /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS mxhook.c /Fe:winmm.dll
  bin\FPR_Emu.exe      fpr_emu\fpr_emu.c
                       cl /nologo /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS fpr_emu.c /Fe:FPR_Emu.exe /link user32.lib
  bin\logowin.exe      logowin\logowin_standin.c
                       cl /nologo /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS logowin_standin.c /Fe:logowin.exe /link /SUBSYSTEM:WINDOWS
  overlay\wccfpanel.dll   overlay\wccfpanel.c
                       cl /nologo /LD /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS wccfpanel.c /Fe:wccfpanel.dll
                          /link d3d9.lib gdi32.lib user32.lib ole32.lib windowscodecs.lib
  overlay\inject.exe   overlay\inject.c (must be 32-bit: it hands the game 32-bit LoadLibraryA's address)
                       cl /nologo /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS inject.c /Fe:inject.exe
  overlay\fakegame.c   not shipped: a stand-in for seat 1's game window to see the panel without the game (its
                       header: the steps, and the settings that keep a test off the live game)
                       cl /nologo /O2 /MT /W3 /D_CRT_SECURE_NO_WARNINGS fakegame.c /Fe:fakegame.exe /link d3d9.lib user32.lib

PLAY.exe, SETUP.exe, ENGLISH.exe   launcher\ (Rust; Cargo.lock pins every crate)
                       cargo build --release --locked --target x86_64-pc-windows-msvc
                       then copy target\x86_64-pc-windows-msvc\release\{PLAY,SETUP,ENGLISH}.exe to the kit folder.
                       The C runtime is linked in (launcher\.cargo\config.toml); checks: cargo fmt --check,
                       cargo clippy --all-targets -- -D warnings, cargo test

overlay\skin.tex is a picture (the panel's art, 1728x1080, BGRA) rendered from the project's skin page; it has no
source here.

What each does, in short:
  winmm.dll     loaded by the game in place of Windows' winmm.dll (the game's folder is searched first); passes
                every winmm call through, and stands in for the arcade's devices: serial ports to the card reader
                and I/O board stand-ins (named pipes), the RingEdge memory, the network address (127.0.0.1)
  FPR_Emu.exe   answers the game's card-table polls with the cards in seat1\fpr_table0.txt
  logowin.exe   Sega's start-up notice window, replaced by one that only records the notice
  wccfpanel.dll the panel around seat 1's picture (drawn with the game's own Direct3D 9 device)
  inject.exe    loads wccfpanel.dll into seat 1's running game
  launchers     run scripts\play.py, setup.py or english.py with the kit's Python and keep the window as the .bat
                files did; PLAY leaves a windowless watcher (PLAY.exe --watch) that stops the rest of the run once a
                game window is closed (launcher\src\watch.rs; scripts\_debug_launch.py ends the game itself)
