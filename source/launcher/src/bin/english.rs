//! ENGLISH.exe - the game in English, built from your own game files (Sega's are kept in data\english_backup):
//! scripts\english.py with this exe's arguments.  "off" puts Sega's Japanese files back; "check" only says what it
//! would do.

use std::ffi::OsString;
use std::process::ExitCode;

use launcher::Kit;

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let rc = Kit::here().run("english.py", &args);
    println!();
    launcher::pause();
    ExitCode::from(rc)
}
