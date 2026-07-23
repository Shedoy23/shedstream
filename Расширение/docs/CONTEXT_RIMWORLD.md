# RimWorld Module — Context (chat handoff)

**Назначение:** для чата по RimWorld-модулю (legacy + Module API rework).
Общее — см. `CONTEXT.md`. Bannerlord — `CONTEXT_BANNERLORD.md`.

**Last updated:** 2026-05-16

## TL;DR

**Первый** gaming-модуль платформы. **Legacy** code из эпохи single-tenant
(до multi-tenant refactor). Большая часть прошла через Phase 1-7
compliance rework — сейчас стабильна, но имеет долг по миграции на
**Module API** generic pattern (как Bannerlord).

## Текущий статус

### 🔎 2026-07-22 — аудит покупок (найдено, НЕ чиню: владелец держит паузу до ревью Twitch)

Быстрый проход по платным эндпоинтам `rimworld.py`. От худшего к мелкому:

1. **НОВЫЙ, реальный: прогрессивный счётчик не откатывается при рефанде →
   зритель переплачивает за следующую покупку.** Гены/трейты дорожают по числу
   купленных (`purchase_counters`, ген №1=1000, №2=2000…). Счётчик инкрементится
   ПРИ покупке (`rimworld.py:1457` гены, `:1726` трейты), ДО того как известен
   исход. Путь рефанда (`_refund_cmd_row_tx`) возвращает только ОЧКИ
   (`add_points_tx`) и **счётчик не трогает**. Мод корректно отдаёт `success=false`
   на no-op (нет пешки / ген уже есть — `AddGeneCommand.Execute` возвращает false),
   рефанд срабатывает — но счётчик уже уехал вверх. Итог: неудачный ген №1
   вернул 1000, счётчик=1, следующий РЕАЛЬНЫЙ ген №1 стоит уже 2000. Баг
   вскрылся взаимодействием свежего рефанда (19.07) со старым счётчиком.
   Фикс: в `_refund_cmd_row_tx` декрементить счётчик для gene/trait (decrement
   уже есть в remove-gene, `:1812` — переиспользовать). Проверяемо: цена
   следующего гена после отменённого.

