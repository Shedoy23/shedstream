<#
.SYNOPSIS
  One-command deploy for the AfterLait / shedstream project.

.DESCRIPTION
  Replaces the manual tar -> scp -> ssh extract -> restart dance.
  - Frontend deploy auto-bumps the viewer.js?v= cache-bust SYNCHRONOUSLY in
    extension.html AND mobile.html (no more hand-editing / desync).
  - Backend/frontend are tarred WHOLE (with excludes) so you can never "forget
    a file". Excludes *.db / .env / __pycache__ so prod data is never clobbered.
  - Mod deploy builds Release and copies the DLL+pdb into the game Modules
    folder with an md5 verify.
  - After a backend/frontend push it restarts the service and verifies health
    (RUNNING + no fresh Traceback in stderr).

  ASCII-only on purpose: PowerShell 5.1 reads BOM-less .ps1 as ANSI, so
  non-ASCII text would corrupt. Keep it that way.

.EXAMPLE
  ./scripts/deploy.ps1                 # backend + frontend (the common case)
  ./scripts/deploy.ps1 -All            # mod + backend + frontend
  ./scripts/deploy.ps1 -Mod            # build + copy mod DLL into the game only
  ./scripts/deploy.ps1 -Backend        # backend only
  ./scripts/deploy.ps1 -DryRun         # print actions, change nothing
#>
[CmdletBinding()]
param(
    [switch]$Backend,
    [switch]$Frontend,
    [switch]$Mod,
    [switch]$All,
    [switch]$NoRestart,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# -- Config ----------------------------------------------------------------
$ProdHost = 'root@31.130.132.224'
$ProdDir  = '/root/twitch-extension'
$Service  = 'twitchbot'
$GamePath = 'X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord'
$ModId    = 'Shedoy23.BannerlordLink'

# -- Resolve paths ---------------------------------------------------------
$RepoRoot = Split-Path -Parent $PSScriptRoot
# Find the extension dir (the one containing backend/) without hardcoding the
# Cyrillic folder name (avoids PS 5.1 script-encoding pitfalls).
$ExtDir = Get-ChildItem -LiteralPath $RepoRoot -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'backend') } |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $ExtDir) { throw "Could not find extension dir (with backend/) under $RepoRoot" }
$ModSrc = Join-Path $RepoRoot 'BannerlordLink\src\BannerlordLink.csproj'

# Default: backend + frontend if nothing specified.
if (-not ($Backend -or $Frontend -or $Mod -or $All)) { $Backend = $true; $Frontend = $true }
if ($All) { $Backend = $true; $Frontend = $true; $Mod = $true }

function Info($m){ Write-Host "-> $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[ok] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }

# -- 1. Mod: build + copy DLL into game ------------------------------------
if ($Mod) {
    Info "Building mod (Release)..."
    if (-not $DryRun) {
        & dotnet build $ModSrc -c Release -v minimal
        if ($LASTEXITCODE -ne 0) { throw "dotnet build failed (exit $LASTEXITCODE)" }
    }
    $srcBin = Join-Path $RepoRoot 'BannerlordLink\bin\Win64_Shipping_Client'
    $dstBin = Join-Path $GamePath "Modules\$ModId\bin\Win64_Shipping_Client"
    foreach ($f in 'BannerlordLink.dll','BannerlordLink.pdb') {
        $s = Join-Path $srcBin $f; $d = Join-Path $dstBin $f
        if ($DryRun) { Write-Host "  [dry] copy $f -> game" -ForegroundColor DarkGray; continue }
        if (-not (Test-Path $s)) { throw "missing built $f in $srcBin" }
        Copy-Item -LiteralPath $s -Destination $d -Force
    }
    if (-not $DryRun) {
        $h1 = (Get-FileHash (Join-Path $srcBin 'BannerlordLink.dll') -Algorithm MD5).Hash
        $h2 = (Get-FileHash (Join-Path $dstBin 'BannerlordLink.dll') -Algorithm MD5).Hash
        if ($h1 -ne $h2) { throw "DLL md5 mismatch after copy!" }
        Ok "Mod DLL copied into game (md5 $($h1.Substring(0,8))...). Restart Bannerlord to load it."
    }
}

# -- 2. Frontend cache-bust (sync both html) -------------------------------
if ($Frontend) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmm')
    $utf8  = New-Object System.Text.UTF8Encoding($false)   # no BOM
    foreach ($html in 'extension.html','mobile.html') {
        $p = Join-Path $ExtDir "frontend\$html"
        if (-not (Test-Path $p)) { Warn "no $html - skip cache-bust"; continue }
        if ($DryRun) { Write-Host "  [dry] cache-bust $html -> v=$stamp" -ForegroundColor DarkGray; continue }
        $txt = [IO.File]::ReadAllText($p, $utf8)
        $new = [regex]::Replace($txt, 'viewer\.js\?v=[^"'']+', "viewer.js?v=$stamp")
        [IO.File]::WriteAllText($p, $new, $utf8)
    }
    Ok "Cache-bust viewer.js?v=$stamp (extension.html + mobile.html)"
}

