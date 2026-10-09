//! SETUP.exe - the kit's window (2026-10-09; before, a console that ran setup.py, and ENGLISH.exe beside it).
//!   GAME FOLDER  set up / repair (scripts\setup.py GAME) and undo (setup.py undo GAME); the folder is typed, picked,
//!                dropped on the window or on SETUP.exe, and remembered by setup.py in data\settings.json
//!   LANGUAGE     the game in English (scripts\english.py on) or Sega's Japanese back (english.py off)
//!   UPDATE       the kit's GitHub releases and test builds (pre-releases): the chosen one's kit ZIP is downloaded,
//!                unzipped into data\update and copied over the kit folder - data\ (club cards, keys, settings, logs)
//!                is never written, and nothing is copied while the game or a kit tool runs.  Files the old kit
//!                shipped (files.txt) that the new one does not are removed; then setup runs again, and English if on.
//! The scripts' output fills the window.  "SETUP.exe GAME" and "SETUP.exe undo" start that at once.
//!
//! The download and the unzip are Windows' own curl.exe and tar.exe (in System32 since Windows 10 1803): HTTPS with
//! Windows' certificates, and tar refuses a ZIP entry that would land outside its folder (an absolute path or "..").

#![windows_subsystem = "windows"]

mod text;

use std::collections::HashSet;
use std::ffi::{OsStr, OsString};
use std::io::{BufRead, BufReader, Read};
use std::os::windows::process::CommandExt;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Mutex, MutexGuard, PoisonError};
use std::time::Duration;
use std::{env, fs, mem, ptr, thread};

use launcher::Kit;
use launcher::release::{REPO, curl, is_newer, system32};
use serde_json::Value;
use text::{fill, t};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    COLOR_BTNFACE, CreateFontIndirectW, GetDC, GetDeviceCaps, LOGPIXELSY, ReleaseDC,
};
use windows_sys::Win32::System::Com::{COINIT_APARTMENTTHREADED, CoInitializeEx, CoTaskMemFree};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::SystemServices::SS_ETCHEDHORZ;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::UI::Controls::{
    EM_REPLACESEL, EM_SETLIMITTEXT, EM_SETSEL, ICC_PROGRESS_CLASS, INITCOMMONCONTROLSEX, InitCommonControlsEx,
    PBM_SETPOS, PBM_SETRANGE32, PROGRESS_CLASSW,
};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::EnableWindow;
use windows_sys::Win32::UI::Shell::{
    BIF_NEWDIALOGSTYLE, BIF_RETURNONLYFSDIRS, BROWSEINFOW, DragAcceptFiles, DragFinish, DragQueryFileW, HDROP,
    SHBrowseForFolderW, SHGetPathFromIDListW, ShellExecuteW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::*;
use windows_sys::core::{PCWSTR, w};

/// Launchers of earlier kits that this one replaced (PLAY.exe, SETUP.exe): removed unless the kit lists them.
const LEGACY: &[&str] = &[
    "PLAY.bat",
    "STOP.bat",
    "SETUP.bat",
    "ENGLISH.bat",
    "STOP.exe",
    "ENGLISH.exe",
    "UPDATE.exe",
];

const ID_FOLDER: i32 = 10;
const ID_BROWSE: i32 = 11;
const ID_SETUP: i32 = 12;
const ID_UNDO: i32 = 13;
const ID_ENGLISH: i32 = 14;
const ID_JAPANESE: i32 = 15;
const ID_LANGUAGE: i32 = 16;
const ID_HEADING: i32 = 17;
const ID_LIST: i32 = 18;
const ID_UPDATE: i32 = 19;
const ID_NOTES: i32 = 20;
const ID_STATUS: i32 = 21;
const ID_BAR: i32 = 22;
const ID_LOG: i32 = 23;
const BUTTONS: [i32; 7] = [
    ID_BROWSE,
    ID_SETUP,
    ID_UNDO,
    ID_ENGLISH,
    ID_JAPANESE,
    ID_UPDATE,
    ID_NOTES,
];

#[derive(Clone, Debug, PartialEq)]
struct Release {
    tag: String,
    test: bool,
    date: String,
    page: String,
    zip_url: String,
    zip_size: u64,
}

enum Step {
    Script(&'static str, Vec<OsString>),
    Update(Release),
}

/// What the worker threads tell the window; the window looks every 100 ms.
struct Shared {
    releases: Vec<Release>,
    listed: bool, // `releases` is new: the list box gets it
    status: String,
    progress: u32, // of 1000
    log: String,   // lines for the output box, not shown yet
    busy: bool,    // a job runs
    updated: bool, // an update has just finished: offer setup
    changed: bool,
}

static SHARED: Mutex<Shared> = Mutex::new(Shared {
    releases: Vec::new(),
    listed: false,
    status: String::new(),
    progress: 0,
    log: String::new(),
    busy: false,
    updated: false,
    changed: true,
});

fn shared() -> MutexGuard<'static, Shared> {
    SHARED.lock().unwrap_or_else(PoisonError::into_inner)
}

fn say(status: impl Into<String>, progress: u32) {
    let mut s = shared();
    s.status = status.into();
    s.progress = progress;
    s.changed = true;
}

fn log(line: &str) {
    let mut s = shared();
    s.log.push_str(line);
    s.log.push_str("\r\n");
    s.changed = true;
}

// ---- the kit's releases on GitHub -------------------------------------------------------------------------------

/// The releases that have a kit ZIP, newest first (as GitHub lists them).
fn releases(json: &str) -> Result<Vec<Release>, String> {
    let list: Vec<Value> = serde_json::from_str(json).map_err(|e| format!("not a list of releases ({e})"))?;
    let zip = |a: &&Value| {
        a["name"]
            .as_str()
            .is_some_and(|n| n.to_ascii_lowercase().ends_with(".zip"))
    };
    Ok(list
        .iter()
        .filter(|r| r["draft"].as_bool() != Some(true))
        .filter_map(|r| {
            let asset = r["assets"].as_array()?.iter().find(zip)?;
            let url = asset["browser_download_url"].as_str()?;
            Some(Release {
                tag: r["tag_name"].as_str()?.to_owned(),
                test: r["prerelease"].as_bool() == Some(true),
                date: r["published_at"].as_str().unwrap_or("").chars().take(10).collect(),
                page: r["html_url"].as_str().unwrap_or("").to_owned(),
                zip_url: url.starts_with("https://").then(|| url.to_owned())?,
                zip_size: asset["size"].as_u64().unwrap_or(0),
            })
        })
        .collect())
}

fn fetch() -> Result<Vec<Release>, String> {
    let api = format!("https://api.github.com/repos/{REPO}/releases?per_page=30");
    let out = curl()
        .args(["-H", "Accept: application/vnd.github+json", "--url", &api])
        .output()
        .map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_owned());
    }
    releases(&String::from_utf8_lossy(&out.stdout))
}

