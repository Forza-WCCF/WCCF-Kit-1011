# check.ps1 - the kit's own checks that need no game (2026-10-08), after build.ps1; CI runs it too (kit.yml):
#   every script in scripts\ compiles with the kit's own Python (nothing written)
#   the key driver's self-test (_keys_seat1.py --selftest: a scratch file, nothing live)
#   play.py's choice when a game window ends: a closed window stops the rest, a crash does not (source\test_ended.py)
#   the club card editor's self-test (edit_club_card.py --self-test: cards made in memory, no real card)
#   a missing club-card helper file never stops a start (source\test_card_fix.py: a scratch panel.txt)
#   the run before last zipped into data\logs\archive, the archive kept to its size (source\test_log_archive.py)
#   a transferred card is listed as such and never played again (source\test_wallet_transferred.py: scratch cards)
#   the seat desk never gives a seat that is in the game (source\test_seat_desk_game.py: a scratch control log, the
#   desk on 127.0.0.1:20932)
#   the projector box held off the game until a player is in (source\test_hold_projector.py: the desk on 127.0.0.1:20933-6,
#   the firewall rule written to a scratch file)
#   SEND LOGS: packed without the club card, names taken out, kept by the log inbox - which refuses junk, too big, not
#   a ZIP and too many (source\test_send_logs.py: a scratch kit, inboxes on 127.0.0.1:20952 and 20953)
#   the panel's money, relay and dealt-card self-tests (wccfpanel.dll loaded by source\build\fakegame.exe, in a
#   scratch folder; the relay test plays two seats through scripts\_relay.py on 127.0.0.1:20941 - the C side and
#   the Python side of the match relay checked against each other)
# The panel's frame-wait test (WCCFPANEL_LIMITERTEST) measures milliseconds and stays out: a busy machine fails it.
#
#   powershell -ExecutionPolicy Bypass -File source\check.ps1
$ErrorActionPreference = 'Stop'
$kit = Split-Path $PSScriptRoot -Parent
$py = Join-Path $kit 'python\python.exe'
$failed = @()

& $py -I -c "import pathlib, sys; [compile(p.read_bytes(), str(p), 'exec') for p in sorted(pathlib.Path(sys.argv[1]).glob('*.py'))]; print('scripts: all compile')" (Join-Path $kit 'scripts')
if ($LASTEXITCODE) { $failed += 'scripts compile' }

# Kit 5.5 reused the name PANEL for wccfpanel.dll: a plain start read the dll as data\panel.txt and never went online
& $py -I -c "import sys; sys.path.insert(0, sys.argv[1]); import play; assert play.PANEL.endswith('panel.txt'), play.PANEL; print('play.py: PANEL is panel.txt')" (Join-Path $kit 'scripts')
if ($LASTEXITCODE) { $failed += 'play.py PANEL' }

& $py -I (Join-Path $kit 'scripts\_keys_seat1.py') --selftest | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'key driver self-test' }

& $py -I (Join-Path $PSScriptRoot 'test_ended.py')
if ($LASTEXITCODE) { $failed += 'play.py ended: a closed window vs a crash' }

& $py -I (Join-Path $kit 'scripts\edit_club_card.py') --self-test | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'club card editor self-test' }

& $py -I (Join-Path $PSScriptRoot 'test_card_fix.py')
if ($LASTEXITCODE) { $failed += 'a missing card helper file must not stop a start' }

& $py -I (Join-Path $PSScriptRoot 'test_log_archive.py')
if ($LASTEXITCODE) { $failed += 'logs: the run before last zipped, the archive kept to its size' }

& $py -I (Join-Path $PSScriptRoot 'test_wallet_transferred.py')
if ($LASTEXITCODE) { $failed += 'a transferred card: listed as such, never played again' }

