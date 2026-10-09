//! SETUP.exe - sets up your copy of the game (once; again to check and repair): scripts\setup.py with this exe's
//! arguments.  Drag the game folder (the one with client_Release.exe) onto it, or start it and answer the question;
//! "undo" puts the game folder back the way it was before setup.

use std::ffi::OsString;
use std::process::ExitCode;

use launcher::Kit;

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let rc = Kit::here().run("setup.py", &args);
    println!();
    launcher::pause();
    ExitCode::from(rc)
}
