# Bannerlord Module — Context (chat handoff)

**Назначение:** для чата по Bannerlord-модулю. Для общей extension
работы — см. `CONTEXT.md`. Для RimWorld — `CONTEXT_RIMWORLD.md`.

**Last updated:** 2026-05-16 (dual-currency economy live)

---

## TL;DR

Второй gaming-модуль платформы. Зрители adopt'ят NPC героя в Bannerlord
(имя hero = ник зрителя), выбирают **класс** (Tank/Archer/Cavalry/...
13 классов) с подходящим snar'ем и passive/active powers, тратят валюту
из стрима на:

- **Боевое:** призыв в бой (за или против стримера), 4 active powers
  (heal_burst / shield_break / rage / retribution_toggle)
- **Экономику:** конвертация крустиков в Hero.Gold или skill XP
- **Прогрессию:** улучшение снаряжения по 6 tier'ам (платится Hero.Gold,
  не крустиками — это создаёт economy loop)
- **Случайности:** random equip (оружие / броня / конь)

**Архитектура:** C# Bannerlord-submodule (`BannerlordLink/`,
prod-mirror в `Modules/Shedoy23.BannerlordLink/`) ↔ FastAPI backend
(`Расширение/backend/`) через Module API generic dispatcher
(`routes/module_api.py`) + Bannerlord-specific endpoints
(`routes/bannerlord.py`).

---

## Экономика — две валюты (важно!)

| Валюта | Где живёт | Что покупает |
|---|---|---|
| **Крустики ⦷** | Backend `viewers.points` | Быстрые boost'ы — powers, summon, random-equip, конверсия в Hero.Gold / XP |
| **Hero.Gold 💰** | In-game (Bannerlord save) | Gear tier upgrades (T1→T6) — единственный sink |

**Loop:** viewer накапливает крустики на стриме → конвертирует часть
в Hero.Gold (1000⦷ = 5000💰, 1:5) → копит много 💰 → улучшает снаряжение
в extension'е (mod-side списывает Hero.Gold, replace'ит slots на
random items нужного tier'а).

**Source of truth:**
- Крустики: backend `viewers.points`, atomic charge внутри `/action` TX
- Hero.Gold: мод (`hero.Gold` через `GiveGoldAction.ApplyBetweenCharacters`)
- gear_tier: мод пушит `hero.gear_tier_changed` event после successful
  in-game upgrade → backend обновляет DB cache. Если мод не смог
  списать (insufficient gold) — event не отправлен, backend остаётся
  синхронизирован.

---

## Текущий статус — 19 sprints закрыто

### Backend infrastructure
- **Migrations:**
  - M14 — `bannerlord_heroes` / `_skills` / `_attributes` /
    `_equipment` / `_events_log` (TENANT-scoped, M14_bannerlord.py)
  - M15 — `bannerlord_classes` (13 seeded) + `bannerlord_hero_class`
  - M16 — `bannerlord_class_powers` (33 power rows)
  - M17 (parallel) — eventsub_dedupe (не наш, из main)
  - M18 — `armor_bypass_pct → ignore_armor_pct` fixup + 4 active power seeds
    (tank/shield_break_burst, psycho+berserk/rage, knight/retribution_toggle)
  - M19 — bannerlord_heroes meta: `level INT DEFAULT 1`, `clan_name TEXT`,
    `kingdom_name TEXT`
  - M20 — bannerlord_heroes: `gear_tier INT DEFAULT 0`

- **routes/bannerlord.py:** 9 endpoints (см. ниже)
- **modules/bannerlord/_adapter.py:** 15 event types обработаны.
  In-memory state: `_last_seen`, `_active_buffs`, `_cooldowns`.
  Helpers: `get_active_buffs`, `get_active_cooldowns`, `check_cooldown`,
  `set_cooldown`.
- **POWER_COOLDOWNS** в `_adapter.py`: heal=30s / shield_break=90s /
  rage=60s / retribution=90s / player.spawn=120s. Server-side enforced
  в `/action` (key=power_key для power.activate, key=action_type для
  player.spawn).
