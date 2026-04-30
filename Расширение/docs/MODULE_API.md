# Module API Specification

**Status:** Draft v0.1 (2026-04-30)
**Owner:** Edward
**Цель документа:** зафиксировать контракт между **ядром** (game-agnostic SaaS-бэк) и **модулями интеграции с играми** (RimWorld, Minecraft, Terraria, …) ДО того как начнётся multi-tenant рефакторинг и вынос RimWorld в `modules/rimworld/`. Спецификация не описывает реализацию — только контракт.

См. также: [`PLATFORM_VISION.md`](../../PLATFORM_VISION.md) — стратегический контекст.

---

## 1. Глоссарий

| Термин | Определение |
|---|---|
| **Core** | Ядро платформы. FastAPI + SQLite. Game-agnostic. Знает про каналы, очки, инвентарь, казино, дуэли. |
| **Module** | Backend-плагин внутри ядра, реализующий контракт `ModuleAdapter` для конкретной игры. Живёт в `backend/modules/<id>/`. |
| **Connector** | Game-side код (мод/плагин), запускается на машине стримера, держит сессию с Module. |
| **Channel** | Twitch-канал стримера. Tenant-разделитель. Все данные сегрегируются по `channel_id`. |
| **Player** | Зритель, привязавший Twitch-аккаунт к in-game персонажу через connector. Идентификатор — `viewer_id` (Twitch user id) + `character_ref` (специфичная для игры ссылка). |
| **Event** | Сообщение, которое connector шлёт в core (направление IN). |
| **Action** | Команда, которую core инициирует в connector (направление OUT). |
| **Catalog** | Список сущностей, которые модуль публикует в core (shop items, triggerable events). Динамический. |

---

## 2. Цели / не-цели

### Цели
1. **Один модуль = одна игра.** Стример выбирает в админке какой модуль активен (за раз — один).
2. **Стабильный контракт.** Старый connector работает с новой версией core (semver, см. §11).
3. **Минимум обязательных событий.** Модуль может быть «бедным» (только heartbeat + spawn) — этого достаточно чтобы ядро начисляло viewer points.
4. **Расширяемость без правки core.** Кастомные события и actions кладутся в `extensions.<module_id>.*` и не требуют merge в ядро.
5. **Multi-tenant из коробки.** Каждое сообщение несёт `channel_id`; core отказывает если auth-токен не соответствует.

### Не-цели
- НЕ описываем UI-фронт. Frontend-слоты упомянуты в манифесте, но детали — отдельный документ.
- НЕ описываем биллинг и квоты — это слой ядра, не Module API.
- НЕ предписываем язык connector'а. Контракт чисто wire-level (JSON over WS/HTTP).

---

## 3. Транспорт

### 3.1 WebSocket (целевой)
- Endpoint: `wss://api.example.com/v1/module/<module_id>/socket`
- Persistent. Двусторонний. Идеален для polling-free actions.
- Сообщение — JSON-объект, по одному на frame.
- Heartbeat: connector шлёт `module.heartbeat` каждые 30 секунд. Core закрывает сокет если 90 с тишины.

### 3.2 REST fallback (для совместимости / простых connector'ов)
- `POST /v1/module/<module_id>/events` — connector → core, batch событий.
- `GET  /v1/module/<module_id>/actions?since=<cursor>` — connector → core, polling actions. Long-poll до 25 с.
- `POST /v1/module/<module_id>/actions/ack` — connector → core, подтверждение выполнения.
- Кэдра не теряет actions: они хранятся в БД с TTL до ACK.

### 3.3 Конверт сообщения (одинаковый для WS и REST)
```json
{
  "v": 1,
  "id": "uuid-v4",
  "channel_id": "twitch-12345678",
  "module_id": "rimworld",
  "kind": "event" | "action" | "ack" | "control",
  "type": "player.spawn",
  "ts": "2026-04-30T18:23:45.123Z",
  "data": { ... },
  "extensions": { "rimworld": { ... } }
}
```
- `id` — uuid, для идемпотентности и ACK.
- `v` — версия конверта (не путать с версией API).
- `kind` различает категорию; `type` — конкретный тип внутри категории (см. §7-8).

