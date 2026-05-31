<#
.SYNOPSIS
  Triage the latest Bannerlord crash: faulting managed exception + stack + mod-log context.

.DESCRIPTION
  Automates the manual dump dive: finds the newest crash folder, summarizes
  crash_tags (modules / integrity / runtime), then uses dotnet-dump to pull the
  faulting thread's managed exception object (type + message + stack trace), and
  finally tails the BannerlordLink mod log + greps it for swallowed/unhandled
  exceptions. Turns a ~20-min manual dive into one command.

  Requires dotnet-dump:  dotnet tool install -g dotnet-dump

  ASCII-only on purpose (PS 5.1 reads BOM-less .ps1 as ANSI).

.PARAMETER Folder
  Specific crash folder. Default = newest under %ProgramData%\...\crashes.

.PARAMETER SkipDump
  Skip the (slow, ~1-2 min) dotnet-dump analysis; only show tags + mod log.

.EXAMPLE
  ./scripts/triage-crash.ps1
  ./scripts/triage-crash.ps1 -SkipDump
#>
[CmdletBinding()]
param(
    [string]$Folder,
    [switch]$SkipDump
)
$ErrorActionPreference = 'Stop'

$CrashRoot = Join-Path $env:ProgramData 'Mount and Blade II Bannerlord\crashes'
$ModLogDir = Join-Path $env:USERPROFILE 'Documents\Mount and Blade II Bannerlord\Configs\ModLogs'
$DotnetDump = Join-Path $env:USERPROFILE '.dotnet\tools\dotnet-dump.exe'

function Section($t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }

# ── 1. Locate crash folder ────────────────────────────────────────────────
if (-not $Folder) {
    if (-not (Test-Path $CrashRoot)) { throw "No crashes dir: $CrashRoot" }
    $Folder = (Get-ChildItem $CrashRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
if (-not $Folder) { throw "No crash folders found under $CrashRoot" }
Write-Host "Crash folder: $Folder" -ForegroundColor Green

# ── 2. crash_tags summary ─────────────────────────────────────────────────
$tags = Join-Path $Folder 'crash_tags.txt'
if (Test-Path $tags) {
    Section "crash_tags (runtime / integrity)"
    Select-String -Path $tags -Pattern 'Game Integrity|New Game Version|App Run Time|Build Version' |
        ForEach-Object { Write-Host "  $($_.Line.Trim())" }
    Section "active modules"
    $mods = Select-String -Path $tags -Pattern 'Has Installed Unofficial Modules' | Select-Object -First 1
    if ($mods) { Write-Host "  $($mods.Line -replace '.*\]\[','' )" }
}

# ── 3. dotnet-dump: faulting managed exception ────────────────────────────
$dump = Join-Path $Folder 'dump.dmp'
if (-not $SkipDump -and (Test-Path $dump)) {
    if (-not (Test-Path $DotnetDump)) {
        Write-Host "`n[!] dotnet-dump not found ($DotnetDump). Install: dotnet tool install -g dotnet-dump" -ForegroundColor Yellow
    } else {
        Section "managed threads (finding faulting thread) - this loads the dump, ~1-2 min"
        $threads = & $DotnetDump analyze $dump -c "clrthreads" -c "exit" 2>&1
        # Faulting thread row ends with: <ExceptionType> <objaddr>
        $exMatch = $threads | Select-String -Pattern '(System\.\w+(?:Exception|Error))\s+([0-9a-fA-F]{6,})\s*$' |
            Select-Object -First 1
        if ($exMatch) {
            $exType = $exMatch.Matches[0].Groups[1].Value
            $exAddr = $exMatch.Matches[0].Groups[2].Value
            Write-Host "  Faulting exception: $exType @ $exAddr" -ForegroundColor Yellow
            Section "exception object + managed stack trace"
            $pe = & $DotnetDump analyze $dump -c "printexception $exAddr" -c "exit" 2>&1
            $pe | Where-Object { $_ -notmatch '^(Loading core dump|Ready to process)' } |
                ForEach-Object { Write-Host "  $_" }
        } else {
            Write-Host "  No managed exception found on any thread (likely a pure native crash)." -ForegroundColor Yellow
            Write-Host "  Open dump.dmp in WinDbg ('!analyze -v') for the native faulting module." -ForegroundColor DarkGray
        }
    }
} elseif ($SkipDump) {
    Write-Host "`n(-SkipDump: dump analysis skipped)" -ForegroundColor DarkGray
}

# ── 4. Mod log context ────────────────────────────────────────────────────
if (Test-Path $ModLogDir) {
    $modLog = Get-ChildItem (Join-Path $ModLogDir 'bannerlordlink_*.txt') -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($modLog) {
        Section "mod log: recent swallowed/unhandled exceptions ($($modLog.Name))"
        Select-String -Path $modLog.FullName -Pattern 'SWALLOWED|CRASHED|Unhandled|NullReference|InvalidCast' |
            Select-Object -Last 10 | ForEach-Object { Write-Host "  $($_.Line.Trim())" }
        Section "mod log: last 15 lines"
        Get-Content $modLog.FullName -Tail 15 -Encoding UTF8 | ForEach-Object { Write-Host "  $_" }
    }
}

Write-Host "`n[ok] Triage done." -ForegroundColor Green