- **Server-side price maps** в `routes/bannerlord.py`:
  - `RANDOM_EQUIP_PRICES`: weapon=1M⦷ / armor=500K⦷ / horse=1.25M⦷
  - `SPAWN_PRICES`: player=500⦷ / enemy=1000⦷
  - `HERO_GOLD_TIER_COSTS` (display + mod mirror): T1=50K / T2=100K /
    T3=200K / T4=400K / T5=800K / T6=1.5M динаров
  - `GIVE_GOLD_PRESETS`: 1K⦷→5K💰 / 5K⦷→25K💰 / 20K⦷→100K💰 (1:5)
  - `ADD_SKILL_XP_PRESETS`: 500⦷→50XP / 1K⦷→100XP / 5K⦷→500XP
- **Test 19** — 15 isolation assertions (не обновлялся под новые поля,
  TODO добавить assertions для gear_tier / level / clan)

### C# mod (BannerlordLink)
- SDK-style csproj, `.NET Framework 4.8` net472, x64, Bannerlord 1.3.15
- BackendClient + Config + ActionPoller + MainThreadDispatcher
- Action handlers (10 real):
  - `hero.create` — adopt fresh wanderer + SetName + initial state push
  - `hero.set_class` — apply class equipment (FindRandomItem per slot)
  - `hero.upgrade_gear` — 6-tier progression, Hero.Gold deduction +
    push hero.gear_tier_changed (M21+ dual-currency)
  - `hero.add_skill` — XP boost; **random skill** если skill_key пуст
  - `player.heal` / `player.give_item` (gold) /
    `player.modify_attribute`
  - `player.spawn` — summon в Mission через `Mission.SpawnTroop`;
    `data.side` ("player"/"enemy"). Mode check via `.ToString()=="Battle"`
    (reflection-safe). Guards: alive + Continuing + не already spawned.
  - `player.equip_item` — targeted (`item_id`) или random
    (`random_category`: weapon/armor/horse) с tier ≥4 filter
  - `power.activate` — 4 power_keys: heal_burst / shield_break_burst
    (AoE + particle + sound) / rage (timed multi) / retribution_toggle
- Campaign behaviors:
  - `MainCampaignBehavior` — HeroKilled → player.died; HeroLevelledUp →
    HeroStateSync.Push (full state)
  - `PowersMissionBehavior` — `OnAgentBuild` apply passive HP/scale +
    slow-tick `ActiveBuffState.RemoveExpired` + `OnEndMission → Clear`
- Harmony patches (`src/Patches/`):
  - `DamageHookPatch.cs` — Prefix на `Mission.RegisterBlow`:
    passive ignore_armor + damage_reflect + active rage outgoing multi +
    retribution_toggle overlay (sum capped 95%)
  - `IsSideDepletedPatch.cs` — Postfix на `MissionAgentSpawnLogic`:
    если на side есть adopted hero (PowerCache) → side не depleted
    (reinforcement waves продолжаются)
- Helpers:
  - `Net/PowerCache.cs` — class+power dict singleton (DB-synced)
  - `Net/ActiveBuffState.cs` — timed buffs ConcurrentDictionary;
    expiry source `Mission.Current.CurrentTime` (паузо-чувств.)
  - `Util/HeroStateSync.cs` — push full state (gold/level/clan/kingdom/
    location/is_alive/is_prisoner) на backend; вызывается из
    AdoptHeroHandler + MainCampaignBehavior + UpgradeGearHandler

### Frontend (`extension.html` / `viewer.js`)
- Hero card grid: 💰 Динары / ⭐ Уровень / 🛡 Снаряжение (T1-T6 ★) /
  🏰 Клан / 👑 Королевство (последние 3 "не вступил" если null)
- Class picker (13 кнопок)
- Online badge (🟢/🔴 polling /status)
- Active power buttons (heal / shield_break / rage / retribution) —
  disabled на active buff или cooldown, показ X с countdown
- Buff HUD — chip-list над picker'ом (rage 24с / retribution 58с)
- Summon: 2 кнопки «📯 Призвать за стримера 500⦷» / «⚔️ Призвать против
  стримера 1000⦷» (красная). Общий cooldown 120с.
