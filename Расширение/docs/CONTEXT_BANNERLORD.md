# Bannerlord Module — Context (chat handoff)

**Назначение:** для чата по Bannerlord-модулю. Для общей extension
работы — см. `CONTEXT.md`. Для RimWorld — `CONTEXT_RIMWORLD.md`.

**Last updated:** 2026-05-16 (Sprint 5.1c closed — random equip коробочки)

## TL;DR

Второй gaming-модуль платформы. Зрители adopt'ят NPC героя, выбирают
**класс** (Tank/Archer/Cavalry/...) с подходящим snar'ем и passive
powers (HP×, skill boost, body scale), могут активировать active power
(heal_burst). Adoption / class change / actions — через extension UI
+ action queue.

## Текущий статус — Sprint 5.1c closed

### ✅ Закрыто (17 sprints)

**Backend infrastructure:**
- M14 migration: `bannerlord_heroes` / `_skills` / `_attributes` /
  `_equipment` / `_events_log` (TENANT-scoped)
- M15 migration: `bannerlord_classes` (13 seeded) + `bannerlord_hero_class`
- M16 migration: `bannerlord_class_powers` (33 power rows)
- **M17 migration** (Sprint 4.5): armor_bypass_pct→ignore_armor_pct fixup
  + 4 active powers seeded (tank/shield_break_burst, psycho/berserk/rage,
  knight/retribution_toggle)
- routes/bannerlord.py: 8 endpoints (my-hero, shop, action (4.8 cooldown enforcement),
  ping, status, class-state, classes (+ current_powers Sprint 4.7),
  my-buffs (4.6, +cooldowns Sprint 4.8))
- modules/bannerlord/_adapter.py: 14 event types обработаны (+ buff.activated /
  buff.expired Sprint 4.6, кэш in-memory `_active_buffs` per (channel_id, username)).
  Sprint 4.8: `_cooldowns` dict + POWER_COOLDOWNS map (heal 30s / shield_break 90s /
  rage 60s / retribution 90s) + check_cooldown / set_cooldown helpers.
- Test 19 — 15 isolation assertions

**C# mod** (`BannerlordLink/`, `Modules/Shedoy23.BannerlordLink/` на проде):
- SDK-style csproj, `.NET Framework 4.8` net472, x64
- BackendClient + Config + ActionPoller + MainThreadDispatcher
- 7 real action handlers (+ Sprint 4.5 расширил `power.activate`):
  - `hero.create` (adoption — fresh NPC + SetName)
  - `hero.set_class` (apply equipment + skill boosts + powers cache)
  - `player.heal` (max HP)
  - `player.give_item` (gold)
  - `hero.add_skill` (XP boost)
  - `player.modify_attribute` (attribute points)
  - `player.spawn` (5.0 + 5.1a) — summon viewer hero в текущую Mission через
    `Mission.Current.SpawnTroop(new PartyAgentOrigin(MainParty, character),
    isPlayerSide:true, isReinforcement:true, ...)`. Гард: Mission alive +
    `CurrentState==Continuing` + Mode == "Battle" (reflection-safe через
    `.ToString()`) + hero не уже spawned. spawnWithHorse — по class_key
    (cavalry/horse_archer/knight = mounted). HeroLookup + AgentVisuals.FadeIn
    для smooth entry. Reinforcement waves поддержаны через Harmony postfix
    на `MissionAgentSpawnLogic.IsSideDepleted` (Patches/IsSideDepletedPatch.cs):
    если на side есть adopted hero (PowerCache contains username) — side
    не depleted, vanilla spawn logic продолжит реinforcement.
  - `player.equip_item` (5.1b + 5.1c) — два режима:
    • **Targeted** (5.1b): `data.item_id` → `MBObjectManager.GetObject<ItemObject>`
      → resolve slot (`data.slot` или auto-infer по ItemType) → apply.
    • **Random** (5.1c): `data.random_category` (weapon/armor/horse) →
      `MBObjectManager.GetObjectTypeList<ItemObject>()` filter by ItemType +
      Tier ≥ 4 (high-tier) + `!NotMerchandise` → `MBRandom.RandomInt` pick.
    Slot resolve по ItemType. `hero.BattleEquipment[idx] = new EquipmentElement(item)`.
    Fire-and-forget `hero.equipment_changed` event на backend.
  - `power.activate` — 4 power_keys:
    - `heal_burst` (4.3) — +50 HP instant
    - `shield_break_burst` (4.5+4.6+4.9) — AoE: ChangeWeaponHitPoints(shield,0)
      + particle `psys_game_shield_break` через `Mission.Scene.CreateBurstParticle`
      + sound `event:/mission/combat/shield/broken` через `Mission.MakeSound`
      (TaleWorlds.MountAndBlade SoundEvent API)
    - `rage` (4.5) — timed 30s outgoing damage multi (1.3-1.8× per level)
    - `retribution_toggle` (4.5) — timed 60s extra reflect % overlay
