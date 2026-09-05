<#
.SYNOPSIS
  One-command deploy for the ShedLink / shedstream project.

.DESCRIPTION
  Replaces the manual tar -> scp -> ssh extract -> restart dance.
  - Frontend deploy auto-bumps the viewer.js?v= cache-bust SYNCHRONOUSLY in
    extension.html AND mobile.html (no more hand-editing / desync).
  - Backend/frontend are tarred WHOLE (with excludes) so you can never "forget
    a file". Excludes *.db AND its -wal/-shm/-journal sidecars (a stray local WAL
    shipped over the prod DB = "database disk image is malformed"), plus .env /
    __pycache__, so prod data is never clobbered.
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
    [switch]$Admin,
    [switch]$Site,
    [switch]$Mod,
    [switch]$All,
    [switch]$Staging,    # ROADMAP 1.3: deploy to the on-demand staging app (:8001), NOT prod
    [switch]$NoRestart,
    [switch]$DryRun,
    # Deploy freeze override. Requires a written reason, on purpose: typing it
    # forces you to name what is actually on fire.
    [string]$CriticalReason = ''
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
if (-not ($Backend -or $Frontend -or $Admin -or $Site -or $Mod -or $All -or $Staging)) { $Backend = $true; $Frontend = $true; $Admin = $true; $Site = $true }
if ($All) { $Backend = $true; $Frontend = $true; $Admin = $true; $Site = $true; $Mod = $true }

# -- Deploy freeze (owner request 2026-07-26) ------------------------------
# The Twitch review is a live, scheduled slot: the reviewer opens the channel at
# a fixed time and a broken prod at that moment costs weeks of waiting for
# another slot. The owner asked, in his own words, to be stopped from touching
# prod before it -- a promise is not a mechanism, so this is one.
#
# Not a wall, a speed bump: -CriticalReason "..." lets a real emergency through
# in one flag. Typing the reason is the point -- it makes you name what is
# actually broken instead of shipping on impulse.
# 2026-08-19: the 2026-07-28 date-based freeze expired on its own while a NEW
# review (0.0.2, submitted 2026-08-16) is open -- the guard was inert exactly
# when it was needed. A date goes stale in the UNSAFE direction; a flag goes
# stale in the safe one. So this is a flag now: flip it to $false the day Twitch
# answers, and say so in STATUS.md.
#
# Scope is FRONTEND ONLY. ROADMAP section 9: backend deploys continue during the
# review and must serve public 0.0.1 and submitted 0.0.2 at the same time.
# What this stops: the default `deploy.ps1` (backend+frontend) shipping a
# half-refactored frontend to prod AND auto-bumping the cache-bust while the
# submitted ZIP is pinned at tag submit/0.0.2.
$FrontendReviewOpen = $false                 # 2026-09-05: Review НЕ идёт — 0.0.3 и 0.0.4
                                             # обе в Hosted Test (RELEASE_RECORD.md).
                                             # Взводить обратно в день подачи на Review.
$FreezeUntil = Get-Date '2026-07-28 23:30'   # expired; kept for the log below
$IsProdTarget = $Frontend -and -not $Staging
if ($IsProdTarget -and -not $DryRun -and $FrontendReviewOpen) {
    if ([string]::IsNullOrWhiteSpace($CriticalReason)) {
        Write-Host ''
        Write-Host '  FRONTEND DEPLOY BLOCKED -- Twitch review of 0.0.2 is open' -ForegroundColor Red
        Write-Host ''
        Write-Host '  Submitted 2026-08-16, pinned at tag submit/0.0.2. Deploying the'
        Write-Host '  frontend now would also auto-bump the cache-bust in both shells,'
        Write-Host '  so our server and the CDN copy under review stop matching.'
        Write-Host ''
        Write-Host '  Lift it by setting $FrontendReviewOpen = $false in this script'
        Write-Host '  the day Twitch answers (and note the verdict in STATUS.md).'
        Write-Host ''
        Write-Host '  Safe right now:'
        Write-Host '      ./scripts/deploy.ps1 -Backend     # backend only, allowed during review'
        Write-Host '      ./scripts/deploy.ps1 -DryRun      # show what would happen'
        Write-Host '      ./scripts/deploy.ps1 -Staging     # staging app on :8001'
        Write-Host '      ./scripts/deploy.ps1 -Mod         # game DLL, prod untouched'
        Write-Host ''
        Write-Host '  If it really is critical:'
        Write-Host '      ./scripts/deploy.ps1 -Frontend -CriticalReason "what is on fire"'
        Write-Host ''
        exit 1
    }
    Write-Host ''
    Write-Host ("  FREEZE OVERRIDDEN: {0}" -f $CriticalReason) -ForegroundColor Yellow
    Write-Host '  Logged to deploy-freeze-overrides.log. Proceeding.'
    Write-Host ''
    $line = '{0}  {1}  reason: {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $env:USERNAME, $CriticalReason
    Add-Content -Path (Join-Path $PSScriptRoot 'deploy-freeze-overrides.log') -Value $line
}

