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
  - After a backend/frontend push it restarts the service and verifies health:
    RUNNING + no fresh Traceback in stderr AND the /health endpoint returns 200
    (with warmup retries). A live process that 502s on a dead DB pool is caught
    here and FAILS the deploy loud, instead of being waved through as [ok].

  ASCII-only on purpose: PowerShell 5.1 reads BOM-less .ps1 as ANSI, so
  non-ASCII text would corrupt. Keep it that way.

.EXAMPLE
  ./scripts/deploy.ps1                 # backend + frontend (the common case)
  ./scripts/deploy.ps1 -All            # mod + backend + frontend
  ./scripts/deploy.ps1 -Mod            # build + copy mod DLL into the game only
  ./scripts/deploy.ps1 -Backend        # backend only
  ./scripts/deploy.ps1 -Staging        # deploy to on-demand staging app (:8001), NOT prod
  ./scripts/deploy.ps1 -DryRun         # print actions, change nothing
#>
[CmdletBinding()]
param(
    [switch]$Backend,
    [switch]$Frontend,
    [switch]$Mod,
    [switch]$All,
    [switch]$Staging,    # ROADMAP 1.3: deploy to the on-demand staging app (:8001), NOT prod
    [switch]$NoRestart,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# -- Config ----------------------------------------------------------------
$ProdHost = 'root@31.130.132.224'
$ProdDir  = '/root/twitch-extension'
$Service  = 'twitchbot'
$StagingDir     = '/root/twitch-extension-staging'   # ROADMAP 1.3: on-demand staging app
$StagingService = 'twitchbot-staging'                # supervisor program, autostart=false, :8001
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

# Default: backend + frontend if nothing specified. -Staging is its own path
# (deploys to the staging app, never prod) so it must NOT trigger the prod default.
if (-not ($Backend -or $Frontend -or $Mod -or $All -or $Staging)) { $Backend = $true; $Frontend = $true }
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
        # Кэш-бастим ВСЕ viewer*.js (viewer.js + сплит-модули viewer-rimworld.js /
        # viewer-bannerlord.js — ROADMAP 2.4) одним штампом, чтобы не было рассинхрона.
        $new = [regex]::Replace($txt, '(viewer[\w-]*\.js)\?v=[^"'']+', ('$1?v=' + $stamp))
        [IO.File]::WriteAllText($p, $new, $utf8)
    }
    Ok "Cache-bust viewer.js?v=$stamp (extension.html + mobile.html)"
}

# -- 2.5 Test gate (ROADMAP 1.2): critical tenant/security invariants MUST pass
#        before a backend push. Red = deploy aborts. Game/feature tests are NOT
#        gating (run them manually via the same script without --critical).
if ($Backend -or $Staging) {
    Info "Test gate: critical tenant/security tests (--critical)..."
    Push-Location (Join-Path $ExtDir 'backend')
    try { & python tests/test_multi_tenant_isolation.py --critical; $gateRc = $LASTEXITCODE }
    finally { Pop-Location }
    if ($gateRc -ne 0) {
        throw "CRITICAL tests FAILED (exit $gateRc) - deploy ABORTED. Fix the tenant/security regression first."
    }
    Ok "Critical tests green - safe to deploy"
}