# The checks that wait on their own servers (the seat desk, SEND LOGS) run side by side, beside the panel's
# self-tests below (each on its own ports); their last line and exit code are read once they end (2026-10-10: one
# after another they took 16 of check.ps1's 35 s in CI)
function Start-Check([string]$what, [string]$script) {
    $out = Join-Path ([IO.Path]::GetTempPath()) "wccf-check-$PID-$([IO.Path]::GetFileNameWithoutExtension($script)).txt"
    $p = Start-Process -FilePath $py -ArgumentList '-I', "`"$(Join-Path $PSScriptRoot $script)`"" -PassThru -NoNewWindow `
        -RedirectStandardOutput $out -RedirectStandardError "$out.err"
    $null = $p.Handle                        # kept open, so the exit code can be read after the end
    [pscustomobject]@{ What = $what; Process = $p; Out = $out }
}
$side = @(
    Start-Check 'the seat desk: never a seat that is in the game' 'test_seat_desk_game.py'
    Start-Check 'the projector box: held until a player is in' 'test_hold_projector.py'
    Start-Check 'SEND LOGS: packed, sent, kept - and refused when it must be' 'test_send_logs.py'
)

$t = Join-Path ([IO.Path]::GetTempPath()) "wccfpanel-check-$PID"
Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $t 'data') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'build\fakegame.exe') $t
$env:WCCFPANEL_ROLE = 'seat1'            # the cabinet's code path (the panel would take a folder named "extracted"
$env:WCCFPANEL_DRYKEYS = '1'             # for the projector); keys logged, never pressed; never maximized
$env:WCCFPANEL_FULLSCREEN = '0'
$env:WCCF_DATA = Join-Path $t 'data'
$env:WCCF_KEYS = Join-Path $t 'data\keys.txt'
$env:WCCFPANEL_MONEYTEST = '1'
$env:WCCFPANEL_RELAYTEST = '1'
$env:WCCFPANEL_DEALTEST = '1'             # the dealt card's odds
$env:WCCF_RELAY_PORT = '20941'
$relay = Start-Process -FilePath $py -ArgumentList '-I', "`"$(Join-Path $kit 'scripts\_relay.py')`"", '60' -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 1
    $p = Start-Process -FilePath (Join-Path $t 'fakegame.exe') -WorkingDirectory $t -PassThru -Wait -NoNewWindow `
        -ArgumentList "`"$(Join-Path $kit 'overlay\wccfpanel.dll')`" wait:12000"
    $log = Get-Content (Join-Path $t 'wccfpanel.log') -ErrorAction SilentlyContinue
    $tests = @($log | Select-String -Pattern ' test: (PASS|FAIL) ')
    $bad = @($tests | Where-Object { $_.Line -match ' test: FAIL ' })
    $done = ($log | Select-String 'money test: \d+ checks') -and ($log | Select-String 'relay test: done')
    $bad | ForEach-Object { Write-Host $_.Line }
    Write-Host "panel self-tests: $($tests.Count) checks, $($bad.Count) failed$(if (-not $done) { ' - DID NOT FINISH' })"
    if ($p.ExitCode -or $bad.Count -or -not $done -or -not $tests.Count) {
        $log | Select-Object -Last 30 | ForEach-Object { Write-Host "  log: $_" }
        $failed += 'panel self-tests'
    }
} finally {
    if (-not $relay.HasExited) { Stop-Process -Id $relay.Id -Force }
    'WCCF_RELAY_PORT', 'WCCFPANEL_ROLE', 'WCCFPANEL_DRYKEYS', 'WCCFPANEL_FULLSCREEN', 'WCCF_DATA', 'WCCF_KEYS', 'WCCFPANEL_MONEYTEST',
    'WCCFPANEL_RELAYTEST', 'WCCFPANEL_DEALTEST' | ForEach-Object { Remove-Item "env:$_" -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
}

foreach ($c in $side) {
    $c.Process.WaitForExit()
    $text = @(Get-Content $c.Out -ErrorAction SilentlyContinue)
    if ($c.Process.ExitCode) {
        $text + @(Get-Content "$($c.Out).err" -ErrorAction SilentlyContinue) | Select-Object -Last 20 | ForEach-Object { Write-Host "  $_" }
        $failed += $c.What
    } else {
        $text | Select-Object -Last 1
    }
    Remove-Item $c.Out, "$($c.Out).err" -ErrorAction SilentlyContinue
}

if ($failed) { throw "FAILED: $($failed -join ', ')" }
Write-Host 'all checks passed'
