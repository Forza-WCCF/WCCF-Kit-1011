//! Closing the game's window ends the run (2026-10-08).  Before, closing the projector's and seat 1's windows ended
//! only those two (and the cabinet program ran on without its window); the server (its window hidden), its match
//! engines and the kit's helpers (stand-ins, key driver, panel helper) ran on in the background until STOP or their
//! 12 hours were up.  There is no STOP now: closing a game window is how the game is quit.
//!
//! After a start or a restart, PLAY leaves a watcher: the same exe again, `--watch`, without a window.  It waits for
//! the run's cabinet and projector launchers (data\running.json; _debug_launch.py ends each game, and itself, when the
//! game's window is closed) and once one has ended, runs `play.py ended`, which stops the rest of the run - by full
//! path, nothing else on the PC is touched.  Its output: data\logs\run_ended.txt.  When that stop is refused (the
//! projector's window closed while seat 1 is in a card session: a match is on), it watches the rest again.
//!
//! One watcher per kit folder.  Every PLAY first takes the watch over (`take_over`): it signals the quit event and
//! waits for the watch lock, so a watcher never stops a run that a restart is busy with.

use std::ffi::OsString;
use std::fs::{self, OpenOptions};
use std::os::windows::ffi::{OsStrExt, OsStringExt};
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;
use std::{env, io, ptr};

use windows_sys::Win32::Foundation::{
    FALSE, HANDLE, HANDLE_FLAG_INHERIT, SetHandleInformation, TRUE, WAIT_ABANDONED, WAIT_OBJECT_0,
};
use windows_sys::Win32::System::Console::{GetStdHandle, STD_ERROR_HANDLE, STD_INPUT_HANDLE, STD_OUTPUT_HANDLE};
use windows_sys::Win32::System::ProcessStatus::K32EnumProcesses;
use windows_sys::Win32::System::Threading::{
    CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW, CreateEventW, CreateMutexW, DETACHED_PROCESS, INFINITE, OpenProcess,
    PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE, QueryFullProcessImageNameW,
    ReleaseMutex, ResetEvent, SetEvent, WaitForMultipleObjects, WaitForSingleObject,
};

use crate::Kit;

/// How long a take-over waits for the watcher before it: one that is stopping a run (`play.py ended`) needs seconds.
const TAKE_OVER: Duration = Duration::from_secs(60);
/// After a game window closed: a restart under way has this long to take the watch over first.
const GRACE: Duration = Duration::from_secs(5);

struct Watch {
    lock: OwnedHandle,
    quit: OwnedHandle,
}

impl Watch {
    /// The kit folder's watch lock and quit event, made if no one has them yet.
    fn open(kit: &Kit) -> io::Result<Self> {
        let key = folder_key(&kit.dir);
        let lock = wide(&format!("Local\\wccf-kit-watch-{key:016x}"));
        let quit = wide(&format!("Local\\wccf-kit-quit-{key:016x}"));
        // SAFETY: the names are NUL-terminated UTF-16; each handle is checked, then owned (closed on drop).
        unsafe {
            Ok(Self {
                lock: owned(CreateMutexW(ptr::null(), FALSE, lock.as_ptr()))?,
                quit: owned(CreateEventW(ptr::null(), TRUE, FALSE, quit.as_ptr()))?,
            })
        }
    }

    /// The watch lock, within `wait`.  A watcher that ended without letting go (killed) leaves it abandoned: it is
    /// ours then too.
    fn lock(&self, wait: Duration) -> bool {
        let ms = u32::try_from(wait.as_millis()).unwrap_or(INFINITE - 1);
        // SAFETY: a valid mutex handle.
        let r = unsafe { WaitForSingleObject(raw(&self.lock), ms) };
        r == WAIT_OBJECT_0 || r == WAIT_ABANDONED
    }

    /// True if a PLAY takes the watch over within `wait`.
    fn quit_within(&self, wait: Duration) -> bool {
        let ms = u32::try_from(wait.as_millis()).unwrap_or(INFINITE - 1);
        // SAFETY: a valid event handle.
        unsafe { WaitForSingleObject(raw(&self.quit), ms) == WAIT_OBJECT_0 }
    }
}