2. **Подтверждён старый (аудит #3): `purchase_counters` глобальный, не
   channel-scoped.** Код пишет в `purchase_counters WHERE username` без
   channel_id (`:1391`, `:1812`), хотя channel-scoped `rimworld_purchase_counters`
   существует. Прогрессивная цена гена/трейта **потечёт между каналами**, когда
   подключится 2-й стример. Латентно: RimWorld пока на одном канале.

3. **Кулдаун лечения тоже глобальный.** `rimworld_heal_cooldowns` ключуется
   только по `username` (`:300`), без channel_id → полечился на канале A →
   на кулдауне и на канале B. Тот же латентный класс.

4. **id команды с секундной точностью** — `f"buy_{username}_{int(time.time())}"`.
   Два действия одного типа в одну секунду → одинаковый cmd_id → второй ловит
   `UNIQUE(channel_id, cmd_id)` в `_db_enqueue_command` (после фикса очереди),
   в БД не попадает, но в in-memory очередь уже добавлен → уедет моду без
   строки → на провале рефанда не будет. Прикрыто клиентским кулдауном 3с
   (обходится через devtools). Низкая severity, самоадресный. Фикс:
   добавить в id суффикс (`uuid4().hex[:6]` или счётчик).

**НЕ баг (проверено):** `remove_points` атомарен против ухода в минус (один
UPDATE с `points >= amount`) — двойной траты на балансе нет. Мод детектит no-op
генов/пешек и возвращает false → рефанд по очкам работает.

## Текущий статус

### 🟢 2026-07-22 — связь подтверждена, два скрытых бага закрыты

**Связь мод→прод РАБОТАЕТ.** Июльский фикс (https + Bearer) подтверждён логом
последней сессии игры: `Сервер: https://shedoy23.ru`, `Event catalog synced:
248 events` — и на проде ровно 248 строк в `rimworld_event_catalog`. Тема
«POST не доходят» закрыта, секции ниже — история.

**Баг 1 — каталог магазина не заливался (413).** Лог: `BuildCatalogWithPrices:
2559 предметов` → `SyncShopCatalog failed: (413) Request Entity Too Large`.
В nginx на проде не был задан `client_max_body_size` → действовал дефолт 1 МБ,
а 2559 предметов с русскими описаниями в него не влезают. Зрители видели
устаревший срез `shop_catalog` из **493 позиций от 19.07 10:10** — последнюю
удачную заливку. Починено: `client_max_body_size 20m` в
`/etc/nginx/sites-enabled/twitchbot` (бэкап рядом: `/root/twitchbot.nginx.bak.*`),
`nginx -t` + graceful `reload`. Проверено: тело 2.6 МБ доходит до приложения
(401 вместо 413). **Остаётся сделать:** заливать каталог порциями — при росте
числа модов он снова упрётся в любой лимит, а приёмник делает полную замену
(`DELETE` + вставка), так что чанкам нужен протокол (первая порция сбрасывает,
остальные дописывают).

**Баг 2 — очередь команд не сохранялась НИ РАЗУ с миграции m1.** m1 пересоздала
`rimworld_pending_commands` со схемой `channel_id INTEGER NOT NULL` +
`UNIQUE(channel_id, cmd_id)`, а локальный `CREATE TABLE IF NOT EXISTS` остался
досетевым (без channel_id) и на мигрированной базе не срабатывал. `INSERT OR
IGNORE` не передавал channel_id → нарушение NOT NULL, и «OR IGNORE» глотало
строку молча. На проде в таблице **0 строк**. Следствия: обещание «команда
переживёт рестарт сервера» не выполнялось, и рефанд-механика от 19.07 физически
не могла работать — возвращать было не из чего. Починено (`6a54b58`): схема в
коде приведена к схеме миграции, INSERT передаёт channel_id, «OR IGNORE» убран
(нарушение теперь шумит), команда без channel_id логируется явно.
**Почему не поймал линтер:** `rimworld.py` помечен `tenant-lint: skip-file` как
известный долг — исключение спрятало ровно тот класс бага, ради которого
проверка и заводилась.

**Не проверено:** пешки/колонисты. В последней сессии была новая игра
(«Загружено пешек: 0»), поэтому `rimworld_pawns/_skills/_traits` пустые — это
может быть отсутствие данных, а не поломка. Нужен запуск с реальной колонией.

**Замечено:** `rimworld_catalog` (0 строк) — в неё никто не пишет, каталог живёт
в `shop_catalog`. Похоже на мёртвый дубль раннего дизайна, надо проверить, кто
её читает.

### 🟡 2026-07-19 — ROOT CAUSE НАЙДЕН + ПОФИКШЕН, ждёт запуска игры

Причина «POST не долетают»: **DLL в игре была собрана 2026-06-12 со старым
`http://31.130.132.224:8000`**; фикс Security 2.1 (https://shedoy23.ru + Bearer)
внесли в исходники 2026-06-27, но DLL не пересобрали — мод месяц стучался
на голый IP:8000 plain-HTTP (вероятно, POST'ы туда режет DPI провайдера —
тот же, что резал RTMP; GET'ы мелкие и проскакивали). Сделано (`04338ee`):
- DLL пересобрана из репо-исходников → в игре (md5 сверен), зашит `https://shedoy23.ru`;
- + форс TLS 1.2 (Mono/WebClient), + heartbeat-ошибки логируются (раньше Release молчал);
- прод проверен курлом: `POST /api/rimworld/heartbeat` + токен из настроек мода = **200**,
  без токена = **401** (строгий режим уже работает, токен в конфиге мода валиден до ~2027-06).
**Осталось:** запустить RimWorld → проверить в логе `Сервер: https://shedoy23.ru`,
`Session started`, и на проде `rimworld_catalog` > 0 строк. Секция ниже — история.

### 🔴 KNOWN ISSUE (2026-06-14) — мод НЕ заливает данные на прод (POST не доходят)

Обнаружено при проверке module-token: **исходящие POST'ы мода до прода не долетают**,
доходит только `GET /api/rimworld/status` (+`/api/event/status`) — проба «я на связи».

Доказательства (prod `31.130.132.224`):
- мод (debug log) рапортует `Shop catalog synced: 493 items` / `Session started`, НО
  `rimworld_catalog` в `viewers.db` = **0 строк**;
- в `/var/log/twitchbot.out.log` **ноль POST'ов** с IP мода — только GET'ы статуса
  (при этом uvicorn POST'ы пишет: чужие `POST /api/viewer/attendance` видны → дело не в логе);
- мод в release-сборке **глотает сетевые ошибки**, поэтому в игре пишет «synced» оптимистично.

Вывод: проблема на **стороне мода/сети** (запрос не доходит до uvicorn — иначе залогировался бы
даже с ошибкой), НЕ в бэкенд-коде. GET работает, POST нет → сужает круг: сериализация / таймаут /
TLS на больших телах / другой код-путь отправки POST. Начинать с `RimLink/Source/API/RimLinkAPI.cs`
(методы POST vs `Ping()`/GET) + где ловятся/глотаются исключения отправки.

**Связанное:** backend имеет SOFT-режим module-token авторизации (`rimworld.py:56`,
`RIMWORLD_REQUIRE_TOKEN`). Флипать в STRICT **нельзя пока POST не доходят** — защищать нечего,
а STRICT просто 401-ит и так не доходящие запросы. Токен в настройках мода ВСТАВЛЕН и валиден
(проверено) — он не причина. Оставлен SOFT.

Приоритет: отложено (2026-06-14, по решению владельца — фокус на Bannerlord, RimWorld legacy).

### ✅ Что работает (production)

**Backend:**
- `routes/rimworld.py` (~2000 строк, legacy endpoints) — pawn create,
  equip, skills, hediffs, traits, genes, xenotype, settlement sync
- 11 `rimworld_*` таблиц в `database.py` (через M1-M6 migrations):
  pawns, pawn_equipment, pawn_skills, pawn_hediffs, pawn_traits,
  pawn_genes, colonists, skills, catalog, pending_commands, ...
- `modules/rimworld/_adapter.py` (316 строк) — Module API adapter
  (Step 2 of migration plan: lifecycle + log-only)

**C# mod** (legacy, **отдельный repo** или path):
- `RimLink/Source/Managers/` — PawnManager, EventManager,
  ShopManager, CommandQueue, PawnDataBuilder
- Communicates через старый file-based protocol (TwitchCommands.txt
  polling, не HTTP yet)

**Frontend:**
- `extension.html` tab «🔌 Интеграция» когда active_module='rimworld'
- Pawn card, equipment, skills, shop, events panel

### 🟡 Pending — Module API migration

См. `docs/MODULE_MIGRATION.md` план. Текущий status (примерно):
- **Step 2 ✓** lifecycle hooks реализованы в adapter
- **Step 3** ⏳ HTTP transport (mod должен POST events на
  `/v1/module/rimworld/events` вместо file polling)
- **Step 4-6** ⏳ player events → upsert в rimworld_pawns через adapter
  (вместо legacy /api/rimworld/sync_pawns_bulk)

Это **большая** работа потому что меняется С# mod transport layer
(file → HTTP/JWT). Legacy endpoints `/api/rimworld/*` должны
сосуществовать с new Module API endpoints `/v1/module/rimworld/*`
до миграции mod'а.

### 🟢 Compliance status

Все Phase 1-7 cleanup'ы применены:
- Casino / craft / market / donate / transfer вырезаны
- Items value=0 (cosmetic-only)
- Quest rewards без `reward_item`
- Roulette mode removed
- Lexicon scrub passed

См. `COMPLIANCE_REWORK_PLAN.md` §1-7 для деталей.

## Stack

- **C# mod:** `.NET Framework 4.7.2` net472, RimWorld 1.5+, Harmony
- **Backend transport:** HTTP polling (legacy) → Module API (target)
- **Auth:** Twitch Extension JWT (стандартный extension flow)

## Файл map

### Backend (Python)
| Где | Что |
|---|---|
| `Расширение/backend/routes/rimworld.py` | Legacy endpoints (2000 строк) |
| `Расширение/backend/rimworld.py` | Helpers + middleware |
| `Расширение/backend/modules/rimworld/manifest.yaml` | Module API declaration |
| `Расширение/backend/modules/rimworld/_adapter.py` | Module API adapter (~316 строк) |
| `Расширение/backend/migrations/m1_multitenant.py` | RimWorld tables → multi-tenant |
| `Расширение/backend/database.py` | `rimworld_*` table definitions |
| `Расширение/docs/MODULE_MIGRATION.md` | Step-by-step plan for legacy → Module API |

### C# mod (RimLink)
Не в monorepo. Локация на dev машине:
- `C:\Users\Edward\Desktop\Рабочая версия\RimLink\Source\`
- `Managers/PawnManager.cs` — pawn registration + sync
- `Managers/EventManager.cs` — event lifecycle
- `Managers/ShopManager.cs` — shop catalog
- `Managers/CommandQueue.cs` — pending commands processor
- `Components/RimLinkGameComponent.cs` — GameComponent tick loop
- `Actions/EventCommands.cs` — game-side action handlers

### Frontend
| Где | Что |
|---|---|
| `Расширение/frontend/pawn.js` | Pawn card render |
| `Расширение/frontend/shop.js` | Shop catalog UI |
| `Расширение/frontend/xenotype.js` | Xenotype picker |
| `Расширение/frontend/duels.js` | Pawn dueling UI (но dueling — core feature, не rimworld-specific) |

## Endpoints (RimWorld-specific)

Legacy `/api/rimworld/*`:
- `POST /api/rimworld/sync_pawns_bulk` — mod пушит pawn state batch
- `POST /api/rimworld/pawn_link` — link Twitch login ↔ in-game pawn
- `POST /api/rimworld/spawn_pawn` — create new pawn for viewer
- `GET /api/rimworld/my_pawn/{username}` — pawn info для extension
- `POST /api/rimworld/heal_pawn` — heal action
- `POST /api/rimworld/equip_pawn` — equip item
- `POST /api/rimworld/event/*` — event triggers
- `POST /api/rimworld/shop/*` — catalog queries

Module API (новый, на пути миграции):
- `POST /v1/module/rimworld/events` — generic event ingest
- `GET /v1/module/rimworld/actions` — long-poll outbox
- `POST /v1/module/rimworld/ack` — ACK исполнения

## Что бы делать в этом чате

**Хорошо подходит:**
- C# mod (RimLink) изменения — code в `RimLink/Source/`
- Module API migration steps 3-6 (HTTP transport, player events handlers)
- RimWorld-specific bugs в `rimworld.py` / `routes/rimworld.py`
- Pawn / skill / xenotype / hediff features
- Mod manifest update

**Лучше другой чат:**
- Multi-tenant / auth / overall extension architecture → `CONTEXT.md`
- Bannerlord work → `CONTEXT_BANNERLORD.md`
- Compliance / lexicon / submission → `CONTEXT.md` + COMPLIANCE_REWORK_PLAN.md

## Open вопросы / next steps

1. **Module API migration** — mod transport на HTTP/JWT (steps 3-6)
2. **Pawn equipment slot naming** — слот «Primary» vs «weapon» (см. project_twitch_rimworld.md memory)
3. **RimLink.dll recompile** после изменений PawnManager.cs (по memory note)
4. **Rebrand?** В отличие от Bannerlord (BLT reference), RimLink — наш
   изначальный mod, нет third-party license concerns

## Repo

- **GitHub backend:** `Shedoy23/shedstream` (private monorepo, есть)
- **RimLink C# mod:** не в monorepo. Возможно отдельный repo (нужно
  уточнить у юзера) либо локальный код в `RimLink/`

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT_RIMWORLD.md, продолжаем работу над RimWorld-модулем»*.
