# check.ps1 - the kit's own checks that need no game (2026-10-08), after build.ps1; CI runs it too (kit.yml):
#   every script in code\ compiles with the kit's own Python (nothing written)
#   the key driver's self-test (hardware\keyboard.py --selftest: a scratch file, nothing live)
#   play.py's choice when a game window ends: a closed window stops the rest, a crash does not (source\test_ended.py)
#   the club card editor's self-test (cards\edit.py --self-test: cards made in memory, no real card)
#   a missing club-card helper file never stops a start (source\test_card_fix.py: a scratch panel.txt)
#   the run before last zipped into data\logs\archive, the archive kept to its size (source\test_log_archive.py)
#   a transferred card is listed as such and never played again (source\test_wallet_transferred.py: scratch cards)
#   the seat desk never gives a seat that is in the game (source\test_seat_desk_game.py: a scratch control log, the
#   desk on 127.0.0.1:20932)
#   the projector box held off the game until a player is in (source\test_hold_projector.py: the desk on 127.0.0.1:20933-6,
#   the firewall rule written to a scratch file)
#   SEND LOGS: packed without the club card, names taken out, kept by the log inbox - which refuses junk, too big, not
#   a ZIP and too many (source\test_send_logs.py: a scratch kit, inboxes on 127.0.0.1:20952 and 20953)
#   English in the game's pictures: added at the archive's end, taken back out byte for byte
#   (source\test_english_pictures.py: a scratch archive with one picture)
#   the Italian tables: each key once, the game's font, the kit's English codes (source\test_italian_tables.py)
#   a crash leaves a lean and a full memory snapshot (source\test_crash_dump.py: build\crashme.exe under the real
#   debugger.py, from a scratch folder)
#   the panel's money, relay and dealt-card self-tests (wccfpanel.dll loaded by source\build\fakegame.exe, in a
#   scratch folder; the relay test plays two seats through code\server\relay.py on 127.0.0.1:20941 - the C side and
#   the Python side of the match relay checked against each other)
# The panel's frame-wait test (WCCFPANEL_LIMITERTEST) measures milliseconds and stays out: a busy machine fails it.
#
#   powershell -ExecutionPolicy Bypass -File source\check.ps1
$ErrorActionPreference = 'Stop'
$kit = Split-Path $PSScriptRoot -Parent
$py = Join-Path $kit 'python\python.exe'
$failed = @()

& $py -I -c "import pathlib, sys; [compile(p.read_bytes(), str(p), 'exec') for p in sorted(pathlib.Path(sys.argv[1]).rglob('*.py'))]; print('code: all compile (every folder)')" (Join-Path $kit 'code')
if ($LASTEXITCODE) { $failed += 'code compile' }

# the launchers run python\python.exe code\<script>: the kit's modules are found ONLY through python\python313._pth
# (2026-10-11: scripts\ was renamed to code\ but the _pth still said ..\scripts - every test here adds code\ to the
# path itself, so they all passed while a real PLAY.exe could not import kit_common).  Every file, every folder.
& $py -I (Join-Path $PSScriptRoot 'test_imports.py') | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'every file in code\ imports through python313._pth, as the launchers run them' }

# a HANDOFF.md in every folder, naming every file in it - a file added or renamed without its line fails here
& $py -I (Join-Path $PSScriptRoot 'test_handoffs.py') | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'every folder has a HANDOFF.md that names every file in it' }