// ---- an update --------------------------------------------------------------------------------------------------

fn running_check(kit: &Kit) -> Result<(), String> {
    match launcher::kit_program_running(kit) {
        Some(p) => {
            let name = p.file_name().map_or(p.as_os_str(), OsStr::new).display().to_string();
            Err(fill(t().close_game, &[&name]))
        }
        None => Ok(()),
    }
}

/// Download, unzip, copy over the kit folder, remove what the new kit no longer ships.
fn apply(kit: &Kit, r: &Release) -> Result<(), String> {
    running_check(kit)?;
    let dir = kit.dir();
    let work = dir.join("data").join("update");
    let unzipped = work.join("kit");
    let zip = work.join("kit.zip");
    let _ = fs::remove_dir_all(&work);
    fs::create_dir_all(&unzipped).map_err(|e| format!("{}: {e}", work.display()))?;

    log(&fill(t().downloading, &[&r.tag]));
    let mut child = curl()
        .arg("-o")
        .arg(&zip)
        .args(["--url", &r.zip_url])
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| fill(t().download_failed, &[&e.to_string()]))?;
    while child.try_wait().map_err(|e| e.to_string())?.is_none() {
        let got = fs::metadata(&zip).map_or(0, |m| m.len());
        let mb = |b: u64| b as f64 / 1_048_576.0;
        say(
            format!(
                "{}  {:.1} / {:.1} MB",
                fill(t().downloading, &[&r.tag]),
                mb(got),
                mb(r.zip_size)
            ),
            (got.saturating_mul(900) / r.zip_size.max(1)).min(900) as u32,
        );
        thread::sleep(Duration::from_millis(200));
    }
    let out = child.wait_with_output().map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(fill(
            t().download_failed,
            &[String::from_utf8_lossy(&out.stderr).trim()],
        ));
    }

    log(t().unzipping);
    say(t().unzipping, 920);
    let out = system32("tar.exe")
        .arg("-xf")
        .arg(&zip)
        .arg("-C")
        .arg(&unzipped)
        .output()
        .map_err(|e| fill(t().unzip_failed, &[&e.to_string()]))?;
    if !out.status.success() {
        return Err(fill(t().unzip_failed, &[String::from_utf8_lossy(&out.stderr).trim()]));
    }
    // the kit ZIP holds one folder (WCCF-2010-11-kit\) with the kit in it
    let top = fs::read_dir(&unzipped)
        .map_err(|e| e.to_string())?
        .flatten()
        .map(|e| e.path())
        .find(|p| p.join("PLAY.exe").is_file())
        .ok_or(t().not_a_kit)?;

    running_check(kit)?; // the game may have started during the download
    log(&fill(t().copying, &[&r.tag]));
    say(fill(t().copying, &[&r.tag]), 950);
    let mut old = manifest(&dir.join("files.txt")).unwrap_or_default();
    old.extend(LEGACY.iter().map(|&f| f.to_owned()));
    let new = manifest(&top.join("files.txt"));
    // an older kit brings neither: the newer kit's must not stay behind and speak for it
    for f in ["files.txt", "version.txt"] {
        let _ = fs::remove_file(dir.join(f));
    }
    copy_over(&top, dir, true)?;
    // without the new kit's list nothing is known to be gone: nothing is removed
    if let Some(new) = new {
        for f in obsolete(&old, &new) {
            if fs::remove_file(dir.join(f)).is_ok() {
                log(&format!("  removed {f}"));
            }
        }
    }
    let _ = fs::remove_dir_all(&work);
    Ok(())
}

