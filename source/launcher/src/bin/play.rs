//! PLAY.exe - starts the game: scripts\play.py with this exe's arguments ("debug", "local", "server", "remote ...",
//! "status", "show", "restart"; play.py's own help lists them).  After a good start the window closes in 30 seconds;
//! after a problem, or with "debug", it stays until a key.  The run's watcher stays behind (closing a game window
//! quits the game: the rest stops too); "status" and "show" only look, so they leave the watch alone.  "stop" (a
//! game that is stuck) and "stop force" go to play.py like the rest.  Meanwhile it asks GitHub for the kit's latest
//! release (not a test build) and says so when it is newer than this kit.

use std::ffi::OsString;
use std::process::ExitCode;
use std::time::Duration;

use launcher::Kit;
use launcher::release::{LatestRelease, is_newer};

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
    let latest = LatestRelease::ask(); // while play.py starts the game
    if !looks_only {
        launcher::take_over(&kit);
    }
    let rc = kit.run("play.py", &args);
    if !looks_only {
        launcher::spawn_watcher(&kit);
    }
    if let (Some(tag), Some(here)) = (latest.tag(Duration::from_secs(3)), kit.version())
        && is_newer(&tag, &here)
    {
        println!();
        println!("A newer kit is out: {tag} (this one is {here}). To update: close the game, open SETUP.exe, UPDATE.");
    }
    println!();
    if rc != 0 || word("debug") {
        launcher::pause();
    } else {
        launcher::countdown(Duration::from_secs(30));
    }
    ExitCode::from(rc)
}
