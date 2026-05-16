# Bannerlord Module — MVP Plan

**Goal:** Mirror RimLink functionality для Mount & Blade II: Bannerlord.
Зрители владеют героями (Hero), стримерские акции через extension влияют
на игру (summon в битву, give item, attribute boost).

**Architecture:** mirror RimLink — тонкий C# submodule в Bannerlord
общается с FastAPI backend через HTTP polling (action queue) + push
events. Module API (`modules/_base.py`) уже game-agnostic.

**Reference:** `C:\Users\Edward\Downloads\Bannerlord-Twitch-5.2.4.zip`
(BLT исходники, LGPL 2.1) — читаем как описание для clean-room
имплементации, не форкаем.

---

## 0. Scope mapping: RimLink → Bannerlord

| RimLink | Bannerlord | Что зрители видят |
|---|---|---|
| Pawn (колонист) | Hero (NPC-герой) | Аватар + инвентарь + скиллы |
| Pawn skills (Construction, Cooking…) | Hero attributes + skills (Vigor, Riding, Bow…) | Прокачка через actions |
| Pawn equipment | Hero equipment slots (weapon, armor, horse) | Купить/выдать снаряжение |
| Pawn hediffs (травмы, болезни) | Hero wound/captured/dead status | Лечение / воскрешение |
| Pawn xenotype | Hero culture (Vlandian/Aserai/…) | Меняется через action |
| Pawn traits | Hero traits (Mercy, Honor, Valor…) | Косметика характера |
| Pawn purchase (event/spawn/heal) | Hero action queue (summon/give/effect) | Action triggered from extension |
| Shop catalog | Equipment + event triggers catalog | Покупаем за крустики |
| `current_stream_id` per-channel | `current_save_id` per-channel | Изоляция между сессиями |

## 1. Standard events (Module API §7)

Наш `manifest.yaml` уже декларирует. Mapping на Bannerlord:

| Module event | Bannerlord `CampaignEvents.*` | Описание |
|---|---|---|
| `module.session_start` | OnGameLoadFinishedEvent | Load save / new game |
| `module.session_end` | OnGameEnd / SubModule.OnGameEnd | Save/quit |
| `module.heartbeat` | DailyTickEvent (каждый игровой день) | Health check |
| `module.catalog_update` | — (push from mod при init) | Sync prices/items |
| `player.linked` | (AdoptAHero command) | Зритель привязан к Hero |
| `player.unlinked` | (admin unlink) | Открепили |
| `player.state_update` | HeroLevelledUp / equipment change | Hero changed |
| `player.died` | HeroKilledEvent | Hero убит |
| `player.respawned` | (через heir succession / respawn action) | Перерождение |
| `world.event_occurred` | MapEventStarted, OnSiegeEventStartedEvent, etc. | Глобальные ивенты стримера |

### Extension events (Bannerlord-specific)

| Event | When |
|---|---|
| `hero.skill_changed` | Skill points changed |
| `hero.equipment_changed` | Equip/unequip item |
| `hero.relation_changed` | Relations with NPCs |
| `hero.faction_changed` | Joined/left clan |
| `world.battle_outcome` | Battle won/lost (with winner side) |
| `world.settlement_captured` | Player took settlement |

## 2. Standard actions (Module API §8)

Что зрители могут «купить» через extension:

| Action | Эффект in-game | Аналог RimLink |
|---|---|---|
| `player.spawn` | Summon hero в текущую battle на стороне игрока | RimLink event_spawn |
| `player.heal` | Heal wounds, restore to full HP | pawn_heal |
| `player.respawn` | Re-create hero после смерти (через heir/respawn) | pawn_respurrect |
| `player.give_item` | Дать оружие/доспех/коня в инвентарь | inventory item |
| `player.equip_item` | Надеть item на hero | equipment slot change |
| `player.modify_attribute` | +1 attribute point / skill point | skill upgrade |
| `world.trigger_event` | Spawn bandit attack / mercenary offer / etc. | event triggers |
| `world.broadcast_message` | In-game popup для всех | toast message |

### Bannerlord-specific actions

| Action | Эффект |
|---|---|
| `hero.add_skill` | +N points to specific skill (e.g. Bow) |
| `hero.set_culture` | Cosmetic culture switch |
| `hero.set_faction` | Транзитом в другой клан |
| `hero.recruit_troops` | +N солдат в personal retinue |