/// Every file of `from` over `to`; the kit folder's own data\ is left out.
fn copy_over(from: &Path, to: &Path, top: bool) -> Result<(), String> {
    for entry in fs::read_dir(from).map_err(|e| format!("{}: {e}", from.display()))? {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name();
        if top && name.eq_ignore_ascii_case("data") {
            continue;
        }
        let (src, dst) = (entry.path(), to.join(&name));
        let dir = entry.file_type().is_ok_and(|t| t.is_dir());
        let written = if dir {
            fs::create_dir_all(&dst)
        } else {
            replace(&src, &dst)
        };
        written.map_err(|e| fill(t().write_failed, &[&dst.display().to_string(), &e.to_string()]))?;
        if dir {
            copy_over(&src, &dst, false)?;
        }
    }
    Ok(())
}

/// A program that runs (this SETUP.exe) cannot be written over, but it can be moved aside: SETUP.exe.old, deleted
/// at the next start.
fn replace(src: &Path, dst: &Path) -> std::io::Result<()> {
    match fs::copy(src, dst) {
        Ok(_) => Ok(()),
        Err(e) if env::current_exe().is_ok_and(|me| me == dst) => {
            let old = old_exe(dst);
            let _ = fs::remove_file(&old);
            fs::rename(dst, &old).map_err(|_| e)?;
            fs::copy(src, dst).map(drop)
        }
        Err(e) => Err(e),
    }
}

fn old_exe(exe: &Path) -> PathBuf {
    let mut name = exe.as_os_str().to_owned();
    name.push(".old");
    name.into()
}

/// files.txt: every file a kit ships, one path under the kit folder per line (source\package.ps1 writes it).
fn manifest(path: &Path) -> Option<Vec<String>> {
    let text = fs::read_to_string(path).ok()?;
    let lines = text.trim_start_matches('\u{feff}').lines();
    Some(
        lines
            .map(|l| l.trim().replace('/', "\\"))
            .filter(|l| !l.is_empty())
            .collect(),
    )
}

/// What `old` lists and `new` does not: only plain paths inside the kit folder, never under data\.
fn obsolete<'a>(old: &'a [String], new: &[String]) -> Vec<&'a str> {
    let new: HashSet<String> = new.iter().map(|n| n.to_ascii_lowercase()).collect();
    old.iter()
        .map(String::as_str)
        .filter(|o| {
            let parts: Vec<Component> = Path::new(o).components().collect();
            parts.iter().all(|c| matches!(c, Component::Normal(_)))
                && !parts
                    .first()
                    .is_some_and(|c| c.as_os_str().eq_ignore_ascii_case("data"))
                && !new.contains(&o.to_ascii_lowercase())
        })
        .collect()
}

// ---- the kit's scripts ------------------------------------------------------------------------------------------