- Shop card ("Действия в игре") — 4 блока:
  1. 🎁 Случайный товар: weapon/armor/horse buttons
  2. 🛡 Снаряжение: ⚒ Улучшить до T{N+1} (цена в **💰 динарах**, не крустиках)
  3. 💰 Динары: +5K/25K/100K за 1K/5K/20K⦷
  4. 📚 Опыт: +50/100/500 XP в random skill за 500/1K/5K⦷

### ⏳ Pending sprints
- **4.10** Balancing после live test: финальные cooldowns + active
  power values + tier costs (Hero.Gold + крустики rates) — нужны
  stream data
- **5.2** Compliance rebrand перед public release: аудит class_keys /
  power_keys / numeric values vs BLT, NOTICE.md, Twitch submission prep
- **Test 19 extend** — assertions для gear_tier / level / clan
  изоляции между channels
- **Adapter sync на cache invalidate** — после смены clan/kingdom
  в-игре нужен trigger для re-sync state (сейчас обновляется только
  на adopt + level-up)

---

## Stack
- **C# mod:** `.NET Framework 4.8` net472 x64, Bannerlord 1.3.15
- **References:** TaleWorlds.{Core / Library / MountAndBlade /
  CampaignSystem / CampaignSystem.AgentOrigins / CampaignSystem.Party /
  CampaignSystem.Actions / Engine / Localization / ObjectSystem /
  DotNet}, Bannerlord.Harmony, Newtonsoft.Json
- **Build:** `dotnet build` (~1-2 сек), output в
  `Modules/Shedoy23.BannerlordLink/bin/Win64_Shipping_Client/`
- **Editor:** VS Code + `ms-dotnettools.csharp`

## File structure (BannerlordLink mod)

```
X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\
└── Modules\Shedoy23.BannerlordLink\
    ├── SubModule.xml          ← module declaration (DLC-free deps)
    ├── config.json            ← module_token + channel_id (gitignored)
    ├── src\
    │   ├── BannerlordLink.csproj
    │   ├── BannerlordLinkModule.cs   ← MBSubModuleBase entry
    │   ├── MainThreadDispatcher.cs   ← cross-thread queue
    │   ├── Net\
    │   │   ├── BackendConfig.cs / BackendClient.cs / ActionPoller.cs
    │   │   ├── PowerCache.cs         ← class+power singleton (DB-synced)
    │   │   └── ActiveBuffState.cs    ← timed buffs runtime
    │   ├── Actions\
    │   │   ├── IActionHandler.cs / ActionRegistry.cs / EchoHandler.cs
    │   │   ├── AdoptHeroHandler.cs (hero.create)
    │   │   ├── SetClassHandler.cs (hero.set_class)
    │   │   ├── UpgradeGearHandler.cs (hero.upgrade_gear — M21 dual-currency)
    │   │   ├── HealHeroHandler.cs / GiveGoldHandler.cs
    │   │   ├── AddSkillXpHandler.cs / ModifyAttributeHandler.cs
    │   │   ├── ActivatePowerHandler.cs (power.activate)
    │   │   ├── SummonHeroHandler.cs (player.spawn ally/enemy)
    │   │   ├── EquipItemHandler.cs (player.equip_item targeted/random)
    │   │   └── HeroLookup.cs
    │   ├── Behaviors\
    │   │   ├── MainCampaignBehavior.cs   ← HeroKilled / LevelledUp
    │   │   └── PowersMissionBehavior.cs  ← OnAgentBuild + buff tick
    │   ├── Patches\
    │   │   ├── DamageHookPatch.cs        ← Mission.RegisterBlow Prefix
    │   │   └── IsSideDepletedPatch.cs    ← reinforcement keep-alive
    │   └── Util\
    │       └── HeroStateSync.cs          ← push full state snapshot
    └── bin\Win64_Shipping_Client\
        └── BannerlordLink.dll  ← output после dotnet build
```

Mirror в git-репо: `BannerlordLink/` (sync через `cp` после правок).

---

## Backend endpoints (Bannerlord-specific)