- **Buff event push** (Sprint 4.6): ActiveBuffState.Activate / RemoveExpired
  пушат `buff.activated` / `buff.expired` события на backend через
  PostEventAsync (fire-and-forget, не ждут ACK). Backend хранит in-memory
  для frontend HUD.
- MainCampaignBehavior (HeroKilled, HeroLevelledUp → events)
- PowersMissionBehavior (HP multi + body_scale via reflection +
  Sprint 4.5 slow-tick cleanup expired buffs через `ActiveBuffState.RemoveExpired`,
  OnEndMission → Clear)
- **Patches/DamageHookPatch.cs** — Sprint 4.4-4.5 Harmony Prefix на
  `Mission.RegisterBlow`:
   • passive `ignore_armor_pct` / `armor_bypass_pct` (alias, attacker outgoing —
     сдвигает damage из AbsorbedByArmor в InflictedDamage),
   • passive `damage_reflect_pct` (victim incoming — counter-blow с recursion
     guard через ThreadLocal),
   • active `rage` (outgoing multi ×1.5 после ignore_armor, capped 5x),
   • active `retribution_toggle` (incoming reflect overlay, sum с passive
     capped 95%).
  Username резолвится через CharacterObject.HeroObject.Name.
- **Net/ActiveBuffState.cs** (Sprint 4.5) — ConcurrentDictionary singleton
  `username → powerKey → BuffEntry{powerKey, ExpiresAt, Value}`. Expiry source:
  `Mission.Current.CurrentTime` (паузо-чувствительный — buff не утечёт во время
  Esc-меню). API: Activate / GetValue / RemoveExpired / Clear.

**Frontend** (`extension.html` Bannerlord tab):
- Hero card (avatar, culture, gold, skills, equipment)
- Class picker (13 buttons, current highlighted)
- Online badge (🟢/🔴 polling /api/bannerlord/status)
- «⚔️ Стать героем» в empty state
- **Active power buttons** (Sprint 4.7+4.8, viewer.js): heal_burst (100💎),
  shield_break_burst (200💎, только tank), rage (300💎), retribution_toggle
  (300💎). Hardcoded prices. Disabled пока buff активен ИЛИ cooldown идёт
  (показывается "Xс" вместо цены, decrement client-side между poll'ами).
- **Summon button** (Sprint 5.0, viewer.js): «📯 Призвать в бой» (500💎,
  cooldown 120с — `player.spawn` key в POWER_COOLDOWNS). Wide button под
  active powers, disabled на cooldown.
- **Random equip buttons** (Sprint 5.1c, viewer.js): «🗡 Купить оружие 1М⦷» /
  «🛡 Купить броню 500К⦷» / «🐎 Купить коня 1.25М⦷». Horse-button disabled
  для non-mounted classes. Цены отображаются на UI, **server-side
  override'ит** `data.price` из `RANDOM_EQUIP_PRICES` map в
  routes/bannerlord.py — viewer не может послать price:0.
- **Buff HUD** (Sprint 4.6, viewer.js): chip-list над class picker'ом
  с current remaining time. Polling /api/bannerlord/my-buffs каждые 2.5с +
  client-side decrement 1с для smooth countdown.

### ⏳ Pending sprints

- **4.10** Active power balancing — собрать stream-feedback на rage 1.3-1.8×,
  retribution 20-50%, cooldowns 30/60/90с после live test. Скорее всего
  cooldown в админку (per-streamer rebalance) — 4.11.
- **5.2** Class re-balance + compliance rebrand (наши class names + values
  vs BLT — должны полностью отличаться перед public release).
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
    │   │   ├── PowerCache.cs         ← class+power state singleton (DB-synced)
    │   │   └── ActiveBuffState.cs    ← timed active buffs runtime (Sprint 4.5)
    │   ├── Actions\
    │   │   ├── IActionHandler.cs / ActionRegistry.cs
    │   │   ├── AdoptHeroHandler.cs (hero.create)
    │   │   ├── SetClassHandler.cs (hero.set_class)
    │   │   ├── HealHeroHandler.cs / GiveGoldHandler.cs
    │   │   ├── AddSkillXpHandler.cs / ModifyAttributeHandler.cs
    │   │   ├── ActivatePowerHandler.cs (power.activate)
    │   │   ├── SummonHeroHandler.cs (player.spawn — 5.0 + 5.1a improvements)
    │   │   ├── EquipItemHandler.cs (player.equip_item — 5.1b MVP)
    │   │   ├── EchoHandler.cs (stub для unimplemented actions)
    │   │   └── HeroLookup.cs (find Hero by viewer login)
    │   ├── Behaviors\
    │   │   ├── MainCampaignBehavior.cs   ← HeroKilled / LevelledUp
    │   │   └── PowersMissionBehavior.cs  ← OnAgentBuild apply HP/scale
    │   └── Patches\
    │       ├── DamageHookPatch.cs        ← Harmony Prefix Mission.RegisterBlow
    │       └── IsSideDepletedPatch.cs    ← Harmony Postfix для reinforcement (5.1a)
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