/// python\python.exe scripts\<script> args, its output line by line into the window.
fn run_script(kit: &Kit, script: &str, args: &[OsString]) -> Result<(), String> {
    let shown: Vec<String> = args.iter().map(|a| a.to_string_lossy().into_owned()).collect();
    log(&format!("> {script} {}", shown.join(" ")));
    let mut child = Command::new(kit.dir().join("python").join("python.exe"))
        .arg(kit.dir().join("scripts").join(script))
        .args(args)
        .current_dir(kit.dir())
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map_err(|e| format!("python\\python.exe: {e}"))?;
    let readers: Vec<_> = [
        child.stdout.take().map(|o| Box::new(o) as Box<dyn Read + Send>),
        child.stderr.take().map(|e| Box::new(e) as Box<dyn Read + Send>),
    ]
    .into_iter()
    .flatten()
    .map(|pipe| {
        thread::spawn(move || {
            let mut pipe = BufReader::new(pipe);
            let mut line = Vec::new();
            while pipe.read_until(b'\n', &mut line).is_ok_and(|n| n > 0) {
                log(String::from_utf8_lossy(&line).trim_end());
                line.clear();
            }
        })
    })
    .collect();
    let status = child.wait().map_err(|e| e.to_string())?;
    for r in readers {
        let _ = r.join();
    }
    if status.success() {
        Ok(())
    } else {
        Err(t().failed.to_owned())
    }
}

/// English is on: english.py's list of Sega's backed-up files is not empty (as kit_common.english_on reads it).
fn english_on(kit: &Kit) -> bool {
    fs::read_to_string(kit.dir().join("data").join("english_backup").join("manifest.json"))
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .is_some_and(|v| v.as_object().is_some_and(|o| !o.is_empty()) || v.as_array().is_some_and(|a| !a.is_empty()))
}

/// The game folder setup.py remembered.
fn remembered_game(kit: &Kit) -> String {
    fs::read_to_string(kit.dir().join("data").join("settings.json"))
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|v| v["game"].as_str().map(str::to_owned))
        .unwrap_or_default()
}

fn this_kit(kit: &Kit) -> String {
    kit.version().unwrap_or_else(|| t().not_known.into())
}

/// The steps one by one in a worker; the first that fails ends the job.
fn start(steps: Vec<Step>) {
    {
        let mut s = shared();
        if s.busy {
            return;
        }
        s.busy = true;
        s.progress = 0;
        s.changed = true;
    }
    thread::spawn(move || {
        let kit = Kit::here();
        let mut result = Ok(());
        let mut updated = None;
        for step in steps {
            result = match &step {
                Step::Script(script, args) => {
                    say(format!("{script} ..."), 0);
                    run_script(&kit, script, args)
                }
                Step::Update(r) => apply(&kit, r).map(|()| updated = Some(r.tag.clone())),
            };
            if result.is_err() {
                break;
            }
        }
        let status = match (&result, &updated) {
            (Err(e), _) => e.clone(),
            (Ok(()), Some(tag)) => fill(t().updated, &[tag]),
            (Ok(()), None) => t().done.to_owned(),
        };
        log(&status);
        log("");
        let mut s = shared();
        s.status = status;
        s.progress = if result.is_ok() { 1000 } else { 0 };
        s.updated = updated.is_some();
        s.busy = false;
        s.changed = true;
    });
}

// ---- the window -------------------------------------------------------------------------------------------------

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain([0]).collect()
}

fn item(hwnd: HWND, id: i32) -> HWND {
    // SAFETY: a control of our own window (null if there is none: every call below takes that).
    unsafe { GetDlgItem(hwnd, id) }
}

fn set_text(hwnd: HWND, id: i32, text: &str) {
    // SAFETY: a NUL-terminated string for a control of our own window.
    unsafe { SetWindowTextW(item(hwnd, id), wide(text).as_ptr()) };
}

fn get_text(hwnd: HWND, id: i32) -> String {
    let c = item(hwnd, id);
    // SAFETY: the buffer holds the length Windows reports plus the NUL.
    unsafe {
        let mut buf = vec![0u16; GetWindowTextLengthW(c) as usize + 1];
        let n = GetWindowTextW(c, buf.as_mut_ptr(), buf.len() as i32);
        String::from_utf16_lossy(&buf[..n.max(0) as usize]).trim().to_owned()
    }
}

fn ask(hwnd: HWND, text: &str) -> bool {
    // SAFETY: NUL-terminated strings, our own window as the owner.
    unsafe {
        MessageBoxW(
            hwnd,
            wide(text).as_ptr(),
            wide(t().title).as_ptr(),
            MB_YESNO | MB_ICONQUESTION,
        ) == IDYES
    }
}

fn selected(hwnd: HWND) -> Option<Release> {
    // SAFETY: a list box of our own window.
    let i = unsafe { SendMessageW(item(hwnd, ID_LIST), LB_GETCURSEL, 0, 0) };
    usize::try_from(i).ok().and_then(|i| shared().releases.get(i).cloned())
}

