# the keeper (code\server\keeper.ps1), 2026-10-07 (its quicker rules 2026-10-08; in the kit 2026-10-24), in Windows
# PowerShell 5.1 like the Azure machine, with a scratch folder (its own kit\ too), made-up process and task names and
# -NoStop - it never touches the real server, a real task or play.py. "Up" is this test's own TCP listener on
# 127.0.0.1:20977 plus the powershell process the keeper runs in; "deaf" is that process with a port nobody listens on.
# Sections 1-13 are the community server's rules (-Always); 14 a host's kit (only while it hosts). build.ps1 makes
# build\zz_spin.exe (spin.c), the hung control's stand-in.
#   powershell -NoProfile -ExecutionPolicy Bypass -File source\test_keeper.ps1
$ErrorActionPreference = 'Stop'
$keeper = Join-Path $PSScriptRoot '..\code\server\keeper.ps1'
$root = Join-Path ([IO.Path]::GetTempPath()) ('keepertest_' + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $root | Out-Null
$results = New-Object System.Collections.Generic.List[bool]
$logf = Join-Path $root 'keeper_log.txt'
$mark = Join-Path $root 'keeper_down_since.txt'
$pause = Join-Path $root 'keeper.pause'
$restarted = Join-Path $root 'keeper_restarted.txt'
$up = @('-ProcessName', 'powershell', '-Port', '20977')
$gone = @('-ProcessName', 'zz_no_such_process', '-Port', '20977')
$deaf = @('-ProcessName', 'powershell', '-Port', '20978')
$logsDir = Join-Path $root 'kit\data\logs'
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $logsDir 'run_server.txt') -Value 'pretend crash log'
$evid = Join-Path $root 'crash_evidence'
function EvidenceFolders([string]$pat) {
    if (Test-Path -LiteralPath $evid) { return @(Get-ChildItem -LiteralPath $evid -Directory -Filter $pat) }
    return @()
}

