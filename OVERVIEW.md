# ShedLink / shedstream — обзор проекта

> Точка входа для понимания «что это и как устроено». Инструкции для работы —
> в [CLAUDE.md](CLAUDE.md). Живой статус по областям — в `Расширение/docs/CONTEXT*.md`.
> Стратегия, деньги и границы — в [PLATFORM_VISION.md](PLATFORM_VISION.md).
> Здесь — устройство системы; статуса «что готово / что сломано» здесь нет
> намеренно, он в `STATUS.md`.
>
> **Сверено с кодом 2026-07-27.**

---

## Суть

**ShedLink** (git-репо `shedstream`) — мультитенантное **Twitch-расширение**,
которое превращает зрителей стрима в **участников игры стримера**. Один backend
обслуживает много каналов одновременно. Зритель через панель расширения тратит
валюту, заработанную на стриме, чтобы влиять на игру: призывать бойцов в бой,
прокачивать «своего» героя, управлять кланом/королевством, и т.д.

Архитектурная цель — **game-agnostic**: новые игры подключаются как модули через
**Module API**, не переписывая ядро. Сегодня объявлено три модуля:

| Модуль | Состояние | Код |
|---|---|---|
| **Bannerlord** | **флагман**, на нём играют на стриме | `BannerlordLink/`, `Расширение/backend/modules/bannerlord/` |
| **RimWorld** | фактически выключен; legacy-монолит ждёт переезда на Module API | `RimLink/`, `modules/rimworld/` + `rimworld.py` (legacy-эндпоинты) |
| **shedcolony** | ранний (MineColonies × Twitch); мод в отдельном репо `D:\sheddev` | `modules/shedcolony/` |

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
│   │   └── templates/         ← HTML страниц стримера (дашборд); НЕ Python-строки
│   ├── frontend/              ← Twitch-расширение (static JS/HTML, без сборки)
│   │   ├── viewer.js          ← 2.5k строк, ОБЩАЯ оболочка (не 7k — распилен 13.06)
│   │   ├── viewer-bannerlord.js ← 4.7k, основной объём игровой логики
│   │   ├── viewer-rimworld.js   ← 0.4k
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
├── reference/BLT_RC22         ← BLT reference (read-only, LGPL clean-room — идеи/API)
│   + reference/BLT_lait          вне git; папки `БЛТ/` из старых версий этого файла НЕТ
└── scripts/                   ← deploy.ps1 · lint_consistency.py · preflight.ps1
                                  triage-crash.ps1 · pack-extension.py (сборка .zip
                                  расширения) · local-setup.py (копия прода на ПК)
                                  fake-mod.py (эмулятор мода) · verify-backup.py
                                  pull-backup.ps1 (офсайт-бэкап)
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
- **Распилен 13.06:** `viewer.js` (2.5k) — общая оболочка, игровая логика в
  `viewer-bannerlord.js` (4.7k) и `viewer-rimworld.js` (0.4k). Число «~7k строк
  в viewer.js» кочевало по документам полтора месяца после распила — это сумма
  трёх файлов, а не размер одного.
- Все ~18 JS-файлов грузятся простыми `<script>` в **одно общее пространство
  имён** — модулей нет. Отсюда класс мин: коллизии глобалей и неявный контракт
  «порядок подключения». Явные коллизии объявлений стережёт линтер.
- `extension.html` и `mobile.html` — параллельные оболочки, держать в синхроне
  (cache-bust `viewer.js?v=…` идентичен; `deploy.ps1 -Frontend` синхронит сам).
- **Поллинг** (когда панель видима): `/my-hero`, `/status`, классы — ~8с;
  баффы — 2.5с; battle-status — 2с; overlay-питомцы — 1с.
- Flicker-архитектура: build-once скелеты + per-poll суб-лоадеры через
  `_smartInnerHTML` (дедуп → ребайнд только при изменении).

## Игровые модули

- **Bannerlord** (`BannerlordLink/`, `net472`, игра **v1.3.15** — сверено с
  `Version.xml` игры 27.07; переезд на 1.4.5 обсуждался, но НЕ сделан):
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
- **RimWorld** (`RimLink/`): пешки/гены/скиллы/ксенотипы. Модуль фактически
  выключен. `rimworld.py` — исторический монолит (~2000 строк): часть точек без
  авторизации и **без привязки к каналу** (помечено в шапке файла
  `tenant-lint: skip-file`, чинится при реактивации). Переезд на Module API —
  отдельный этап, единственный, где нужна живая игра.
- **shedcolony**: зритель управляет своим колонистом в колонии MineColonies.
  Game-side — NeoForge-мод в отдельном репозитории (`D:\sheddev`), ходит в этот
  же backend по Module API. Ранняя стадия, не продакшн.

## Деплой / инфра

- **Прод:** `root@31.130.132.224:/root/twitch-extension/`, под **supervisor** как
  сервис `twitchbot` (Timeweb VDS).
- **Деплой:** `scripts/deploy.ps1` (tar backend+frontend без `*.db`/`.env` → scp →
  extract → `supervisorctl restart twitchbot` → health-check). Флаги:
  `-Backend` / `-Frontend` / `-Mod` (сборка+копия DLL в игру с md5) / `-All`.
  Перед прод-действиями — подтверждение.
- **Бэкапы — три уровня, все работают:** cron на проде (`backend/backup_db.sh`),
  внутрипроцессный `backup_loop.py`, и **офсайт-забор на ПК владельца** (задача
  Windows, ежедневно, 14 суточных срезов). Каждый забор сам себя проверяет
  (`scripts/verify-backup.py`: распаковать → проверить целостность → убедиться,
  что зрители внутри есть). Восстановление отрепетировано — `docs/RESTORE_PLAYBOOK.md`.
  Ограничение по устройству: ПК должен быть включён, пропущенный день = дырка
  в календаре, а не поломка.
- **Мониторинг:** UptimeRobot пингует `/health` снаружи. Ловит только «прод лёг»;
  «прод жив, а платная механика молча не работает» — не ловит (см. ROADMAP §7.2).
- **Перед стримом/ревью:** `scripts/preflight.ps1` — здоровье прода, сервис,
  мод в сети, свежие ошибки одним прогоном.

## Где искать детали

- **Что сейчас (первым делом в сессии):** [STATUS.md](STATUS.md).
- **Стратегия, деньги, границы:** [PLATFORM_VISION.md](PLATFORM_VISION.md).
- **Операционная правда по проду:** [RUNBOOK.md](RUNBOOK.md).
- **План и приоритеты:** [ROADMAP.md](ROADMAP.md); отложенное — [DEFERRED.md](DEFERRED.md).
- **Инструкции / конвенции / гочи:** [CLAUDE.md](CLAUDE.md).
- **Живой статус по областям:** `Расширение/docs/CONTEXT.md` (ядро/платформа),
  `CONTEXT_BANNERLORD.md`, `CONTEXT_RIMWORLD.md`.
- **Архитектура:** `Расширение/docs/ARCHITECTURE.md`, `MULTITENANT_PLAN.md`,
  `MODULE_API.md`, `ARCH_DATA_OWNERSHIP.md`.
- **Bannerlord-мод:** `BANNERLORD_DEV_ENV.md` (сборка), `TESTING_PLAYBOOK.md`
  (проверка в игре), `BANNERLORD_API_CHEATSHEET.md`, `BLT_RC22_REFERENCE.md`.