## 3. БД schema (M14 migration)

```sql
-- Bannerlord heroes per-channel (mirror rimworld_pawns)
CREATE TABLE bannerlord_heroes (
    channel_id INTEGER NOT NULL,
    username   TEXT NOT NULL,            -- viewer Twitch login
    hero_id    TEXT NOT NULL,            -- Bannerlord internal hero ID (Hero.StringId)
    name       TEXT NOT NULL,
    culture    TEXT,                     -- vlandian/empire/aserai/...
    is_alive   INTEGER DEFAULT 1,
    is_prisoner INTEGER DEFAULT 0,
    gold       INTEGER DEFAULT 0,
    location   TEXT,                     -- current settlement/area
    last_sync  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (channel_id, username)
);

CREATE TABLE bannerlord_skills (
    channel_id INTEGER NOT NULL,
    username   TEXT NOT NULL,
    skill_key  TEXT NOT NULL,            -- Vigor/Riding/Bow/OneHanded/...
    level      INTEGER DEFAULT 0,
    xp         INTEGER DEFAULT 0,
    PRIMARY KEY (channel_id, username, skill_key)
);

CREATE TABLE bannerlord_equipment (
    channel_id INTEGER NOT NULL,
    username   TEXT NOT NULL,
    slot       TEXT NOT NULL,            -- weapon_0/.../armor/helmet/horse/...
    item_id    TEXT,                     -- Bannerlord ItemObject.StringId
    item_name  TEXT,
    PRIMARY KEY (channel_id, username, slot)
);

CREATE TABLE bannerlord_attributes (
    channel_id INTEGER NOT NULL,
    username   TEXT NOT NULL,
    attribute  TEXT NOT NULL,            -- vigor/control/endurance/cunning/social/intelligence
    value      INTEGER DEFAULT 0,
    PRIMARY KEY (channel_id, username, attribute)
);

-- Events log (для analytics/audit, не для state)
CREATE TABLE bannerlord_events_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,            -- hero_killed/battle_won/...
    payload    TEXT,                     -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_bnr_events_channel ON bannerlord_events_log(channel_id, created_at DESC);
```

Action queue — используем существующий `pending_commands` из M5 (generic
action queue). Bannerlord-mod polls `/api/module/pending-actions` каждые
N секунд.

## 4. Backend deliverables (Sprint 1, ~1 неделя)

1. **`migrations/m14_bannerlord.py`** — 4 таблицы выше + indexes + idempotency через `migrations_applied`
2. **`modules/bannerlord/_adapter.py`** — реальные event handlers:
   - `player.linked` → upsert в `bannerlord_heroes`
   - `player.died` → set `is_alive=0` + log в `bannerlord_events_log`
   - `player.state_update` → update skills/equipment/attributes
   - `world.event_occurred` → log + push в TG если major (siege, settlement captured)
3. **`routes/bannerlord.py`** — viewer-facing endpoints:
   - `GET /api/bannerlord/my-hero` — мой hero state
   - `POST /api/bannerlord/adopt` — adoption flow (зритель ↔ free NPC hero)
   - `GET /api/bannerlord/shop` — catalog actions+items
   - `POST /api/bannerlord/action` — купить action (списать крустики, enqueue)
4. **Isolation tests** (Test 19 в test_multi_tenant_isolation.py):
   - Heroes изолированы per channel_id
   - Event log per-channel
   - Cross-channel adoption блокирован

## 5. Frontend deliverables (Sprint 1.5, ~3 дня)

В extension.html tab «🔌 Интеграция» — conditional render по
`channel.active_module`:
- `'rimworld'` → existing pawn UI
- `'bannerlord'` → new hero UI
- `null` → «Подключи модуль игры»

Bannerlord UI:
- Hero card (avatar/name/culture/is_alive/gold)
- Equipment slots grid
- Skills bars
- Shop tab — actions + items (с ценами)

## 6. C# mod deliverables (Sprint 2-3, ~2-3 недели)

**`BannerlordLink/`** Bannerlord submodule. Структура зеркал
`BLTAdoptAHero/`:

