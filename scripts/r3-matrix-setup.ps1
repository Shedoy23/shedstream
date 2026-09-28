# r3-matrix-setup.ps1 -- arm and disarm the conditions of the R3 verification
# matrix so the run costs clicks instead of an evening of preparation.
#
# WHY. The matrix in ROADMAP R3 is the only open front before the Twitch
# verdict, and it is blocked on the owner's time, which is the scarcest resource
# in this project. Every condition this script creates is one he does not have
# to build by hand.
#
# WHAT IT NEVER TOUCHES. Real game folders. Every fake instance is created under
# a sandbox directory and removed by -Disarm. The script refuses to operate on a
# path that contains a real game.
#
# ASCII-only on purpose: a .ps1 without BOM is read as ANSI on this machine and
# Cyrillic in the source breaks parsing (see the global CLAUDE.md).
#
# USAGE
#   pwsh -File scripts/r3-matrix-setup.ps1 -Arm 3      # nonstandard path
#   pwsh -File scripts/r3-matrix-setup.ps1 -Arm 4      # game not found
#   pwsh -File scripts/r3-matrix-setup.ps1 -Arm 5      # denied write
#   pwsh -File scripts/r3-matrix-setup.ps1 -Arm 9      # incompatible version
#   pwsh -File scripts/r3-matrix-setup.ps1 -Arm all
#   pwsh -File scripts/r3-matrix-setup.ps1 -Disarm     # remove everything
#   pwsh -File scripts/r3-matrix-setup.ps1 -Status
#
# Rows 1, 2, 6, 7, 10 need no folders -- the script prints what to do for them.
param(
    [string]$Arm = '',
    [switch]$Disarm,
    [switch]$Status,
    [string]$Sandbox = "$env:LOCALAPPDATA\ShedLink\r3-matrix"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Info($m) { Write-Host "-> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ok] $m" -ForegroundColor Green }
function Note($m) { Write-Host "     $m" -ForegroundColor DarkGray }
function Warn($m) { Write-Host "[!] $m" -ForegroundColor Yellow }

# A Minecraft instance is anything with a mods folder; the MineColonies jar name
# carries the game version. That is exactly what the Manager looks for, so a
# folder built this way is indistinguishable from a real instance to it -- and
# contains no game.
function New-FakeInstance {
    param([string]$Path, [string]$MineColoniesJar)
    New-Item -ItemType Directory -Force -Path (Join-Path $Path 'mods') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $Path 'config') | Out-Null
    if ($MineColoniesJar) {
        Set-Content -Path (Join-Path $Path "mods\$MineColoniesJar") -Value 'not a real jar' -Encoding ascii
    }
    Set-Content -Path (Join-Path $Path 'mods\structurize-1.0.830-1.21.1.jar') -Value 'not a real jar' -Encoding ascii
}

function Reset-SandboxAcl {
    # icacls /T обходит ВСЕ вложенные папки и файлы, /C не останавливается на
    # первой ошибке. .NET-вариант в первой редакции смотрел только верхний
    # уровень и потому не видел запрет на mods\.
    if (Test-Path $Sandbox) {
        Assert-Sandboxed $Sandbox
        & icacls "$Sandbox" /reset /T /C /Q 2>&1 | Out-Null
    }
}

