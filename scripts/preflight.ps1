# preflight.ps1 - one-command readiness check before a stream / Twitch review window.
#
# Usage:   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\preflight.ps1
# Checks:  prod health, service state, which game mod is online, fresh backend
#          errors, last stream-status line. Prints PASS/FAIL list, exit 1 on FAIL.
#
# ASCII-only on purpose (PowerShell 5.1 reads BOM-less .ps1 as ANSI).
# Server-side grep patterns are ASCII too; Cyrillic appears only in OUTPUT.

$ErrorActionPreference = 'Continue'
$ProdHost = 'root@31.130.132.224'
$fail = 0

function Check($name, $ok, $detail) {
    if ($ok) { Write-Host ("[PASS] " + $name + "  " + $detail) }
    else     { Write-Host ("[FAIL] " + $name + "  " + $detail); $script:fail = 1 }
}

Write-Host "=== ShedLink preflight ==="
Write-Host ("local time: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Write-Host ""

# 1. Prod HTTP health
$code = ""
try { $code = (curl.exe -s -o NUL -w "%{http_code}" --max-time 10 https://shedoy23.ru/health) } catch {}
Check "prod /health" ($code -eq "200") ("HTTP " + $code)

# 2. Supervisor service
$svc = ssh $ProdHost "supervisorctl status twitchbot" 2>$null
$svcOk = ($svc -match 'RUNNING')
Check "twitchbot service" $svcOk ([string]$svc).Trim()

# 3. Game mod online? (nginx access log, last 5 minutes, ASCII patterns)
$modInfo = ssh $ProdHost "awk -v d=`"`$(date -d '5 minutes ago' '+%d/%b/%Y:%H:%M')`" '`$4 > `"[`"d' /var/log/nginx/access.log 2>/dev/null | grep -aoE 'module/bannerlord/events|RimLink-Mod' | sort | uniq -c" 2>$null
$bnr = [bool]($modInfo -match 'bannerlord')
$rim = [bool]($modInfo -match 'RimLink')
$modDetail = "bannerlord=" + $bnr + " rimworld=" + $rim
if ($bnr -or $rim) { Check "game mod online (last 5 min)" $true $modDetail }
else { Check "game mod online (last 5 min)" $false ($modDetail + "  -> start the game with the mod") }

# 4. Fresh backend errors (last 300 log lines)
$errCount = ssh $ProdHost "tail -300 /var/log/twitchbot.out.log 2>/dev/null | grep -acE 'Traceback|\[ERROR\]'" 2>$null
$errN = 0; [void][int]::TryParse(([string]$errCount).Trim(), [ref]$errN)
Check "no fresh backend errors" ($errN -eq 0) ("errors in last 300 lines: " + $errN)

# 4b. Broadcaster OAuth token is ALIVE (2026-07-27).
#
# Why this exists. The channel token died 2026-07-10 and nobody noticed for 2.5
# weeks: viewers spent Twitch Channel Points and got no crustics, because EventSub
# subscriptions cannot register without a live token. The backend DID complain --
# 448 times -- but the line reads:
#     "WARN-emoji  OAuth refresh failed: 400 Invalid refresh token"
# It is printed via plain print(), carries no log level, and contains neither
# 'Traceback' nor '[ERROR]', so check 4 above scored it as ZERO errors. Truthfully:
# it greps a vocabulary, not a severity. Chasing every possible wording is a losing
# game -- so we check the FACT instead: ask Twitch whether the token still works.
#
# Note it asks the app for the token (get_fresh_oauth_token) rather than reading the
# column: the value in the DB is encrypted ("enc:..."), and validating the ciphertext
# returns 401 for a perfectly healthy token. That false alarm cost time on 2026-07-27.
$tokenProbe = ssh $ProdHost @'
cd /root/twitch-extension/backend && ../venv/bin/python - <<'PY' 2>/dev/null | tail -1
import sys, asyncio, json, urllib.request
sys.path.insert(0, '.')
from dependencies import set_db
from database import Database
db = Database('viewers.db'); set_db(db)
from routes.streamer import get_fresh_oauth_token
async def main():
    await db.init_pool()
    try:
        tok = await get_fresh_oauth_token(98319857)
        if not tok:
            print('TOKEN=none'); return
        req = urllib.request.Request('https://id.twitch.tv/oauth2/validate',
                                     headers={'Authorization': 'OAuth ' + tok})
        d = json.load(urllib.request.urlopen(req, timeout=15))
        ok = 'channel:read:redemptions' in (d.get('scopes') or [])
        print('TOKEN=live' if ok else 'TOKEN=noscope')
    except Exception:
        print('TOKEN=dead')
    finally:
        try: await db._pool.close()
        except Exception: pass
asyncio.run(main())
PY
'@ 2>$null
$tokState = ([string]$tokenProbe).Trim()
if ($tokState -match 'TOKEN=live') {
    Check "channel token alive (channel points work)" $true "validated with Twitch"
} else {
    Check "channel token alive (channel points work)" $false ($tokState + "  -> re-auth: open https://shedoy23.ru/api/streamer/auth/start as the broadcaster, THEN restart twitchbot (subscriptions register at startup only)")
}

# 5. Last stream-status line (informational, human-readable; no auto-verdict)
$streamLine = ssh $ProdHost "grep -a 'rimlink.bot' /var/log/twitchbot.out.log 2>/dev/null | grep -a 'ch=' | tail -1" 2>$null
Write-Host ""
Write-Host ("stream status (from backend log): " + ([string]$streamLine).Trim())

Write-Host ""
if ($fail -eq 0) { Write-Host "=== PREFLIGHT OK ==="; exit 0 }
else { Write-Host "=== PREFLIGHT FAILED - fix [FAIL] items above ==="; exit 1 }