---

## 4. Авторизация

1. Стример заходит в админку → core генерирует **module token** (HMAC-подписанный JWT, scope = `channel_id + module_id`).
2. Стример вводит токен в connector один раз. Connector сохраняет.
3. WebSocket: токен в заголовке `Authorization: Bearer <token>` при upgrade.
4. REST: тот же заголовок на каждом запросе.
5. Core валидирует токен → извлекает `channel_id` и `module_id` → отказывает если в сообщении эти поля не совпадают.
6. Ротация: токен можно отозвать в админке; следующий запрос вернёт `401`, connector должен попросить пользователя ввести новый.

**Multi-tenant invariant:** ни одно сообщение не обрабатывается без подтверждённого `channel_id`. Это хард-требование к рефакторингу.

---

## 5. Manifest модуля

Каждый модуль декларирует себя файлом `manifest.yaml` (читается ядром при загрузке) **и** во время handshake (см. §6) connector присылает свой подмножество — чтобы core видел версию connector'а.

```yaml
id: rimworld                       # уникальный slug, [a-z0-9_]
version: 1.0.0                     # semver, версия модуля
core_api_version: ">=1.0.0,<2.0.0" # с какими core API совместим
display_name: "RimWorld"
icon: "icon.png"
description: "Двусторонняя интеграция с RimWorld колонией стримера."

# Какие СТАНДАРТНЫЕ события модуль умеет слать (см. §7)
events:
  - module.heartbeat
  - module.session_start
  - module.session_end
  - module.catalog_update
  - player.linked
  - player.unlinked
  - player.state_update
  - player.died

# Какие СТАНДАРТНЫЕ actions модуль умеет принимать (см. §8)
actions:
  - player.spawn
  - player.heal
  - player.respawn
  - player.give_item
  - player.equip_item
  - player.apply_effect
  - player.modify_attribute
  - world.trigger_event

# Расширения — кастомные типы, не входящие в core API
extensions:
  events:
    - pawn.trait_changed
    - pawn.implant_installed
    - pawn.gene_changed
  actions:
    - pawn.add_trait
    - pawn.add_gene
    - pawn.set_xenotype
    - pawn.set_passion

# Какие каталоги модуль публикует (см. §9)
catalogs:
  - shop
  - events

# UI-слоты (детали в frontend-spec, отдельный документ)
ui_slots:
  - shop_panel
  - event_trigger_panel
  - player_inspector
```

Core отбрасывает action, тип которого не указан в `actions` или `extensions.actions` манифеста — это защита от рассинхронизации версий.

---

## 6. Жизненный цикл

```
[connector start]
   ↓
   open WS → send module.hello (manifest digest, connector version)
   ↓
   ← module.welcome (core_version, accepted_capabilities, server_time)
   ↓
   send module.session_start
   ↓
   ── normal loop ──────────────────────────────────────────────
   │  events: player.linked, player.state_update, ...
   │  receive: actions (player.spawn, world.trigger_event, ...)
   │  send: action.ack {id, success, message}
   │  every 30s: module.heartbeat
   ──────────────────────────────────────────────────────────────
   ↓
   send module.session_end (graceful shutdown)
   ↓
[connector stop]
```

**Reconnect:** при разрыве connector переоткрывает сокет с тем же токеном. Core продолжает копить actions; их можно дозабрать через `GET /v1/module/<id>/actions?since=<cursor>`.

**ACK:** каждое action имеет `id`. Connector обязан прислать `kind=ack` с `{id, success: bool, error?: string}` после исполнения. Core помечает action завершённым; до ACK — будет переотправлен после reconnect.

---

## 7. Стандартные события (connector → core)