function Check([string]$name, [bool]$ok, [string]$detail = '') {
    $results.Add($ok)
    '  ' + $(if ($ok) { 'PASS' } else { 'FAIL' }) + '  ' + $name + $(if ($detail) { '  - ' + $detail } else { '' })
}
function Run-Keeper([string[]]$extra) {
    $out = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $keeper -Root $root -NoStop `
        -Kit (Join-Path $root 'kit') -ServerTask 'WCCF keeper test - no such task' -Always @extra 2>&1
    return ($out | Out-String).Trim()
}
function Log-Text { if (Test-Path -LiteralPath $logf) { return (Get-Content -LiteralPath $logf -Raw) } return '' }
function Count-Log([string]$pattern) { return [regex]::Matches((Log-Text), $pattern).Count }
function Restarts { return (Count-Log '(?m) - restarting\r?$') }
function Make-Old([string]$path, [int]$minutes) { (Get-Item -LiteralPath $path).LastWriteTime = (Get-Date).AddMinutes(-$minutes) }

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 20977)
$listener.Start()
try {
    '== 1 up =='
    $o = Run-Keeper $up
    Check 'up: no log line, no mark' ((-not (Test-Path $logf)) -and (-not (Test-Path $mark))) $o
    $o = Run-Keeper ($up + '-DryRun')
    Check 'up, dry run: nothing to do' ($o -match 'server up') $o

    '== 2 control gone: restarted at the FIRST check =='
    $o = Run-Keeper ($gone + '-DryRun')
    Check 'dry run: would restart now, writes nothing' (($o -match 'would restart now: server down \(zz_no_such_process: not running') -and
        (-not (Test-Path $logf)) -and (-not (Test-Path $restarted))) $o
    $o = Run-Keeper $gone
    $t = Log-Text
    Check 'first check: restart tried (no such task, a kit with no Python - said so), its time kept, no mark' (
        ($t -match 'is gone \(it never comes back by itself\) - restarting') -and
        ($t -match 'could not start the server: no .*python\.exe') -and
        (Test-Path $restarted) -and (-not (Test-Path $mark)) -and ((Restarts) -eq 1)) $t.Trim()
    $ev = EvidenceFolders '*_control_gone'
    Check 'the crash logs were saved before the restart' (($ev.Count -ge 1) -and
        (Test-Path -LiteralPath (Join-Path $ev[0].FullName 'run_server.txt')) -and ($t -match 'saved 1 log files')) ($ev.Count.ToString() + ' folder(s)')

    '== 3 still gone right after: at most one restart in 3 min =='
    $o = Run-Keeper $gone
    Check 'waits: one line, a mark, no second restart' (((Count-Log 'after the keeper restarted it - waiting') -eq 1) -and
        (Test-Path $mark) -and ((Restarts) -eq 1)) $o
    $before = Log-Text
    $o = Run-Keeper $gone
    Check 'the next minute: no new line (a line per change), still one restart' (((Log-Text) -eq $before) -and ((Restarts) -eq 1)) $o
    $o = Run-Keeper ($gone + '-DryRun')
    Check 'dry run: says waiting, writes nothing' (($o -match 'waiting: server down') -and ((Log-Text) -eq $before)) $o

    '== 4 still gone 3 min after the restart: restarted again =='
    Make-Old $restarted 4
    $o = Run-Keeper $gone
    Check 'restarts again; the mark goes; the restart time is new' (((Restarts) -eq 2) -and (-not (Test-Path $mark)) -and
        ((Get-Item -LiteralPath $restarted).LastWriteTime -gt (Get-Date).AddMinutes(-1))) $o

    '== 5 up again clears a mark =='
    Set-Content -LiteralPath $mark -Value 'x'
    $o = Run-Keeper $up
    Check 'up again: mark removed, logged' ((-not (Test-Path $mark)) -and ((Log-Text) -match 'server up again')) $o

    '== 6 control runs, its port does not listen: restarted only when that lasts 3 min =='
    Make-Old $restarted 10
    $o = Run-Keeper $deaf
    Check 'first sight: a mark and a line, no restart' ((Test-Path $mark) -and ((Restarts) -eq 2) -and
        ((Log-Text) -match 'powershell: runs, TCP 20978: not listening\) - restarting it if that lasts 3 min')) $o
    $before = Log-Text
    $o = Run-Keeper $deaf
    Check 'a minute later (the mark is fresh): nothing new, no restart' (((Log-Text) -eq $before) -and ((Restarts) -eq 2)) $o
    $o = Run-Keeper ($deaf + '-DryRun')
    Check 'dry run: waiting, so many s of 180' ($o -match 'waiting: .* for \d+ s of 180') $o
    Make-Old $mark 4
    $o = Run-Keeper ($deaf + '-DryRun')
    Check 'dry run after 4 min: would restart' ($o -match 'would restart now: .*for 4 min') $o
    $o = Run-Keeper $deaf
    Check 'after 4 min: restarted, the mark goes' (((Restarts) -eq 3) -and ((Log-Text) -match 'for 4 min - restarting') -and
        (-not (Test-Path $mark))) $o

    '== 7 pause =='
    Make-Old $restarted 10
    Set-Content -LiteralPath $pause -Value 'test'
    $before = Log-Text
    $o = Run-Keeper $gone
    Check 'fresh pause: nothing written, no restart, no mark' (((Log-Text) -eq $before) -and (-not (Test-Path $mark))) $o
    Make-Old $pause 30
    $o = Run-Keeper $gone
    Check 'stale pause (30 min): ignored and logged, the check goes on (control gone: restarted)' (
        ((Log-Text) -match 'min old - ignored') -and ((Restarts) -eq 4)) $o
    Remove-Item -LiteralPath $pause

    '== 8 at start-up =='
    Make-Old $restarted 10
    $evBefore = (EvidenceFolders '*').Count
    $o = Run-Keeper ($deaf + '-Boot')
    Check 'restarts at the first check, even a control that runs' (((Log-Text) -match 'not listening\) at start-up - restarting') -and
        ((Restarts) -eq 5)) $o
    Check 'a boot restart saves no evidence (nothing useful yet)' ((EvidenceFolders '*').Count -eq $evBefore) (
        'before ' + $evBefore + ', after ' + (EvidenceFolders '*').Count)
    $o = Run-Keeper ($gone + '-Boot')
    Check 'right after that restart it waits, even at start-up' (((Restarts) -eq 5) -and
        ((Count-Log 'after the keeper restarted it - waiting') -eq 2)) $o

    '== 9 a missing folder =='
    $missing = Join-Path $root 'nope'
    & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $keeper -Root $missing -NoStop -ServerTask 'x' `
        -ProcessName 'zz_no_such_process' 2>&1 | Out-Null
    Check 'exit 1, nothing made' (($LASTEXITCODE -eq 1) -and (-not (Test-Path $missing))) ''
    '== 10 hung: control runs, its port listens, TWO threads busy (build\zz_spin.exe stands in) =='
    $spinExe = Join-Path $PSScriptRoot 'build\zz_spin.exe'
    if (-not (Test-Path -LiteralPath $spinExe)) { throw 'no build\zz_spin.exe - run source\build.ps1 first' }
    $hungArgs = @('-ProcessName', 'zz_spin', '-Port', '20977')
    Make-Old $restarted 10
    Remove-Item -LiteralPath $mark -Force -ErrorAction SilentlyContinue      # section 8 left its "waiting" mark
    $sp = Start-Process -FilePath $spinExe -ArgumentList '2', '40' -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 500
    $o = Run-Keeper $hungArgs
    Check 'first sight: a mark and a line naming 2 busy threads, no restart' ((Test-Path $mark) -and ((Restarts) -eq 5) -and
        ((Log-Text) -match 'zz_spin: runs, TCP 20977: listens, 2 threads busy: hung\) - restarting it if that lasts 3 min')) $o
    Make-Old $mark 4
    $o = Run-Keeper $hungArgs
    Check 'hung for 4 min: restarted, its logs saved as "hung"' (((Restarts) -eq 6) -and ((EvidenceFolders '*_hung').Count -ge 1)) $o
    Stop-Process -Id $sp.Id -Force
    Make-Old $restarted 10
    $sp = Start-Process -FilePath $spinExe -ArgumentList '1', '30' -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 500
    $before = Log-Text
    $o = Run-Keeper $hungArgs
    Check 'ONE busy thread is a healthy control: nothing done' (((Restarts) -eq 6) -and (-not (Test-Path $mark)) -and
        ((Log-Text) -eq $before)) $o
    Stop-Process -Id $sp.Id -Force

    '== 11 takes no one in: seats given, nobody let in since (zz_spin 0 = a quiet control; documentation addresses) =='
    $inv = [Globalization.CultureInfo]::InvariantCulture
    function Seat-Line([int]$agoSec, [string]$ip, [int]$seat, [switch]$Free) {
        $t = (Get-Date).AddSeconds(-$agoSec).ToString('yyyy-MM-dd HH:mm:ss', $inv)
        if ($Free) { return $t + ' ' + $ip + ':5000: seat ' + $seat + ' free again - taken now: none' }
        return $t + ' ' + $ip + ':5000: seat ' + $seat + ' - taken now: ' + $seat
    }
    function Accept-Lines([int]$agoSec, [string]$ep, [int]$sateId) {
        $t = (Get-Date).AddSeconds(-$agoSec).ToString('yyyy/M/d(ddd) HH:mm:ss', $inv)
        return @(('t+ 10.00s INFO  ClientManage  ClientManage::INIT() : client[0] : sateID=' + $sateId + ',version=7128,serial=PC'),
                 ("t+ 10.00s INFO  ClientManage  ClientManage::INIT() : ++ACCEPT++  '" + $ep + "', " + $t))
    }
    $seatLog = Join-Path $logsDir 'seat_broker.txt'
    $dbgLog = Join-Path $logsDir '_dbg_control.txt'
    function Set-Logs([string[]]$seatLines, [string[]]$dbgLines) {
        Set-Content -LiteralPath $seatLog -Value $seatLines
        Set-Content -LiteralPath $dbgLog -Value (@('t+  0.10s DEBUG  start') + $dbgLines)
    }
    $connf = Join-Path $root 'conns.txt'
    Set-Content -LiteralPath $connf -Value ''
    $qa = @('-ProcessName', 'zz_spin', '-Port', '20977', '-ConnFile', $connf)
    $p1 = '203.0.113.7'; $p2 = '198.51.100.9'; $proj = '192.0.2.50'
    $sp = Start-Process -FilePath $spinExe -ArgumentList '0', '300' -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 500
    Make-Old $restarted 10

    Set-Logs @((Seat-Line 300 $proj 1), (Seat-Line 200 $p1 2)) ((Accept-Lines 230 ($proj + ':3552') 0) + (Accept-Lines 180 ($p1 + ':4000') 2))
    $before = Log-Text
    $o = Run-Keeper $qa
    Check 'everyone given a seat was let in: nothing done' (((Restarts) -eq 6) -and ((Log-Text) -eq $before) -and
        (-not (Test-Path $mark))) $o
    Set-Logs @((Seat-Line 300 $proj 1), (Seat-Line 100 $p1 2)) (Accept-Lines 230 ($proj + ':3552') 0)
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'a seat 100 s old, not let in yet: too early to tell' ($o -match 'server up') $o
    Set-Logs @((Seat-Line 300 $p1 2), (Seat-Line 270 $p1 2 -Free)) @()
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'a seat given back after 30 s (the player left): not counted' ($o -match 'server up') $o
    Set-Logs @((Seat-Line 300 $p1 2), (Seat-Line 250 $p2 3)) (Accept-Lines 200 ($p2 + ':4000') 3)
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'someone let in after that seat: control takes players in - not counted' ($o -match 'server up') $o

    Set-Content -LiteralPath $connf -Value ('Established ' + $p1 + ':4001')
    Set-Logs @((Seat-Line 400 $proj 1), (Seat-Line 240 $p1 2)) (Accept-Lines 380 ($proj + ':3552') 0)
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'stuck, dry run: would restart now, names the address' (
        $o -match 'would restart now: control takes no one in \(seat given to 203\.0\.113\.7, nobody let in for 4 min\)') $o
    $o = Run-Keeper $qa
    Check 'stuck: restarted at once, logs saved as "noaccept", the address kept' (((Restarts) -eq 7) -and
        ((EvidenceFolders '*_noaccept').Count -ge 1) -and
        ((Get-Content -LiteralPath (Join-Path $root 'keeper_noaccept.txt')) -eq $p1)) $o

    Make-Old $restarted 10
    Set-Logs @((Seat-Line 240 $p1 2)) @()
    $o = Run-Keeper $qa
    Check 'the same address again within the hour: not restarted, said once' (((Restarts) -eq 7) -and
        ((Log-Text) -match 'that PC, not the server - not restarting') -and (Test-Path $mark)) $o
    $before = Log-Text
    $o = Run-Keeper $qa
    Check 'a minute later: no new line' (((Log-Text) -eq $before) -and ((Restarts) -eq 7)) $o
    Set-Content -LiteralPath $connf -Value ('CloseWait ' + $p2 + ':4002')
    Set-Logs @((Seat-Line 300 $p2 3), (Seat-Line 200 $p2 3 -Free)) @()
    $o = Run-Keeper $qa
    Check 'another address, its game gave up waiting (CloseWait), seat given back: restarted, the mark goes' (
        ((Restarts) -eq 8) -and (-not (Test-Path $mark))) $o

    Make-Old $restarted 10
    Set-Content -LiteralPath $connf -Value @(('Established ' + $p2 + ':4000'), ('Established ' + $p1 + ':4001'))
    Set-Logs @((Seat-Line 2000 $p2 2), (Seat-Line 240 $p1 3)) (Accept-Lines 1990 ($p2 + ':4000') 2)
    $o = Run-Keeper $qa
    Check 'a player still in a session: waits for them, says so, no restart' (((Restarts) -eq 8) -and
        ((Log-Text) -match '1 player\(s\) still in a session: waiting for them, at most 20 min')) $o
    Set-Logs @((Seat-Line 2000 $p2 2), (Seat-Line 1300 $p1 3)) (Accept-Lines 1990 ($p2 + ':4000') 2)
    $o = Run-Keeper $qa
    Check 'that seat waiting 21 min: restarted even so' ((Restarts) -eq 9) $o
    # 2026-10-15: a player's PC lost its link to the seat desk for 2 s and took its seat again while its game stayed in
    # control - the seat given again is no one waiting outside (the old rule cut two players' matches 21 min later)
    Make-Old $restarted 10
    Set-Content -LiteralPath $connf -Value ('Established ' + $p1 + ':4000')
    Set-Logs @((Seat-Line 3000 $p1 2), (Seat-Line 1302 $p1 2 -Free), (Seat-Line 1300 $p1 2)) (Accept-Lines 2990 ($p1 + ':4000') 2)
    $before = Log-Text
    $o = Run-Keeper $qa
    Check 'his seat given again while his game stays in, 21 min on: nothing done' (((Restarts) -eq 9) -and
        ((Log-Text) -eq $before) -and (-not (Test-Path $mark))) $o
    Set-Logs @((Seat-Line 3000 $p1 2), (Seat-Line 400 $p1 3)) (Accept-Lines 2990 ($p1 + ':4000') 2)
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'two players of one house, the second not trying: not counted' ($o -match 'server up') $o
    Set-Content -LiteralPath $connf -Value @(('Established ' + $p1 + ':4000'), ('Established ' + $p1 + ':4001'))
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'two players of one house, the second knocking: counted (waits for the first)' (
        $o -match 'waiting: control takes no one in \(seat given to 203\.0\.113\.7') $o
    # 2026-10-15 12:28 UTC: a game left on Error 3000 since a restart kept its seat-desk link, which took its seat again
    # on a blink; the old rule read that as control taking no one in and restarted it - the game had no link at all
    Set-Content -LiteralPath $connf -Value ('Established ' + $p2 + ':4000')
    Set-Logs @((Seat-Line 3000 $p1 2), (Seat-Line 242 $p1 2 -Free), (Seat-Line 240 $p1 2)) (Accept-Lines 2990 ($p2 + ':4000') 3)
    $before = Log-Text
    $o = Run-Keeper $qa
    Check 'a PC whose game is not trying takes its seat again, 4 min on: nothing done' (((Restarts) -eq 9) -and
        ((Log-Text) -eq $before) -and (-not (Test-Path $mark))) $o
    Set-Content -LiteralPath $connf -Value ('TimeWait ' + $p1 + ':4001')
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'only a TimeWait link from it (the run before a restart): not counted' ($o -match 'server up') $o

    Make-Old $restarted 10
    Set-Content -LiteralPath $connf -Value @(('Established ' + $proj + ':3552'), ('Established ' + $p2 + ':4002'))
    Set-Logs @((Seat-Line 400 $proj 1), (Seat-Line 240 $p2 2)) (Accept-Lines 380 ($proj + ':3552') 0)
    $o = Run-Keeper $qa
    Check 'only the projector connected (sateID 0 is not a player): restarted' ((Restarts) -eq 10) $o

    Make-Old $restarted 10
    Remove-Item -LiteralPath $seatLog
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'no seat desk log: cannot tell - nothing done' ($o -match 'server up') $o
    Set-Logs @((Seat-Line 240 $p2 2)) @()
    Make-Old $dbgLog 10
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'a debug log older than control (not this run): nothing done' ($o -match 'server up') $o

    '== 12 the projector box on hold (kit\data\hold_projector.txt): its seat is never a miss; a restart holds it first =='
    $holdFile = Join-Path (Split-Path $logsDir) 'hold_projector.txt'
    Set-Content -LiteralPath $holdFile -Value $proj
    Make-Old $restarted 10
    Remove-Item -LiteralPath (Join-Path $root 'keeper_noaccept.txt') -Force -ErrorAction SilentlyContinue
    Set-Content -LiteralPath $connf -Value ''
    Set-Logs @((Seat-Line 400 $proj 1)) @()
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'only the held box has a seat, nobody let in for 400 s: not a stuck server' ($o -match 'server up') $o
    Set-Content -LiteralPath $connf -Value ('Established ' + $p2 + ':4002')
    Set-Logs @((Seat-Line 400 $proj 1), (Seat-Line 240 $p2 2)) @()
    $o = Run-Keeper $qa
    Check 'a player not let in beside it: restarted, the box held first, the player named (not the box)' (
        ((Restarts) -eq 11) -and ((Log-Text) -match 'would hold the projector box 192\.0\.2\.50') -and
        ((Log-Text) -match 'seat given to 198\.51\.100\.9, nobody') -and -not ((Log-Text) -match 'seat given to 192\.0\.2\.50')) $o
    Set-Content -LiteralPath $holdFile -Value 'not an address'
    Make-Old $restarted 10
    Remove-Item -LiteralPath (Join-Path $root 'keeper_noaccept.txt') -Force -ErrorAction SilentlyContinue
    Set-Content -LiteralPath $connf -Value ('Established ' + $proj + ':3553')
    Set-Logs @((Seat-Line 400 $proj 1)) @()
    $o = Run-Keeper ($qa + '-DryRun')
    Check 'a hold file without an address: the box counts like any seat (would restart)' ($o -match 'would restart now: control takes no one in \(seat given to 192\.0\.2\.50') $o
    Remove-Item -LiteralPath $holdFile

    '== 13 the real port (no scratch file): a link this test listener never takes is knocking =='
    Make-Old $restarted 10
    Remove-Item -LiteralPath (Join-Path $root 'keeper_noaccept.txt') -Force -ErrorAction SilentlyContinue
    $real = @('-ProcessName', 'zz_spin', '-Port', '20977', '-DryRun')
    Set-Logs @((Seat-Line 240 '127.0.0.1' 2)) @()
    $o = Run-Keeper $real
    Check 'a seat, no link on the port: nothing (its game is not trying)' ($o -match 'server up') $o
    $cl = [System.Net.Sockets.TcpClient]::new()
    $cl.Connect('127.0.0.1', 20977)
    $o = Run-Keeper $real
    Check 'its game connected, never taken in (Established): would restart' (
        $o -match 'would restart now: control takes no one in \(seat given to 127\.0\.0\.1') $o
    $cl.Close()
    Start-Sleep -Milliseconds 300
    $o = Run-Keeper $real
    Check 'its game gave up (CloseWait): still knocking' (
        $o -match 'would restart now: control takes no one in \(seat given to 127\.0\.0\.1') $o
    $listener.AcceptTcpClient().Close()
    Start-Sleep -Milliseconds 300
    $o = Run-Keeper $real
    Check 'the link taken and closed: nothing' ($o -match 'server up') $o
    Stop-Process -Id $sp.Id -Force

    '== 14 a host''s kit (no -Always): only while it hosts - PLAY.exe server, until a person''s PLAY.exe stop =='
    $hostRoot = Join-Path $root 'host'
    New-Item -ItemType Directory -Path $hostRoot | Out-Null
    $hostLog = Join-Path $hostRoot 'keeper_log.txt'
    $wanted = Join-Path $hostRoot 'server.wanted'
    $running = Join-Path $root 'kit\data\running.json'
    function Run-Host([string[]]$extra) {
        $out = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $keeper -Root $hostRoot -NoStop `
            -Kit (Join-Path $root 'kit') -ServerTask 'WCCF keeper test - no such task' @extra 2>&1
        return ($out | Out-String).Trim()
    }
    function Host-Restarts { if (Test-Path -LiteralPath $hostLog) { return [regex]::Matches((Get-Content -LiteralPath $hostLog -Raw), '(?m) - restarting\r?$').Count } return 0 }
    $o = Run-Host ($gone + '-DryRun')
    Check 'no server started here, control gone: not hosting (dry run says so)' ($o -match 'not hosting') $o
    $o = Run-Host $gone
    Check '... and the real check does nothing: no log, no restart, nothing noted' ((-not (Test-Path $hostLog)) -and
        (-not (Test-Path $wanted)) -and (-not (Test-Path (Join-Path $hostRoot 'keeper_restarted.txt')))) $o
    Set-Content -LiteralPath $running -Value '{"mode": "remote", "processes": {"41": "seat 1 launcher", "42": "key driver"}}'
    $o = Run-Host $gone
    Check 'a player''s PC (running.json without a server launcher): not hosting' ((-not (Test-Path $hostLog)) -and
        (-not (Test-Path $wanted))) $o
    Set-Content -LiteralPath $running -Value '{"mode": "server", "processes": {"51": "scene service", "52": "server launcher"}}'
    $o = Run-Host $up
    Check 'hosting, server up: nothing done, the server noted as wanted' ((Test-Path $wanted) -and (-not (Test-Path $hostLog))) $o
    $o = Run-Host $gone
    Check 'hosting, control gone: restarted at once' ((Host-Restarts) -eq 1) $o
    Remove-Item -LiteralPath $running              # the keeper's own stop ends running.json; the start did not come up
    (Get-Item -LiteralPath (Join-Path $hostRoot 'keeper_restarted.txt')).LastWriteTime = (Get-Date).AddMinutes(-4)
    $o = Run-Host $gone
    Check 'no running.json but still wanted (a start that failed): tried again 3 min later' ((Host-Restarts) -eq 2) $o
    Remove-Item -LiteralPath $wanted               # what a person's PLAY.exe stop does (play.py _stop)
    (Get-Item -LiteralPath (Join-Path $hostRoot 'keeper_restarted.txt')).LastWriteTime = (Get-Date).AddMinutes(-4)
    $o = Run-Host $gone
    Check 'a person stopped it: nothing more' ((Host-Restarts) -eq 2) $o
    Set-Content -LiteralPath $running -Value 'not json {'
    $o = Run-Host $gone
    Check 'a broken running.json: not hosting, no error' (((Host-Restarts) -eq 2) -and ($LASTEXITCODE -eq 0)) $o
    '--- the scratch log ---'
    (Log-Text).Trim()
} finally {
    $listener.Stop()
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}
'{0}/{1} checks passed' -f @($results | Where-Object { $_ }).Count, $results.Count
if ($results -contains $false) { exit 1 }
