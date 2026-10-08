//! PLAY.exe - starts the game: scripts\play.py with this exe's arguments ("debug", "local", "server", "remote ...",
//! "status", "show", "restart"; play.py's own help lists them).  After a good start the window closes in 30 seconds;
//! after a problem, or with "debug", it stays until a key.  The run's watcher stays behind (closing every game window
//! stops the rest); "status" and "show" only look, so they leave the watch alone.

use std::ffi::OsString;
use std::process::ExitCode;
use std::time::Duration;

use launcher::Kit;

fn main() -> ExitCode {
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let kit = Kit::here();
    if args.first().is_some_and(|a| a == "--watch") {
        launcher::watch(&kit);
        return ExitCode::SUCCESS;
    }
    let word = |w: &str| args.iter().any(|a| a.eq_ignore_ascii_case(w));
    let looks_only = args
        .first()
        .is_some_and(|a| a.eq_ignore_ascii_case("status") || a.eq_ignore_ascii_case("show"));
    if !looks_only {
        launcher::take_over(&kit);
    }
    let rc = kit.run("play.py", &args);
    if !looks_only {
        launcher::spawn_watcher(&kit);
    }
    println!();
    if rc != 0 || word("debug") {
        launcher::pause();
    } else {
        launcher::countdown(Duration::from_secs(30));
    }
    ExitCode::from(rc)
}
