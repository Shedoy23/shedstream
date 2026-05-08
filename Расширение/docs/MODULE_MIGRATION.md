# Module Migration Plan — RimWorld

**Status:** Step 1 (foundation) задеплоен в репо. Steps 2+ — поэтапно.
**Context:** [PLATFORM_VISION.md](../../PLATFORM_VISION.md) этап 3 / [MODULE_API.md](MODULE_API.md).

Цель: вынести `backend/rimworld.py` (~1981 строк) в `backend/modules/rimworld/` так, чтобы ядро платформы знало RimWorld только через Module API. Это разблокирует подключение второго модуля (Bannerlord, Minecraft, …) тем же интерфейсом.

---

## Зачем поэтапно

Полная миграция = многонедельная работа с риском регрессов на проде. Поэтому делаем шагами по 1-2 часа каждый. Между шагами система **рабочая** — старые `/api/rimworld/*` эндпоинты не отключаются пока не покрыты Module API эквивалентами.

---

## Шаги (укрупнённо)

### Step 1 — Foundation ✅
- [x] `modules/_base.py`: `ModuleAdapter` ABC, `ModuleManifest`, `ModuleEnvelope`
- [x] `modules/_loader.py`: `discover_modules()` из manifest.yaml (PyYAML с fallback)
- [x] `modules/rimworld/manifest.yaml`: capabilities из `rimworld.py` + C# мода
- [x] `modules/rimworld/_adapter.py`: stub-уровень, реальная логика — следующие шаги
- [x] `routes/module_api.py`: `GET /v1/modules`, `GET /v1/module/<id>/info`, `POST /v1/module/<id>/hello`
- [x] `discover_modules()` вызов в `main.on_startup`

### Step 2 — Read events from connector ⏳
Цель: мод начинает слать `player.linked` / `player.died` / `player.state_update` через `POST /v1/module/rimworld/events` параллельно с легаси `/api/rimworld/link`. Двойная подача — переходный период.

- [ ] `POST /v1/module/<id>/events` endpoint в `routes/module_api.py`. Принимает массив envelope'ов. Валидирует через `manifest.supports_event()`.
- [ ] HMAC auth (§4 спеки): `Authorization: Module <token>` где token подписан `MODULE_SECRET` из .env. Mod side берёт от стримера через OAuth (M4.3).
- [ ] `RimWorldAdapter.handle_event` — диспатч по `env.type`. Стандартные события (player.linked → создать pawn в БД) реализуем напрямую через `db.*` helpers. Custom (pawn.gene_changed) — обновляют rimworld_pawn_genes.
- [ ] Идемпотентность: храним последние `env.id` в Redis или in-memory ring; повторный envelope игнорим.

### Step 3 — Action queue (core → connector)
Цель: `player.spawn` вместо `POST /api/rimworld/spawn` идёт через action queue.

- [ ] Таблица `module_actions` (TENANT, channel_id PK + action_id): outbox для actions. Колонки: id, channel_id, module_id, type, data (JSON), status (queued/dispatched/acked/failed), created_at, dispatched_at, acked_at.
- [ ] `RimWorldAdapter.dispatch_action(channel_id, env)` → INSERT в module_actions со status=queued.
- [ ] `GET /v1/module/<id>/actions?since=<cursor>` — long-poll outbox. Возвращает batch + cursor.
- [ ] `POST /v1/module/<id>/ack` — connector подтверждает execution. Ставит status=acked.
- [ ] Routes shop/spawn/heal в rimworld.py перепишут `await rimworld.spawn_pawn(username)` на `await adapter.dispatch_action(channel_id, env_for_player_spawn)`. Старые routes остаются как тонкий wrapper.

### Step 4 — Catalogs publish/consume
Цель: shop_catalog и rimworld_event_catalog публикуются мод'ом через Module API а не legacy `/api/rimworld/catalog/*`.

- [ ] `module.catalog_update` event (тип=shop|events, items: [...]). Adapter.handle_event запишет в session-scoped таблицы (см. MULTITENANT_PLAN.md §H).
- [ ] `GET /api/shop/catalog?channel_id=X` теперь читает через adapter view, не напрямую таблицу. Frontend без изменений (тот же JSON-shape).

### Step 5 — Decommission rimworld.py routes
- [ ] Постепенно удаляем `/api/rimworld/*` routes по мере покрытия в Module API. Либо превращаем в shim-форвардер.
- [ ] `rimworld.py` исчезает или ужимается до compatibility wrapper (~50 строк).

### Step 6 — Add Bannerlord module (validation)
- [ ] Создаём `modules/bannerlord/` с своим manifest.yaml + adapter.
- [ ] Тот же handshake / events / actions работают без core-кода.
- [ ] Проверка: ничего RimWorld-specific не утекло в core. Если утекло — refactor.

---

## Mapping table — текущие routes → Module API

| Текущий endpoint | Тип Module API | Куда мигрирует |
|---|---|---|
| `POST /api/rimworld/link` | event `player.linked` | Step 2 |
| `POST /api/rimworld/unlink` | event `player.unlinked` | Step 2 |
| `POST /api/rimworld/sync_pawns` | event `player.state_update` (bulk) | Step 2 |
| `POST /api/rimworld/spawn` | action `player.spawn` | Step 3 |
| `POST /api/rimworld/heal` | action `player.heal` | Step 3 |
| `POST /api/rimworld/resurrect` | action `player.respawn` | Step 3 |
| `POST /api/rimworld/equip` | action `player.equip_item` | Step 3 |
| `POST /api/rimworld/give_item` | action `player.give_item` | Step 3 |
| `POST /api/rimworld/trigger_event` | action `world.trigger_event` | Step 3 |
| `POST /api/rimworld/add_trait` | action `pawn.add_trait` (extension) | Step 3 |
| `POST /api/rimworld/add_gene` | action `pawn.add_gene` (extension) | Step 3 |
| `POST /api/rimworld/set_passion` | action `pawn.set_passion` (extension) | Step 3 |
| `GET  /api/rimworld/catalog/shop` | catalog `shop` | Step 4 |
| `GET  /api/rimworld/catalog/events` | catalog `events` | Step 4 |

---

## Риски

1. **Регресс на проде во время миграции.** Mitigation: dual-path — legacy /api/rimworld/* живёт пока новый Module API не покрыт.
2. **Утечка RimWorld-specifics в core.** Mitigation: при добавлении Bannerlord (Step 6) любой RimWorld-named код в core/ — обязательно рефакторить.
3. **C# мод нужен под Module API.** Это работа в `RimLink/Source/`, не охвачена этим документом. Можно пилотировать с Python-симулятором connector'а.

---

## История

| Дата | Шаг | Изменения |
|---|---|---|
| 2026-05-08 | Step 1 | Foundation: ModuleAdapter ABC, manifest.yaml, loader, /v1/module/* routes. RimWorldAdapter — stub. Existing rimworld.py не тронут. |
