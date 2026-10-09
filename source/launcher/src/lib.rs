//! The kit's launchers' shared code (in place of the .bat files, 2026-10-08), used by PLAY.exe.  It runs one
//! kit script with the kit's own Python (python\python.exe) in its window, passes its arguments on as they are and
//! keeps the window as the .bat did: after a problem until a key is pressed, after a good PLAY for 30 seconds.
//! PLAY also leaves the run's watcher behind (watch.rs): once a game window is closed, it stops the rest.

mod watch;

use std::ffi::OsStr;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};
use std::{env, mem};

use windows_sys::Win32::Foundation::{FALSE, HANDLE, INVALID_HANDLE_VALUE, TRUE, WAIT_OBJECT_0};
use windows_sys::Win32::System::Console::{
    CTRL_BREAK_EVENT, CTRL_C_EVENT, FlushConsoleInputBuffer, GetConsoleMode, GetStdHandle, INPUT_RECORD, KEY_EVENT,
    ReadConsoleInputW, STD_INPUT_HANDLE, SetConsoleCtrlHandler,
};
use windows_sys::Win32::System::Threading::{INFINITE, WaitForSingleObject};
use windows_sys::core::BOOL;

pub use watch::{kit_program_running, spawn_watcher, take_over, watch};

/// The kit folder: the one this exe is in.
pub struct Kit {
    dir: PathBuf,
}

impl Kit {
    pub fn here() -> Self {
        let exe = env::current_exe().unwrap_or_default();
        let dir = exe.parent().map_or_else(|| PathBuf::from("."), Path::to_path_buf);
        Self { dir }
    }

    pub fn dir(&self) -> &Path {
        &self.dir
    }

    fn python(&self) -> PathBuf {
        self.dir.join("python").join("python.exe")
    }

    fn data(&self) -> PathBuf {
        self.dir.join("data")
    }

    /// `python\python.exe scripts\<script>`, to add arguments to
    fn script(&self, script: &str) -> Command {
        let mut cmd = Command::new(self.python());
        cmd.arg(self.dir.join("scripts").join(script));
        cmd
    }

    /// Runs a kit script in this window; its exit code (1 if it could not run).
    pub fn run<S: AsRef<OsStr>>(&self, script: &str, args: &[S]) -> u8 {
        // Ctrl+C goes to the script (Python stops with its own message); this window stays to show it, as cmd did
        // for the .bat.  A handler, not SetConsoleCtrlHandler(None, TRUE): that one the script would inherit.
        // SAFETY: `keep_window` is a valid handler for the life of the process.
        unsafe { SetConsoleCtrlHandler(Some(keep_window), TRUE) };
        match self.script(script).args(args).status() {
            Ok(status) => status.code().and_then(|c| u8::try_from(c).ok()).unwrap_or(1),
            Err(e) => {
                println!("Could not start the kit's Python ({}): {e}", self.python().display());
                1
            }
        }
    }
}

unsafe extern "system" fn keep_window(event: u32) -> BOOL {
    if event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT {
        TRUE
    } else {
        FALSE
    }
}

/// "pause": waits for a key.
pub fn pause() {
    println!("Press any key to continue . . .");
    wait_key(None);
}

/// After a good start: the window closes by itself, or at a key.
pub fn countdown(time: Duration) {
    println!(
        "This window closes by itself in {} seconds (any key closes it now).",
        time.as_secs()
    );
    wait_key(Some(time));
}

/// A key pressed, or `limit` over.  Without a console keyboard (input from a pipe or a file: a tool, a test) it
/// does not wait at all - never a window that nobody can close.
fn wait_key(limit: Option<Duration>) {
    // SAFETY: plain Win32 calls on this process's own standard input handle.
    let input: HANDLE = unsafe { GetStdHandle(STD_INPUT_HANDLE) };
    let mut mode = 0;
    if input.is_null() || input == INVALID_HANDLE_VALUE || unsafe { GetConsoleMode(input, &mut mode) } == 0 {
        return;
    }
    unsafe { FlushConsoleInputBuffer(input) }; // a key pressed while the script ran does not count
    let end = limit.map(|d| Instant::now() + d);
    loop {
        let ms = match end {
            None => INFINITE,
            Some(end) => match end.checked_duration_since(Instant::now()) {
                Some(left) if !left.is_zero() => u32::try_from(left.as_millis()).unwrap_or(INFINITE - 1),
                _ => return,
            },
        };
        // the input handle is signalled for every console event (mouse, focus, a key let go): read them one by one
        if unsafe { WaitForSingleObject(input, ms) } != WAIT_OBJECT_0 {
            return;
        }
        // SAFETY: INPUT_RECORD is plain data; ReadConsoleInputW fills at most the one record given.
        let mut rec: INPUT_RECORD = unsafe { mem::zeroed() };
        let mut read = 0;
        if unsafe { ReadConsoleInputW(input, &mut rec, 1, &mut read) } == 0 {
            return;
        }
        if read == 1 && u32::from(rec.EventType) == KEY_EVENT && unsafe { rec.Event.KeyEvent.bKeyDown } != 0 {
            return;
        }
    }
}
