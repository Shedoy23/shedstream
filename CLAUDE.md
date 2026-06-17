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

Repo root: `OVERVIEW.md` (what the project is — structure, data flow), `ROADMAP.md` (the owner's stabilization plan — current priorities; check it when the owner asks "what should we do next").

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
- **New mod→backend event MUST be declared in `manifest.yaml` `events:`.** The backend rejects any event type not in the manifest (`event_not_in_manifest`, gated in `routes/module_api.py`) BEFORE the adapter handler runs — so a fresh `PostEventAsync("bannerlord", "hero.X", …)` silently no-ops until you add `- hero.X` under `events:`. Bit twice: `hero.properties_snapshot` (mirror was dead) and `hero.restore_profile` (per-save class wouldn't restore). Symptom: mod logs the push, backend never processes it, DB unchanged. Same rule for new actions (`manifest.supports_action`).
- **Two currencies, never conflate.** 💎 crustics = platform points (`userPoints`, earned watching/chat); 💰 dinars = in-game `Hero.Gold`. 1 💎 = 5 dinars. An action charges ONE currency by meaning. (Frontend currently shows crustics with two glyphs, `💎` and `⦷` — unify if you touch that area.)
- **Cache-bust both shells.** `viewer.js?v=...` must be identical in `extension.html` and `mobile.html`; `deploy.ps1` keeps them in sync. Desync = part of the audience runs stale JS.
- **Mod crash protection pattern.** Vanilla Bannerlord daily-tick code (e.g. `PregnancyCampaignBehavior`, `BannerCampaignBehavior`) throws NPE/InvalidCast on the mod's clanless or edge-case viewer heroes. The fix pattern is a defensive Harmony finalizer/prefix that swallows the *specific* exception and lets the engine continue — see `BannerlordLink/src/Patches/PregnancyModelPatch.cs` and `BannerCampaignBehaviorPatch.cs`. `BannerlordLinkModule.cs` has a resilient `PatchAll` with a `SKIP_PATCH_NAMES` kill-switch.
- **Vanilla NRE: decompile to root-cause, don't blind-swallow.** A finalizer that only swallows trades a crash for a *silently broken feature* (bug #10: the kingdom-vote popup's NRE was swallowed → players couldn't vote, it just "flashed and vanished"). Before swallowing, **decompile the vanilla method to find the exact null**: `& "$env:USERPROFILE\.dotnet\tools\ilspycmd.exe" "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\bin\Win64_Shipping_Client\<Assembly>.dll" -t "<Full.Type.Name>"` (ilspycmd is installed as a dotnet global tool; it's NOT on PATH — use the full `~/.dotnet/tools/` path). Then write a **prefix that guards the specific null** (graceful handle, e.g. `ExecuteRemove`) and lets the valid case fall through to vanilla, so the feature still works — see `Patches/KingdomVoteNotificationPatch.cs`. Keep a finalizer backstop that logs the **full stack** (`__exception.ToString()`) for any null you didn't anticipate. Reminder: mod features need in-game verification (no auto-test) — a decompile-grounded fix is *plausible*, not *proven*, until tested. **2026-06-16 — 2-й случай того же класса (`BannerCampaignBehavior.DailyTickHero`, InvalidCast у @bapah1_1/@k0r0b14):** старый finalizer ГЛОТАЛ → баннер не назначался + спам 23×/день. Декомпиль → единственный каст `(BannerComponent)hero.BannerItem.Item.ItemComponent`; prefix теперь **чистит** битый `BannerItem` → vanilla видит invalid и сам переназначает корректный (**self-heal — prefix не только guard'ит «плохой» путь, но может ПОЧИНИТЬ вход**, чтобы vanilla отработал верно, а не просто скипнулся). Урок одной строкой: **глушить исключение — последнее средство; сначала декомпиль + прицельный prefix, который ЧИНИТ, а не прячет.**
- **Gate viewer actions by game state, both ends.** Actions requiring a clan/kingdom/leader/ruler (marriage, children, party, kingdom ops) are gated in `viewer.js` (disabled + reason tooltip) AND refused server-side in `routes/bannerlord.py` — the frontend is bypassable.
- **CodeGraph MCP** (`codegraph_*` tools) indexes this repo — prefer it for "what calls X / where is X / impact of changing X" over grep (details in the global CLAUDE.md).
- **Dashboard HTML = Python f-string: дублируй скобки + render-тест перед деплоем.** `routes/streamer.py:_dashboard_html` — большой f-string. Любой литеральный `{`/`}` в JS/CSS дублируй (`{{`/`}}`); одинарные `{...}` — только Python-интерполяция (`{var}`). Перед деплоем дашборда render-тестируй: `PYTHONIOENCODING=utf-8 TWITCH_OAUTH_TOKEN=x TWITCH_CLIENT_ID=x TWITCH_CLIENT_SECRET=x TWITCH_BOT_ID=x python -c "import routes.streamer as s; s._dashboard_html({'login':'x'})"` — ловит brace-синтаксис (compile) И NameError из `{var}` (runtime). Кусало: 500 на дашборде (`{confirm_phrase}` без двойных скобок) + каждая новая карточка.
- **deploy.ps1 «tar: timestamp … in the future» — безвредный транзиент.** Локальные Windows-часы впереди прод-часов → GNU tar на проде ругается, PowerShell ловит stderr как exit 1 и обрывает скрипт ПОСЛЕ распаковки (файлы уже легли). Не паниковать: проверить `curl`-ом, что прод отдаёт новый контент — деплой фактически прошёл. Корень — рассинхрон часов (`w32tm /resync`).
- **Тонкий фронт: балансовые числа — истина на бэке, не display-копия во фронте.** Цены/кулдауны/лимиты, которые бэк enforce'ит, НЕ дублировать хардкодом во фронте — фронт рисует то, что прислал бэк (`/my-hero` / `/config`). Иначе одно число живёт в 2-3 местах (frontend JS / backend / C#-мод — напр. focus-cost `30000` = `BNR_FOCUS_TIER_COSTS` + `FOCUS_TIER_COSTS` + мод): меняешь — правишь все, а после публичного релиза замёрзший на CDN Twitch фронт покажет старую цену → mismatch с бэком («не хватает» при «хватает», как было с каталогом). Пока в Local Test — не срочно (фронт катается мгновенно); выносить постепенно / перед submission. Верстка/статичные подписи — ок во фронте. (План — ROADMAP «Пре-релизная подготовка».)
- **Платное + асинхронное действие → обязателен подтверждающий тост «не мгновенно».** Любая viewer-операция, которая тратит крустики И имеет отложенный/неопределённый исход (голосование кланов, ставки, отложенные эффекты), на успехе ДОЛЖНА показать action-specific тост: это заявка, исход решается позже, повторно жать не нужно. Иначе зритель видит «ничего не произошло» → жмёт снова → переплачивает (bugs #16/#17: `propose_war`/`propose_peace` молча уходили на клан-вотум — slopkom подал войну на королевство стримера 4× подряд; «не заключается мир» = вотум против, НЕ баг механики). Generic-тост charge'а («OK») не считается — нужен текст про конкретное действие. `showNotification` replace-style → тост в хендлере после `await _bannerlordBuyAction` (теперь возвращает `result`) перетирает generic.

## Session workflow rules (2026-06-11 — rationale in ROADMAP.md §0)

The owner is a non-programmer building this solo with Claude; these rules are the project's guardrails — **enforce them proactively, don't wait to be asked**. They exist because every expensive past mistake (casino built → cut for Twitch compliance; BLT-modeled mechanics → LGPL audit still blocking release; 13 CRITICAL security findings) shares one root: *build first, check constraints later*.

1. **Check before code.** Before implementing any NEW viewer-facing mechanic: (a) run a Twitch-compliance check (`/twitch-compliance`), (b) if the idea mirrors BLT, flag the license implication, (c) present a 5–10 line spec and get explicit approval. If asked to "just build it", do the checks anyway first — that's cheaper than another casino.
2. **Done = evidence.** Never report done without proof: test output, log line, prod DB query, screenshot. A red test blocks deploy — no exceptions. (Extends the global "verify before done".)
3. **Prod deploys after stream, not during.** If a stream is live, only hotfix a broken prod; otherwise prepare everything and say "ready to deploy on break". A mid-stream backend restart drops viewer connections; a mod copy needs the game closed anyway.
4. **Feature in — feature out.** When a new mechanic is requested, ask which low-usage feature gets frozen/removed in exchange (use usage metrics once they exist; until then, ask). The 7k-line viewer.js is what unbounded "yes" looks like.
5. **Suggest the monthly audit.** If ~a month has passed since the last audit session (security / dead code / dependencies / debt), propose one instead of the next feature. The 2026-04 audit (13 CRITICAL) out-earned any feature.
6. **Update the CONTEXT doc** (`docs/CONTEXT*.md`) after any significant change — it's the handoff that keeps future sessions from re-discovering everything.
7. **End every work session with a plain-language summary**: what changed, what is deployed where (prod / game DLL / not yet), and what the owner must do by hand (restart game, test on stream, click something). The owner can't read diffs — the summary IS the interface.