/// The game folder box, or a message that it is empty.
fn folder(hwnd: HWND) -> Option<OsString> {
    let f = get_text(hwnd, ID_FOLDER);
    if f.is_empty() {
        // SAFETY: NUL-terminated strings, our own window as the owner.
        unsafe {
            MessageBoxW(
                hwnd,
                wide(t().no_folder).as_ptr(),
                wide(t().title).as_ptr(),
                MB_ICONWARNING,
            )
        };
        return None;
    }
    Some(f.into())
}

fn browse(hwnd: HWND) {
    let title = wide(t().browse_title);
    let info = BROWSEINFOW {
        hwndOwner: hwnd,
        lpszTitle: title.as_ptr(),
        ulFlags: BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE,
        ..Default::default()
    };
    // SAFETY: `info` and `title` live across the call; the path buffer is MAX_PATH long, as Windows asks; the item
    // list Windows gives back is freed once.
    unsafe {
        let pidl = SHBrowseForFolderW(&info);
        if pidl.is_null() {
            return;
        }
        let mut path = [0u16; 260];
        let ok = SHGetPathFromIDListW(pidl, path.as_mut_ptr());
        CoTaskMemFree(pidl.cast());
        if ok != 0 {
            let len = path.iter().position(|&c| c == 0).unwrap_or(path.len());
            set_text(hwnd, ID_FOLDER, &String::from_utf16_lossy(&path[..len]));
        }
    }
}

fn dropped(hwnd: HWND, drop: HDROP) {
    // SAFETY: the drop handle Windows gave with WM_DROPFILES, finished once; the buffer and its length go together.
    unsafe {
        let mut path = vec![0u16; 32_768];
        let n = DragQueryFileW(drop, 0, path.as_mut_ptr(), path.len() as u32);
        DragFinish(drop);
        if n > 0 {
            set_text(hwnd, ID_FOLDER, &String::from_utf16_lossy(&path[..n as usize]));
        }
    }
}

fn update_clicked(hwnd: HWND) {
    let Some(r) = selected(hwnd) else { return };
    if ask(
        hwnd,
        &fill(if r.test { t().confirm_test } else { t().confirm_release }, &[&r.tag]),
    ) {
        start(vec![Step::Update(r)]);
    }
}

fn open_notes(hwnd: HWND) {
    let page = selected(hwnd).map_or_else(|| format!("https://github.com/{REPO}/releases"), |r| r.page);
    // SAFETY: NUL-terminated strings; Windows opens the page in the default browser.
    unsafe {
        ShellExecuteW(
            hwnd,
            w!("open"),
            wide(&page).as_ptr(),
            ptr::null(),
            ptr::null(),
            SW_SHOWNORMAL,
        )
    };
}

/// The timer: what the workers said since the last look.
fn refresh(hwnd: HWND) {
    let (status, progress, log, busy, has_list, list, updated) = {
        let mut s = shared();
        if !mem::take(&mut s.changed) {
            return;
        }
        let list = mem::take(&mut s.listed).then(|| s.releases.clone());
        let log = mem::take(&mut s.log);
        (
            s.status.clone(),
            s.progress,
            log,
            s.busy,
            !s.releases.is_empty(),
            list,
            mem::take(&mut s.updated),
        )
    };
    let kit = Kit::here();
    let installed = this_kit(&kit);
    set_text(hwnd, ID_STATUS, &status);
    set_text(hwnd, ID_HEADING, &fill(t().update_heading, &[&installed]));
    set_text(
        hwnd,
        ID_LANGUAGE,
        if english_on(&kit) {
            t().english_is_on
        } else {
            t().japanese_is_on
        },
    );
    // SAFETY: controls of our own window; every string is NUL-terminated and copied by the control.
    unsafe {
        SendMessageW(item(hwnd, ID_BAR), PBM_SETPOS, progress as usize, 0);
        for id in BUTTONS {
            let on = !busy && (id != ID_UPDATE || has_list);
            EnableWindow(item(hwnd, id), i32::from(on));
        }
        if !log.is_empty() {
            let out = item(hwnd, ID_LOG);
            let end = GetWindowTextLengthW(out) as usize;
            SendMessageW(out, EM_SETSEL, end, end as LPARAM);
            SendMessageW(out, EM_REPLACESEL, 0, wide(&log).as_ptr() as LPARAM);
        }
        if let Some(list) = list {
            let box_ = item(hwnd, ID_LIST);
            SendMessageW(box_, LB_RESETCONTENT, 0, 0);
            for r in &list {
                let kind = if r.test { t().test_build } else { t().release };
                let mark = if r.tag == installed {
                    t().this_kit
                } else if !r.test && is_newer(&r.tag, &installed) {
                    t().newer
                } else {
                    ""
                };
                let line = wide(&format!("{}\t{kind}\t{}\t{mark}", r.tag, r.date));
                SendMessageW(box_, LB_ADDSTRING, 0, line.as_ptr() as LPARAM);
            }
            let first = list.iter().position(|r| !r.test).unwrap_or(0);
            SendMessageW(box_, LB_SETCURSEL, first, 0);
        }
    }
    if updated {
        {
            let mut s = shared();
            s.listed = true; // the "(this kit)" mark moves
            s.changed = true;
        }
        let game = get_text(hwnd, ID_FOLDER);
        let english = english_on(&kit);
        let question = if english {
            t().after_update_english
        } else {
            t().after_update
        };
        if !game.is_empty() && ask(hwnd, question) {
            let mut steps = vec![Step::Script("setup.py", vec![game.into()])];
            if english {
                steps.push(Step::Script("english.py", vec!["on".into()]));
            }
            start(steps);
        }
    }
}