function Info($m){ Write-Host "-> $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[ok] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }

# -- 1. Mod: build + copy DLL into game ------------------------------------
if ($Mod) {
    # 2026-09-02: guard against a running game OR LAUNCHER holding the DLL.
    # CLAUDE.md has warned about this since day one ("game may be running -
    # holds the mod DLL, the copy will fail"), but nothing checked it. That day
    # the copy failed with "file in use" while Bannerlord.exe was NOT running:
    # the launcher (TaleWorlds.MountAndBlade.Launcher) and Watchdog held it.
    # A name mask of 'Bannerlord*' misses both, so match on the game PATH.
    $holders = Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($GamePath, 'OrdinalIgnoreCase') }
    if ($holders -and -not $DryRun) {
        Write-Host ''
        Write-Host '  MOD COPY BLOCKED -- the game folder is in use' -ForegroundColor Red
        foreach ($h in $holders) { Write-Host ("    {0} (pid {1})" -f $h.ProcessName, $h.Id) }
        Write-Host ''
        Write-Host '  Close the game AND the launcher, then run again.'
        Write-Host '  (The launcher alone is enough to lock BannerlordLink.dll.)'
        Write-Host ''
        throw "Mod copy aborted: game/launcher running"
    }
    Info "Building mod (Release)..."
    if (-not $DryRun) {
        & dotnet build $ModSrc -c Release -v minimal
        if ($LASTEXITCODE -ne 0) { throw "dotnet build failed (exit $LASTEXITCODE)" }
    }
    $srcBin = Join-Path $RepoRoot 'BannerlordLink\bin\Win64_Shipping_Client'
    $dstBin = Join-Path $GamePath "Modules\$ModId\bin\Win64_Shipping_Client"
    # 2026-07-31: snapshot the DLL that is ALREADY in the game before we
    # overwrite it. Without this the previous build is simply gone: on
    # 2026-07-31 the 27.07 DLL (md5 E1847C9D, the one that carried the #38
    # war/peace fix confirmed on stream) was overwritten and the only
    # "rollback" file left in the folder was two versions old. Rolling back
    # then means rebuilding from git instead of renaming a file.
    $liveDll = Join-Path $dstBin 'BannerlordLink.dll'
    if (-not $DryRun -and (Test-Path $liveDll)) {
        $liveHash = (Get-FileHash $liveDll -Algorithm MD5).Hash.Substring(0,8)
        $stamp    = Get-Date -Format 'yyyy-MM-dd'
        $snap     = Join-Path $dstBin "BannerlordLink.dll.rollback-$stamp-$liveHash"
        if (-not (Test-Path $snap)) {
            Copy-Item -LiteralPath $liveDll -Destination $snap -Force
            Ok "Previous DLL kept as $(Split-Path $snap -Leaf)"
        }
    }
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
        # Cache-bust ALL *.js?v= modules (viewer*.js + pets/family/cases/duels/voting/...)
        # with one stamp. Previously only viewer*.js was bumped, so an edit to a non-viewer
        # module never reached viewers: its ?v= was hardcoded, so the CDN/browser kept
        # serving the old file. Bit us with pets.js / family.js (2026-06-27).
        # 2026-08-05: .css попал в тот же regex. До этого правка viewer.css
        # никак не сбрасывала кэш — её ?v= стоял вручную с 15 июня, то есть
        # любое изменение стилей просто не доезжало до зрителя. Тот же дефект,
        # что был с pets.js/family.js, только в соседнем расширении файла.
        $new = [regex]::Replace($txt, '([\w][\w-]*\.(?:js|css))\?v=[^"'']+', ('$1?v=' + $stamp))
        [IO.File]::WriteAllText($p, $new, $utf8)
    }
    Ok "Cache-bust *.js / *.css ?v=$stamp (extension.html + mobile.html)"
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
    $sExcl = @('--exclude=*.db','--exclude=*.db-wal','--exclude=*.db-shm','--exclude=*.db-journal','--exclude=*.pyc','--exclude=__pycache__','--exclude=.env','--exclude=venv','--exclude=.venv')
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

# -- 2.7 Публичные страницы сайта (НЕ входят в ZIP расширения) -------------
# index.html, privacy.html и terms.html лежат рядом с фронтом расширения, но в
# поданный на ревью архив НЕ попадают — проверено списком файлов ZIP. Значит
# заморозка фронта их не касается, а везти их вместе с -Frontend нельзя: тот
# тащит и viewer*.js, которые как раз заморожены. Поэтому отдельный флаг и
# точечная отправка ровно трёх файлов.
if ($Site) {
    # overlay.html + pet-layout.js добавлены 2026-08-23. Оверлей — это виджет
    # для OBS, а НЕ Twitch video-overlay: в поданный архив он намеренно не
    # кладётся (см. pack-extension.py), поэтому заморозка фронта его не
    # касается. pet-layout.js подключён только оверлеем, в оболочки расширения
    # не входит и в ZIP не попадает — сборщик берёт скрипты из шеллов.
    $siteFiles = @('index.html', 'privacy.html', 'terms.html',
                   'overlay.html', 'pet-layout.js')
    foreach ($f in $siteFiles) {
        $src = Join-Path $ExtDir "frontend\$f"
        if (-not (Test-Path $src)) { Warn "no $f - skip"; continue }
        if ($DryRun) { Write-Host "  [dry] scp $f -> prod frontend/" -ForegroundColor DarkGray; continue }
        & scp $src "${ProdHost}:/root/twitch-extension/frontend/$f"
        if ($LASTEXITCODE -ne 0) { throw "scp $f failed" }
    }
    if (-not $DryRun) { Ok "Site pages updated ($($siteFiles -join ', '))" }
}