# the key driver's live file is where play.py's stop guard reads the card state, and the I/O board's outputs file is
# beside it (hardware\io_board.py derives it): if they ever disagree, the stop guard reads "card out" with a card in
& $py -I -c "import os, play; from hardware import keyboard as k; n = os.path.normcase; assert n(play.KEYS_INPUT) == n(k.LIVE), (play.KEYS_INPUT, k.LIVE); assert n(k.OUTPUTS) == n(k.LIVE[:-len('_input.txt')] + '_outputs.txt'); assert os.path.basename(os.path.dirname(k.LIVE)) == 'data'; print('key driver files: in data\\, the same for play.py and the I/O board')"
if ($LASTEXITCODE) { $failed += 'the key driver, the I/O board and play.py name the same live files in data\' }

# Kit 5.5 reused the name PANEL for wccfpanel.dll: a plain start read the dll as data\panel.txt and never went online
& $py -I -c "import sys; sys.path.insert(0, sys.argv[1]); import play; assert play.PANEL.endswith('panel.txt'), play.PANEL; print('play.py: PANEL is panel.txt')" (Join-Path $kit 'code')
if ($LASTEXITCODE) { $failed += 'play.py PANEL' }

& $py -I (Join-Path $kit 'code\hardware\keyboard.py') --selftest | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'key driver self-test' }

& $py -I (Join-Path $PSScriptRoot 'test_ended.py')
if ($LASTEXITCODE) { $failed += 'play.py ended: a closed window vs a crash' }

& $py -I (Join-Path $kit 'code\cards\edit.py') --self-test | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'club card editor self-test' }

& $py -I (Join-Path $PSScriptRoot 'test_card_fix.py')
if ($LASTEXITCODE) { $failed += 'a missing card helper file must not stop a start' }

& $py -I (Join-Path $PSScriptRoot 'test_icc_reader.py')
if ($LASTEXITCODE) { $failed += 'the card reader: a failed save never writes in place; a bad card does not lock out' }

& $py -I (Join-Path $PSScriptRoot 'test_take_seat.py')
if ($LASTEXITCODE) { $failed += 'the seat decision: only "no broker" falls back to seat 1; other answers stop' }

& $py -I (Join-Path $PSScriptRoot 'test_seat_lease.py') | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'the seat lease reconnects and re-claims its seat after a break' }

& $py -I (Join-Path $PSScriptRoot 'test_relay.py') | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'the match relay: a live seat cannot be taken over by another address' }

& $py -I (Join-Path $PSScriptRoot 'test_rotate_logs.py')
if ($LASTEXITCODE) { $failed += 'log rotation never stops a start when a log file is held open' }

& $py -I (Join-Path $PSScriptRoot 'test_setup_state.py') | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'a missing card catalogue does not stop a start' }

& $py -I (Join-Path $PSScriptRoot 'test_old_layout.py') | Select-Object -Last 1
if ($LASTEXITCODE) { $failed += 'an older kit''s scripts\ bin\ overlay\ tidied, the catalogue moved to data\cache\' }

& $py -I (Join-Path $PSScriptRoot 'test_patch_hook_import.py')
if ($LASTEXITCODE) { $failed += 'the hook-import patcher: winmm -> wccfk, valid checksum, reversible' }

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
    Start-Check 'the wccf.online sign-in: a code, approved, kept, never printed' 'test_account.py'
    Start-Check 'the seat desk and the sign-in: optional or needed, a good or refused token, no token logged' 'test_seat_desk_signin.py'
    Start-Check 'the online club: owned cards make the CATALOGUE and a new club''s table, the slot when anything is wrong' 'test_online_club.py'
    Start-Check 'the server''s witness: a finished match tells the website whose it was, with the server''s secret' 'test_witness.py'
)

& $py -I (Join-Path $PSScriptRoot 'test_english_pictures.py')
if ($LASTEXITCODE) { $failed += 'English pictures: added to the archive, taken back out byte for byte' }

& $py -I (Join-Path $PSScriptRoot 'test_italian_tables.py')
if ($LASTEXITCODE) { $failed += 'the Italian tables: keys, font and codes' }

