// SETUP.exe is a window: Windows' current look for its controls (Common Controls 6, also the progress bar's).
//
// PLAY.exe and SETUP.exe carry Windows version information (2026-10-10): product, publisher, description and version,
// what a file's Properties show. Without it they were nameless unsigned programs, the kind Windows Defender's machine
// learning distrusts most: Kit 5.5's first SETUP.exe was quarantined as "Trojan:Win32/Sabsik.FL.A!ml" when it was
// unzipped. Made with the Windows SDK's rc.exe (on PATH after vcvarsall, as build.ps1 runs it; otherwise the newest
// under Windows Kits). source\package.ps1 refuses a kit whose programs lack it.
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn main() {
    println!("cargo:rustc-link-arg-bin=SETUP=/MANIFEST:EMBED");
    println!(
        "cargo:rustc-link-arg-bin=SETUP=/MANIFESTDEPENDENCY:type='win32' name='Microsoft.Windows.Common-Controls' \
         version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'"
    );
    println!("cargo:rerun-if-changed=build.rs");
    let Some(rc) = find_rc() else {
        println!("cargo:warning=no rc.exe (Windows SDK): PLAY.exe and SETUP.exe built without version information");
        return;
    };
    let out = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let version = env::var("CARGO_PKG_VERSION").expect("CARGO_PKG_VERSION");
    for (bin, what) in [
        ("PLAY", "starts the game: server, projector and seat 1"),
        (
            "SETUP",
            "sets up the game folder, the game's language and the kit's updates",
        ),
    ] {
        let script = out.join(format!("{bin}.rc"));
        let res = out.join(format!("{bin}.res"));
        fs::write(&script, version_rc(bin, what, &version)).expect("write the .rc");
        let ok = Command::new(&rc)
            .arg("/nologo")
            .arg("/fo")
            .arg(&res)
            .arg(&script)
            .status()
            .is_ok_and(|s| s.success());
        assert!(ok, "rc.exe could not make {}", res.display());
        println!("cargo:rustc-link-arg-bin={bin}={}", res.display());
    }
}

/// rc.exe on PATH (after vcvarsall), else the newest x64 one under the Windows Kits.
fn find_rc() -> Option<PathBuf> {
    if Command::new("rc.exe").arg("/?").output().is_ok() {
        return Some(PathBuf::from("rc.exe"));
    }
    let kits = Path::new(r"C:\Program Files (x86)\Windows Kits\10\bin");
    let mut found: Vec<PathBuf> = fs::read_dir(kits)
        .ok()?
        .filter_map(|e| e.ok().map(|e| e.path().join("x64").join("rc.exe")))
        .filter(|p| p.is_file())
        .collect();
    found.sort();
    found.pop()
}

/// The version resource of one program: 5.5.0 -> FILEVERSION 5,5,0,0.
fn version_rc(bin: &str, what: &str, version: &str) -> String {
    let nums: Vec<&str> = version.split('.').chain(["0", "0", "0"]).take(4).collect();
    let comma = nums.join(",");
    format!(
        "1 VERSIONINFO\nFILEVERSION {comma}\nPRODUCTVERSION {comma}\nFILEOS 0x40004\nFILETYPE 0x1\nBEGIN\n\
         BLOCK \"StringFileInfo\"\nBEGIN\nBLOCK \"040904b0\"\nBEGIN\n\
         VALUE \"CompanyName\", \"Forza-WCCF community\"\n\
         VALUE \"FileDescription\", \"WCCF 2010-11 kit - {bin}: {what}\"\n\
         VALUE \"FileVersion\", \"{version}\"\n\
         VALUE \"InternalName\", \"{bin}\"\n\
         VALUE \"LegalCopyright\", \"Community-made tools for your own copy of the game; the game is not included\"\n\
         VALUE \"OriginalFilename\", \"{bin}.exe\"\n\
         VALUE \"ProductName\", \"WCCF 2010-11 kit\"\n\
         VALUE \"ProductVersion\", \"{version}\"\n\
         END\nEND\nBLOCK \"VarFileInfo\"\nBEGIN\nVALUE \"Translation\", 0x409, 1200\nEND\nEND\n"
    )
}