«Стандартные» = ядро их понимает напрямую и может реагировать (начислять очки, пушить в фронт). Модуль волен слать их или нет; чем больше шлёт — тем «богаче» опыт зрителя.

| Тип | Когда шлётся | `data` (минимум) |
|---|---|---|
| `module.hello` | при открытии сокета | `{manifest_digest, connector_version, connector_platform}` |
| `module.heartbeat` | каждые 30 с | `{}` |
| `module.session_start` | старт игровой сессии | `{game_seed?, world_name?}` |
| `module.session_end` | graceful shutdown | `{reason}` |
| `module.catalog_update` | при изменении каталога | `{catalog: "shop"\|"events", entries: [...]}` (см. §9) |
| `player.linked` | зритель привязал свой Twitch к in-game персонажу | `{viewer_id, character_ref, display_name}` |
| `player.unlinked` | разлинковка | `{viewer_id, character_ref}` |
| `player.state_update` | периодически или по дельте, общее состояние | `{viewer_id, character_ref, alive: bool, health_pct: 0..1, level?: int, inventory?: [{item_id, qty}], stats?: {key: number}}` |
| `player.died` | смерть | `{viewer_id, character_ref, cause?}` |
| `player.respawned` | возрождение | `{viewer_id, character_ref}` |
| `world.event_occurred` | произошло событие игрового мира (рейд, погода и т.п.), в т.ч. инициированное actions | `{event_id, params, triggered_by_action_id?}` |

Поля `?` — опциональны.

**Принцип маппинга на не-RimWorld:**
- *Minecraft:* `character_ref` = UUID игрока, `inventory` = маппинг minecraft-item-id → qty, `stats.experience` вместо `level`.
- *Terraria:* `character_ref` = TShock user id, `health_pct` от max HP, `inventory` стандартен.
- *RimWorld* (текущий): `character_ref` = pawn ThingID, всё RimWorld-специфичное (skills, traits, hediffs, implants, genes) уезжает в `extensions.rimworld.*` (см. §10).

---

## 8. Стандартные actions (core → connector)

| Тип | Назначение | `data` |
|---|---|---|
| `player.spawn` | материализовать игрового персонажа для зрителя | `{viewer_id, display_name, hints?: {...}}` |
| `player.heal` | восстановить здоровье/состояние | `{viewer_id, full?: bool, amount?: number}` |
| `player.respawn` | вернуть из мёртвых | `{viewer_id}` |
| `player.kick` | удалить персонажа из игры | `{viewer_id, reason?}` |
| `player.give_item` | выдать предмет | `{viewer_id, item_id, quantity}` |
| `player.equip_item` | экипировать предмет (если уже в инвентаре) | `{viewer_id, item_id, slot?}` |
| `player.apply_effect` | универсальный бафф/дебафф/имплант (то, что игра сама умеет) | `{viewer_id, effect_id, duration_sec?, params?}` |
| `player.modify_attribute` | универсальный апдейт скаляра у персонажа | `{viewer_id, key, value, mode: "set"\|"add"\|"mul"}` |
| `world.trigger_event` | запустить именованное событие мира | `{event_id, params}` |
| `world.broadcast_message` | показать сообщение в игре от имени стрим-бота | `{text, target?: "all"\|viewer_id, level: "info"\|"warn"\|"alert"}` |

Не каждое action обязательно к реализации модулем. Manifest объявляет поддерживаемое подмножество. Core при отсутствии возможности отдаёт фронту дисабленный UI.

**Маппинг RimWorld-команд (валидация спеки на существующем коде):**