# -- 2.5 Test gate (ROADMAP 1.2): critical tenant/security invariants MUST pass
#        before a backend push. Red = deploy aborts. Game/feature tests are NOT
#        gating (run them manually via the same script without --critical).
if ($Backend) {
    Info "Test gate: critical tenant/security tests (--critical)..."
    Push-Location (Join-Path $ExtDir 'backend')
    try { & python tests/test_multi_tenant_isolation.py --critical; $gateRc = $LASTEXITCODE }
    finally { Pop-Location }
    if ($gateRc -ne 0) {
        throw "CRITICAL tests FAILED (exit $gateRc) - deploy ABORTED. Fix the tenant/security regression first."
    }
    Ok "Critical tests green - safe to deploy"
}

# -- 3. Backend/Frontend: tar -> scp -> extract -> restart -> verify -------
$paths = @()
if ($Backend)  { $paths += 'backend' }
if ($Frontend) { $paths += 'frontend' }
# Admin panel (static, served by backend from ../admin/admin.html). Раньше не
# деплоился ни backend-, ни frontend-таром → правки админки уезжали только ручным
# scp. Цепляем к -Frontend (общий случай deploy.ps1 = backend+frontend).
if ($Frontend) { $paths += 'admin' }

if ($paths.Count -gt 0) {
    $tar = Join-Path $env:TEMP 'shedstream_deploy.tar'
    $excl = @('--exclude=*.db','--exclude=*.pyc','--exclude=__pycache__','--exclude=.env','--exclude=venv','--exclude=.venv')
    $tarArgs = @('-cf', $tar) + $excl + @('-C', $ExtDir) + $paths
    Info "tar [$($paths -join ', ')] (excl db/.env/pycache)..."
    if (-not $DryRun) { & tar @tarArgs; if ($LASTEXITCODE -ne 0){ throw "tar failed" } }

    if ($DryRun) {
        Write-Host "  [dry] scp tar -> ${ProdHost}:/tmp/" -ForegroundColor DarkGray
        Write-Host "  [dry] ssh extract into $ProdDir" -ForegroundColor DarkGray
        if (-not $NoRestart) { Write-Host "  [dry] ssh supervisorctl restart $Service + health check" -ForegroundColor DarkGray }
    }
    else {
        Info "scp -> prod"
        & scp $tar "${ProdHost}:/tmp/shedstream_deploy.tar"; if ($LASTEXITCODE -ne 0){ throw "scp failed" }
        Info "extract on prod"
        & ssh $ProdHost "cd $ProdDir && tar -xf /tmp/shedstream_deploy.tar && echo extracted"
        if ($LASTEXITCODE -ne 0){ throw "remote extract failed" }

        if (-not $NoRestart) {
            Info "restart $Service + health check (6s)..."
            $health = & ssh $ProdHost "supervisorctl restart $Service >/dev/null 2>&1; sleep 6; supervisorctl status $Service; echo '---ERR---'; supervisorctl tail -120 $Service stderr 2>/dev/null | grep -iE 'Traceback|SyntaxError|ImportError' | tail -5"
            $health | ForEach-Object { Write-Host "  $_" }
            if ($health -match 'RUNNING') { Ok "Service RUNNING" } else { Warn "Service NOT running - check log!" }
            if ($health -match 'Traceback|SyntaxError|ImportError') { Warn "Errors in stderr - check above!" }
        } else { Warn "-NoRestart: tar extracted, service NOT restarted" }
    }
}

Ok "Deploy done."
if ($Frontend -and -not $DryRun) { Warn "Remember to commit the cache-bust change in the html files." }