/// Before PLAY runs play.py: the watcher of an earlier run (if any) lets go.
pub fn take_over(kit: &Kit) {
    let Ok(w) = Watch::open(kit) else { return };
    // SAFETY: valid handles; the mutex is released by the thread that took it.
    unsafe {
        SetEvent(raw(&w.quit));
        if w.lock(TAKE_OVER) {
            ReleaseMutex(raw(&w.lock));
        }
        ResetEvent(raw(&w.quit)); // the next watcher (ours) waits for the next take-over
    }
}

/// After play.py: the watcher, windowless and apart from this console (closing this window does not end it).  It
/// finds by itself whether there is a run to watch, and ends at once if not.
pub fn spawn_watcher(kit: &Kit) {
    // Windows hands a child every inheritable handle (std's Command always lets it inherit).  This window's own
    // input and output must not go along: a program that reads PLAY's output through a pipe would otherwise
    // wait for the watcher - for the whole game (found 2026-10-08: a stop returned 35 s late).
    for std in [STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE] {
        // SAFETY: this process's own standard handles; a missing one makes the call fail harmlessly.
        unsafe { SetHandleInformation(GetStdHandle(std), HANDLE_FLAG_INHERIT, 0) };
    }
    let exe = env::current_exe().unwrap_or_else(|_| kit.dir.join("PLAY.exe"));
    let started = Command::new(exe)
        .arg("--watch")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
        .spawn();
    if let Err(e) = started {
        println!("(Closing the game's window will not stop the rest - the watcher did not start: {e}.");
        println!(" \"PLAY.exe stop\" does.)");
    }
}

/// `--watch`: once a launcher of the run ends (its game window was closed), stops what is left - unless a PLAY takes
/// the watch over first.  A stop refused for a card session leaves the others watched.
pub fn watch(kit: &Kit) {
    let Ok(w) = Watch::open(kit) else { return };
    if !w.lock(TAKE_OVER) {
        return;
    }
    let mut launchers = run_launchers(kit);
    while !launchers.is_empty() {
        let handles: Vec<HANDLE> = [raw(&w.quit)].into_iter().chain(launchers.iter().map(raw)).collect();
        let count = u32::try_from(handles.len()).unwrap_or(u32::MAX);
        // SAFETY: valid handles, at most 1 + the run's launchers (a few, far under MAXIMUM_WAIT_OBJECTS).
        let r = unsafe { WaitForMultipleObjects(count, handles.as_ptr(), FALSE, INFINITE) };
        match r.wrapping_sub(WAIT_OBJECT_0) as usize {
            0 => return, // taken over
            i if i < handles.len() => drop(launchers.swap_remove(i - 1)),
            _ => return, // the wait failed: leave everything as it is
        }
        if w.quit_within(GRACE) || !stop_refused(kit) {
            return;
        }
    }
    // the lock goes when this process ends (abandoned is as good as released for the next one)
}

/// `play.py ended`, hidden, its output added to data\logs\run_ended.txt; true if it refused (exit 3: a card session
/// is open on a cabinet that still runs).
fn stop_refused(kit: &Kit) -> bool {
    let logs = kit.data().join("logs");
    let mut cmd = kit.script("play.py");
    cmd.arg("ended").stdin(Stdio::null()).creation_flags(CREATE_NO_WINDOW);
    let log = fs::create_dir_all(&logs).and_then(|()| {
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("run_ended.txt"))
    });
    if let Ok(out) = log {
        if let Ok(err) = out.try_clone() {
            cmd.stderr(err);
        }
        cmd.stdout(out);
    }
    cmd.status().is_ok_and(|s| s.code() == Some(3))
}

/// The run's cabinet and projector launchers that still run: from data\running.json, each checked to be the kit's
/// own Python (a process id Windows gave to another program since is left alone).
fn run_launchers(kit: &Kit) -> Vec<OwnedHandle> {
    let Ok(text) = fs::read_to_string(kit.data().join("running.json")) else {
        return Vec::new();
    };
    let Ok(python) = fs::canonicalize(kit.python()) else {
        return Vec::new();
    };
    launcher_pids(&text)
        .into_iter()
        .filter_map(|pid| open_if_runs(pid, &python))
        .collect()
}

/// The process ids of running.json's launchers: "seat N launcher" and "projector launcher" (not the server's).
fn launcher_pids(running_json: &str) -> Vec<u32> {
    let Ok(info) = serde_json::from_str::<serde_json::Value>(running_json) else {
        return Vec::new();
    };
    let Some(processes) = info.get("processes").and_then(serde_json::Value::as_object) else {
        return Vec::new();
    };
    processes
        .iter()
        .filter(|(_, role)| role.as_str().is_some_and(is_window_launcher))
        .filter_map(|(pid, _)| pid.parse().ok())
        .collect()
}