| RimWorld command (как сейчас) | Стандартный action (предлагается) |
|---|---|
| `spawn_pawn` | `player.spawn` |
| `heal_pawn` | `player.heal {full: true}` |
| `resurrect_pawn` | `player.respawn` |
| `equip_item(def_name)` | `player.equip_item {item_id: def_name}` |
| `install_implant(def_name, part)` | `player.apply_effect {effect_id: def_name, params: {part}}` |
| `train_skill(def_name)` | `player.apply_effect {effect_id: "neurotrainer", params: {skill: def_name}}` |
| `add_trait / remove_trait` | extension `pawn.add_trait` / `pawn.remove_trait` |
| `add_gene / remove_gene / add_xenotype` | extension `pawn.add_gene` / ... |
| `set_passion` | `player.modify_attribute {key: "skill.passion."+def, value: passion, mode: "set"}` |
| `fire_incident(def, points)` | `world.trigger_event {event_id: def, params: {points}}` |
| `event_weather / event_raid / event_drop / event_wanderer / event_animals` | то же самое, конкретные `event_id` объявляются в каталоге событий модуля (см. §9) |

→ Вывод: 90% RimWorld-команд укладываются в стандартные actions без потерь. Действительно специфичны только `add_trait/remove_trait/add_gene/add_xenotype` (нет аналога во многих играх).

---

## 9. Каталоги

Модуль декларирует свои покупаемые сущности через `module.catalog_update`. Это решает проблему: ядро не знает что продаётся в игре — модуль сам публикует прайс.

### 9.1 Shop catalog
```json
{
  "catalog": "shop",
  "entries": [
    {
      "item_id": "Apparel_Parka",        // unique within module
      "display_name": "Parka",
      "category": "apparel",              // free-form, для UI-фильтров
      "cost": 150,
      "currency": "points",
      "icon_url": "...",
      "delivery_action": "player.give_item",
      "extra": { "def_name": "Apparel_Parka" }
    }
  ]
}
```
Когда зритель покупает товар, core порождает action `delivery_action` с merge `{viewer_id, item_id, ...extra, quantity: 1}`. Модуль не пишет своих эндпоинтов — просто реагирует на стандартный action.

### 9.2 Events catalog
```json
{
  "catalog": "events",
  "entries": [
    {
      "event_id": "Raid",
      "display_name": "Рейд",
      "tier": 4,                 // 0..5, для UI и ограничений ядра
      "cost": 500,
      "params_schema": {
        "points": { "type": "int", "min": 100, "max": 5000, "default": 800 }
      },
      "trigger_action": "world.trigger_event"
    }
  ]
}
```
Параметры схемы → core рендерит форму на фронте → assembled `params` уезжают в action.

### 9.3 Инвалидация
Модуль может слать каталог целиком (replace) или дельту (`{op: "upsert"|"remove", entries: [...]}`) — управляется полем `mode`. Core кэширует и инвалидирует фронт-подписки.

---

## 10. Extensions

Всё, что не вписывается в стандартные типы, идёт под пространство имён модуля:

```json
{
  "kind": "event",
  "type": "pawn.trait_changed",
  "data": {},
  "extensions": {
    "rimworld": {
      "viewer_id": "...",
      "trait_def": "Bloodlust",
      "degree": 1,
      "added": true
    }
  }
}
```

**Правила:**
1. `type` начинается с произвольного префикса (например `pawn.*`), но регистрируется в манифесте под `extensions.events` / `extensions.actions`.
2. Полезная нагрузка лежит в `extensions.<module_id>` — это явно сигнализирует ядру «не пытайся понять».
3. Core ретранслирует extensions на фронт без интерпретации — UI-слоты модуля сами рендерят.
4. Ядро **никогда** не реагирует на extensions автоматически (никаких начислений очков, триггеров достижений и т.п.). Это сохраняет инкапсуляцию.

---

## 11. Версионирование

- **Module API version:** semver, начинаем с `1.0.0`. Объявлена в каждом ответе core (`module.welcome.core_version`).
- **Manifest `core_api_version`:** semver-range. Core отказывает в handshake если не совпадает.
- **Конверт `v`:** integer, инкрементируется при breaking changes на уровне формата сообщения. Core поддерживает N-1 версию минимум 6 месяцев.
- **Тип события / action**, однажды добавленный в стандарт, не удаляется в minor-версиях. Только deprecation → удаление в major.
- **Поля `data`:** добавление опциональных полей — minor. Удаление / смена типа — major.

