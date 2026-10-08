//! STOP.exe - stops everything PLAY started: scripts\play.py stop, with this exe's arguments ("force", "check").
//! During a card session it asks first; a stop that was refused leaves the game running and watched again.

use std::ffi::OsString;
use std::process::ExitCode;

use launcher::Kit;

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let kit = Kit::here();
    if args.first().is_some_and(|a| a == "--watch") {
        launcher::watch(&kit);
        return ExitCode::SUCCESS;
    }
    launcher::take_over(&kit);
    let rc = kit.run("play.py", &[&[OsString::from("stop")], args.as_slice()].concat());
    launcher::spawn_watcher(&kit);
    println!();
    launcher::pause();
    ExitCode::from(rc)
}
