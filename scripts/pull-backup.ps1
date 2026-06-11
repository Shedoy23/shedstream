# pull-backup.ps1 -- offsite DB backup: this PC pulls the latest prod backup.
# ROADMAP 1.1 (2026-06-11). Runs from a Windows Scheduled Task
# ('shedstream-db-backup-pull', daily 13:00, StartWhenAvailable -> catches up
# when the PC was off).
#
# This file in the repo is the source-of-truth copy. The LIVE copy runs from
#   %USERPROFILE%\shedstream-backups\pull-backup.ps1
# (a stable path, NOT a temporary git worktree). If you edit this, re-copy it
# there:  Copy-Item scripts\pull-backup.ps1 $env:USERPROFILE\shedstream-backups\
#
# To (re)register the scheduled task after a fresh checkout:
#   $s = "$env:USERPROFILE\shedstream-backups\pull-backup.ps1"
#   $a = New-ScheduledTaskAction -Execute powershell.exe -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $s)
#   $t = New-ScheduledTaskTrigger -Daily -At '13:00'
#   $g = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
#   Register-ScheduledTask -TaskName 'shedstream-db-backup-pull' -Action $a -Trigger $t -Settings $g -Force
#
# ASCII-only on purpose (PS 5.1 reads BOM-less .ps1 as cp1251).

$ErrorActionPreference = 'Stop'

$ProdHost  = 'root@31.130.132.224'
$RemoteDir = '/root/twitch-extension/backups'
$LocalDir  = Join-Path $env:USERPROFILE 'shedstream-backups'
$Keep      = 14
$LogFile   = Join-Path $LocalDir 'pull-backup.log'

function Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

try {
    # Find the newest consistent daily backup on prod (.zst from backup_db.sh).
    $latest = (ssh $ProdHost "ls -t $RemoteDir/viewers.daily.*.db.zst 2>/dev/null | head -1")
    if ($latest) { $latest = $latest.Trim() }
    if (-not $latest) { Log "ERROR: no remote daily backup found in $RemoteDir"; exit 1 }

    $fname = Split-Path $latest -Leaf
    $dest  = Join-Path $LocalDir $fname

    if (Test-Path $dest) {
        Log "ok (already have) $fname"
    } else {
        & scp "${ProdHost}:${latest}" $dest
        if (-not (Test-Path $dest)) { Log "ERROR: scp produced no file for $fname"; exit 1 }
        $size = (Get-Item $dest).Length
        if ($size -lt 1024) { Remove-Item $dest -Force; Log "ERROR: scp file too small ($size b), deleted"; exit 1 }
        Log ("ok pulled {0} ({1:N0} bytes)" -f $fname, $size)
    }

    # Rotation: keep the newest $Keep, delete older.
    $old = Get-ChildItem $LocalDir -Filter 'viewers.daily.*.db.zst' |
           Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep
    foreach ($f in $old) { Remove-Item $f.FullName -Force; Log "rotated out $($f.Name)" }

    $count = (Get-ChildItem $LocalDir -Filter 'viewers.daily.*.db.zst' | Measure-Object).Count
    Log "done: $count local backups in $LocalDir"
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    exit 1
}
