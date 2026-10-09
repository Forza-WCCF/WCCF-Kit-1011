// SETUP.exe is a window: Windows' current look for its controls (Common Controls 6, also the progress bar's).
fn main() {
    println!("cargo:rustc-link-arg-bin=SETUP=/MANIFEST:EMBED");
    println!(
        "cargo:rustc-link-arg-bin=SETUP=/MANIFESTDEPENDENCY:type='win32' name='Microsoft.Windows.Common-Controls' \
         version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'"
    );
}
