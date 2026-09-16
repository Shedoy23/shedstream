# Viewer polling 429 hotfix — 2026-09-16

Owner supplied browser errors for channel 98319857: HTTP 429 with
`channel_rate_limited`, free tier, 300/min. Current production dependencies.py
was downloaded read-only to D:/shedlink-build/rate-limit-20260916/ and reproduces
the failure in the new regression. It matches the pre-fix local file.

## Change

GET/HEAD and the two automatic presence POST routes `/api/viewer/online` and
`/api/viewer/activity` share a quota per verified JWT identity and channel.
All other methods/routes retain the shared channel action quota. Existing tier
values are unchanged. User identity comes from verified claims, never query/body
username or raw token. Anonymous opaque identity is supported; missing identity
uses the shared channel bucket. Repeated auth helpers charge a request once.
429 keeps the old status and adds scope and Retry-After; the misleading upgrade
message is removed. Viewer bucket growth is capped, with bounded shared fallback.

No migrations, frontend/cache-bust/CDN changes or new dependencies. This fixes
quota accounting, not server capacity: synthetic checks are not load benchmarks.
Limits are still in-process fixed windows, as before.

## Evidence

- `python tests/test_viewer_poll_rate_limit.py`: old local and downloaded
  production code exit 1 on ordinary polls; fixed code exit 0.
- 50 viewers x 150 reads/min, 400 viewers' automatic presence messages, per-viewer
  overflow, shared action overflow, two auth helpers, channel isolation, exact
  window reset, opaque/missing/invalid identity and full-cache fallback tested.
- In-memory negative control replacing the limiter with always-allow: exit 1,
  `one viewer can exceed the read quota`. No production files changed for tests.
- `test_frozen_client_0_0_5.py`: exit 0, including incompatible-response controls.
- `test_multi_tenant_isolation.py`: 1335 passed, 0 failed, exit 0.
- `compileall` for dependencies.py/config.py: exit 0.

## Deployment boundary

Not deployed. Supervisor was RUNNING during read-only inspection. Minimal
production payload is only `/root/twitch-extension/backend/dependencies.py`;
config.py changes are comments. Before applying, recheck the original file hash,
back it up, replace atomically, compile-check, restart twitchbot, verify service,
health, deployed hash and fresh errors. If health fails, restore the original
file and restart. No database, environment or frontend changes required.
CLAUDE.md explicitly requires confirmation before production restart/deployment.
Live panel behavior after this fix remains unverified until deployment.