# -- 2.6 Staging deploy (ROADMAP 1.3) --------------------------------------
#   Pushes backend+frontend+admin into the SEPARATE staging dir and restarts
#   the staging service (:8001). Does NOT touch prod. The staging service runs
#   with DISABLE_LIVE_INTEGRATIONS=1 (its own .env) so it never joins the live
#   chat / EventSub / PubSub. On-demand: start it for a test, stop when done.
if ($Staging) {
    $sTar = Join-Path $env:TEMP 'shedstream_staging.tar'
    $sExcl = @('--exclude=*.db','--exclude=*.pyc','--exclude=__pycache__','--exclude=.env','--exclude=venv','--exclude=.venv')
    $sPaths = @('backend','frontend','admin')
    $sTarArgs = @('-cf', $sTar) + $sExcl + @('-C', $ExtDir) + $sPaths
    Info "STAGING tar [$($sPaths -join ', ')] (excl db/.env/pycache)..."
    if ($DryRun) {
        Write-Host "  [dry] scp staging tar -> ${ProdHost}:/tmp/" -ForegroundColor DarkGray
        Write-Host "  [dry] ssh extract into $StagingDir" -ForegroundColor DarkGray
        Write-Host "  [dry] ssh supervisorctl restart $StagingService + health :8001" -ForegroundColor DarkGray
    }
    else {
        & tar @sTarArgs; if ($LASTEXITCODE -ne 0){ throw "staging tar failed" }
        Info "scp -> staging"
        & scp $sTar "${ProdHost}:/tmp/shedstream_staging.tar"; if ($LASTEXITCODE -ne 0){ throw "staging scp failed" }
        Info "extract on staging dir"
        # --warning=no-timestamp: same clock-skew guard as the prod extract below.
        & ssh $ProdHost "mkdir -p $StagingDir && cd $StagingDir && tar --warning=no-timestamp -xf /tmp/shedstream_staging.tar && echo extracted"
        if ($LASTEXITCODE -ne 0){ throw "staging remote extract failed" }
        if (-not $NoRestart) {
            Info "restart $StagingService + health check :8001 (6s)..."
            $sHealth = & ssh $ProdHost "supervisorctl restart $StagingService >/dev/null 2>&1; sleep 7; supervisorctl status $StagingService; echo '---HTTP---'; curl -s -o /dev/null -w 'http=%{http_code}' http://127.0.0.1:8001/docs; echo; echo '---STAGING-MODE---'; grep -c 'STAGING MODE' /var/log/twitchbot-staging.out.log; echo '---ERR---'; supervisorctl tail -120 $StagingService stderr 2>/dev/null | grep -iE 'Traceback|SyntaxError|ImportError' | tail -5"
            $sHealth | ForEach-Object { Write-Host "  $_" }
            if ($sHealth -match 'RUNNING') { Ok "Staging RUNNING (:8001)" } else { Warn "Staging NOT running - check log!" }
            if ($sHealth -match 'http=200') { Ok "Staging HTTP 200 (/docs)" } else { Warn "Staging HTTP not 200 - check log!" }
            if ($sHealth -match 'Traceback|SyntaxError|ImportError') { Warn "Errors in staging stderr - check above!" }
        } else { Warn "-NoRestart: staging tar extracted, service NOT restarted" }
    }
    Ok "Staging deploy done. Stop it when finished: ssh $ProdHost 'supervisorctl stop $StagingService'"
    return
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
        if (-not $NoRestart) { Write-Host "  [dry] ssh supervisorctl restart $Service + health check (status RUNNING + HTTP /health 200)" -ForegroundColor DarkGray }
    }
    else {
        Info "scp -> prod"
        & scp $tar "${ProdHost}:/tmp/shedstream_deploy.tar"; if ($LASTEXITCODE -ne 0){ throw "scp failed" }
        Info "extract on prod"
        # --warning=no-timestamp: on clock skew (local ahead of prod) GNU tar prints
        # a non-fatal "time stamp .. in the future" line to stderr; with
        # $ErrorActionPreference=Stop that stderr line aborts the script even though
        # extraction succeeded. Silence only that warning class; real tar/ssh errors
        # still write stderr AND return non-zero (caught by $LASTEXITCODE below).
        & ssh $ProdHost "cd $ProdDir && tar --warning=no-timestamp -xf /tmp/shedstream_deploy.tar && echo extracted"
        if ($LASTEXITCODE -ne 0){ throw "remote extract failed" }

        if (-not $NoRestart) {
            Info "restart $Service + health check (RUNNING + HTTP /health 200)..."
            # Real health = the HTTP endpoint answers 200. A bare 'supervisorctl
            # RUNNING' is NOT enough: uvicorn can stay up as a process while every
            # request 502s (e.g. a corrupt WAL -> 'database disk image is malformed'
            # -> 0 DB connections). That exact case took prod down ~15 min on
            # 2026-06-25 while the old check still printed [ok]. So we curl /health
            # on prod with a few warmup retries and FAIL LOUD (throw) if it never
            # returns 200. http_code is always a 3-digit number, so the unquoted
            # bash test is safe; ` $ are escaped so $code/$( reach the remote shell.
            $health = & ssh $ProdHost "supervisorctl restart $Service >/dev/null 2>&1; sleep 6; supervisorctl status $Service; echo '---ERR---'; supervisorctl tail -120 $Service stderr 2>/dev/null | grep -iE 'Traceback|SyntaxError|ImportError' | tail -5; echo '---HTTP---'; code=000; for i in 1 2 3 4 5; do code=`$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/health); [ `$code = 200 ] && break; sleep 3; done; echo http=`$code"
            $health | ForEach-Object { Write-Host "  $_" }
            if ($health -match 'RUNNING') { Ok "Service RUNNING" } else { Warn "Service NOT running - check log!" }
            if ($health -match 'Traceback|SyntaxError|ImportError') { Warn "Errors in stderr - check above!" }
            if ($health -match 'http=200') { Ok "HTTP /health 200 - backend is live" }
            else {
                $hc = "$($health -match 'http=')".Trim()
                throw "PROD UNHEALTHY after deploy: /health did not return 200 ($hc). Process may be RUNNING but the backend is dead (DB pool / startup error). Inspect: ssh $ProdHost 'supervisorctl tail -200 $Service stderr'"
            }
        } else { Warn "-NoRestart: tar extracted, service NOT restarted" }
    }
}

Ok "Deploy done."
if ($Frontend -and -not $DryRun) { Warn "Remember to commit the cache-bust change in the html files." }