& (Join-Path $PSScriptRoot 'build\test_wholemsg.exe')
if ($LASTEXITCODE) { $failed += 'whole messages: a batch in pieces waits for its rest, bytes that are no batch are skipped' }
& $py -I (Join-Path $PSScriptRoot 'test_crash_dump.py')
if ($LASTEXITCODE) { $failed += 'a crash leaves its memory snapshots (lean + full) in data\dumps' }

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
$env:WCCFPANEL_SETTEST = '1'              # a panel.txt save keeps auto_logs=0
$env:WCCF_RELAY_PORT = '20941'
$env:WCCF_SKIN = Join-Path $kit 'art\skin.tex'      # the panel's art (play.py passes it; no longer beside the panel)
$relay = Start-Process -FilePath $py -ArgumentList '-I', "`"$(Join-Path $kit 'code\server\relay.py')`"", '60' -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 1
    $p = Start-Process -FilePath (Join-Path $t 'fakegame.exe') -WorkingDirectory $t -PassThru -Wait -NoNewWindow `
        -ArgumentList "`"$(Join-Path $kit 'programs\wccfpanel.dll')`" wait:12000"
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
    'WCCF_RELAY_PORT', 'WCCF_SKIN', 'WCCFPANEL_ROLE', 'WCCFPANEL_DRYKEYS', 'WCCFPANEL_FULLSCREEN', 'WCCF_DATA', 'WCCF_KEYS', 'WCCFPANEL_MONEYTEST',
    'WCCFPANEL_RELAYTEST', 'WCCFPANEL_DEALTEST', 'WCCFPANEL_SETTEST' | ForEach-Object { Remove-Item "env:$_" -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
}

# the online club (2026-10-14): play.py's WCCF_CLUB_CARD reaches the panel - the card its close warning and SETTINGS
# watch, the transfer card beside it, its backups - and switches YOUR CARDS off; without it, the slot card
$t = Join-Path ([IO.Path]::GetTempPath()) "wccfpanel-club-$PID"
Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $t 'data') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'build\fakegame.exe') $t
$env:WCCFPANEL_ROLE = 'seat1'; $env:WCCFPANEL_DRYKEYS = '1'; $env:WCCFPANEL_FULLSCREEN = '0'
$env:WCCF_DATA = Join-Path $t 'data'; $env:WCCF_KEYS = Join-Path $t 'data\keys.txt'
$env:WCCF_SKIN = Join-Path $kit 'art\skin.tex'
$club = Join-Path $t 'data\save\online\u7'
try {
    $lines = foreach ($online in $true, $false) {
        if ($online) { $env:WCCF_CLUB_CARD = "$club\club.bin"; $env:WCCF_ACCOUNT_NAME = "Kak$([char]0xE1)7" }   # SETTINGS'
        else { 'WCCF_CLUB_CARD', 'WCCF_ACCOUNT_NAME' | ForEach-Object { Remove-Item "env:$_" -ErrorAction SilentlyContinue } }
        Remove-Item (Join-Path $t 'wccfpanel.log') -ErrorAction SilentlyContinue       # ACCOUNT row: the name, folded
        Start-Process -FilePath (Join-Path $t 'fakegame.exe') -WorkingDirectory $t -Wait -NoNewWindow `
            -ArgumentList "`"$(Join-Path $kit 'programs\wccfpanel.dll')`" wait:3000"
        $log = Get-Content (Join-Path $t 'wccfpanel.log') -ErrorAction SilentlyContinue
        @($log | Select-String 'club card: ')[0].Line
        @($log | Select-String '^account: ')[0].Line
    }
    $slot = Join-Path $t 'data\save'
    $want = @("club card: $club\club.bin (transfer $club\club.new.bin, backups $club\backup\club.bin.*.bak) - the online club: YOUR CARDS off, no card dealt",
              "account: Kaka7",
              "club card: $slot\seat1_club.bin (transfer $slot\seat1_club.new.bin, backups $slot\backup\seat1_club.bin.*.bak)",
              "account: not signed in")
    $ok = 0
    for ($i = 0; $i -lt 4; $i++) {
        if ($lines[$i] -and $lines[$i].EndsWith($want[$i])) { $ok++ } else { Write-Host "  wanted: $($want[$i])`n  got:    $($lines[$i])" }
    }
    Write-Host "panel club card and account: $ok/4 checks passed"
    if ($ok -ne 4) { $failed += 'the panel watches the club card in play (the online club or the slot) and shows the account' }
} finally {
    'WCCF_CLUB_CARD', 'WCCF_ACCOUNT_NAME', 'WCCF_SKIN', 'WCCFPANEL_ROLE', 'WCCFPANEL_DRYKEYS', 'WCCFPANEL_FULLSCREEN', 'WCCF_DATA', 'WCCF_KEYS' |
        ForEach-Object { Remove-Item "env:$_" -ErrorAction SilentlyContinue }
    Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
}