- `_Module/SubModule.xml` — dependencies: Harmony, Native, SandBoxCore, Sandbox, StoryMode
- `BannerlordLinkModule.cs` extends `MBSubModuleBase` — entry point
- `Behaviors/MainCampaignBehavior.cs` — CampaignEvents subscriptions (mapping см. §1)
- `Net/BackendClient.cs` — HTTP client + JWT auth (streamer token из local config file)
- `Net/ActionPoller.cs` — polling `/api/module/pending-actions` каждые ~3 сек
- `Actions/` — каждый action из §2 как handler class:
  - `SummonHeroAction.cs` (lift logic из BLT SummonHero.cs)
  - `GiveItemAction.cs`
  - `HealHeroAction.cs`
  - `ModifyAttributeAction.cs`
  - и т.д.
- `Util/HeroLookup.cs` — username ↔ Hero mapping cache
- `Config/BackendConfig.cs` — JWT token, backend URL, polling interval

**Не делаем** (cut for MVP):
- BLT WPF Configure UI — не нужен (всё через extension)
- BLT IRC bot — не нужен (Twitch Extension JWT уже даёт auth)
- BLT Bucks валюта — наша платформа имеет крустики
- BLT SignalR overlay — наш Twitch Extension overlay делает это
- BLT Settings.yaml — конфиг приходит через `/api/module/catalog` push
- AdoptAHero advanced features (heirs, clan management, marriages) —
  отложено на post-MVP

## 7. Sprints

| Sprint | Длительность | Что |
|---|---|---|
| **0. Discovery** | 1 day | ✅ done (этот документ) |
| **1. Backend infra** | 1 нед | M14, _adapter real, routes, tests |
| **1.5 Frontend stub** | 3 дня | extension.html bannerlord conditional |
| **2. C# mod skeleton** | 1 нед | SubModule.xml, HTTP client, polling, GameLoad handshake |
| **3. C# events + simple actions** | 1 нед | hero adoption, heal, give gold, basic CampaignEvents subscriptions |
| **4. C# advanced actions** | 1-2 нед | summon в battle, agent effects, world events |
| **5. Polish + tests** | 3-5 дней | live test on stream, fix edge cases |

**Total: 4-6 недель MVP.** RimLink заняла ~3-4 месяца для аналогичного scope —
у нас фора потому что infrastructure (Module API, БД pool, JWT auth,
multi-tenant) уже есть.

## 8. Open вопросы перед стартом

1. **Bannerlord version target.** Latest stable = 1.3.x. BLT под 1.3.15.
   Я фиксирую 1.3.15 как target? Или хочешь latest 1.4.x?
2. **C# IDE.** Visual Studio Community / Rider у тебя готово?
3. **Test save.** Нужен «clean» save с парой готовых NPC-героев чтобы
   тестить adoption. У тебя такой есть, или генерим новый?
4. **JWT token transfer.** Стример скопирует свой JWT из extension config
   в `BannerlordLink/config.json` локально на своём ПК. ОК?
5. **Hero name policy.** Если зритель `@LuckyLokki` adoptит NPC `Lord
   Rolf of Vlandia` — мы переименовываем NPC на «LuckyLokki» в игре, или
   оставляем original имя и просто mapping в БД? Скорее всего вариант 2
   (UX в игре естественнее, mapping в overlay показывает «Hero Lord
   Rolf — owned by @LuckyLokki»).
6. **Death = permanent или respawn?** RimLink имеет respurrect через
   purchase. Bannerlord: 1) permanent death + heir succession (BLT
   pattern), либо 2) respawn-purchase. Что выбираем?

## 9. Что я делаю прямо сейчас (после approve'а)

**Sprint 1 backend** — никакого C# / Bannerlord окружения не нужно. Можно
сделать без участия стримера (полностью на бэке):

1. Создать `m14_bannerlord.py` миграцию
2. Расширить `_adapter.py` (real event handlers)
3. Создать `routes/bannerlord.py` (4 endpoints)
4. Test 19 в isolation tests
5. Минимальный stub в extension.html

Это даст **функциональный backend ready to receive events** через 5-7
дней работы. C# мод (Sprint 2+) — после того как ты подтвердишь готовность
IDE/environment, и параллельно сможешь тестить in-game.

---

**Approve этот план или скажи что поменять. После — старт.**