# -- 3. Backend/Frontend: tar -> scp -> extract -> restart -> verify -------
$paths = @()
if ($Backend)  { $paths += 'backend' }
if ($Frontend) { $paths += 'frontend' }
# Admin panel (static, served by backend from ../admin/admin.html). Раньше не
# деплоился ни backend-, ни frontend-таром → правки админки уезжали только ручным
# scp. Теперь у неё свой флаг -Admin, и она входит в набор по умолчанию.
# 2026-08-20: админка больше НЕ едет вместе с фронтом расширения. Она не
# входит в ZIP, поданный в Twitch, и ревью её не касается — а связка означала,
# что заморозка фронта на время ревью морозила и наблюдательную панель, которой
# как раз в это время и пользуешься. Свой флаг: -Admin.
if ($Admin) { $paths += 'admin' }

if ($paths.Count -gt 0) {
    $tar = Join-Path $env:TEMP 'shedstream_deploy.tar'
    $excl = @('--exclude=*.db','--exclude=*.db-wal','--exclude=*.db-shm','--exclude=*.db-journal','--exclude=*.pyc','--exclude=__pycache__','--exclude=.env','--exclude=venv','--exclude=.venv')
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

        # 2026-07-27: DEPENDENCY SYNC. Deploy used to copy code and restart the
        # service but NEVER install packages. A new dependency landed in
        # requirements.txt and never reached prod, so the code paths importing it
        # returned 500. That is exactly what happened: the streamer dashboard moved
        # to jinja2 templates, jinja2 was added to requirements on 07-26, prod never
        # got it, and from the 07-27 deploy every streamer page -- including the
        # Twitch OAuth return page -- served Internal Server Error. Found only
        # because the owner opened it by hand. (This file is ASCII-only on purpose:
        # a .ps1 without BOM is read as ANSI here and Cyrillic breaks the parser.)
        if ($Backend) {
            Info "sync deps (pip install -r requirements.txt)..."
            # Exit code is captured BEFORE the pipe: $? after `| tail` is tail's
            # status, which always succeeds -- a failed pip would slip through.
            $pip = & ssh $ProdHost "$ProdDir/venv/bin/pip install -q -r $ProdDir/backend/requirements.txt >/tmp/pipdeploy.log 2>&1; ec=`$?; grep -viE '^\[notice\]' /tmp/pipdeploy.log | tail -5; echo pip_exit=`$ec"
            $pip | Where-Object { $_ } | ForEach-Object { Write-Host "  $_" }
            if ("$pip" -notmatch 'pip_exit=0') { throw "pip install failed on prod - deploy aborted before restart. Inspect: ssh $ProdHost '$ProdDir/venv/bin/pip install -r $ProdDir/backend/requirements.txt'" }
            Ok "Deps in sync"
        }

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

            # 2026-07-27: /health only proves the DB answers. It stayed green all
            # day while streamer pages returned 500 over a missing package. So hit
            # the real pages. privacy/terms are not decoration: those URLs are in
            # the Twitch extension submission -- if they break, the review fails.
            Info "smoke: real pages answer (not just /health)..."
            # SINGLE-quoted PS string: $p/$c are remote bash vars and pass through
            # untouched. Double quotes would need escaping for both $ and the inner
            # quotes -- that is what broke the parser on 2026-07-27.
            $pages = & ssh $ProdHost 'for p in / /extension.html /overlay.html /privacy.html /terms.html; do c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "http://127.0.0.1:8000$p"); echo "$p=$c"; done'
            $pages | ForEach-Object { Write-Host "  $_" }
            $bad = @($pages | Where-Object { $_ -and $_ -notmatch '=200$' })
            if ($bad.Count -gt 0) { throw ("PAGES BROKEN after deploy: " + ($bad -join ' ') + ". Usual cause: a dependency that never reached prod, or a template error. Inspect: ssh " + $ProdHost + " 'tail -50 /var/log/twitchbot.err.log'") }
            Ok "Pages OK"
        } else { Warn "-NoRestart: tar extracted, service NOT restarted" }
    }
}

Ok "Deploy done."
if ($Frontend -and -not $DryRun) { Warn "Remember to commit the cache-bust change in the html files." }
