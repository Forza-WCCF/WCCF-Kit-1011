# WCCF 2010-11 - the keeper (2026-10-07; quicker 2026-10-08): brings a server back when Sega's control crashes, hangs
# or stops letting players in. Written for the community server on Azure (there: C:\wccf1011\keeper.ps1, the task
# "WCCF 2010-11 keeper" runs it as SYSTEM at start-up and every minute, with -Always and its own -Root); in the kit
# since 2026-10-24 for every host: "PLAY.exe keeper on" runs it every minute while that Windows user is logged on
# (play.py keeper). Windows PowerShell 5.1.
#   A kit's keeper acts only while this PC hosts: data\running.json holds a "server launcher" (PLAY.exe server) - it
#   notes that in <Root>\server.wanted, so a server that crashed or could not start again is still wanted; PLAY.exe
#   stop (by a person, not the keeper's own restart: WCCF_KEEPER) removes it. -Always: wanted all the time (Azure).
#   The server is UP when control_Release runs AND TCP 20002 listens: then it does nothing.
#   control_Release NOT RUNNING: it restarts the server at once - a control that crashed never comes back by itself
#   (2026-10-08 a crash cost 7 minutes while the old rule waited for a second check 5 minutes later).
#   control runs but TCP 20002 does not listen: it waits 3 minutes (a server that is starting listens within 90 s -
#   play.py's own limit) and restarts it if that lasts. In the first 10 minutes after the machine starts: at once.
#   Restarting = "play.py stop force" (leftover parts of the old server - a start refuses while any run), then the task
#   "WCCF 2010-11 server" where there is one (Azure), else "play.py server". At most one restart in 3 minutes: right
#   after one it waits, so a server that is still starting is never restarted again, and one that cannot start is
#   tried every 3 minutes, not every minute.
#   <Root>\keeper.pause younger than 20 minutes: it does nothing (the update scripts make it while they work; an
#   older one is a script that never finished, and is ignored). <Root> = the kit's data\keeper unless -Root says.
# Before every mid-life restart (not at boot) it copies the logs aside to <Root>\crash_evidence\<clock>_<why>, so
# every crash is kept without anyone awake (what az_read_crash.ps1 did by hand). It writes keeper_log.txt (a line per
# change, never per check), keeper_down_since.txt and keeper_restarted.txt (its last restart).
#   control runs, its port listens, but TWO of its threads keep a CPU busy: hung (2026-10-09). A healthy control has ONE
#   busy thread (its main loop polls); both hangs seen (2026-10-08 evening, 2026-10-09 morning) had two, and took no one
#   in. Counted over a 2 s sample; treated like a closed port - restarted if it lasts 3 minutes, evidence tagged "hung".
#   control runs its rounds but TAKES NO NEW PLAYER IN (2026-10-09: for 8 hours after its last ACCEPT the seat desk still
#   gave seats, every new player's game waited and showed Error 3000; one busy thread, so the check above missed it):
#   a seat the seat desk gave (seat_broker.txt) that was held 60 s or more, and 150 s later control has let NO ONE in
#   since ("++ACCEPT++" in its debug log, written line by line) = a player it does not take in -> evidence "noaccept"
#   and a restart at once. Measured on every saved run: players were let in 5-43 s after their seat, the projector box
#   within 90 s; in the stuck run all 9 seats from its first miss on got nothing. Not while a player it DID take in is
#   still connected (a session on) unless the miss is 20 minutes old. Not twice within an hour for the same addresses
#   (keeper_noaccept.txt): then it is that PC, not the server - one broken PC alone on the server never loops restarts.
#   Only a seat whose PC's game is KNOCKING counts: it has a link to the game port that control has not let in (a link
#   control never takes stays Established, then CloseWait once the game gives up - seen on Windows 2026-10-15). A seat
#   whose PC has no such link is that PC: its game is not trying (2026-10-15: a game left on Error 3000 for hours kept
#   its seat-desk link and took its seat again on every blink, and the old rule restarted control for it twice, at
#   10:34 and 12:28 UTC; it was not let in after the restart either). So a seat given again while that PC's game stays
#   in is no one waiting.
#   The projector box in kit\data\hold_projector.txt (2026-10-09): the seat desk keeps it off the game's port until a
#   player is in, so its seat is never counted as "not taken in"; and before every restart the keeper sets that hold
#   itself (firewall rule "WCCF hold projector box"), so a new run never starts with the box first.
#   -DryRun: say what it would do, write and start nothing.   -NoStop, and the names below: the tests only.
param([switch]$Boot, [switch]$DryRun, [switch]$NoStop, [switch]$Always, [string]$Root = '', [string]$Kit = '',
      [string]$ServerTask = 'WCCF 2010-11 server', [string]$ProcessName = 'control_Release', [int]$Port = 20002,
      [string]$ConnFile = '')

