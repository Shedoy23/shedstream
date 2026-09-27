# Living pets: production rollout, 27 September 2026

## Installed

The supplied OBS candidate was deployed through the normal SSH connection after a fresh Helix check reported no active stream for channel 98319857 (shedoy23).

Server release directory:
`/root/shedlink-deploy-backups/pets-living-rollout-20260927/`

- `catalog/`: newly prepared backend-only release, exact patches against fresh production source. It adds FANTASY_COMPANIONS and shared 500000 pricing, wires M130 immediately after M129, and supplies the fantasy migration/tests. No complete backend checkout was uploaded.
- `obs/`: supplied candidate (apply-obs-only.py, check-stream.py, manifest, payload and evidence).
- Catalog activation restarted twitchbot once. OBS installation required no additional restart.
- Public catalogue now contains 14 active items: two original skins plus both new collections. All 12 collection skins are rare at 500000 crustics.
- Installed OBS entrypoint cache version is 20260927a. New obs-living.js uses independent per-pet motion and the existing 8-walk / 12-behaviour atlases.
- Preserved greetings, reactions, signature scenes, skin/level updates, reduced-motion and fallback rendering.
- Kept the production channel-scoped drop query and 30-second final battle result.
- Frozen Twitch shells, pet-stage.js, submitted ZIP and unrelated production fixes were preserved.

## Validation

Before installation:
- All 68 OBS change/dependency/protected source checks matched the supplied manifest and fresh server files.
- Catalogue material was reused selectively from the earlier walk bundle; only backend patches/files were selected into the NEW release. Old OBS/preview patches were excluded. The old combined installer was never applied.
- Fresh server SQLite schema was inspected before querying. A SQLite backup API snapshot and source backups were created.
- Real-schema migration on the snapshot preserved existing catalogue rows and inventory count, adding only the six fantasy skins.
- Both collections' actual purchase-method tests passed in isolated databases, including price, auto-equip, insufficient funds, duplicate ownership, channel isolation and original prices.
- Repeated test-living-pets-obs.cjs and test-living-pets-obs-browser.cjs passed. The latter exercised actual overlay.html with 12 simultaneous new pets + a legacy skin, all eight walking frames, six scene frames, sleep/wake, movement, directions, bounds, scales, reactions, skin/level replacement, reduced motion and load failures.
- The tested workspace's three payload files matched the candidate manifest exactly.

After installation:
- Catalog installer checked installed source hashes, public prices and all 28 frozen-file hashes.
- OBS installer rechecked offline status twice, took its own fresh source/SQLite backup, installed only three files with HTML last, and verified changed/protected hashes.
- Public SHA-256 checks passed for all 68 OBS changes/dependencies/protected files.
- Public /health returned status=ok, db=ok; supervisor showed twitchbot RUNNING after startup.
- Local verify-candidate.py --version 0.0.5 passed; ZIP SHA-256 remains 6f8e07f56b7d6a0b4f628a2731d81686a47b77dd8b7cfcc912dd1f8af3f90672.
- Public overlay.html?channel_id=98319857 was loaded in Chromium with real API data and no substituted viewers. Fisher, crimson knight and lantern mage all entered living mode, showed all eight walking frames, greetings/scenes and changing positions. No JS exceptions or failed pet-asset requests.
- Screenshot was visually inspected; three equipped pets were visible. This is a public-browser check, not an OBS application check.

Local verification report and screenshot (ignored):
`dist/pets-living-rollout-20260927/verification.json`
`dist/pets-living-rollout-20260927/public-live-overlay.png`

No live purchase or viewer-balance mutation was performed for testing.

## OBS follow-up

OBS was not running on this computer; its WebSocket server is disabled. No OBS process was launched or settings changed. Refresh the existing browser source after opening OBS and inspect the scene. Direct OBS rendering remains unverified.

Public overlay:
https://shedoy23.ru/overlay.html?channel_id=98319857

## Rollback and handoff

Do NOT run the older pet-walk-fix-20260926 or pets-fantasy-20260926 installers after this release.

OBS-only rollback, executed on the server after verifying the stream is offline:

```sh
/root/twitch-extension/venv/bin/python /root/shedlink-deploy-backups/pets-living-rollout-20260927/obs/apply-obs-only.py rollback-obs
```

It checks for intervening source changes, restores the previous overlay entrypoint/bridge, and leaves the unused new controller on disk. Refresh OBS afterward. It never restores SQLite or removes inventory.

Catalog backup and deployed metadata are under `catalog/backup`, `catalog/prepared.json`, `catalog/deployed.json`. OBS backup location is recorded in `obs/installed.json`. If catalogue rollback is separately needed, use only the release's six added rows and source backups, preserving all subsequent viewer transactions and ownership. Do not restore the entire live DB.

Candidate supplied by another chat:
`C:/Users/Edward/Documents/Codex/2026-09-26/github-gpt-bannerlordautopilot-handoff-md-26/outputs/pets-obs-20260927-candidate.zip`

The three OBS source files and regression tests were copied into the authoritative codex-public-release worktree. Its overlay.html also reconciles the two already-live production fixes mentioned above. Unrelated worktree changes were preserved.