unsafe extern "system" fn wndproc(hwnd: HWND, msg: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    match msg {
        WM_COMMAND if (wp >> 16) as u32 == BN_CLICKED => {
            match (wp & 0xffff) as i32 {
                ID_BROWSE => browse(hwnd),
                ID_SETUP => {
                    if let Some(game) = folder(hwnd) {
                        start(vec![Step::Script("setup.py", vec![game])]);
                    }
                }
                ID_UNDO => {
                    if let Some(game) = folder(hwnd).filter(|_| ask(hwnd, t().undo_confirm)) {
                        start(vec![Step::Script("setup.py", vec!["undo".into(), game])]);
                    }
                }
                ID_ENGLISH => start(vec![Step::Script("english.py", vec!["on".into()])]),
                ID_JAPANESE => start(vec![Step::Script("english.py", vec!["off".into()])]),
                ID_UPDATE => update_clicked(hwnd),
                ID_NOTES => open_notes(hwnd),
                _ => {}
            }
            0
        }
        WM_DROPFILES => {
            dropped(hwnd, wp as HDROP);
            0
        }
        WM_TIMER => {
            refresh(hwnd);
            0
        }
        // never a kit left half copied: the window stays while a job runs
        WM_CLOSE if shared().busy => {
            say(t().busy, shared().progress);
            0
        }
        WM_DESTROY => {
            // SAFETY: plain Win32 call.
            unsafe { PostQuitMessage(0) };
            0
        }
        // SAFETY: the message as Windows gave it.
        _ => unsafe { DefWindowProcW(hwnd, msg, wp, lp) },
    }
}

