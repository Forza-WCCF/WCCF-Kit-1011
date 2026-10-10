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

$built = 'PLAY.exe', 'SETUP.exe', 'bin\winmm.dll', 'bin\FPR_Emu.exe',
         'overlay\wccfpanel.dll'
foreach ($f in $built) {
    $from = Join-Path $kit $f
    if (-not (Test-Path $from)) { throw "$f is missing - run source\build.ps1 first" }
    $to = Join-Path $root $f
    New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
    Copy-Item $from $to
}
# every program must carry its version information (source\launcher\build.rs, source\build.ps1, 2026-10-10): a nameless
# unsigned program is what Windows Defender's machine learning flagged (Kit 5.5's first SETUP.exe, then its winmm.dll)
foreach ($f in 'PLAY.exe', 'SETUP.exe', 'bin\winmm.dll', 'bin\FPR_Emu.exe', 'overlay\wccfpanel.dll') {
    $v = (Get-Item (Join-Path $root $f)).VersionInfo
    if ($v.ProductName -ne 'WCCF 2010-11 kit' -or -not $v.FileVersion) { throw "$f has no version information - see source\build.ps1" }
    Write-Host "$f : $($v.ProductName) $($v.FileVersion) - $($v.FileDescription)"
}

# for SETUP.exe's update: version.txt, which kit this is (kit-5.4, kit-5.5-test1, or CI's commit), and files.txt,
# every file this kit ships - an update removes what the old kit's list has and the new one's does not
$version = $Name -replace '^WCCF-2010-11-kit-?', ''
if ($version) { "kit-$version" | Set-Content -Encoding ascii (Join-Path $root 'version.txt') }
$shipped = Get-ChildItem -Recurse -File $root | ForEach-Object { $_.FullName.Substring($root.Length + 1) }
$shipped + 'files.txt' | Set-Content -Encoding utf8 (Join-Path $root 'files.txt')

$zip = Join-Path $dist "$Name.zip"
# Windows' own tar (bsdtar): '/' in the names - Compress-Archive of Windows PowerShell 5.1 writes '\', which other
# unzip programs take as part of a file name
& tar -a -c -f $zip -C $dist 'WCCF-2010-11-kit'
if ($LASTEXITCODE) { throw 'tar (zip) failed' }

# read the ZIP back: every program must be in it, not only in the folder it was made from (a kit without them
# cannot start); python.exe comes from git, the rest from build.ps1
$entries = @(& tar -t -f $zip)
if ($LASTEXITCODE) { throw 'tar (list) failed' }
$missing = @($built + 'python\python.exe' + $(if ($version) { 'version.txt' }) | Where-Object {
    $entry = 'WCCF-2010-11-kit/' + ($_ -replace '\\', '/')
    $entries -notcontains $entry
})
if ($missing) { throw "the ZIP lacks: $($missing -join ', ')" }
Write-Host "the ZIP has every program: $(($built + 'python\python.exe') -join ', ')"

$hash = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
"$hash  $Name.zip" | Set-Content -Encoding ascii "$zip.sha256"
Write-Host "packaged $zip ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB, sha256 $hash)"