| Endpoint | Что |
|---|---|
| `GET /api/bannerlord/ping` | Public health check |
| `GET /api/bannerlord/status` | Online/offline (last event < 60s) |
| `GET /api/bannerlord/my-hero` | Hero + skills + attributes + equipment + level/clan/kingdom/gear_tier |
| `GET /api/bannerlord/classes` | Catalog + viewer's current class + current_powers (active) |
| `GET /api/bannerlord/class-state` | All channel heroes + powers (для mod на handshake) |
| `GET /api/bannerlord/shop` | module_catalogs (mod-pushed item shop, optional) |
| `GET /api/bannerlord/my-buffs` | `{buffs: [{power_key, remaining_s}], cooldowns: [...]}` (HUD polling) |
| `POST /api/bannerlord/action` | Atomic charge крустиков + cooldown check + enqueue в module_actions |
| `POST /api/admin/module/issue-token` | Issue module-token для mod auth |

## Schema (M14-M20)

```
bannerlord_heroes        (channel_id, username) PK
                          hero_id, display_name, culture, is_alive,
                          is_prisoner, gold, location, last_sync,
                          level, clan_name, kingdom_name,   ← M19
                          gear_tier                          ← M20
bannerlord_skills        (channel_id, username, skill_key) PK, level, xp
bannerlord_attributes    (channel_id, username, attribute) PK, value
bannerlord_equipment     (channel_id, username, slot) PK, item_id, item_name
bannerlord_events_log    id PK, channel_id, event_type, username, payload
bannerlord_classes       class_key PK, formation, slot1-4, use_horse/camel
bannerlord_hero_class    (channel_id, username) PK, class_key, class_level
bannerlord_class_powers  (class_key, power_key) PK, lvl1/2/3 values
```

## Event types (mod → backend)

Standard: `module.{heartbeat,session_start,session_end,catalog_update}`,
`player.{linked,unlinked,state_update,died,respawned}`,
`world.event_occurred`.

Extensions (Bannerlord-specific):
- `hero.{skill_changed, equipment_changed, relation_changed, faction_changed}`
- `buff.{activated, expired}` — runtime active power state (Sprint 4.6)
- `hero.gear_tier_changed` — после successful in-game upgrade (Sprint M21)

## Build + deploy cycle

```cmd
# C# build (mirror в production folder)
cd "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src"
dotnet build

# Restart Bannerlord (нет hot-reload). Mod log:
type "C:\Users\Edward\Documents\Mount and Blade II Bannerlord\Configs\ModLogs\bannerlordlink_*.txt"

# Sync обратно в git-репо (для commit)
cd C:\Users\Edward\Desktop\work\.claude\worktrees\<...>
cp "X:\SteamLibrary\...\Shedoy23.BannerlordLink\src\*.cs" BannerlordLink\src\

# Backend + frontend deploy на прод
cd Расширение
tar -cz backend frontend | ssh root@31.130.132.224 \
  'cd /root/twitch-extension && tar -xz && supervisorctl restart twitchbot'
```

## Лицензия BLT (важно!)

**BLT (LGPL 2.1)** — используем как **reference только**, не copy-paste.
- ✅ Идеи / архитектурные паттерны / API discovery / 5-10 строчные idioms
- ❌ Целые классы / method bodies / identical names+numbers

Наш `BannerlordLink/` — clean-room re-impl: отличающаяся архитектура
(DB-driven + flat handlers vs BLT's class hierarchy), отличающиеся
numeric values (например M16 ignore_armor 10/25/40 vs BLT 12/27/45),
наши имена классов (Tank/Archer/Psycho/Berserk/Knight). **Перед public
release** (Sprint 5.2) — полный аудит для финального compliance check.

## Тестирование

См. `CONTEXT.md` §«Тестирование» — те же flows работают:
- `/dev` login + extension preview
- `curl /api/admin/dev/jwt` для preview tokens
- `TESTING_BYPASS_STREAM_LIVE=true` для actions без go-live

**Module test данные:**
- Channel: 98319857 (shedoy23)
- Module token (issued, 1 год TTL) — в config.json мода

## Repo

- **GitHub:** `Shedoy23/shedstream` (private)
- **Files:** `BannerlordLink/` (mirror mod), `Расширение/backend/`
  ({routes/bannerlord.py, migrations/m14_*-m20_*, modules/bannerlord/}),
  `Расширение/frontend/viewer.js`, `Расширение/docs/BANNERLORD_*.md`

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT_BANNERLORD.md, продолжаем Bannerlord-модуль»*.