fn main() {
    let kit = Kit::here();
    if let Ok(me) = env::current_exe() {
        let _ = fs::remove_file(old_exe(&me));
    }
    // a kit unzipped by hand over an older one: its replaced launchers go
    if let Some(shipped) = manifest(&kit.dir().join("files.txt")) {
        let legacy: Vec<String> = LEGACY.iter().map(|&f| f.to_owned()).collect();
        for f in obsolete(&legacy, &shipped) {
            let _ = fs::remove_file(kit.dir().join(f));
        }
    }
    thread::spawn(|| {
        say(t().asking, 0);
        let found = fetch();
        let mut s = shared();
        match found {
            Ok(list) if !list.is_empty() => {
                let installed = this_kit(&Kit::here());
                let newest = list.iter().find(|r| !r.test && is_newer(&r.tag, &installed));
                s.status = newest.map_or_else(|| t().pick.into(), |r| fill(t().available, &[&r.tag]));
                s.releases = list;
                s.listed = true;
            }
            Ok(_) => s.status = t().none_listed.into(),
            Err(e) => s.status = format!("{} {}", fill(t().no_answer, &[&e]), t().retry),
        }
        s.changed = true;
    });

    // SAFETY: plain Win32 window set-up on this (the only UI) thread; every string is NUL-terminated and lives
    // across its call, every handle comes from the call before.
    unsafe {
        SetProcessDPIAware();
        CoInitializeEx(ptr::null(), COINIT_APARTMENTTHREADED as u32); // the folder picker's new style needs COM
        let screen = GetDC(ptr::null_mut());
        let dpi = GetDeviceCaps(screen, LOGPIXELSY as i32);
        ReleaseDC(ptr::null_mut(), screen);
        let s = |v: i32| v * dpi / 96;
        let icc = INITCOMMONCONTROLSEX {
            dwSize: size_of::<INITCOMMONCONTROLSEX>() as u32,
            dwICC: ICC_PROGRESS_CLASS,
        };
        InitCommonControlsEx(&icc);
        let mut metrics: NONCLIENTMETRICSW = mem::zeroed();
        metrics.cbSize = size_of::<NONCLIENTMETRICSW>() as u32;
        SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, metrics.cbSize, (&raw mut metrics).cast(), 0);
        let font = CreateFontIndirectW(&metrics.lfMessageFont);

        let instance = GetModuleHandleW(ptr::null());
        let class = WNDCLASSW {
            lpfnWndProc: Some(wndproc),
            hInstance: instance,
            hCursor: LoadCursorW(ptr::null_mut(), IDC_ARROW),
            hbrBackground: (COLOR_BTNFACE + 1) as usize as _,
            lpszClassName: w!("WccfKitSetup"),
            ..mem::zeroed()
        };
        RegisterClassW(&class);
        let style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
        let mut rect = RECT {
            left: 0,
            top: 0,
            right: s(580),
            bottom: s(600),
        };
        AdjustWindowRectEx(&mut rect, style, 0, 0);
        let title = wide(&format!("{} - {}", t().title, kit.dir().display()));
        let hwnd = CreateWindowExW(
            0,
            w!("WccfKitSetup"),
            title.as_ptr(),
            style,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            rect.right - rect.left,
            rect.bottom - rect.top,
            ptr::null_mut(),
            ptr::null_mut(),
            instance,
            ptr::null(),
        );
        let child = |class: PCWSTR, text: &str, style: u32, id: i32, x: i32, y: i32, cx: i32, cy: i32| {
            let text = wide(text);
            let framed = class == w!("LISTBOX") || class == w!("EDIT");
            let c = CreateWindowExW(
                if framed { WS_EX_CLIENTEDGE } else { 0 },
                class,
                text.as_ptr(),
                WS_CHILD | WS_VISIBLE | style,
                s(x),
                s(y),
                s(cx),
                s(cy),
                hwnd,
                id as usize as HMENU,
                instance,
                ptr::null(),
            );
            SendMessageW(c, WM_SETFONT, font as usize, 0);
            c
        };
        let tx = t();
        child(w!("STATIC"), tx.intro, 0, 0, 12, 10, 556, 36);
        child(w!("STATIC"), tx.game_folder, 0, 0, 12, 56, 110, 20);
        let edit = (ES_AUTOHSCROLL as u32) | WS_TABSTOP;
        child(w!("EDIT"), &remembered_game(&kit), edit, ID_FOLDER, 124, 52, 344, 24);
        child(w!("BUTTON"), tx.browse, WS_TABSTOP, ID_BROWSE, 476, 52, 92, 24);
        child(w!("BUTTON"), tx.set_up, WS_TABSTOP, ID_SETUP, 124, 84, 170, 28);
        child(w!("BUTTON"), tx.undo, WS_TABSTOP, ID_UNDO, 302, 84, 166, 28);
        child(w!("STATIC"), tx.game_text, 0, 0, 12, 128, 110, 20);
        child(w!("BUTTON"), tx.english, WS_TABSTOP, ID_ENGLISH, 124, 122, 110, 28);
        child(w!("BUTTON"), tx.japanese, WS_TABSTOP, ID_JAPANESE, 242, 122, 110, 28);
        child(w!("STATIC"), "", 0, ID_LANGUAGE, 362, 128, 206, 20);
        child(w!("STATIC"), "", SS_ETCHEDHORZ, 0, 12, 162, 556, 2);
        child(w!("STATIC"), "", 0, ID_HEADING, 12, 172, 556, 20);
        let list_style = (LBS_NOTIFY | LBS_USETABSTOPS) as u32 | WS_VSCROLL | WS_TABSTOP;
        let list = child(w!("LISTBOX"), "", list_style, ID_LIST, 12, 194, 556, 110);
        let stops: [i32; 3] = [90, 150, 210]; // dialog units: tag, kind, date, "(this kit)"
        SendMessageW(list, LB_SETTABSTOPS, stops.len(), stops.as_ptr() as LPARAM);
        child(w!("BUTTON"), tx.update, WS_TABSTOP, ID_UPDATE, 12, 310, 130, 28);
        child(w!("BUTTON"), tx.whats_new, WS_TABSTOP, ID_NOTES, 150, 310, 130, 28);
        child(w!("STATIC"), "", SS_ETCHEDHORZ, 0, 12, 348, 556, 2);
        child(w!("STATIC"), "", 0, ID_STATUS, 12, 358, 556, 36);
        let bar = child(PROGRESS_CLASSW, "", 0, ID_BAR, 12, 396, 556, 14);
        SendMessageW(bar, PBM_SETRANGE32, 0, 1000);
        let out = (ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL) as u32 | WS_VSCROLL;
        let out = child(w!("EDIT"), "", out, ID_LOG, 12, 418, 556, 170);
        SendMessageW(out, EM_SETLIMITTEXT, 0, 0); // more than the 32,767 characters a box takes by default

        DragAcceptFiles(hwnd, 1);
        ShowWindow(hwnd, SW_SHOWNORMAL);
        SetTimer(hwnd, 1, 100, None);

        // dropped on SETUP.exe, or given on the command line: set up that folder (or undo) at once
        let args: Vec<OsString> = env::args_os().skip(1).collect();
        match args.first() {
            Some(a) if a.eq_ignore_ascii_case("undo") => start(vec![Step::Script("setup.py", args.clone())]),
            Some(game) => {
                set_text(hwnd, ID_FOLDER, &game.to_string_lossy());
                start(vec![Step::Script("setup.py", args.clone())]);
            }
            None => {}
        }

        let mut msg: MSG = mem::zeroed();
        while GetMessageW(&mut msg, ptr::null_mut(), 0, 0) > 0 {
            if IsDialogMessageW(hwnd, &msg) == 0 {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn releases_with_a_kit_zip() {
        let json = r#"[
            {"tag_name": "kit-5.5-test1", "prerelease": true, "draft": false, "published_at": "2026-10-09T15:18:17Z",
             "html_url": "https://github.com/x/releases/tag/kit-5.5-test1",
             "assets": [{"name": "WCCF-2010-11-kit-5.5-test1.zip.sha256", "browser_download_url": "https://a/s"},
                        {"name": "WCCF-2010-11-kit-5.5-test1.ZIP", "browser_download_url": "https://a/z", "size": 7}]},
            {"tag_name": "kit-5.4", "prerelease": false, "published_at": "2026-10-09T12:06:08Z", "html_url": "",
             "assets": [{"name": "k.zip", "browser_download_url": "https://a/k"}]},
            {"tag_name": "notes-only", "assets": []},
            {"tag_name": "draft", "draft": true, "assets": [{"name": "d.zip", "browser_download_url": "https://a/d"}]},
            {"tag_name": "plain-http", "assets": [{"name": "h.zip", "browser_download_url": "http://a/h"}]}
        ]"#;
        let list = releases(json).unwrap();
        assert_eq!(
            list.iter().map(|r| r.tag.as_str()).collect::<Vec<_>>(),
            ["kit-5.5-test1", "kit-5.4"]
        );
        assert!(list[0].test && !list[1].test);
        assert_eq!(
            (list[0].zip_url.as_str(), list[0].zip_size, list[0].date.as_str()),
            ("https://a/z", 7, "2026-10-09")
        );
        assert!(releases(r#"{"message": "API rate limit exceeded"}"#).is_err());
    }

    #[test]
    fn copy_over_keeps_data() {
        let base = env::temp_dir().join(format!("wccf-setup-test-{}", std::process::id()));
        let (from, to) = (base.join("zip"), base.join("kit"));
        fs::create_dir_all(from.join("data")).unwrap();
        fs::create_dir_all(from.join("bin")).unwrap();
        fs::create_dir_all(to.join("data")).unwrap();
        fs::write(from.join("data").join("keys.txt"), "new").unwrap();
        fs::write(from.join("bin").join("a.dll"), "new").unwrap();
        fs::write(to.join("data").join("keys.txt"), "mine").unwrap();
        copy_over(&from, &to, true).unwrap();
        assert_eq!(fs::read_to_string(to.join("data").join("keys.txt")).unwrap(), "mine");
        assert_eq!(fs::read_to_string(to.join("bin").join("a.dll")).unwrap(), "new");
        fs::remove_dir_all(&base).unwrap();
    }

    #[test]
    fn obsolete_only_kit_files_gone_from_the_new_kit() {
        let old: Vec<String> = [
            "PLAY.exe",
            "ENGLISH.exe",
            "scripts\\old.py",
            "data\\keys.txt",
            "..\\x",
            "C:\\x",
        ]
        .map(String::from)
        .into();
        let new: Vec<String> = ["play.exe", "SETUP.exe"].map(String::from).into();
        assert_eq!(obsolete(&old, &new), ["ENGLISH.exe", "scripts\\old.py"]);
    }

    #[test]
    fn fill_in_order() {
        assert_eq!(fill("{}: {} ({})", &["a", "b"]), "a: b ()");
        assert_eq!(fill("no gaps", &["a"]), "no gaps");
    }
}
