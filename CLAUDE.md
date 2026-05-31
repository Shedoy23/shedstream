# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**shedstream / AfterLait** — a multi-tenant Twitch Extension platform that turns viewers into participants in the streamer's game. One backend deployment serves many streamer channels. Two game modules exist today: **Bannerlord** (C# mod + backend module) and **RimWorld** (RimLink). The architecture goal is game-agnostic: games plug in via the Module API (`docs/MODULE_API.md`).

## Repo layout (only the parts that need explaining)

- `Расширение/backend/` — FastAPI + SQLite (aiosqlite) backend. Multi-tenant: every tenant table is scoped by `channel_id`.
- `Расширение/backend/modules/<game>/` — per-game adapter (`_adapter.py`) + `manifest.yaml` declaring that game's events/actions/catalogs.
- `Расширение/backend/migrations/` — `m<N>_*.py` migrations, each `async def apply(conn)`.
- `Расширение/frontend/` — the Twitch extension UI. `viewer.js` (~7k lines) is **shared** by RimWorld + Bannerlord. `extension.html` and `mobile.html` are parallel shells that must stay in sync.
- `BannerlordLink/` — C# Bannerlord mod (Harmony patches, `MissionBehavior`, `CampaignBehaviorBase`). Clean-room re-impl using BLT as reference.
- `RimLink/` — RimWorld module (C# mod + assets).
- `БЛТ/` — BLT reference checkout. **Read-only, clean-room** (LGPL): ideas/APIs/short idioms only, never copy class bodies.
- `scripts/` — deploy / consistency-lint / crash-triage automation (see Commands).

## Where the real docs live — read before non-trivial work

`Расширение/docs/` is the knowledge base. The **`CONTEXT*.md` files are the living per-area status/handoff docs — read the relevant one first**:
- `CONTEXT.md` (core/platform), `CONTEXT_BANNERLORD.md`, `CONTEXT_RIMWORLD.md`.
- Architecture: `ARCHITECTURE.md`, `MULTITENANT_PLAN.md`, `MODULE_API.md`, `ARCH_DATA_OWNERSHIP.md`.
- Bannerlord mod: `BANNERLORD_DEV_ENV.md` (build env), `TESTING_PLAYBOOK.md` (in-game verification), `BANNERLORD_API_CHEATSHEET.md` (Bannerlord/TaleWorlds API by task — fast orientation), `BLT_RC22_REFERENCE.md` (deep BLT file-by-file).

## Commands

**Backend** (`cd Расширение/backend`):
- Run: `python main.py` — uvicorn on :8000; runs all migrations on startup (prints `✅ Migrations complete`).
- Compile-check: `python -m compileall -q .`
- Tests are **standalone scripts, not pytest**: `python tests/test_multi_tenant_isolation.py` (also `test_pubsub.py`, `test_eventsub.py`). A failure means a real regression in a tenant/security invariant.
- Deps: `pip install -r requirements.txt`.

**Frontend**: no build step (static JS/HTML served by backend). Syntax-check: `node --check frontend/viewer.js`.

**Bannerlord mod** (C#, net472):
- Build: `dotnet build BannerlordLink/src/BannerlordLink.csproj -c Release` — references game DLLs at `X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord`. Output lands in `BannerlordLink/bin/Win64_Shipping_Client/` (NOT the game folder).
- The DLL must then be copied into the game's `Modules/Shedoy23.BannerlordLink/bin/Win64_Shipping_Client/` (`scripts/deploy.ps1 -Mod` does build + copy + md5-verify). Restart Bannerlord to load it — no hot-reload.
- Edit in this worktree (git source of truth); the `src` copy under the game's Modules folder is stale.

**Automation** (`scripts/`, see `scripts/README.md`):
- `pwsh scripts/deploy.ps1` — one-command deploy (`-All` adds the mod, `-Backend`/`-Frontend`, `-DryRun`).
- `python scripts/lint_consistency.py` — version-sync / migrations-wired / manifest-drift checks (run by CI + the pre-commit hook).
- `pwsh scripts/triage-crash.ps1` — summarize the latest Bannerlord crash dump via dotnet-dump.

## Deploy

Prod = `root@31.130.132.224:/root/twitch-extension/`, run under supervisor as `twitchbot`. Use `scripts/deploy.ps1` (tars `backend`+`frontend` excluding `*.db`/`.env`, scp + extract + `supervisorctl restart twitchbot` + health-check). **Confirm before deploying / restarting prod.** DB backups are already automated (`backend/backup_db.sh` cron + in-process `backend/backup_loop.py`); offsite is the only gap.

## Conventions & gotchas that actually bite

- **Multi-tenant scoping is mandatory.** Every query/insert on a tenant table must include `channel_id`. Resolve it via `resolve_channel_id_or_default()` (admin/legacy boundaries) or the JWT context (`require_jwt_user` / `require_jwt_channel` set a ContextVar). Omitting it causes cross-channel data leaks or `NOT NULL` insert failures.
- **Migrations must be wired.** Add `m<N>_*.py` AND register it in `main.py:run_migrations()` (sequential, idempotent via the `migrations_applied` table). `lint_consistency.py` fails CI/commit if a migration file isn't wired. Never edit an already-applied migration — add a new one. The seed in a migration only affects fresh DBs; to change existing prod rows, write an `UPDATE` migration.
- **Two currencies, never conflate.** 💎 crustics = platform points (`userPoints`, earned watching/chat); 💰 dinars = in-game `Hero.Gold`. 1 💎 = 5 dinars. An action charges ONE currency by meaning. (Frontend currently shows crustics with two glyphs, `💎` and `⦷` — unify if you touch that area.)
- **Cache-bust both shells.** `viewer.js?v=...` must be identical in `extension.html` and `mobile.html`; `deploy.ps1` keeps them in sync. Desync = part of the audience runs stale JS.
- **Mod crash protection pattern.** Vanilla Bannerlord daily-tick code (e.g. `PregnancyCampaignBehavior`, `BannerCampaignBehavior`) throws NPE/InvalidCast on the mod's clanless or edge-case viewer heroes. The fix pattern is a defensive Harmony finalizer/prefix that swallows the *specific* exception and lets the engine continue — see `BannerlordLink/src/Patches/PregnancyModelPatch.cs` and `BannerCampaignBehaviorPatch.cs`. `BannerlordLinkModule.cs` has a resilient `PatchAll` with a `SKIP_PATCH_NAMES` kill-switch.
- **Gate viewer actions by game state, both ends.** Actions requiring a clan/kingdom/leader/ruler (marriage, children, party, kingdom ops) are gated in `viewer.js` (disabled + reason tooltip) AND refused server-side in `routes/bannerlord.py` — the frontend is bypassable.
- **CodeGraph MCP** (`codegraph_*` tools) indexes this repo — prefer it for "what calls X / where is X / impact of changing X" over grep (details in the global CLAUDE.md).
