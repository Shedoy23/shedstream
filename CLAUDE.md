# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**shedstream / ShedLink** — a multi-tenant Twitch Extension platform that turns viewers into participants in the streamer's game. One backend deployment serves many streamer channels. Two game modules exist today: **Bannerlord** (C# mod + backend module) and **RimWorld** (RimLink). The architecture goal is game-agnostic: games plug in via the Module API (`docs/MODULE_API.md`).

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

Repo root: **`STATUS.md` — витрина «что сейчас»: 10 строк, что на проде / что ждёт деплоя / что горит / ближайшая дата. Открывать ПЕРВОЙ в начале сессии, обновлять в КОНЦЕ каждой.** Дальше: **`RUNBOOK.md` — операционная правда: где что лежит на проде, чем проверять, ловушки, «выглядит сломанным, но это не так». Читать при любой работе с продом, базой, бэкапами, деплоем, публикацией модов — он избавляет от повторного расследования.** `OVERVIEW.md` (what the project is — structure, data flow), `ROADMAP.md` (the owner's stabilization plan — current priorities; check it when the owner asks "what should we do next"), `DEFERRED.md` (что отложено сознательно + «решено НЕ делать»).

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

- **Multi-tenant scoping is mandatory.** Every query/insert on a tenant table must include `channel_id` — via `resolve_channel_id_or_default()` (admin/legacy) or the JWT ContextVar (`require_jwt_user` / `require_jwt_channel`). Omitting it = cross-channel leak or `NOT NULL` failure. **Lint-gated:** `lint_consistency.py:check_tenant_scoping` fails CI/pre-commit on DML against a scoped table without `channel_id` or a globally-unique id/FK filter. Escape hatches: trailing `# tenant-ok: <reason>` (or `-- tenant-ok` in the SQL) for admin cross-channel / global-id lookups; `tenant-lint: skip-file` for known debt (rimworld.py is parked there).
- **Migrations must be wired.** Add `m<N>_*.py` AND register it in `main.py:run_migrations()` (sequential, idempotent via the `migrations_applied` table). `lint_consistency.py` fails CI/commit if a migration file isn't wired. Never edit an already-applied migration — add a new one. The seed in a migration only affects fresh DBs; to change existing prod rows, write an `UPDATE` migration.
- **New mod→backend event MUST be declared in `manifest.yaml` `events:`.** The backend drops unknown types (`event_not_in_manifest`, `routes/module_api.py`) BEFORE the adapter runs, so a fresh `PostEventAsync("bannerlord", "hero.X", …)` silently no-ops. Symptom: mod logs the push, DB unchanged. **Now lint-gated:** `check_manifest_events` scans literal push sites in `BannerlordLink/src` and hard-fails on any undeclared type (it caught a 3rd live case, `hero.marriage_activated`, the day it was written). Pushes built from a *variable* stay invisible to it — those are still on you. Declaring the event only makes the backend accept it; route it in `_adapter.handle_event` too, or it lands nowhere. Same rule for new actions (`manifest.supports_action`).
- **Two currencies, never conflate.** 💎 crustics = platform points (`userPoints`, earned watching/chat); 💰 dinars = in-game `Hero.Gold`. 1 💎 = 5 dinars. An action charges ONE currency by meaning. (Frontend currently shows crustics with two glyphs, `💎` and `⦷` — unify if you touch that area.)
- **Charge + effect in ONE transaction.** `add_points`/`remove_points` open their own connection and commit alone — never pair them with a separate state change: a crash in that window = money debited without effect, or a double reward. Use `Database.add_points_tx(conn,…)` / `remove_points_tx(conn,…)`, which run on the CALLER's `conn` and join the same `BEGIN IMMEDIATE` → one commit, all-or-nothing. Same for TOCTOU: re-check the guard (cooldown/dedup) INSIDE that transaction. (Found 7× — `docs/AUDIT_CORE_MECHANICS_2026-07-02.md`.)
- **Платное действие обязано детектить тихий no-op ДО ack-true (иначе зритель платит за ноль).** Движковый API «сделай X» часто молча ничего не делает (кап / дубль / нет цели / оффлайн), хендлер отдаёт success → списание без эффекта и без рефанда. У каждого НОВОГО платного действия найти его no-op пути и возвращать на них fail → авто-рефанд. Детект — по НАБЛЮДАЕМОМУ эффекту (before/after публичными геттерами, или «WorkOrder появился» для void-API), НЕ по копии внутренней формулы движка — она сломается на апдейте игры. (Класс всплыл 3× подряд в shedcolony 2026-07-04.)
- **Cache-bust both shells.** `viewer.js?v=...` must be identical in `extension.html` and `mobile.html`; `deploy.ps1` keeps them in sync. Desync = part of the audience runs stale JS.
- **Mod crash protection pattern.** Vanilla Bannerlord daily-tick code (e.g. `PregnancyCampaignBehavior`, `BannerCampaignBehavior`) throws NPE/InvalidCast on the mod's clanless or edge-case viewer heroes. The fix pattern is a defensive Harmony finalizer/prefix that swallows the *specific* exception and lets the engine continue — see `BannerlordLink/src/Patches/PregnancyModelPatch.cs` and `BannerCampaignBehaviorPatch.cs`. `BannerlordLinkModule.cs` has a resilient `PatchAll` with a `SKIP_PATCH_NAMES` kill-switch.
- **Vanilla NRE: decompile to root-cause, don't blind-swallow.** A finalizer that only swallows trades a crash for a *silently broken feature*. Decompile the vanilla method to find the exact null first: `& "$env:USERPROFILE\.dotnet\tools\ilspycmd.exe" "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\bin\Win64_Shipping_Client\<Assembly>.dll" -t "<Full.Type.Name>"` (ilspycmd is a dotnet global tool, NOT on PATH). Then write a **prefix that guards that specific null** and lets the valid case fall through to vanilla — better still, one that **repairs the input** so vanilla does the right thing (self-heal) instead of skipping. See `Patches/KingdomVoteNotificationPatch.cs` and `BannerCampaignBehaviorPatch.cs`. Keep a finalizer backstop logging the full stack (`__exception.ToString()`). Swallowing is the LAST resort — bit twice (bug #10 kingdom-vote popup; 2026-06-16 banner InvalidCast), both times the swallow hid a dead feature for weeks. Mod fixes have no auto-test: a decompile-grounded fix is *plausible*, not *proven*, until played.
- **Gate viewer actions by game state, both ends.** Actions requiring a clan/kingdom/leader/ruler (marriage, children, party, kingdom ops) are gated in `viewer.js` (disabled + reason tooltip) AND refused server-side in `routes/bannerlord.py` — the frontend is bypassable.
- **CodeGraph MCP** (`codegraph_*` tools) indexes this repo — prefer it for "what calls X / where is X / impact of changing X" over grep (details in the global CLAUDE.md).
- **Dashboard HTML = Python f-string: дублируй скобки + render-тест перед деплоем.** В `routes/streamer.py:_dashboard_html` любой литеральный `{`/`}` в JS/CSS дублируй (`{{`/`}}`); одинарные `{...}` — только Python-интерполяция. Render-тест ловит и синтаксис, и NameError: `PYTHONIOENCODING=utf-8 TWITCH_OAUTH_TOKEN=x TWITCH_CLIENT_ID=x TWITCH_CLIENT_SECRET=x TWITCH_BOT_ID=x python -c "import routes.streamer as s; s._dashboard_html({'login':'x'})"`. Кусало на каждой новой карточке.
- **Тонкий фронт: балансовые числа — истина на бэке, не display-копия во фронте.** Цены/кулдауны/лимиты, которые enforce'ит бэк, НЕ дублировать хардкодом во фронте: одно число в 2-3 местах (JS / backend / C#-мод) = после релиза замёрзший на CDN фронт покажет старую цену и разойдётся с бэком. Вёрстка и статичные подписи — ок во фронте. **Статус 2026-07-25:** бэк уже отдаёт всё через `/api/bannerlord/config` и `/api/rimworld/config`; выпилить хардкоды во фронте — фаза 2, после разморозки (список в DEFERRED §A0).
- **Платное + асинхронное действие → обязателен подтверждающий тост «не мгновенно».** Если операция тратит крустики И имеет отложенный/неопределённый исход (клан-вотум, ставка, отложенный эффект), на успехе нужен action-specific тост: это заявка, исход позже, жать снова не надо. Иначе зритель видит «ничего не произошло» и переплачивает (bugs #16/#17: зритель объявил войну 4× подряд). Generic-тост charge'а не считается. Реализация: тост в хендлере ПОСЛЕ `await _bannerlordBuyAction` — replace-style `showNotification` перетирает generic.

## Session workflow rules (2026-06-11 — rationale in ROADMAP.md §0)

The owner is a non-programmer building this solo with Claude; these rules are the project's guardrails — **enforce them proactively, don't wait to be asked**. They exist because every expensive past mistake (casino built → cut for Twitch compliance; BLT-modeled mechanics → LGPL audit still blocking release; 13 CRITICAL security findings) shares one root: *build first, check constraints later*.

1. **Check before code.** Before implementing any NEW viewer-facing mechanic: (a) run a Twitch-compliance check (`/twitch-compliance`), (b) if the idea mirrors BLT, flag the license implication, (c) present a 5–10 line spec and get explicit approval. If asked to "just build it", do the checks anyway first — that's cheaper than another casino.
2. **Done = evidence.** Never report done without proof: test output, log line, prod DB query, screenshot. A red test blocks deploy — no exceptions. (Extends the global "verify before done".)
2b. **Тест, который никогда не видели красным, не доказывает НИЧЕГО.** Написал тест на баг — покажи его в ДВУХ состояниях: (а) временно убрать фикс → тест падает и НАЗЫВАЕТ проблему; (б) вернуть фикс → зелёный; (в) `git diff` после этого пуст. Зелёный тест, написанный ПОСЛЕ фикса, мог быть зелёным и без него — это известный способ ИИ обмануть и себя, и владельца (владелец спросил прямо, 2026-07-25). Тот же приём для линтеров: подложи исторический баг, покажи exit 1. **Красный тест чиним КОДОМ, а не правкой ожидания.**
3. **Prod deploys after stream, not during.** If a stream is live, only hotfix a broken prod; otherwise prepare everything and say "ready to deploy on break". A mid-stream backend restart drops viewer connections; a mod copy needs the game closed anyway.
4. **Feature in — feature out.** When a new mechanic is requested, ask which low-usage feature gets frozen/removed in exchange (use usage metrics once they exist; until then, ask). The 7k-line viewer.js is what unbounded "yes" looks like.
5. **Suggest the monthly audit — TWO kinds, don't conflate** (ROADMAP §6). **Код-аудит** reads code for what's wrong in it (security / dead code / debt). **Аудит работы** runs each paid mechanic end-to-end against live data and catches what code-audits structurally cannot: mechanics dead in prod, code-vs-migration/load-order drift, silent no-ops. Propose аудит работы before every Twitch submission (it would have caught the dead RimWorld shop) and either kind after ~a month. The 2026-04 audit (13 CRITICAL) out-earned any feature.
6. **Update the CONTEXT doc** (`docs/CONTEXT*.md`) after any significant change — it's the handoff that keeps future sessions from re-discovering everything.
6b. **Записал отложенное — в `DEFERRED.md`, в ту же сессию.** Любое «сделаем потом / ждём разморозки фронта / решим по данным / решили не делать» уходит строкой в этот файл: причина + что разблокирует. Иначе отложенное либо теряется, либо через месяц всплывает как «а давай обсудим» и обсуждается с нуля. Раздел «Решено НЕ делать» не чистится — он и существует, чтобы не возвращаться к закрытым вопросам (владелец просил завести журнал явно, 2026-07-22).
7. **End every work session with a plain-language summary**: what changed, what is deployed where (prod / game DLL / not yet), and what the owner must do by hand (restart game, test on stream, click something). The owner can't read diffs — the summary IS the interface.
8. **Пост-стрим-триаж — предлагать САМ, не ждать просьбы.** Если по датам файлов / контексту видно, что был свежий стрим (новый `bannerlordlink_ГГГГММДД.txt`, свежий `Player.log`, слова владельца «поиграли / стримили»), предложить разбор логов на ошибки — не дожидаясь «сделай триаж». Ловит баги ДО того, как зритель напишет багрепорт. Дешёвыми субагентами по логам, вывод — сам. (Владелец просил проактивность, 2026-07-23.)
9. **Обновлять `STATUS.md` в конце сессии** — витрина «что сейчас» (10 строк). Устарела строка — поправить. Это то, с чего начинается следующий заход.
10. **Перед стримом — тест-план на 5 минут + preflight.** Мод-фиксы систематически зависают «дедуцировано, не проверено» (battle-фиксы 19.07, урон/роспуск 24.07). Перед стримом: (а) выдай владельцу ОДНО сообщение — список непроверенных мод-фиксов с «глянь X, скажи да/нет» (собирать из STATUS/DEFERRED §C); (б) прогони `powershell -File scripts\preflight.ps1` — health/сервис/мод-онлайн/ошибки одним прогоном (перед ревью Twitch — обязательно). После стрима свериться с логом и **закрыть подтверждённые bug_reports на проде сразу** — это часть определения «фикс готов», не отдельный шаг (2026-07-24: #23 висел open при доказанном фиксе).
11. **Рискованные бэк-правки — сначала staging.** Миграции, меняющие данные, и переделки синка/очередей — через `deploy.ps1 -Staging` (:8001, своя БД), потом прод. Staging поднят в июне и простаивает; сухой прогон на снапшоте — минимум, staging — для правок, где важно поведение живого процесса.