function Assert-Sandboxed([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith([IO.Path]::GetFullPath($Sandbox), [StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing to touch $full -- outside the sandbox $Sandbox"
    }
}

$rows = @{
    '3' = @{
        Name = 'nonstandard installation path'
        Dir  = Join-Path $Sandbox 'row3 nonstandard path (probel i kirillica)'
        Jar  = 'minecolonies-1.1.1320-1.21.1-snapshot.jar'
        Say  = 'Point the Manager at this folder. Expected: accepted, version 1.21.1.'
    }
    '4' = @{
        Name = 'game not found'
        Dir  = Join-Path $Sandbox 'row4 not a game at all'
        Jar  = ''      # no mods jar and, below, no mods folder either
        Say  = 'Point the Manager at this folder. Expected: refusal naming mods AND a hint which folder to pick.'
    }
    '5' = @{
        Name = 'denied write'
        Dir  = Join-Path $Sandbox 'row5 denied write'
        Jar  = 'minecolonies-1.1.1320-1.21.1-snapshot.jar'
        Say  = 'Install into this folder. Expected: "Windows ne dal zapisat..." with a next step, NOT a silent close.'
    }
    '9' = @{
        Name = 'incompatible game version'
        Dir  = Join-Path $Sandbox 'row9 wrong minecraft version'
        Jar  = 'minecolonies-1.1.500-1.20.1.jar'
        Say  = 'Point the Manager at this folder. Expected: version not supported, install not offered.'
    }
}

if ($Status) {
    Info "sandbox: $Sandbox"
    if (-not (Test-Path $Sandbox)) { Note 'nothing armed'; exit 0 }
    Get-ChildItem $Sandbox -Directory | ForEach-Object { Note $_.Name }
    exit 0
}

if ($Disarm) {
    if (-not (Test-Path $Sandbox)) { Ok 'nothing to remove'; exit 0 }
    Assert-Sandboxed $Sandbox
    # Row 5 leaves a deny rule -- strip it first or Remove-Item cannot delete.
    # It sits on the mods SUBfolder, so walking only the top level missed it and
    # -Disarm failed on its own sandbox (found 2026-08-24, the script was a
    # one-shot: after the first arm it could neither clean up nor re-arm).
    Reset-SandboxAcl
    Remove-Item $Sandbox -Recurse -Force
    Ok "removed $Sandbox"
    exit 0
}

Reset-SandboxAcl   # повторный -Arm не должен спотыкаться о прошлый прогон

if (-not $Arm) {
    Write-Host ''
    Write-Host '  R3 matrix -- what this script arms and what you do by hand' -ForegroundColor White
    Write-Host ''
    Write-Host '  armed by script:  3 (nonstandard path), 4 (game not found),'
    Write-Host '                    5 (denied write), 9 (incompatible version)'
    Write-Host ''
    Write-Host '  by hand:'
    Write-Host '    1  second Windows account -- app must not remember anything'
    Write-Host '    2  point at a real game folder installed by its launcher'
    Write-Host '    6  start an install, kill ShedLink.Manager.App in Task Manager,'
    Write-Host '       start it again -- expected: "nezavershennaya ustanovka vosstanovlena"'
    Write-Host '    7  backend unreachable: add to hosts (needs admin, revert after)'
    Write-Host '         127.0.0.1 shedoy23.ru'
    Write-Host '       expected: "Ne udalos svyazatsya s ShedLink backend", not a hang'
    Write-Host '    10 update rollback: ask me to build a corrupted update package'
    Write-Host ''
    Write-Host '  expected texts for every row: docs/R3_MATRIX_RUNBOOK.md'
    Write-Host ''
    exit 0
}

$targets = if ($Arm -eq 'all') { $rows.Keys | Sort-Object } else { @($Arm) }
foreach ($key in $targets) {
    if (-not $rows.ContainsKey($key)) { Warn "unknown row: $key"; continue }
    $row = $rows[$key]
    Assert-Sandboxed $row.Dir
    if (Test-Path $row.Dir) { Remove-Item $row.Dir -Recurse -Force -ErrorAction SilentlyContinue }

    if ($key -eq '4') {
        # Deliberately NOT a game: no mods folder at all.
        New-Item -ItemType Directory -Force -Path $row.Dir | Out-Null
        Set-Content -Path (Join-Path $row.Dir 'readme.txt') -Value 'no game here' -Encoding ascii
    } else {
        New-FakeInstance -Path $row.Dir -MineColoniesJar $row.Jar
    }

    if ($key -eq '9') {
        # Structurize carries 1.21.1 in its own name. The detector only globs
        # minecolonies-*.jar so it is never read -- but a human opening this
        # folder should not have to know that. Remove it: the folder must say
        # one thing only, "MineColonies for 1.20.1".
        Remove-Item (Join-Path $row.Dir 'mods\structurize-1.0.830-1.21.1.jar') -Force
    }

    if ($key -eq '5') {
        # Deny write to the mods folder for the current user. This is what the
        # real case looks like: the folder exists, is visible, and refuses.
        $mods = Join-Path $row.Dir 'mods'
        $acl = Get-Acl $mods
        $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $deny = New-Object Security.AccessControl.FileSystemAccessRule(
            $me, 'Write,CreateFiles', 'ContainerInherit,ObjectInherit', 'None', 'Deny')
        $acl.AddAccessRule($deny)
        Set-Acl $mods $acl
        Note 'write access denied for the current user on the mods folder'
    }

    Ok "row $key armed -- $($row.Name)"
    Note $row.Dir
    Note $row.Say
    Write-Host ''
}

Warn 'when finished: pwsh -File scripts/r3-matrix-setup.ps1 -Disarm'