if (-not $Kit) { $Kit = Split-Path (Split-Path $PSScriptRoot) }      # code\server\ -> the kit's folder
if (-not $Root) { $Root = Join-Path $Kit 'data\keeper' }
$logPath = Join-Path $Root 'keeper_log.txt'
$markPath = Join-Path $Root 'keeper_down_since.txt'
$pausePath = Join-Path $Root 'keeper.pause'
$restartPath = Join-Path $Root 'keeper_restarted.txt'
$wantedPath = Join-Path $Root 'server.wanted'
$pyExe = Join-Path $Kit 'python\python.exe'
$playPy = Join-Path $Kit 'code\play.py'
$logsDir = Join-Path $Kit 'data\logs'
$runningPath = Join-Path $Kit 'data\running.json'
$evidenceDir = Join-Path $Root 'crash_evidence'
$listenWaitSec = 180        # control runs, its port does not listen: restart when that has lasted this long
$restartGapSec = 180        # at most one restart in this many seconds
$noAcceptPath = Join-Path $Root 'keeper_noaccept.txt'  # the addresses of its last "takes no one in" restart
$acceptWaitSec = 150        # a seat this old with no one let in since: control takes no one in
$seatHeldSec = 60           # ... counted only when the PC held that seat this long (or still holds it)
$playerWaitMax = 1200       # ... but a session of a player it did take in is waited for this long first