Changelog API ведётся в `docs/MODULE_API_CHANGELOG.md` (создать при первом изменении).

---

## 12. Обработка ошибок

| Ситуация | Поведение core | Поведение connector |
|---|---|---|
| Невалидный токен | `401`, закрыть сокет | попросить пользователя обновить токен |
| `channel_id` в сообщении ≠ токену | `403`, drop message | лог, не ретраить |
| Неизвестный `type` (нет в манифесте) | `400` для action; для event — drop с warning | для action — отправить `ack {success: false, error: "unsupported"}` |
| ACK timeout (action не подтверждён 60 с) | пометить failed, переотправить N=3 раза, потом отказаться | — |
| Connector crashed mid-action | actions не теряются (хранятся до ACK), переотправятся | — |
| Несовместимый `core_api_version` | отказ в handshake с `426 Upgrade Required` | показать пользователю «обновите connector» |

---

## 13. Multi-tenant invariants

Эти инварианты — обязательная база для рефакторинга ядра в шаге 2 дорожной карты. Module API их полагается, ядро обязано обеспечить:

1. Каждая запись в БД, относящаяся к игровой сессии, помечена `channel_id`.
2. Все REST/WS-запросы валидируются: `token.channel_id == request.channel_id`.
3. Per-channel rate limits (защита от шума с одного канала).
4. Каталоги модуля скоупятся по `channel_id` (у каждого стримера свой набор товаров — даже один и тот же модуль).
5. Player records (`viewer_id, character_ref`) уникальны в пределах `(channel_id, module_id)`.

---

## 14. Что осталось решить (open questions)

1. **WS vs SSE+POST.** WebSocket требует реверс-прокси правильной конфигурации. Альтернатива — SSE для core→connector + POST для обратного направления. SSE проще для C# мода. **Решение к следующей итерации.**
2. **Auth: один токен на модуль или раздельные.** Сейчас предлагается один на канал+модуль. Если стример хочет давать доступ только UI-чанку (не connector'у) — нужны scope'ы. **Отложено: не нужно для MVP.**
3. **Player-level quotas.** Должен ли модуль уметь просить core «не пускай этого зрителя в действия N минут»? — кандидат в стандартные actions, но переусложнение. **Отложено.**
4. **Frontend slots контракт.** Нужен отдельный документ `MODULE_UI.md`.
5. **Catalog ограничения per tier.** Pro-стримеры видят все entries, Free — только базовые? Это политика биллинга, не Module API. **Решается на уровне ядра.**
6. **Idempotency для events** (не только actions). Если connector пере-шлёт `player.died` после рестарта — core должен дедупить по `id`? **Да, добавить в §3.3 как обязанность core.**
7. **Бинарные данные** (иконки в каталоге, превью). Сейчас — `icon_url`. Альтернатива — base64 в catalog_update. **Оставляем URL; модуль раздаёт статику сам.**

---

## 15. Чек-лист перед началом кода (Шаг 2 дорожной карты)

- [ ] Утвердить транспорт (WS / SSE+POST). До тех пор используем REST из §3.2.
- [ ] Закрыть open question #1 и #6.
- [ ] Описать `MODULE_UI.md` (UI-слоты).
- [ ] Сделать handler-stub `backend/modules/_base.py` с типами `ModuleAdapter`.
- [ ] Описать миграцию текущих RimWorld-эндпоинтов на Module API (mapping table из §8 — основа).

---

## 16. История

| Дата | Версия | Изменения |
|---|---|---|
| 2026-04-30 | 0.1 | Первая редакция: транспорт, авторизация, manifest, стандартные events/actions, маппинг RimWorld, open questions. |
