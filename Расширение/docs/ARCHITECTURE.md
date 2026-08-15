# Architecture Overview

**Цель документа:** дать однозначную карту того, что где живёт и как добавить новое не сломав существующее. Если что-то противоречит этому документу — он источник правды; нужно поправить код или документ (с обоснованием в коммите).

**Связанные документы:**
- [PLATFORM_VISION.md](../../PLATFORM_VISION.md) — стратегия и бизнес-модель
- [MODULE_API.md](MODULE_API.md) — спецификация Game Bridge SDK
- [MODULE_MIGRATION.md](MODULE_MIGRATION.md) — поэтапный план миграции RimWorld в `modules/rimworld/`
- [MULTITENANT_PLAN.md](MULTITENANT_PLAN.md) — multi-tenant рефакторинг ядра
- [CORE_FEATURES.md](CORE_FEATURES.md) — дизайн будущих core-фич
- [SECURITY_AUDIT_2026-04-30.md](SECURITY_AUDIT_2026-04-30.md) — аудит, фиксы phase A-D

---

## 1. Quick Map (one-screen view)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  CLIENTS                                                                  │
│                                                                            │
│  Twitch viewers (extension iframe)        Streamer (browser)              │
│         │  X-Twitch-JWT                       │  Cookie session           │
│         ▼                                     ▼                           │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  FastAPI (single process, uvicorn)                                │    │
│  │  ┌──────────────────────────────────────────────────────────────┐ │    │
│  │  │  AUTH & MULTI-TENANT (dependencies.py)                       │ │    │
│  │  │  - require_jwt_user/_channel  → 403 if not registered        │ │    │
│  │  │                                → 429 if rate-limited          │ │    │
│  │  │                                → ContextVar.set(channel_id)   │ │    │
│  │  │  - resolve_channel_id        STRICT (raises if unresolved)   │ │    │
│  │  │  - resolve_channel_id_or_default  для legacy boundaries      │ │    │
│  │  └──────────────────────────────────────────────────────────────┘ │    │
│  │                              │                                     │    │
│  │       ┌──────────────────────┴──────────────────────┐             │    │
│  │       ▼                                              ▼             │    │
│  │  ┌────────────────────────┐     ┌─────────────────────────────┐   │    │
│  │  │ ROUTES (game-agnostic) │     │ ROUTES (game-specific legacy)│   │    │
│  │  │ casino/duel/market/    │     │ rimworld.py (1981 lines)    │   │    │
│  │  │ marriage/event/viewer/ │     │ — мигрирует в modules/      │   │    │
│  │  │ admin/promo/misc/      │     │   rimworld/ поэтапно        │   │    │
│  │  │ streamer/module_api    │     │                             │   │    │
│  │  └────────────────────────┘     └─────────────────────────────┘   │    │
│  │             │                              │                      │    │
│  │             ▼                              ▼                      │    │
│  │  ┌──────────────────────────────────────────────────────────┐    │    │
│  │  │ CORE SERVICES                                              │    │    │
│  │  │  bot_core (background loops, IRC bridge, attendance)      │    │    │
│  │  │  event_manager (auctions/roulettes per-channel)           │    │    │
│  │  │  EventSub register/webhook (channel points multi-channel) │    │    │
│  │  │  TwitchChatBot (multi-channel IRC join + scoping)         │    │    │
│  │  │  OAuth refresh loop (proactive every hour)                │    │    │
│  │  └──────────────────────────────────────────────────────────┘    │    │
│  │             │                              │                      │    │
│  │             ▼                              ▼                      │    │
│  │  ┌──────────────────────────────────────────────────────────┐    │    │
│  │  │ DATABASE LAYER (database.py + DBPool + aiosqlite)        │    │    │
│  │  │  - Все TENANT-таблицы скоупятся по channel_id             │    │    │
│  │  │  - Helpers: add_points / give_item / upsert_player_pawn / │    │    │
│  │  │    enqueue_action / replace_module_catalog / etc.         │    │    │
│  │  │  - Migrations: m1_multitenant, m4_channels, m5_module_    │    │    │
│  │  │    actions, m6_module_catalogs (см. backend/migrations/) │    │    │
│  │  └──────────────────────────────────────────────────────────┘    │    │
│  │                              │                                     │    │
│  │                              ▼                                     │    │
│  │                       SQLite (WAL, single file)                    │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                            │
│         MODULE API (Game Bridge SDK)                                       │
│         ┌──────────────────────────────────────────────────┐              │
│         │ /v1/module/<id>/hello   /events  /actions  /ack  │              │
│         │              /catalog/<type>                     │              │
│         │ /v1/modules         /v1/module/<id>/info         │              │
│         └──────────────────────────────────────────────────┘              │
│                              │                                             │
│                              ▼                                             │
│                       modules/<id>/_adapter.py                             │
│                       (RimWorldAdapter, в будущем Bannerlord/Minecraft)    │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼ HTTP (long-poll outbox)
                       Game-side Connector (C# мод RimWorld, BLT submodule)
```

---

## 2. Layers — что где живёт

### 2.1 Transport
- **FastAPI** + **uvicorn** в одном процессе на VPS
- **CORS** разрешён только для `twitch.tv`, `shedoy23.ru`, `*.ext-twitch.tv`, `null` (OBS)
- **Static** mounted на `/static` для frontend extension files
- Inline HTML — для `/streamer` и `/streamer/dashboard` (см. `routes/streamer.py`)

### 2.2 Auth — три типа
| Тип | Носитель | Endpoint | Проверка |
|---|---|---|---|
| **Twitch Extension JWT** | Header `X-Twitch-JWT` | viewer-facing | `auth.verify_twitch_jwt` (HMAC через TWITCH_EXTENSION_SECRET) |
| **Streamer session cookie** | Cookie `streamer_session` | `/streamer/dashboard`, `/api/streamer/*` | HMAC `channel_id\|expires_at`, TTL 30 дней |
| **Module token** | Header `Authorization: Bearer ...` | `/v1/module/<id>/*` (от connector мода) | HMAC `channel_id\|module_id\|expires_at`, TTL 1 год |
| **Admin Basic Auth** | HTTP Basic | `/api/admin/*`, `/admin/*` | env-secret + brute-force lock |

Все три — server-side секреты в env. JWT проверяется через `TWITCH_EXTENSION_SECRET`, cookie + module-token через `MODULE_TOKEN_SECRET` (по умолчанию = TWITCH_EXTENSION_SECRET).

### 2.3 Multi-tenant — ContextVar pattern
- `_current_channel_id: ContextVar` хранит channel_id текущей request-task'и
- **Поставщики:** `require_jwt_user/_channel` (request handlers), `set_request_channel_id` (IRC bot)
- **Потребители:** все `db.*` helpers вызывают `resolve_channel_id(channel_id)` который:
  1. Возвращает явный параметр если передан > 0
  2. Иначе ContextVar.get()
  3. Иначе **raises RuntimeError** (strict-режим, M4 follow-up а)
- Background tasks **обязаны** передавать `channel_id` явно ИЛИ `set_request_channel_id` перед DB-вызовами

### 2.4 Routes layer
- `routes/<feature>.py` — каждая фича = свой router. Импортируются и регистрируются в `main.py`
- **Конвенция:** один файл = одна функциональная область. Не плодить, но и не сваливать.
- Все routes принимающие действия пользователя (write-paths) **обязаны** вызывать `require_jwt_user` ИЛИ `require_jwt_channel` в начале.

### 2.5 Core services (background)
- `bot_core.py` (`BotCore`) — startup-time singleton, держит фоновые loops (все loops **multi-tenant** — итерируют `db.list_channels()` и обрабатывают каждый канал независимо, see Bug 4 fix 2026-05-10)
  - `reward_points_loop` — раз в минуту, начисляет поинты активным viewers per-channel
  - `drop_loop` — раз в N минут, кидает drop-предмет случайному активному viewer per-channel
  - `pending_chat_flush_loop` — safety-net для очереди сообщений до коннекта IRC
  - `auto_message_loop` — авто-сообщения в чат при стриме live, per-channel index
- `event_manager.py` (`EventManager`) — `start_event` / `end_event` / `event_watcher_loop`
  - **Внимание:** один global `active_event` (не dict-per-channel пока). См. **Known limitations** ниже.
- `main.py:register_eventsub_channel_points` — регистрация Twitch EventSub webhook (single или multi-channel зависит от `EVENTSUB_AUTO_REGISTER` flag)
- `main.py:TwitchChatBot` — twitchio multi-channel join + per-message ContextVar set
- `routes/streamer.py:oauth_refresh_loop` — каждый час обновляет OAuth-токены за 30 мин до expiry

### 2.6 Database layer
- `database.py` (`Database` class) — все DB-вызовы идут через helpers ЭТОГО файла
- `DBPool` — connection pool, переиспользует aiosqlite connections
- WAL mode, busy_timeout=5000, synchronous=2 (включаются при `init_pool`)
- **Конвенция (важно):** routes/* и services/* НЕ должны делать `aiosqlite.connect()` напрямую. Используйте `db.<helper>()` — это даёт future-proofing для миграции на Postgres + единая точка для тестов/моков.
- **Где сейчас нарушения** — см. `Известные технические долги` (DB-discipline audit, Блок 2 в плане).

### 2.7 Migrations
- `backend/migrations/m<N>_<name>.py` — каждая миграция = отдельный файл
- Все идемпотентные через таблицу `migrations_applied`
- Регистрация в `main.py:run_migrations` — порядок имеет значение (M1 создаёт `migrations_applied`, потом M4/M5/M6)
- **Правила:**
  - Никаких `DROP TABLE` без бэкапа и явного PR review
  - `ALTER TABLE ADD COLUMN` — безопасно, идемпотентно через `try/except`
  - `CREATE TABLE IF NOT EXISTS` — обязательно
  - Backfill — через `INSERT OR IGNORE` + WHERE-фильтр
  - Migration name → ключ в `migrations_applied` (например `'M5.module_actions.create'`)

### 2.8 Module API (Game Bridge SDK)
**Это отдельный слой между ядром и игровыми модулями.** Подробности — [MODULE_API.md](MODULE_API.md).

```
modules/_base.py         ← ABC + типы (ModuleAdapter, ModuleManifest, ModuleEnvelope)
modules/_loader.py       ← discover_modules(), load_manifest(), get_module()
modules/<id>/manifest.yaml   ← capabilities (events/actions/extensions/catalogs/ui_slots)
modules/<id>/__init__.py     ← re-export Adapter class
modules/<id>/_adapter.py     ← реализация ModuleAdapter
```

Endpoints в `routes/module_api.py`:
- `GET /v1/modules` — список загруженных
- `GET /v1/module/<id>/info` — manifest dump
- `POST /v1/module/<id>/hello` — handshake (no auth)
- `POST /v1/module/<id>/events` — connector → core (with token, dedup)
- `GET /v1/module/<id>/actions?since=N` — long-poll outbox (with token)
- `POST /v1/module/<id>/ack` — connector подтверждает action (with token)
- `GET /v1/module/<id>/catalog/<type>` — frontend читает каталог канала

---

## 3. Multi-tenant invariants — нарушение = баг

1. **Каждый TENANT-table запрос содержит `channel_id` в WHERE/INSERT/UPDATE.** Не должно быть `SELECT * FROM viewers WHERE username=?` — только `... WHERE channel_id=? AND username=?`.

2. **Request handlers ВЫЗЫВАЮТ `require_jwt_user/_channel` в начале.** Без этого ContextVar пустой → strict resolver падёт RuntimeError'ом → 500 пользователю.

3. **Background tasks передают `channel_id` явно ИЛИ ставят ContextVar через `set_request_channel_id` перед DB-вызовами.** Сценарии:
   - `bot_core.reward_points_loop` — читает `channel_id` прямо из row `viewers`, передаёт в `db.add_points(channel_id=...)`
   - `event_manager.end_event` — читает `event['channel_id']` сохранённое при `_build_event`
   - `routes/duel.check_season_end` — итерируется по `db.list_channels()` в `on_startup`
   - `IRC bot event_message` — резолвит `channel_id` через `get_channel_id_by_login(message.channel.name)` + `set_request_channel_id`

4. **`resolve_channel_id_or_default` — only для legacy integration boundaries** где это сейчас неизбежно: рутины мода без HMAC (`rimworld.py`), admin/craft endpoints без JWT, IRC USERNOTICE до того как cache login→id заполнен. Каждое использование помечено TODO с миграционным планом.

5. **Per-channel rate limit (M5)** срабатывает в JWT-helpers ПОСЛЕ registration check, ПЕРЕД ContextVar.set. Tier берётся из `_channel_tier_cache` (загружается на startup из `channels.tier`).

6. **Cross-channel scope — explicit exception, не drift.** Подавляющее большинство таблиц TENANT-scoped (`channel_id` в PK). Некоторые механики **должны** быть cross-channel — например питомцы / cosmetics-inventory / user identity. Такие таблицы:
   - Имеют PK на `username` (без `channel_id`), либо `(username, item_id)` где item_id глобален
   - **Документированы** в этом разделе как exception (см. §3.1 ниже)
   - НЕ резолвят `channel_id` через ContextVar для основных операций (read/write inventory) — это global state
   - `channel_id` может присутствовать как **audit-поле** (например `pet_purchases.channel_id` — где была совершена покупка, для revenue tracking §7.5 compliance-doc), но НЕ как scope-фильтр
   - **Pattern добавления новой cross-channel таблицы:** review-чек на compliance (catalog control §13.11 + §6.2.8), data-protection (cross-channel ≠ public — JWT всё равно требуется), audit для Twitch reviewer'а в submission notes

### 3.1 Cross-channel exception tables

**Status: Phase 7 завершён 2026-05-12** (commits 9a148ed → 9f301d6). Эти 5 таблиц
из миграции M13 — первая работающая cross-channel механика в платформе.
6-я таблица `channel_pet_settings` остаётся per-channel (broadcaster-controlled).

| Таблица | PK | Scope | Назначение |
|---|---|---|---|
| `pets` | `username` | global per user | Pet appearance + state, viewer-owned |
| `pet_inventory` | `(username, item_id)` | global per user | Owned cosmetics (FK на `pet_catalog`) |
| `pet_equipped` | `(username, slot)` | global per user | Currently equipped item per slot |
| `pet_purchases` | `id` (autoincrement) | **audit** с `channel_id` | Transactions log — `channel_id` ХРАНИТСЯ для revenue attribution (§7.5 compliance-doc), но НЕ scope-фильтр |
| `pet_catalog` | `item_id` | global (extension-defined) | Catalog content; controlled by dev (§6.2.8) — НЕ streamer-uploadable |
| `channel_pet_settings` | `channel_id` | **TENANT** (по исключению от исключения) | Broadcaster opt-out для overlay-pets рендера (§7.4 broadcaster-control) |

**Защитный guard rail**: Test 18 в `tests/test_multi_tenant_isolation.py` через
PRAGMA table_info явно проверяет, что PK таблиц `pets/pet_inventory/pet_equipped`
НЕ содержит `channel_id`. Если кто-то случайно добавит `channel_id` в PK —
тест упадёт сразу. Аналогично проверяется что `channel_pet_settings.channel_id`
ОСТАЁТСЯ в PK (per-channel).

**Цена ошибки если случайно сделать pets TENANT-scoped:** viewer переключился
на другой канал → видит пустой инвентарь → теряет купленные за Bits cosmetics.
Refund-операции через Twitch Bits API долгие и снижают доверие к extension.

Все остальные таблицы в `database.py` — TENANT-scoped. Новая cross-channel
таблица = decision-point с review.

---

## 4. Game Bridge SDK invariants

1. **Manifest = source of truth.** `RimWorldAdapter.handle_event` НЕ может обработать event тип не объявленный в `manifest.yaml`. `routes/module_api.py POST /events` отбрасывает неизвестные типы до dispatch.

2. **Token scope.** Module-token подписан per `(channel_id, module_id)`. Mismatch URL ↔ token → 403. Mismatch body.channel_id ↔ token.channel_id → 403.

3. **Idempotency.** Каждый envelope имеет `id`. Per-channel dedup ring (5000 ids) в `routes/module_api.py:_processed_envelopes`. Повторный envelope → ACK с `{duplicate: true}`.

4. **Action queue lifecycle:**
   ```
   queued (enqueued)  →  dispatched (long-poll забрал)  →  acked | failed
   ```
   `fetch_pending_actions` атомарно меняет `queued → dispatched` под `BEGIN IMMEDIATE`. ACK тоже идемпотентен — повторный = `{acked: false}`, но ошибки нет.

5. **Catalog replace-семантика.** `module.catalog_update` event с `entries: [...]` ПОЛНОСТЬЮ заменяет каталог канала+модуля+типа. На `module.session_start` каталоги канала очищаются (см. MULTITENANT_PLAN.md §H).

---

## 5. Data flow examples

### 5.1 Viewer тратит channel points → автоматический drop
```
1. viewer кликает channel-points reward в Twitch UI
2. Twitch → POST /eventsub/channel-points (webhook, signed)
3. main.py:eventsub_channel_points
   - Verify HMAC + replay window
   - Извлекает broadcaster_user_id → channel_id (явный, не через ContextVar)
   - Парсит reward.title → reward_cfg
   - call db.add_points(viewer, points, channel_id=channel_id)
   - call bot.send_message("...", channel_id=channel_id) → IRC chat
```

### 5.2 Стример регистрируется в платформе
```
1. Стример: GET /streamer (landing с кнопкой)
2. POST /api/streamer/auth/start
   - Генерирует CSRF state, кладёт в _oauth_states (TTL 5 min)
   - 302 → https://id.twitch.tv/oauth2/authorize?... (force_verify=true)
3. Twitch → GET /api/streamer/auth/callback?code=X&state=Y
   - Verify state (одноразовый)
   - POST id.twitch.tv/oauth2/token (exchange code → tokens)
   - GET helix/users (получаем user_id, login, display_name)
   - db.upsert_channel(...) с oauth_*
   - dependencies.mark_channel_registered(channel_id, login) → in-memory cache update
   - Set signed session cookie → 302 /streamer/dashboard
4. /streamer/dashboard
   - Read cookie, get channel_id
   - db.get_channel(channel_id) → render inline HTML
```

### 5.3 Connector мода присылает player.linked
```
1. C# мод (когда он будет переведён на Module API):
   POST /v1/module/rimworld/events
   Header: Authorization: Bearer <module-token>
   Body: {channel_id, envelopes: [{id, kind: "event", type: "player.linked",
                                    ts, data: {viewer_id, character_ref}}]}
2. routes/module_api.py:module_events
   - Verify token (HMAC, expires, module_id match URL)
   - Verify body.channel_id == token.channel_id
   - Per envelope:
     - manifest.supports_event("player.linked") → True
     - Dedup check (per-channel ring) → not duplicate
     - adapter.handle_event(channel_id, env)
3. RimWorldAdapter.handle_event → _on_player_event (под feature flag)
   - При MODULE_API_PLAYER_EVENTS_ENABLED=true:
     - db.upsert_player_pawn(channel_id, viewer_id, character_ref)
   - При false: log only (легаси /api/rimworld/link продолжает работать)
4. Return {status: "ok", acks: [{id: <env.id>, success: true}]}
```

### 5.4 Стример заплатил за player.spawn → мод спавнит
```
1. viewer: POST /api/rimworld/spawn  (легаси путь — после Step 6 будет deprecated)
   Header: X-Twitch-JWT
2. require_jwt_user → проверяет JWT, sets ContextVar
3. routes/rimworld.py:spawn_pawn (или адаптер.dispatch_action в новом пути)
   - В новом пути: adapter.dispatch_action(channel_id, ModuleEnvelope(
       id=uuid, kind="action", type="player.spawn", data={viewer_id}))
   - dispatch_action → db.enqueue_action → INSERT module_actions со status=queued
4. Mod-side connector long-poll:
   GET /v1/module/rimworld/actions?since=<last_pk>
   - Wait up to 25s, polling DB каждую секунду
   - При появлении queued → возвращает batch + cursor; статусы → dispatched
5. Connector исполняет в игре
6. Connector: POST /v1/module/rimworld/ack {action_id, success: true}
   - db.ack_action → status=acked, acked_at=now
```

---

## 6. Recipes

### 6.1 Как добавить новый core-route (game-agnostic feature)

**Пример:** добавить `/api/lottery/buy_ticket` — лотерея для зрителей.

1. **Создать `routes/lottery.py`:**
   ```python
   from fastapi import APIRouter, Request
   from dependencies import get_bot, get_db, require_jwt_user, require_stream_live
   router = APIRouter()
   _AUTH_FAIL = {"success": False, "message": "Требуется авторизация"}

   @router.post("/api/lottery/buy")
   async def buy_ticket(request: Request):
       if err := await require_stream_live(): return err
       auth = require_jwt_user(request)  # ← обязательно ПЕРВЫМ делом
       if not auth: return _AUTH_FAIL
       username, channel_id = auth
       db = get_db()
       # ... логика. db-helpers скоупятся через ContextVar автоматически
       return {"success": True, "ticket_id": ...}
   ```

2. **Если нужны новые таблицы — создать миграцию `migrations/m<N>_lottery.py`** (см. recipe 6.3).

3. **Добавить TENANT-table в M1 SCHEMA если оно scopable per-channel:** проверить `MULTITENANT_PLAN.md §A` классификацию и обновить миграцию.

4. **Зарегистрировать router в `main.py`:**
   ```python
   from routes.lottery import router as lottery_router
   app.include_router(lottery_router)
   ```

5. **Если нужны DB-helpers — добавить методы в `database.py` (НЕ raw SQL в routes):**
   ```python
   async def buy_lottery_ticket(self, username, channel_id=None):
       channel_id = resolve_channel_id(channel_id)
       async with self._connect() as db:
           ...
   ```

6. **Добавить frontend (если viewer-facing):** `frontend/lottery.js` + кнопка в `extension.html`.

### 6.2 Как добавить новый game module (Bannerlord / Minecraft / etc.)

**Пример:** добавить Bannerlord.

1. **Создать структуру:**
   ```
   modules/bannerlord/
   ├── __init__.py        # re-export BannerlordAdapter
   ├── manifest.yaml      # capabilities
   └── _adapter.py        # ModuleAdapter implementation
   ```

2. **`manifest.yaml`** — объявить какие events/actions модуль поддерживает:
   ```yaml
   id: bannerlord
   version: 0.1.0
   core_api_version: ">=1.0.0,<2.0.0"
   display_name: "Bannerlord"
   events: [module.heartbeat, module.session_start, player.linked, player.died, player.state_update, world.event_occurred]
   actions: [player.spawn, player.heal, player.give_item, world.trigger_event]
   extensions:
     events: [hero.skill_changed, hero.equipment_changed]
     actions: [hero.add_skill, hero.set_culture]
   catalogs: [shop, events]
   ui_slots: [shop_panel, hero_inspector]
   ```

3. **`_adapter.py`** — наследуется от `ModuleAdapter`, реализует `handle_event` и `dispatch_action`:
   ```python
   from .._base import ModuleAdapter, ModuleEnvelope
   class BannerlordAdapter(ModuleAdapter):
       async def handle_event(self, channel_id, env):
           # Свой dispatcher по env.type
           ...
       async def dispatch_action(self, channel_id, env):
           # Использовать db.enqueue_action для outbox
           ...
   ```

4. **`__init__.py`:**
   ```python
   from ._adapter import BannerlordAdapter
   __all__ = ["BannerlordAdapter"]
   ```

5. **Перезапустить бэкенд.** `discover_modules()` подхватит автоматически. **Никаких изменений в core или routes/module_api.py не нужно** — это валидация архитектуры.

6. **Game-side:** написать свой connector в Bannerlord (BLT submodule, отдельная C# работа).

### 6.3 Как добавить миграцию БД

**Пример:** добавить таблицу `pet_inventory` для будущей фичи.

1. **Создать `backend/migrations/m<N>_pet_inventory.py`** где `<N>` — следующий номер (после m6 → m7):
   ```python
   SCHEMA = """
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       channel_id INTEGER NOT NULL,
       username TEXT NOT NULL,
       pet_def TEXT NOT NULL,
       acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
       UNIQUE(channel_id, username, pet_def)
   """

   async def apply(conn) -> None:
       await _ensure_migrations_table(conn)
       if await _is_applied(conn, "M7.pet_inventory.create"):
           return
       await conn.execute(f"CREATE TABLE IF NOT EXISTS pet_inventory ({SCHEMA})")
       await conn.execute("CREATE INDEX IF NOT EXISTS idx_pet_inventory_lookup "
                          "ON pet_inventory(channel_id, username)")
       await conn.commit()
       print("✅ M7: pet_inventory created")
       await _mark_applied(conn, "M7.pet_inventory.create")

   # _ensure_migrations_table / _is_applied / _mark_applied — копировать как
   # boilerplate из migrations/m6_module_catalogs.py (защитные duplicate'ы).
   ```

2. **Зарегистрировать в `main.py:run_migrations`** в правильном порядке:
   ```python
   try:
       from migrations import m7_pet_inventory
       await m7_pet_inventory.apply(conn)
   except Exception as e:
       print(f"❌ M7 migration FAILED: {type(e).__name__}: {e}")
       raise
   ```

3. **Добавить таблицу в `MULTITENANT_PLAN.md §A` classification** (TENANT/GLOBAL/SPLIT/LOOKUP).

4. **Добавить DB-helpers в `database.py`** работающие с этой таблицей (recipe 6.5).

5. **Test idempotency локально:**
   ```bash
   python -m py_compile migrations/m7_*.py
   # И запустить backend дважды — миграция должна примениться один раз
   ```

### 6.4 Как добавить feature flag

**Пример:** новый `LOTTERY_ENABLED`.

1. **`config.py`:**
   ```python
   LOTTERY_ENABLED = os.getenv('LOTTERY_ENABLED', 'false').lower() == 'true'
   ```
2. **Использование в коде:**
   ```python
   from config import LOTTERY_ENABLED
   if not LOTTERY_ENABLED:
       return {"success": False, "message": "Лотерея временно недоступна"}
   ```
3. **Default — `false`** для безопасных деплоев. Включается явно через `.env` после QA.
4. **TODO в коде** при использовании, чтобы было видно когда удалить флаг (после стабилизации):
   ```python
   # TODO M7+: убрать LOTTERY_ENABLED после успешного A/B на 1-2 каналах
   ```

### 6.5 Как добавить DB-helper

```python
# database.py
async def buy_lottery_ticket(
    self,
    username: str,
    channel_id: Optional[int] = None,
) -> bool:
    """Списать ticket-cost у user, INSERT в lottery_tickets.
    Возвращает True при успехе, False если недостаточно поинтов."""
    channel_id = resolve_channel_id(channel_id)  # ← strict, not _or_default
    async with self._connect() as db:
        await db.execute("BEGIN IMMEDIATE")  # consistency
        # ... твоя логика
        await db.commit()
    return True
```

**Не делать:**
- `aiosqlite.connect(...)` напрямую — используй `self._connect()` (через pool)
- Забывать `channel_id = resolve_channel_id(channel_id)` в начале
- Использовать `resolve_channel_id_or_default` без TODO-комментария почему

---

## 7. Anti-patterns (что НЕ делать)

### 7.1 Raw SQL в routes/*

**❌ Плохо:**
```python
@router.post("/api/foo")
async def foo(request: Request):
    db = get_db()
    async with aiosqlite.connect(db.db_path) as conn:  # ← bypass pool, bypass helpers
        await conn.execute("INSERT INTO viewers ...")
```

**✅ Хорошо:**
```python
@router.post("/api/foo")
async def foo(request: Request):
    db = get_db()
    await db.upsert_viewer(...)  # ← через helper
```

Почему: будущая миграция на Postgres = переписывание ОДНОГО `database.py`, не 10 routes/*. Также упрощает testing (мокаем один слой).

### 7.2 Single-tenant SQL без channel_id

**❌ Плохо:**
```python
"SELECT * FROM duel_stats WHERE username=?"  # вернёт чужие сезоны!
```

**✅ Хорошо:**
```python
"SELECT * FROM duel_stats WHERE channel_id=? AND username=?"
```

После M1 миграции все TENANT-таблицы имеют `channel_id`. Запросы без него возвращают данные смешанных каналов.

### 7.3 Forgetting `require_jwt_user` в action endpoints

**❌ Плохо:**
```python
@router.post("/api/casino/spin")
async def spin(request: Request, body: SpinRequest):
    username = body.username  # ← trust body? нет
    ...
```

**✅ Хорошо:**
```python
@router.post("/api/casino/spin")
async def spin(request: Request, body: SpinRequest):
    auth = require_jwt_user(request)
    if not auth: return _AUTH_FAIL
    username, channel_id = auth  # ← username из JWT, не из body
    ...
```

### 7.4 Background loop без channel_id

**❌ Плохо:**
```python
async def my_loop():
    while True:
        await asyncio.sleep(60)
        await db.add_points("alice", 10)  # ← strict resolver упадёт
```

**✅ Хорошо:**
```python
async def my_loop():
    while True:
        await asyncio.sleep(60)
        for ch in await db.list_channels():
            cid = ch['channel_id']
            await db.add_points("alice", 10, channel_id=cid)
```

### 7.5 Module API: возвращать данные не из manifest

**❌ Плохо:**
```python
class MyAdapter(ModuleAdapter):
    async def handle_event(self, channel_id, env):
        if env.type == "magic.thing":  # ← НЕ в manifest!
            ...
```

`routes/module_api.py:module_events` отбрасывает событие до dispatch если `manifest.supports_event(env.type)` вернул False. Объяви всё что хочешь обрабатывать в `manifest.yaml`.

---

## 8. Configuration management

**Все конфиги — через `config.py`** который читает `.env` через `python-dotenv`.

**Required env vars** (бэк не запустится без них):
- `TWITCH_OAUTH_TOKEN`, `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_BOT_ID`

**Important env vars:**
- `TWITCH_EXTENSION_SECRET` — без него JWT не работает
- `TWITCH_BROADCASTER_ID` — для backfill при первом старте M4 миграции
- `TWITCH_CHANNEL_NAME` — fallback для IRC bot если registry пуст
- `MODULE_TOKEN_SECRET` — fallback на TWITCH_EXTENSION_SECRET если не задан
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — для /api/admin/*
- `EVENTSUB_CALLBACK_URL` — публичный URL для Twitch EventSub webhook
- `TWITCH_OAUTH_REDIRECT_URI` — для /streamer OAuth flow

**Feature flags:**
- `EVENTSUB_AUTO_REGISTER` (default `false`) — multi-channel EventSub registration
- `MODULE_API_PLAYER_EVENTS_ENABLED` (default `false`) — adapter пишет в rimworld_pawns
- `RATE_LIMIT_FREE` / `_PRO` / `_VIP` — override per-tier rate limits

**DEV mode:**
- `DEV_MODE=true` + `DEV_USERNAME=...` — отключает JWT для локального тестирования. **НИКОГДА** не включать на проде.

---

## 9. Testing strategy (текущее состояние)

Backend имеет standalone regression suite в `backend/tests/`. Канонический
запуск из корня repository:

```text
python scripts/run-backend-tests.py
```

На 2026-08-15 suite содержит 47 сценариев и проверяет, среди прочего:

- fresh install и migration ledger;
- multi-tenant isolation и channel approval;
- atomic charge, dedup, ACK/refund ordering и queued TTL;
- Module API delivery gaps и offline gate;
- Bannerlord, RimWorld и ShedColony денежные контракты;
- TTS moderation/approval;
- stream-session identity и устойчивость background loops.

Standalone suite не заменяет игровые smoke-тесты: engine API, установка,
совместимость версий, restart/reconnect и lost ACK должны дополнительно
проверяться в реальной игре. Production smoke выполняется после отдельного
preflight и не должен подменять локальные regression tests.

---

## 10. Известные технические долги

### 10.1 Архитектурные
- **Single SQLite file** — масштабируется до ~50-100 каналов с активным играми. Дальше нужна миграция на Postgres (path: переписать `database.py` под asyncpg, остальные слои не меняются если они дисциплинированные).
- **`event_manager.active_event` — single global** — не dict-per-channel. Multi-tenant proper требует рерайт. Сейчас работает потому что в моменте обычно один стрим активен у всех каналов параллельно (ивенты крутятся независимо в БД, но in-memory state в EventManager — общий).
- **Late-join IRC bot** — новый OAuth-регистрант не джойнится в running TwitchChatBot до рестарта. Future fix: вызвать `self.join_channels([login])` из OAuth callback.
- ~~**🔴 `BotCore.current_stream_id` + `reward_points_loop` — single-channel**~~ — **РЕЗОЛВНУТО 2026-05-10** (Bug 4). `current_stream_id` теперь `Dict[channel_id, str]`, `reward_points_loop`/`drop_loop`/`auto_message_loop`/`run_family_income` итерируют `db.list_channels()`, `_is_stream_live(channel_id, login)` — per-channel cache, `record_viewer_attendance`/`handle_stream_start`/`check_and_unlock_achievements` принимают `channel_id`. Покрыто тестом 8 в `test_multi_tenant_isolation.py`. Каждый канал крутит свой день независимо.

### 10.2 DB-discipline
- **Raw SQL в routes/*** — есть ещё несколько мест где не через `db.*` helpers (например `routes/duel.py:_db_save_duel` использует `aiosqlite.connect` через `db._connect()`). См. Block 2 архитектурной прокачки.
- **`event_manager.py` raw SQL writes** — `db.add_points` через прямой aiosqlite подключения вместо db-helpers (исторически).

### 10.3 Module API gaps
- **pawn.\* extension events** (trait/gene/implant/xenotype) — сейчас log+skip в RimWorldAdapter. Step 6 переведёт.
- **Legacy `/api/rimworld/*` routes** — Step 6 wrapper migration либо удалит, либо превратит в shim-форвардеры на dispatch_action.
- **OAuth refresh** обрабатывает только пользовательский OAuth (стримера). Module-token refresh не нужен (он long-lived 1 год).

### 10.4 Operational
- **Нет visibility** в БД: размер per-table, slow queries, WAL growth. Block 1 архитектурной прокачки.
- **Нет automated migration rollback** — если M_N упала на проде, нужна ручная очистка. Helps: каждая миграция атомарно `BEGIN ... COMMIT` или явный `DROP` rollback procedure в комментарии.

---

## 11. Future migration paths

### 11.1 SQLite → Postgres
**Когда:** при ~50+ активных каналах, сильно растущей БД (>5 GB), или при необходимости read replicas.

**Что нужно:**
1. `database.py` переписать под `asyncpg` (или `databases` + `sqlalchemy`). Все helpers изолированы — переписывание ограничено одним файлом.
2. Migrations переписать на Postgres-syntax (`SERIAL` вместо `AUTOINCREMENT`, `JSONB` вместо `TEXT JSON`, etc.).
3. WAL → нет (Postgres имеет свой MVCC).
4. Connection pool — `asyncpg.create_pool` вместо `DBPool`.
5. Backups: `pg_dump` вместо `.backup` SQLite.

**Что НЕ нужно менять (благодаря дисциплине):**
- Routes
- Adapter / Module API
- Frontend
- Migration файлы (только их содержимое — но pattern `apply(conn)` остаётся)

### 11.2 Single instance → Multi-instance
**Когда:** при single-VPS затыке по CPU/network (вряд ли скоро при разумном кешировании).

**Что нужно:**
1. ContextVar (per-task) уже работает в multi-instance — не shared.
2. In-memory caches (`_channel_login_to_id`, `_channel_tier_cache`, dedup ring, oauth states) — нужно переехать в Redis.
3. Background loops — назначить leader-election (один инстанс обновляет токены, другие пассивны).
4. Sticky sessions для long-poll'а action queue (или вообще пакетировать через broker — RabbitMQ/Redis Streams).
5. EventSub webhook — distribute по инстансам через load balancer (signature verify работает на любом инстансе если секрет один).

### 11.3 Hosted SDK / community marketplace
**Когда:** после 3-5 рабочих модулей.

**Что:**
- Extract `modules/_base.py` + `routes/module_api.py` + `MODULE_API.md` в отдельный репо `shedoy23/module-api`
- Reference SDK clients на C# / Python / Lua / Java
- Tutorial и examples
- Каталог community-модулей в admin-UI

---

## 12. Glossary

| Термин | Что значит |
|---|---|
| **Channel** | Стример как платформенная единица. PK = `channel_id` (Twitch broadcaster user_id, int). |
| **Tenant** | Синоним channel в контексте multi-tenant. TENANT-table = таблица с FK на channel_id. |
| **Viewer** | Зритель в чате конкретного канала. Per-channel запись в `viewers`. |
| **ContextVar** | Per-asyncio-task переменная channel_id, авто-пропагация через await. См. `dependencies._current_channel_id`. |
| **Module** | Pluggable game integration: RimWorld / Bannerlord / Minecraft. Состоит из python-adapter + game-side connector. |
| **Adapter** | Python-часть модуля. `modules/<id>/_adapter.py`, наследник `ModuleAdapter`. |
| **Connector** | Game-side часть модуля (C# мод, Bukkit plugin, etc.). Шлёт events, забирает actions. |
| **Envelope** | Wire-уровень сообщение в Module API: `{id, kind, type, ts, data}`. |
| **Manifest** | YAML-декларация capabilities модуля. Source of truth для validation. |
| **Action queue** | Outbox для core → connector команд. Хранится в `module_actions` таблице. |
| **Catalog** | Module-publishable список items/events. Хранится в `module_catalogs` таблице, replace-семантика. |
| **Tier** | Уровень тарифа канала: `free` / `pro` / `vip`. Влияет на per-channel rate limits. |
| **Module token** | HMAC-подписанный per-channel-per-module credential для connector'а. Long-lived (1 год). |
| **Streamer session** | HMAC-подписанный cookie для streamer dashboard. TTL 30 дней. |
| **Strict resolver** | `resolve_channel_id` который raises RuntimeError если channel_id не разрешается. |
| **Soft resolver** | `resolve_channel_id_or_default` для legacy boundaries без JWT. |
| **Feature flag** | Env-управляемый toggle (default false). См. `EVENTSUB_AUTO_REGISTER`, `MODULE_API_PLAYER_EVENTS_ENABLED`. |

---

## 13. История документа

| Дата | Изменение |
|---|---|
| 2026-05-08 | Первая редакция. Зафиксирована архитектура после M4/M5/M6 + этап 3 step 1-5 Module API. |
