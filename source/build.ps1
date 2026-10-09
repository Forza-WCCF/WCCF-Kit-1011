# build.ps1 - every program the kit ships, built from source\ into the places the kit runs them from (2026-10-08):
#   bin\winmm.dll  bin\FPR_Emu.exe  overlay\wccfpanel.dll                                        (C, 32-bit, MSVC)
#   PLAY.exe  SETUP.exe                                                                        (Rust, 64-bit)
# and source\build\fakegame.exe (tests only, not shipped).  Git holds none of them: run this after a checkout, or take
# the kit ZIP that CI makes (.github\workflows\kit.yml runs this same script).
#
#   powershell -ExecutionPolicy Bypass -File source\build.ps1
#
# Needs Visual Studio 2022 (or its Build Tools) with "Desktop development with C++", and rustup.
$ErrorActionPreference = 'Stop'
$kit = Split-Path $PSScriptRoot -Parent
$src = $PSScriptRoot
$obj = Join-Path $src 'build'
New-Item -ItemType Directory -Force $obj, (Join-Path $kit 'bin') | Out-Null

# MSVC for 32-bit x86: the game is 32-bit, so its hook and its panel must be too
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'no Visual Studio with the C++ tools (vswhere found none)' }
$vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvarsall.bat'
cmd /c "`"$vcvars`" x86 >nul && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2] }
}

# the runtime linked in (/MT): no Visual C++ runtime needed on the player's PC; /Brepro: the same source, the same file
function Build-C([string]$source, [string]$out, [string[]]$compile = @(), [string[]]$link = @()) {
    $name = [IO.Path]::GetFileNameWithoutExtension($out)
    & cl /nologo /O2 /MT /W3 /Brepro /D_CRT_SECURE_NO_WARNINGS @compile (Join-Path $src $source) "/Fo$obj\" "/Fe$out" `
        /link /Brepro "/IMPLIB:$obj\$name.lib" "/PDB:$obj\$name.pdb" @link
    if ($LASTEXITCODE) { throw "cl failed for $source" }
    Write-Host "built $out"
}
Build-C 'mxhook\mxhook.c' "$kit\bin\winmm.dll" @('/LD')
Build-C 'fpr_emu\fpr_emu.c' "$kit\bin\FPR_Emu.exe" @() @('user32.lib')
Build-C 'overlay\wccfpanel.c' "$kit\overlay\wccfpanel.dll" @('/LD') @('d3d9.lib', 'gdi32.lib', 'user32.lib', 'ole32.lib', 'windowscodecs.lib')
Build-C 'overlay\fakegame.c' "$obj\fakegame.exe" @() @('d3d9.lib', 'user32.lib')

# the launchers: the toolchain is pinned by source\launcher\rust-toolchain.toml, every crate by Cargo.lock, the static
# runtime by source\launcher\.cargo\config.toml - rustup and cargo read those two from the CURRENT folder: build there
Push-Location (Join-Path $src 'launcher')
try {
    & cargo build --release --locked --target x86_64-pc-windows-msvc
    if ($LASTEXITCODE) { throw 'cargo build failed' }
} finally { Pop-Location }
foreach ($exe in 'PLAY', 'SETUP') {
    Copy-Item (Join-Path $src "launcher\target\x86_64-pc-windows-msvc\release\$exe.exe") (Join-Path $kit "$exe.exe")
    Write-Host "built $kit\$exe.exe"
}