fn is_window_launcher(role: &str) -> bool {
    role == "projector launcher"
        || role
            .strip_prefix("seat ")
            .and_then(|r| r.strip_suffix(" launcher"))
            .is_some_and(|n| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit()))
}

/// A handle to wait on pid, if it runs `python`.
fn open_if_runs(pid: u32, python: &Path) -> Option<OwnedHandle> {
    let (process, image) = open_with_image(pid)?;
    (image == python).then_some(process)
}

/// The process and the program it runs (canonical path), if this user may look at it.
fn open_with_image(pid: u32) -> Option<(OwnedHandle, PathBuf)> {
    // SAFETY: the handle is checked, then owned; the buffer and its length go together.
    unsafe {
        let process = owned(OpenProcess(
            PROCESS_SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION,
            FALSE,
            pid,
        ))
        .ok()?;
        let mut buf = vec![0u16; 32_768];
        let mut len = u32::try_from(buf.len()).ok()?;
        if QueryFullProcessImageNameW(raw(&process), PROCESS_NAME_WIN32, buf.as_mut_ptr(), &mut len) == 0 {
            return None;
        }
        let image = fs::canonicalize(PathBuf::from(OsString::from_wide(&buf[..len as usize]))).ok()?;
        Some((process, image))
    }
}

/// A program that runs from the kit folder (the kit's Python, a launcher, the injector ...), this one aside: the game
/// or a kit tool is on.  SETUP.exe's update writes over the kit only when there is none.
pub fn kit_program_running(kit: &Kit) -> Option<PathBuf> {
    let dir = fs::canonicalize(&kit.dir).ok()?;
    let mut pids = vec![0u32; 4096];
    let mut bytes = 0;
    let size = u32::try_from(pids.len() * 4).ok()?;
    // SAFETY: the buffer holds `size` bytes; Windows writes at most that many and says how many in `bytes`.
    if unsafe { K32EnumProcesses(pids.as_mut_ptr(), size, &mut bytes) } == 0 {
        return None;
    }
    pids.truncate(bytes as usize / 4);
    pids.into_iter()
        .filter(|&pid| pid != std::process::id())
        .filter_map(open_with_image)
        .map(|(_, image)| image)
        .find(|image| image.starts_with(&dir))
}

/// A name for the kit folder that every build gives the same (FNV-1a over its path, ASCII case folded).
fn folder_key(dir: &Path) -> u64 {
    dir.as_os_str().encode_wide().fold(0xcbf2_9ce4_8422_2325, |h, c| {
        let c = if (u16::from(b'A')..=u16::from(b'Z')).contains(&c) {
            c + 32
        } else {
            c
        };
        (h ^ u64::from(c)).wrapping_mul(0x0100_0000_01b3)
    })
}

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain([0]).collect()
}

fn raw(h: &OwnedHandle) -> HANDLE {
    h.as_raw_handle()
}

/// # Safety
/// `h` is a handle just returned to this process, owned by nobody else.
unsafe fn owned(h: HANDLE) -> io::Result<OwnedHandle> {
    if h.is_null() {
        Err(io::Error::last_os_error())
    } else {
        // SAFETY: as the caller promises.
        Ok(unsafe { OwnedHandle::from_raw_handle(h) })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn launchers_are_the_window_ones() {
        let json = r#"{"mode": "local", "processes": {"10": "scene service", "11": "server launcher",
            "12": "projector launcher", "13": "seat 1 launcher", "14": "seat 12 launcher", "15": "key driver",
            "16": "seat  launcher", "x": "seat 2 launcher", "17": 5}}"#;
        let mut pids = launcher_pids(json);
        pids.sort_unstable();
        assert_eq!(pids, [12, 13, 14]);
    }

    #[test]
    fn no_run_no_launchers() {
        assert!(launcher_pids("").is_empty());
        assert!(launcher_pids("[]").is_empty());
        assert!(launcher_pids(r#"{"processes": []}"#).is_empty());
    }

    #[test]
    fn folder_key_ignores_case() {
        assert_eq!(
            folder_key(Path::new(r"D:\Games\WCCF Kit")),
            folder_key(Path::new(r"d:\games\wccf kit"))
        );
        assert_ne!(folder_key(Path::new(r"D:\Kit1")), folder_key(Path::new(r"D:\Kit2")));
    }
}