# the card a finished match earned, online (2026-10-14, phase 3): the panel helper adds it to the run's CATALOGUE and
# names it in data\dealt.txt while the game runs - the panel reads the CATALOGUE again and shows that card
$t = Join-Path ([IO.Path]::GetTempPath()) "wccfpanel-deal-$PID"
Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $t 'data') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'build\fakegame.exe') $t
function Cat-Line([int]$no, [string]$name, [string]$pos) {     # the panel's catalogue columns (wccfpanel.c load_catalogue)
    ($no, 1, 1, 1, 13, '2001-02', 1, 'REGULAR', 'Normal', 0, "Test $name", $name, 'x', 'x', 'x', $pos, 1, 'Bologna', 5,
     'Italy', 'x', 'x', 'x', 'x', 10, 10, 10, 10, 10, 10, 60) -join "`t"
}
$cat = Join-Path $t 'catalogue_online.tsv'
Set-Content -Encoding ascii $cat ("card_no`tx", (Cat-Line 25 'BRIOSCHI' 'DF'))
$env:WCCFPANEL_ROLE = 'seat1'; $env:WCCFPANEL_DRYKEYS = '1'; $env:WCCFPANEL_FULLSCREEN = '0'
$env:WCCF_DATA = Join-Path $t 'data'; $env:WCCF_KEYS = Join-Path $t 'data\keys.txt'
$env:WCCF_SKIN = Join-Path $kit 'art\skin.tex'; $env:WCCF_CATALOGUE = $cat
$env:WCCF_CLUB_CARD = Join-Path $t 'data\save\online\u7\club.bin'
try {
    $p = Start-Process -FilePath (Join-Path $t 'fakegame.exe') -WorkingDirectory $t -PassThru -NoNewWindow `
        -ArgumentList "`"$(Join-Path $kit 'programs\wccfpanel.dll')`" wait:5000"
    Start-Sleep -Milliseconds 2000                             # the panel up, its catalogue read, dealt.txt looked at
    Add-Content -Encoding ascii $cat (Cat-Line 31 'PAGLIUCA' 'GK')
    Set-Content -Encoding ascii (Join-Path $t 'data\dealt.txt') '1 31'
    $p.WaitForExit()
    $log = Get-Content (Join-Path $t 'wccfpanel.log') -ErrorAction SilentlyContinue
    $ok = @((@($log | Select-String '^browser: catalogue 1 cards').Count -ge 1),    # (each in brackets: a comma binds
            (@($log | Select-String '^browser: catalogue 2 cards').Count -ge 1),    # before -ge in PowerShell)
            (@($log | Select-String '^deal: card 31 PAGLIUCA \(REGULAR\) - given by wccf.online for the match').Count -eq 1))
    Write-Host "panel new card online: $(@($ok | Where-Object { $_ }).Count)/3 checks passed"
    if ($ok -contains $false) {
        $log | Select-String 'browser:|deal:' | ForEach-Object { Write-Host "  log: $($_.Line)" }
        $failed += 'online, the card a match earned: the CATALOGUE read again and the card shown'
    }
} finally {
    'WCCF_CLUB_CARD', 'WCCF_CATALOGUE', 'WCCF_SKIN', 'WCCFPANEL_ROLE', 'WCCFPANEL_DRYKEYS', 'WCCFPANEL_FULLSCREEN', 'WCCF_DATA',
    'WCCF_KEYS' | ForEach-Object { Remove-Item "env:$_" -ErrorAction SilentlyContinue }
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
