# ShedLink / shedstream — обзор проекта

> Точка входа для понимания «что это и как устроено». Инструкции для работы —
> в [CLAUDE.md](CLAUDE.md). Живой статус по областям — в `Расширение/docs/CONTEXT*.md`.

---

## Суть

**ShedLink** (git-репо `shedstream`) — мультитенантное **Twitch-расширение**,
которое превращает зрителей стрима в **участников игры стримера**. Один backend
обслуживает много каналов одновременно. Зритель через панель расширения тратит
валюту, заработанную на стриме, чтобы влиять на игру: призывать бойцов в бой,
прокачивать «своего» героя, управлять кланом/королевством, и т.д.

Архитектурная цель — **game-agnostic**: новые игры подключаются как модули через
**Module API**, не переписывая ядро. Сегодня живут два модуля:

| Модуль | Что | Код |
|---|---|---|
| **Bannerlord** | C#-мод (Harmony) + backend-адаптер | `BannerlordLink/`, `Расширение/backend/modules/bannerlord/` |
| **RimWorld** | C#-мод (RimLink) + backend-адаптер | `RimLink/`, `modules/rimworld/` (Module API) + `rimworld.py` (legacy-эндпоинты) |

---

## Ключевые концепции

- **Мультитенантность.** Каждая tenant-таблица скоупится `channel_id`. Один
  деплой = много каналов; данные каналов изолированы. Резолв канала — через
  `resolve_channel_id_or_default()` или JWT-контекст (`require_jwt_user` /
  `require_jwt_channel`).
- **Зритель-участник.** Зритель «усыновляет» NPC-героя (Bannerlord) / пешку
  (RimWorld) и управляет им за валюту. Имя героя в игре = `[BLink] {login}`.
- **Две валюты (не путать!).**
  - 💎 **крустики** — платформенные очки (`viewers.points`), копятся за
    просмотр/чат. Тратятся на призыв, активные силы, рекрут свиты, конверсию.
  - 💰 **динары** — внутриигровое золото (`Hero.Gold`). Тратятся на тиры
    снаряжения, фокусы, атрибуты, клан/королевство.
  - 1 💎 = 5 💰. Действие списывает **одну** валюту по смыслу.
- **Module API.** Игра = `_adapter.py` (обработчики событий) + `manifest.yaml`
  (декларация её событий/действий/каталогов). Generic-диспетчер общий.
- **Двусторонний поток.** Зритель → backend → мод → игра, и обратно: мод
  зеркалит состояние игры → backend → фронт.

---

## Архитектура (3 слоя)

```
 ┌──────────────┐   JWT     ┌─────────────────────┐  module-token  ┌──────────────┐
 │   Зритель    │  HTTPS    │   FastAPI backend   │   long-poll    │   Game mod   │
 │ Twitch панель│ ───────►  │  SQLite (aiosqlite) │ ◄────────────► │  C# / RimW.  │
 │  (viewer.js) │ ◄───────  │   multi-tenant      │   events       │ (в процессе  │
 └──────────────┘  poll 8s  └─────────────────────┘                │   игры)      │
        ▲                            ▲                              └──────┬───────┘
        │ рендер панели              │ хранит состояние,                   │ Harmony /
        │ (extension.html)           │ списывает/рефандит валюту           │ Behaviors
        ▼                            ▼                                     ▼
   Twitch Extension            module_actions (outbox)                 Игра (Bannerlord /
   (overlay + панель)          module_catalogs (магазин)               RimWorld)
```

---

## Поток данных (действие зрителя)

1. **Клик** → `viewer.js` → `POST /api/bannerlord/action {action_type, data}`
   с заголовком `X-Twitch-JWT`.
2. **Backend** (`routes/bannerlord.py`): валидирует, проверяет whitelist
   (`_PURCHASABLE_ACTIONS`) + server-side цену (`ACTION_PRICES_DEFAULT`),
   **атомарно списывает** валюту, кладёт действие в `module_actions` (outbox).
