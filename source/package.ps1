# package.ps1 - the kit ZIP that players download (2026-10-08), after build.ps1: the files git holds at HEAD
# (git archive; .gitattributes keeps CI's own files out) plus the programs build.ps1 made, all under one folder
# WCCF-2010-11-kit\, as the kit was always shipped.  Writes dist\NAME.zip and dist\NAME.zip.sha256.
#
#   powershell -ExecutionPolicy Bypass -File source\package.ps1 [-Name WCCF-2010-11-kit-5.4]
param([string]$Name = 'WCCF-2010-11-kit')
$ErrorActionPreference = 'Stop'
$kit = Split-Path $PSScriptRoot -Parent
$dist = Join-Path $kit 'dist'
$root = Join-Path $dist 'WCCF-2010-11-kit'
Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $root | Out-Null

$tar = Join-Path $dist 'tree.tar'
& git -C $kit archive --format=tar -o $tar HEAD
if ($LASTEXITCODE) { throw 'git archive failed' }
& tar -xf $tar -C $root
if ($LASTEXITCODE) { throw 'tar failed' }
Remove-Item $tar

# VERSION.txt (2026-10-09): what this kit is, for the panel's corner (under the ping) and the logs a player sends -
# "5.5 (f13c146)" from -Name WCCF-2010-11-kit-5.5 and the commit; a plain build: "dev (f13c146)"
$sha = (& git -C $kit rev-parse --short HEAD).Trim()
if ($LASTEXITCODE) { throw 'git rev-parse failed' }
$ver = if ($Name -match '^WCCF-2010-11-kit-(.+)$') { $Matches[1] } else { 'dev' }
[IO.File]::WriteAllText((Join-Path $root 'VERSION.txt'), "$ver ($sha)`r`n", (New-Object Text.ASCIIEncoding))
Write-Host "VERSION.txt: $ver ($sha)"

$built = 'PLAY.exe', 'SETUP.exe', 'ENGLISH.exe', 'bin\winmm.dll', 'bin\FPR_Emu.exe', 'bin\logowin.exe',
         'overlay\wccfpanel.dll', 'overlay\inject.exe'
foreach ($f in $built) {
    $from = Join-Path $kit $f
    if (-not (Test-Path $from)) { throw "$f is missing - run source\build.ps1 first" }
    $to = Join-Path $root $f
    New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
    Copy-Item $from $to
}

$zip = Join-Path $dist "$Name.zip"
# Windows' own tar (bsdtar): '/' in the names - Compress-Archive of Windows PowerShell 5.1 writes '\', which other
# unzip programs take as part of a file name
& tar -a -c -f $zip -C $dist 'WCCF-2010-11-kit'
if ($LASTEXITCODE) { throw 'tar (zip) failed' }

# read the ZIP back: every program must be in it, not only in the folder it was made from (a kit without them
# cannot start); python.exe comes from git, the rest from build.ps1
$entries = @(& tar -t -f $zip)
if ($LASTEXITCODE) { throw 'tar (list) failed' }
$missing = @($built + 'python\python.exe' + 'VERSION.txt' | Where-Object {
    $entry = 'WCCF-2010-11-kit/' + ($_ -replace '\\', '/')
    $entries -notcontains $entry
})
if ($missing) { throw "the ZIP lacks: $($missing -join ', ')" }
Write-Host "the ZIP has every program: $(($built + 'python\python.exe') -join ', ')"

$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
"$hash  $Name.zip" | Set-Content -Encoding ascii "$zip.sha256"
Write-Host "packaged $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB, sha256 $hash)"
