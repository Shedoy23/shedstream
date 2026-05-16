# Bannerlord Module — Context (chat handoff)

**Назначение:** для чата по Bannerlord-модулю. Для общей extension
работы — см. `CONTEXT.md`. Для RimWorld — `CONTEXT_RIMWORLD.md`.

**Last updated:** 2026-05-16 (Sprint 4.4 closed — damage hooks)

## TL;DR

Второй gaming-модуль платформы. Зрители adopt'ят NPC героя, выбирают
**класс** (Tank/Archer/Cavalry/...) с подходящим snar'ем и passive
powers (HP×, skill boost, body scale), могут активировать active power
(heal_burst). Adoption / class change / actions — через extension UI
+ action queue.

## Текущий статус — Sprint 4.4 closed

### ✅ Закрыто (9 sprints)

**Backend infrastructure:**
- M14 migration: `bannerlord_heroes` / `_skills` / `_attributes` /
  `_equipment` / `_events_log` (TENANT-scoped)
- M15 migration: `bannerlord_classes` (13 seeded) + `bannerlord_hero_class`
- M16 migration: `bannerlord_class_powers` (33 power rows)
- routes/bannerlord.py: 7 endpoints (my-hero, shop, action, ping, status,
  class-state, classes)
- modules/bannerlord/_adapter.py: 12 event types обработаны
- Test 19 — 15 isolation assertions

**C# mod** (`BannerlordLink/`, `Modules/Shedoy23.BannerlordLink/` на проде):
- SDK-style csproj, `.NET Framework 4.8` net472, x64
- BackendClient + Config + ActionPoller + MainThreadDispatcher
- 7 real action handlers:
  - `hero.create` (adoption — fresh NPC + SetName)
  - `hero.set_class` (apply equipment + skill boosts + powers cache)
  - `player.heal` (max HP)
  - `player.give_item` (gold)
  - `hero.add_skill` (XP boost)
  - `player.modify_attribute` (attribute points)
  - `power.activate` (heal_burst MVP)
- MainCampaignBehavior (HeroKilled, HeroLevelledUp → events)
- PowersMissionBehavior (HP multi + body_scale via reflection)
- **Patches/DamageHookPatch.cs** — Sprint 4.4 Harmony Prefix на
  `Mission.RegisterBlow`: applies `ignore_armor_pct` / `armor_bypass_pct`
  (alias, attacker outgoing — сдвигает damage из AbsorbedByArmor в InflictedDamage)
  и `damage_reflect_pct` (victim incoming — counter-blow с recursion guard
  через ThreadLocal). Username резолвится через CharacterObject.HeroObject.Name.

**Frontend** (`extension.html` Bannerlord tab):
- Hero card (avatar, culture, gold, skills, equipment)
- Class picker (13 buttons, current highlighted)
- Online badge (🟢/🔴 polling /api/bannerlord/status)
- «⚔️ Стать героем» в empty state

### ⏳ Pending sprints

- **4.5** Active powers — `shield_break_burst` (instant AoE через
  `Mission.GetNearbyAgents` + `ChangeWeaponHitPoints(slot,0)` + visual
  `psys_game_shield_break`), `rage` (timed 30s damage multi через
  ActiveBuffState dict + check в DamageHookPatch), `retribution_toggle`
  (timed 60s overlay поверх passive reflect). Также M17 fixup migration:
  объединить `armor_bypass_pct` → `ignore_armor_pct` (в текущем DamageHookPatch
  оба обрабатываются как alias, см. ResolvePct).
- **4.6** TG/extension notifications — HeroKilled (player.died уже
  посылается, но TG notify pending)
- **5.0** `player.spawn` (summon в Mission) — complex, BLT 1142 строк
- **5.1** `player.equip_item` — real equipment (ItemRoster + Equipment)
- **5.2** Class re-balance + rebrand перед public (compliance)

## Stack

- **C# mod:** `.NET Framework 4.8` net472 x64, Bannerlord 1.3.15
- **References:** TaleWorlds.{Core/Library/MountAndBlade/CampaignSystem/
  Engine/Localization/ObjectSystem/DotNet}, Bannerlord.Harmony,
  Newtonsoft.Json
- **Build:** `dotnet build` (~1-2 сек), output напрямую в
  `Modules/Shedoy23.BannerlordLink/bin/Win64_Shipping_Client/`
- **Editor:** VS Code + `ms-dotnettools.csharp` extension