3. **Мод** (`Net/ActionPoller`) long-poll'ит `/v1/module/<id>/actions?since=…`
   → получает действие → `ActionRegistry.Get(type)` → конкретный
   `IActionHandler` → применяет в игре на **main-thread** (`MainThreadDispatcher`).
4. **Эхо состояния.** Мод пушит `player.state_update` (`Util/HeroStateSync`) →
   `_adapter` хранит в `bannerlord_heroes` → фронт видит на следующем
   поллинге `/api/bannerlord/my-hero`.
5. **Отказ → рефанд.** Если мод не смог применить (бой, нет клана, и т.п.) →
   `ActionFeedback.PostFailed` → событие `action.failed` → backend **возвращает**
   валюту; фронт показывает причину тостом.

Конфиг класс-сил/каталога мод тянет из `/api/bannerlord/class-state` в
`PowerCache` (на session-start). Поэтому ребаланс значений = миграция в БД,
без пересборки мода.

---

## Структура репозитория

```
shedstream/
├── CLAUDE.md                  ← инструкции для агентов/разработки
├── OVERVIEW.md                ← этот файл
├── Расширение/                ← основное приложение (кириллица в имени — не баг)
│   ├── backend/               ← FastAPI + SQLite (aiosqlite)
│   │   ├── main.py            ← uvicorn :8000; run_migrations() на старте
│   │   ├── dependencies.py    ← get_db, require_jwt_user/channel, resolve_channel_id
│   │   ├── routes/            ← bannerlord.py, module_api.py, promo.py, tts.py, …
│   │   ├── modules/<game>/    ← _adapter.py (event-handlers) + manifest.yaml
│   │   ├── migrations/        ← m<N>_*.py (async def apply(conn)), wired в main.py
│   │   └── tests/             ← standalone-скрипты (НЕ pytest)
│   ├── frontend/              ← Twitch-расширение (static JS/HTML, без сборки)
│   │   ├── viewer.js          ← ~7k строк, ОБЩИЙ для RimWorld + Bannerlord
│   │   ├── extension.html     ← desktop-shell  ┐ держать в синхроне
│   │   ├── mobile.html        ← mobile-shell   ┘ (cache-bust ?v= совпадает)
│   │   └── overlay.html       ← OBS overlay (карточки бойцов, TTS, питомцы)
│   └── docs/                  ← база знаний; CONTEXT*.md — живой статус по областям
├── BannerlordLink/            ← C#-мод Bannerlord (net472, Harmony)
│   └── src/
│       ├── BannerlordLinkModule.cs   ← MBSubModuleBase entry + PatchAll
│       ├── Net/               ← BackendClient, ActionPoller, PowerCache, ActiveBuffState
│       ├── Actions/           ← IActionHandler'ы + ActionRegistry (hero.* / player.*)
│       ├── Behaviors/         ← Campaign/Mission behaviors (KillReward, PowersMission, …)
│       ├── Patches/           ← Harmony-патчи + защитные финализаторы (anti-crash)
│       ├── Models/            ← подмена движковых моделей (clan upgrades бонусы)
│       └── Util/              ← HeroNaming, HeroLookup, HeroStateSync, EquipmentSync
├── RimLink/                   ← C#-мод RimWorld + ассеты
├── БЛТ/                       ← BLT reference (read-only, LGPL clean-room — идеи/API)
└── scripts/                   ← deploy.ps1, lint_consistency.py, triage-crash.ps1
```

---

## Backend

- **Стек:** FastAPI + SQLite через `aiosqlite`. Запуск: `python main.py`
  (uvicorn :8000), на старте прогоняет все миграции (`✅ Migrations complete`).
- **Мультитенант — обязателен.** Любой запрос/INSERT по tenant-таблице включает
  `channel_id`; пропуск → cross-channel leak или `NOT NULL` fail.
- **Миграции.** `m<N>_*.py` с `async def apply(conn)`; регистрируются в
  `main.py:run_migrations()` (последовательно, идемпотентно через
  `migrations_applied`). Никогда не править уже применённую — добавлять новую.
  `lint_consistency.py` валит CI/commit, если миграция не проведена.
