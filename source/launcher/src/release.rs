//! The kit's releases on GitHub (2026-10-09): SETUP.exe's UPDATE lists them; PLAY.exe says when a newer release is
//! out.  Test builds (pre-releases) are never "newer": only a release is offered that way.

use std::env;
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
use std::{fs, thread};

use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;

use crate::Kit;

pub const REPO: &str = "Forza-WCCF/WCCF-Kit-1011";

/// Windows' own program, by full path: never a curl.exe or tar.exe that lies in the kit folder.
pub fn system32(exe: &str) -> Command {
    let root = env::var_os("SystemRoot").unwrap_or_else(|| r"C:\Windows".into());
    let mut cmd = Command::new(Path::new(&root).join("System32").join(exe));
    cmd.stdin(Stdio::null()).creation_flags(CREATE_NO_WINDOW);
    cmd
}

/// curl.exe that fails on an HTTP error and gives up on a connection that stays silent for a minute.
pub fn curl() -> Command {
    let mut cmd = system32("curl.exe");
    cmd.args([
        "-sSfL",
        "--connect-timeout",
        "20",
        "--speed-limit",
        "1",
        "--speed-time",
        "60",
    ])
    .args(["-A", "wccf-kit"]);
    cmd
}

impl Kit {
    /// version.txt, which the kit ZIP brings (source\package.ps1 writes it): kit-5.4, kit-5.5-test1, kit-<commit>.
    pub fn version(&self) -> Option<String> {
        let v = fs::read_to_string(self.dir.join("version.txt")).ok()?;
        Some(v.trim().to_owned()).filter(|v| !v.is_empty())
    }
}

/// kit-5.4 -> ([5, 4], release); kit-5.5-test1 -> ([5, 5], test build); a build of a commit (kit-1208d80) -> None.
fn parse(tag: &str) -> Option<(Vec<u32>, bool)> {
    let rest = tag.strip_prefix("kit-")?;
    let (number, test) = rest.split_once('-').map_or((rest, false), |(n, _)| (n, true));
    let mut parts: Vec<u32> = number.split('.').map(str::parse).collect::<Result<_, _>>().ok()?;
    while parts.len() > 1 && parts.last() == Some(&0) {
        parts.pop(); // kit-5.0 is kit-5
    }
    Some((parts, test))
}

/// The release `tag` is newer than the kit that is here: a higher number, or the release of the test build that is
/// here (kit-5.5 after kit-5.5-test1).  A test build, or a kit of unknown version, is never newer / never older.
pub fn is_newer(tag: &str, installed: &str) -> bool {
    match (parse(tag), parse(installed)) {
        (Some((new, false)), Some((old, old_test))) => new > old || (new == old && old_test),
        _ => false,
    }
}

/// The latest release (never a test build: GitHub's "latest" skips pre-releases and drafts), asked in the background.
pub struct LatestRelease(Option<Child>);

impl LatestRelease {
    pub fn ask() -> Self {
        let api = format!("https://api.github.com/repos/{REPO}/releases/latest");
        let child = curl()
            .args([
                "--max-time",
                "10",
                "-H",
                "Accept: application/vnd.github+json",
                "--url",
                &api,
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn();
        Self(child.ok())
    }

    /// Its tag if GitHub has answered within `wait` (an offline PC never holds anything up); else the ask is dropped.
    pub fn tag(self, wait: Duration) -> Option<String> {
        let mut child = self.0?;
        let end = Instant::now() + wait;
        while child.try_wait().ok()?.is_none() {
            if Instant::now() >= end {
                let _ = child.kill();
                return None;
            }
            thread::sleep(Duration::from_millis(50));
        }
        let out = child.wait_with_output().ok()?;
        let json: serde_json::Value = serde_json::from_slice(&out.stdout).ok()?;
        json["tag_name"].as_str().map(str::to_owned)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn newer_releases_only() {
        assert!(is_newer("kit-5.5", "kit-5.4"));
        assert!(is_newer("kit-6", "kit-5.10"));
        assert!(is_newer("kit-5.10", "kit-5.9"));
        assert!(is_newer("kit-5.5", "kit-5.5-test1"));
        assert!(!is_newer("kit-5.4", "kit-5.4"));
        assert!(!is_newer("kit-5.0", "kit-5"));
        assert!(!is_newer("kit-5.3", "kit-5.4"));
        assert!(!is_newer("kit-5.4", "kit-5.5-test1"));
        assert!(!is_newer("kit-5.6-test1", "kit-5.4")); // a test build is never offered
        assert!(!is_newer("kit-5.5", "kit-1208d80")); // a commit's build: unknown
        assert!(!is_newer("v1", "kit-5.4"));
    }
}