## Файл структура mod'a

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
    │   │   ├── BackendConfig.cs      ← config.json load/save
    │   │   ├── BackendClient.cs      ← HTTP + JWT auth
    │   │   ├── ActionPoller.cs       ← long-poll loop
    │   │   └── PowerCache.cs         ← class+power state singleton
    │   ├── Actions\
    │   │   ├── IActionHandler.cs / ActionRegistry.cs
    │   │   ├── AdoptHeroHandler.cs (hero.create)
    │   │   ├── SetClassHandler.cs (hero.set_class)
    │   │   ├── HealHeroHandler.cs / GiveGoldHandler.cs
    │   │   ├── AddSkillXpHandler.cs / ModifyAttributeHandler.cs
    │   │   ├── ActivatePowerHandler.cs (power.activate)
    │   │   ├── EchoHandler.cs (stub для unimplemented actions)
    │   │   └── HeroLookup.cs (find Hero by viewer login)
    │   ├── Behaviors\
    │   │   ├── MainCampaignBehavior.cs   ← HeroKilled / LevelledUp
    │   │   └── PowersMissionBehavior.cs  ← OnAgentBuild apply HP/scale
    │   └── Patches\
    │       └── DamageHookPatch.cs        ← Harmony Prefix Mission.RegisterBlow
    └── bin\Win64_Shipping_Client\
        └── BannerlordLink.dll  ← output после dotnet build
```

Mirror в git-репо: `BannerlordLink/` (sync через `cp` после правок).

## Лицензия BLT (важно!)

**BLT (LGPL 2.1)** — используем как **reference только**, не copy-paste.
- ✅ Идеи / архитектурные паттерны / API discovery / 5-10 строчные idioms
- ❌ Целые классы / method bodies / identical names+numbers

Наши классы и powers — clean-room re-impl с **отличающимися** numbers
(115/130/150 vs BLT's 120/135/160), переименованными powers, разным
mix. **Перед public release** — full rebrand (свои уникальные names).
См. `docs/BANNERLORD_MVP.md` §8.

## Build + test cycle

```cmd
# Build
cd "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src"
dotnet build

# Restart Bannerlord (нет hot-reload)
# Mod log:
type "C:\Users\Edward\Documents\Mount and Blade II Bannerlord\Configs\ModLogs\bannerlordlink_*.txt"

# Mirror в репо
cd C:\Users\Edward\Desktop\work\.claude\worktrees\<...>
cp X:\SteamLibrary\...\Shedoy23.BannerlordLink\src\*.cs BannerlordLink\src\
# Sync sub-folders Actions/, Behaviors/, Net/ соответственно

# Backend deploy
tar -cz backend/X | ssh root@31.130.132.224 'cd /root/twitch-extension && tar -xz && supervisorctl restart twitchbot'
```

## Backend endpoints (Bannerlord-specific)

| Endpoint | Что |
|---|---|
| `GET /api/bannerlord/ping` | Public health check |
| `GET /api/bannerlord/status` | Online/offline (last event < 60s) |
| `GET /api/bannerlord/my-hero` | Hero + skills + attributes + equipment |
| `GET /api/bannerlord/classes` | Catalog + viewer's current class |
| `GET /api/bannerlord/class-state` | All channel heroes + powers (для mod) |
| `GET /api/bannerlord/shop` | module_catalogs catalog (пока пусто) |
| `POST /api/bannerlord/action` | Atomic charge + enqueue в `module_actions` |
| `POST /api/admin/module/issue-token` | Issue module-token для mod auth |

## Schema (M14-M16)

```
bannerlord_heroes        (channel_id, username) PK
                          hero_id, display_name, culture, is_alive,
                          is_prisoner, gold, location, last_sync
bannerlord_skills        (channel_id, username, skill_key) PK
                          level, xp
bannerlord_attributes    (channel_id, username, attribute) PK, value
bannerlord_equipment     (channel_id, username, slot) PK, item_id, item_name
bannerlord_events_log    id PK, channel_id, event_type, username, payload
bannerlord_classes       class_key PK, formation, slot1-4, use_horse/camel
bannerlord_hero_class    (channel_id, username) PK, class_key, class_level
bannerlord_class_powers  (class_key, power_key) PK, lvl1/2/3 values
```

## Тестирование

См. `CONTEXT.md` §«Тестирование» — те же flows работают:
- `/dev` login + extension preview
- `curl /api/admin/dev/jwt` для preview tokens
- `TESTING_BYPASS_STREAM_LIVE=true` для actions без go-live

Module test данные:
- Channel: 98319857 (shedoy23)
- Module token (issued, 1 год TTL) — в config.json мода

## Open вопросы / next steps

1. **Sprint 4.4 damage hooks** — Harmony patch research
2. **Sprint 4.5** — ещё 2-3 active powers (rage / shield_break / retribution)
3. **Sprint 5.0 summon** — Hero как агент в текущей mission (BLT 1142 строк reference)
4. **Compliance rebrand** перед Twitch submission — свои class names + power values

## Repo

- **GitHub:** `Shedoy23/shedstream` (private)
- **Files:** `BannerlordLink/` (mirror mod) + `Расширение/backend/{routes/bannerlord.py, migrations/m14-m16_*.py, modules/bannerlord/}` + `Расширение/docs/BANNERLORD_*.md`

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT_BANNERLORD.md, продолжаем Bannerlord-модуль»*.