- **Module API.** Generic-диспетчер (`routes/module_api.py`) + per-game адаптер
  (`modules/<game>/_adapter.py`) + Bannerlord-специфичные эндпоинты
  (`routes/bannerlord.py`). Outbox-таблицы: `module_actions`, `module_catalogs`.
- **Auth.** Зритель → Twitch JWT (`X-Twitch-JWT`). Мод → module-token (HMAC).

## Frontend

- **Без сборки** (ограничение Twitch Extension): статический JS/HTML, отдаётся
  бэкендом. Синтаксис-чек: `node --check frontend/viewer.js`.
- `viewer.js` (~7k строк) — **общий** для RimWorld и Bannerlord; `extension.html`
  и `mobile.html` — параллельные оболочки, держать в синхроне (cache-bust
  `viewer.js?v=…` идентичен; `deploy.ps1 -Frontend` синхронит автоматически).
- **Поллинг** (когда панель видима): `/my-hero`, `/status`, классы — ~8с;
  баффы — 2.5с; battle-status — 2с; overlay-питомцы — 1с.
- Flicker-архитектура: build-once скелеты + per-poll суб-лоадеры через
  `_smartInnerHTML` (дедуп → ребайнд только при изменении).

## Игровые модули

- **Bannerlord** (`BannerlordLink/`, .NET Framework 4.8, игра 1.3.15):
  - Зритель усыновляет героя, выбирает **культуру** + **класс** (13 классов с
    passive/active powers), тратит валюту на бой/экономику/прогрессию/династию.
  - `ActionPoller` тянет действия, `IActionHandler`'ы применяют на main-thread;
    `HeroStateSync` зеркалит состояние назад.
  - **Anti-crash паттерн:** защитные Harmony-финализаторы глушат *конкретные*
    ванильные исключения дейли-тика (Pregnancy/BannerCampaign/KingdomVote/Siege),
    чтобы стрим не падал. `BannerlordLinkModule` имеет resilient `PatchAll`.
  - Сборка: `dotnet build BannerlordLink/src/BannerlordLink.csproj -c Release`;
    DLL копируется в `Modules/Shedoy23.BannerlordLink/` (нужна закрытая игра),
    рестарт игры (нет hot-reload). Clean-room re-impl по мотивам **BLT** (LGPL).
- **RimWorld** (`RimLink/`): пешки/гены/скиллы/ксенотипы; часть эндпоинтов —
  legacy (UNAUTH), идёт миграция на Module API.

## Деплой / инфра

- **Прод:** `root@31.130.132.224:/root/twitch-extension/`, под **supervisor** как
  сервис `twitchbot` (Timeweb VDS).
- **Деплой:** `scripts/deploy.ps1` (tar backend+frontend без `*.db`/`.env` → scp →
  extract → `supervisorctl restart twitchbot` → health-check). Флаги:
  `-Backend` / `-Frontend` / `-Mod` (сборка+копия DLL в игру с md5) / `-All`.
  Перед прод-действиями — подтверждение.
- Бэкапы БД автоматизированы (`backend/backup_db.sh` cron + `backup_loop.py`).

## Где искать детали

- **Инструкции / конвенции / гочи:** [CLAUDE.md](CLAUDE.md).
- **Живой статус по областям:** `Расширение/docs/CONTEXT.md` (ядро/платформа),
  `CONTEXT_BANNERLORD.md`, `CONTEXT_RIMWORLD.md`.
- **Архитектура:** `Расширение/docs/ARCHITECTURE.md`, `MULTITENANT_PLAN.md`,
  `MODULE_API.md`, `ARCH_DATA_OWNERSHIP.md`.
- **Bannerlord-мод:** `BANNERLORD_DEV_ENV.md` (сборка), `TESTING_PLAYBOOK.md`
  (проверка в игре), `BANNERLORD_API_CHEATSHEET.md`, `BLT_RC22_REFERENCE.md`.