function Write-Note([string]$msg) {
    if ($DryRun) { return ('dry run: ' + $msg) }
    Add-Content -LiteralPath $logPath -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $msg) -Encoding UTF8
}
function Save-Evidence([string]$tag) {
    # copy the current logs (with logs\previous) aside BEFORE the restart rotates or overwrites them, so every crash is
    # kept without anyone awake.  Named by the clock + why.  Never throws: evidence is a bonus, the restart must go on.
    try {
        if (-not (Test-Path -LiteralPath $logsDir)) { return 'no logs folder to save' }
        $dst = Join-Path $evidenceDir ((Get-Date -Format 'yyyy-MM-dd_HHmmss') + '_' + $tag)
        New-Item -ItemType Directory -Force -Path $dst -ErrorAction Stop | Out-Null
        Copy-Item -Path (Join-Path $logsDir '*') -Destination $dst -Recurse -Force -ErrorAction Stop
        return ('saved ' + @(Get-ChildItem -LiteralPath $dst -Recurse -File).Count + ' log files to ' + (Split-Path $dst -Leaf))
    } catch {
        return ('could not save evidence: ' + $_.Exception.Message.Trim())
    }
}
function Get-BusyThreads([string]$name, [int]$sampleSec = 2) {
    # how many of the process's threads used at least 3/4 of a CPU over the sample (0 when it is not running)
    $p = Get-Process -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $p) { return 0 }
    $before = @{}
    foreach ($t in $p.Threads) { $before[$t.Id] = $t.TotalProcessorTime.TotalSeconds }
    Start-Sleep -Seconds $sampleSec
    $p.Refresh()
    return @($p.Threads | Where-Object { $before.ContainsKey($_.Id) -and
        ($_.TotalProcessorTime.TotalSeconds - $before[$_.Id]) -ge 0.75 * $sampleSec }).Count
}
function Get-GameConns {
    # the game port's links as "State ip:port", every state but Listen and Bound (the tests: a scratch file of such lines)
    if ($ConnFile) {
        if (-not (Test-Path -LiteralPath $ConnFile)) { return @() }
        return @(Get-Content -LiteralPath $ConnFile | Where-Object { $_ -match '^[A-Za-z]+ \d+\.\d+\.\d+\.\d+:\d+$' })
    }
    return @(Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -ne 'Listen' -and
        $_.State -ne 'Bound' } | ForEach-Object { [string]$_.State + ' ' + $_.RemoteAddress + ':' + $_.RemotePort })
}
function Get-NotTakenIn {
    # @{ ips = addresses given a seat that control has not let in, with no one let in since (sorted, none = all fine);
    # oldest = seconds since the first of those seats; players = players it let in still connected (not the projector) }
    # - or $null when it cannot tell (no logs of this run).  Read-only.
    $dbg = Join-Path $logsDir '_dbg_control.txt'
    $seatLog = Join-Path $logsDir 'seat_broker.txt'
    $ctl = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $ctl -or -not (Test-Path -LiteralPath $dbg) -or -not (Test-Path -LiteralPath $seatLog)) { return $null }
    if ((Get-Item -LiteralPath $dbg).LastWriteTime -lt $ctl.StartTime) { return $null }     # not this run's log
    $sate = @{}; $last = -1; $lastAccept = [datetime]::MinValue
    foreach ($line in (Get-Content -LiteralPath $dbg)) {          # Get-Content: the log stays open for writing
        if ($line -match 'client\[\d+\]\s*:\s*sateID=(\d+)') { $last = [int]$Matches[1] }
        elseif ($line -match "\+\+ACCEPT\+\+\s+'([0-9.]+:\d+)', (\d+)/(\d+)/(\d+)\(\w+\) (\d+):(\d+):(\d+)") {
            $sate[$Matches[1]] = $last
            $t = New-Object DateTime ([int]$Matches[2]), ([int]$Matches[3]), ([int]$Matches[4]), ([int]$Matches[5]),
                ([int]$Matches[6]), ([int]$Matches[7])
            if ($t -gt $lastAccept) { $lastAccept = $t }
        }
    }
    $grants = @{}; $held = New-Object System.Collections.Generic.List[object]    # seat -> its grant; seats held long enough
    $now = Get-Date; $inv = [Globalization.CultureInfo]::InvariantCulture
    $box = Get-HoldIp
    foreach ($line in (Get-Content -LiteralPath $seatLog)) {
        if ($line -match '^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) ([0-9.]+):\d+: seat (\d+)(?: \+ the projector)? - taken') {
            if ($box -and $Matches[2] -eq $box) { continue }      # the projector box waits for a player on purpose
            $grants[$Matches[3]] = [pscustomobject]@{ ip = $Matches[2]; at = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $inv) }
        } elseif ($line -match '^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) [0-9.]+:\d+: seat (\d+) free again' -and $grants.ContainsKey($Matches[2])) {
            $g = $grants[$Matches[2]]; $grants.Remove($Matches[2])
            if (([datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $inv) - $g.at).TotalSeconds -ge $seatHeldSec) { $held.Add($g) }
        }
    }
    foreach ($g in $grants.Values) { if (($now - $g.at).TotalSeconds -ge $seatHeldSec) { $held.Add($g) } }
    # only a PC whose game is knocking counts: it has a link to the game port that control has not let in (header). A
    # seat given again while that PC's game stays in has only let-in links; a PC whose game is not trying has none.
    # TimeWait is not knocking: the run before a restart leaves its links in it for minutes.
    # ponytail: a control that closed new links before logging ++ACCEPT++ would leave only TimeWait - never seen; if it
    # ever is, count TimeWait links younger than control's start (Get-NetTCPConnection's CreationTime).
    $game = @(Get-GameConns)
    $knock = @{}
    foreach ($c in $game) {
        $st, $ep = $c -split ' '
        if ($st -ne 'TimeWait' -and -not $sate.ContainsKey($ep)) { $knock[($ep -split ':')[0]] = $true }
    }
    $misses = @($held | Where-Object { ($lastAccept -lt $_.at) -and (($now - $_.at).TotalSeconds -ge $acceptWaitSec) -and
        $knock[$_.ip] })
    $players = @($game | Where-Object { $st, $ep = $_ -split ' '; $st -eq 'Established' -and $sate.ContainsKey($ep) -and
        $sate[$ep] -ne 0 }).Count
    $oldest = 0
    foreach ($m in $misses) { $oldest = [Math]::Max($oldest, ($now - $m.at).TotalSeconds) }
    return @{ ips = @($misses | ForEach-Object { $_.ip } | Sort-Object -Unique); oldest = $oldest; players = $players }
}
function Get-HoldIp {
    # the projector box the seat desk holds until a player is in (kit\data\hold_projector.txt, _seat_broker.py), or ''
    $p = Join-Path (Split-Path $logsDir) 'hold_projector.txt'
    if (-not (Test-Path -LiteralPath $p)) { return '' }
    $w = @((Get-Content -LiteralPath $p -Raw) -split '\s+' | Where-Object { $_ })
    if ($w.Count -and $w[0] -match '^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$' -and
        @($Matches[1..4] | Where-Object { [int]$_ -gt 255 }).Count -eq 0) { return $w[0] }
    return ''
}
function Set-HoldRule([string]$ip) {
    # before a restart: the projector box kept off the game's port, so the new run cannot start with it (the desk
    # lifts it once a player is in); the rule's name is the desk's
    $netsh = Join-Path $env:SystemRoot 'System32\netsh.exe'
    & $netsh advfirewall firewall delete rule name='WCCF hold projector box' 2>&1 | Out-Null
    & $netsh advfirewall firewall add rule name='WCCF hold projector box' dir=in action=block protocol=TCP localport=20002 `
        remoteip=$ip 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}
function Test-Hosting {
    # this kit runs a server now: running.json (play.py write_running) names a "server launcher" among its programs
    try {
        $run = Get-Content -LiteralPath $runningPath -Raw -ErrorAction Stop | ConvertFrom-Json
        return @($run.processes.PSObject.Properties | Where-Object { $_.Value -eq 'server launcher' }).Count -gt 0
    } catch { return $false }
}
function Get-AgeSeconds([string]$path) {         # how old a file is; a missing one counts as endlessly old
    if (-not (Test-Path -LiteralPath $path)) { return [double]::MaxValue }
    return ((Get-Date) - (Get-Item -LiteralPath $path).LastWriteTime).TotalSeconds
}

if (-not (Test-Path -LiteralPath $Root)) { exit 1 }

if (Test-Path -LiteralPath $pausePath) {
    $ageMin = [int]((Get-Date) - (Get-Item -LiteralPath $pausePath).LastWriteTime).TotalMinutes
    if ($ageMin -lt 20) {
        if ($DryRun) { 'paused: keeper.pause is ' + $ageMin + ' min old' }
        exit 0
    }
    Write-Note ('keeper.pause is ' + $ageMin + ' min old - ignored (an update that never finished?)')
}

if (-not $Always) {                              # a kit's keeper: only while this PC hosts (the header)
    if ((Test-Hosting) -and -not (Test-Path -LiteralPath $wantedPath) -and -not $DryRun) {
        Set-Content -LiteralPath $wantedPath -Value (Get-Date -Format 'o')
    }
    if (-not ((Test-Path -LiteralPath $wantedPath) -or ($DryRun -and (Test-Hosting)))) {
        if ($DryRun) { 'not hosting: no server started with PLAY.exe server here - nothing to keep' }
        exit 0
    }
}

$procUp = [bool](Get-Process -Name $ProcessName -ErrorAction SilentlyContinue)
$portUp = [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
$busy = if ($procUp -and $portUp) { Get-BusyThreads $ProcessName } else { 0 }
$hung = $busy -ge 2
$miss = if ($procUp -and $portUp -and -not $hung) { Get-NotTakenIn } else { $null }
$deaf = [bool]($miss -and $miss.ips.Count)
if ($procUp -and $portUp -and -not $hung -and -not $deaf) {
    if (Test-Path -LiteralPath $markPath) {
        if (-not $DryRun) { Remove-Item -LiteralPath $markPath -Force -ErrorAction SilentlyContinue }
        Write-Note 'server up again - nothing done'
    }
    if ($DryRun) { 'server up (' + $ProcessName + ' runs, TCP ' + $Port + ' listens) - nothing to do' }
    exit 0
}

$why = 'server down (' + $ProcessName + ': ' + $(if ($procUp) { 'runs' } else { 'not running' }) + ', TCP ' + $Port +
       ': ' + $(if ($portUp) { 'listens' } else { 'not listening' }) + $(if ($hung) { ', ' + $busy + ' threads busy: hung' }
       else { '' }) + ')'
if ($deaf) {
    $why = 'control takes no one in (seat given to ' + ($miss.ips -join ', ') + ', nobody let in for ' +
           [int]($miss.oldest / 60) + ' min)'
    $hold = ''
    $lastIps = if ((Get-AgeSeconds $noAcceptPath) -lt 3600) { @(Get-Content -LiteralPath $noAcceptPath) } else { @() }
    if ($miss.players -gt 0 -and $miss.oldest -lt $playerWaitMax) {
        $hold = ' - ' + $miss.players + ' player(s) still in a session: waiting for them, at most ' + [int]($playerWaitMax / 60) + ' min'
    } elseif ($lastIps.Count -and -not @($miss.ips | Where-Object { $lastIps -notcontains $_ }).Count) {
        $hold = ' - the same address(es) as its last such restart, under an hour ago: that PC, not the server - not restarting'
    }
    if ($hold) {
        if (-not (Test-Path -LiteralPath $markPath)) {
            if (-not $DryRun) { Set-Content -LiteralPath $markPath -Value (Get-Date -Format 'o') }
            Write-Note ($why + $hold)
        }
        if ($DryRun) { 'waiting: ' + $why + $hold }
        exit 0
    }
}
$sinceRestart = Get-AgeSeconds $restartPath
if ($sinceRestart -lt $restartGapSec) {          # it restarted the server a moment ago: that start gets its time
    if (-not (Test-Path -LiteralPath $markPath)) {
        if (-not $DryRun) { Set-Content -LiteralPath $markPath -Value (Get-Date -Format 'o') }
        Write-Note ($why + ' ' + [int]$sinceRestart + ' s after the keeper restarted it - waiting (at most one restart in ' +
                    [int]($restartGapSec / 60) + ' min)')
    }
    if ($DryRun) { 'waiting: ' + $why + ', ' + [int]$sinceRestart + ' s after the last restart' }
    exit 0
}
$upMin = 999
try { $upMin = ((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalMinutes } catch { }
if ($Boot -or ($upMin -lt 10)) {
    $reason = ' at start-up'
} elseif (-not $procUp) {
    $reason = ' - ' + $ProcessName + ' is gone (it never comes back by itself)'
} elseif ($deaf) {
    $reason = ''                                 # its 150 s wait is behind it already: at once
} else {
    $markAge = Get-AgeSeconds $markPath
    if ($markAge -eq [double]::MaxValue) {
        if (-not $DryRun) { Set-Content -LiteralPath $markPath -Value (Get-Date -Format 'o') }
        Write-Note ($why + ' - restarting it if that lasts ' + [int]($listenWaitSec / 60) + ' min')
        exit 0
    }
    if ($markAge -lt $listenWaitSec) {
        if ($DryRun) { 'waiting: ' + $why + ' for ' + [int]$markAge + ' s of ' + $listenWaitSec }
        exit 0
    }
    $reason = ' for ' + [int]($markAge / 60) + ' min'
}
if ($DryRun) { 'would restart now: ' + $why + $reason; exit 0 }

Write-Note ($why + $reason + ' - restarting')
if ($reason -ne ' at start-up') {               # a real mid-life failure: keep its logs before the restart rotates them
    $tag = if (-not $procUp) { 'control_gone' } elseif ($hung) { 'hung' } elseif ($deaf) { 'noaccept' } else { 'port_closed' }
    Write-Note ('  ' + (Save-Evidence $tag))
}
if ($deaf) { Set-Content -LiteralPath $noAcceptPath -Value $miss.ips }
$box = Get-HoldIp
if ($box) {
    if ($NoStop) { Write-Note ('  would hold the projector box ' + $box + ' (tests: no firewall change)') }
    elseif (Set-HoldRule $box) { Write-Note ('  projector box ' + $box + ' held until a player is in') }
    else { Write-Note ('  projector box ' + $box + ': the hold rule could not be set') }
}
$env:WCCF_KEEPER = '1'                           # play.py: this stop is the keeper's, the server is still wanted
if (-not $NoStop) {
    & $pyExe $playPy stop force 2>&1 | ForEach-Object { Write-Note ('  stop: ' + $_) }
}
if (Get-ScheduledTask -TaskName $ServerTask -ErrorAction SilentlyContinue) {     # Azure: the server runs as its task
    Stop-ScheduledTask -TaskName $ServerTask -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    try {
        Start-ScheduledTask -TaskName $ServerTask -ErrorAction Stop
        Write-Note ('  started the task "' + $ServerTask + '"')
    } catch {
        Write-Note ('  could not start the task "' + $ServerTask + '": ' + $_.Exception.Message.Trim())
    }
} elseif (-not (Test-Path -LiteralPath $pyExe)) {
    Write-Note ('  could not start the server: no ' + $pyExe)
} else {                                         # a kit: PLAY.exe server, as the host started it
    Start-Sleep -Seconds 3
    & $pyExe $playPy server 2>&1 | ForEach-Object { Write-Note ('  start: ' + $_) }
    Write-Note ('  play.py server ended ' + $LASTEXITCODE)
}
Set-Content -LiteralPath $restartPath -Value (Get-Date -Format 'o')
Remove-Item -LiteralPath $markPath -Force -ErrorAction SilentlyContinue
exit 0
