# Bannerlord Module — Context (chat handoff)

**Назначение:** для чата по Bannerlord-модулю. Для общей extension
работы — см. `CONTEXT.md`. Для RimWorld — `CONTEXT_RIMWORLD.md`.

**Last updated:** 2026-05-20 (sprints 5.4–5.18 закрыты, clan/kingdom/party live)

---

## TL;DR

Второй gaming-модуль платформы. Зрители adopt'ят NPC героя в Bannerlord
(имя hero = `[BLink] {viewer_login}`), выбирают **культуру** + **класс**
(13 классов) с подходящим snar'ем и passive/active powers, тратят валюту
из стрима на:

- **Боевое:** призыв в бой (за/против стримера), 4 active powers, kill
  rewards, victory participation bonus
- **Экономику:** конвертация крустиков в Hero.Gold или skill XP
- **Прогрессию:** gear upgrade (6 tier), focus в skills, attribute points
- **Социальное:** clan create/join/leave, kingdom create/join/leave,
  MobileParty creation
- **Свита:** basic + elite retinue (BLT pattern, 5 slots, 3× cost для elite)
- **Турниры:** queue + 16-man bracket + bets

**Архитектура:** C# Bannerlord-submodule (`BannerlordLink/`,
prod-mirror в `Modules/Shedoy23.BannerlordLink/`) ↔ FastAPI backend
(`Расширение/backend/`) через Module API generic dispatcher
(`routes/module_api.py`) + Bannerlord-specific endpoints
(`routes/bannerlord.py`).

---

## Экономика — две валюты

| Валюта | Где живёт | Что покупает |
|---|---|---|
| **Крустики ⦷** | Backend `viewers.points` | Призыв (100/200⦷), powers, retinue recruit (100/300⦷), XP/gold конверсия, бесплатные actions (clan/kingdom/party — 0⦷) |
| **Hero.Gold 💰** | In-game | Gear tier (50K–1.5M), random equip (25K–80K), focus (30K–75K), attributes (50K), retinue troops (5K–80K basic / ×3 elite), clan (1M), kingdom (5M), party (200K), tournament entry (5K), join clan/kingdom (50K/100K) |

**Source of truth:**
- Крустики: backend `viewers.points`, atomic charge внутри `/action` TX
- Hero.Gold: мод (`hero.Gold` через `GiveGoldAction.ApplyBetweenCharacters`)
- gear_tier / clan / kingdom: mod пушит `hero.*_changed` event → backend
  cache. Mod source-of-truth.

---

## Sprints статус — 28 закрыто (5.0 → 5.18)

### Migrations applied (prod)
- **M14** — bannerlord_heroes / _skills / _attributes / _equipment / _events_log
- **M15** — bannerlord_classes (13 seeded) + bannerlord_hero_class
- **M16** — bannerlord_class_powers (33 power rows)
- **M17** — eventsub_dedupe (main)
- **M18** — active power seeds (heal_burst / shield_break / rage / retribution)
- **M19** — heroes.level / clan_name / kingdom_name columns
- **M20** — heroes.gear_tier column
- **M21** — equipment.tier / item_value / weight / stats_json
- **M22** — bannerlord_channel_state (save-switch detection)
- **M23** — bannerlord_retinue (5 slots)
- **M24** — bannerlord_tournament_queue + _state
- **M25** — bannerlord_tournament_bets
- **M26** — bannerlord_skills.focus column
- **M27** — heroes.clan_info_json + kingdom_info_json
- **M28** — retinue.is_elite column

### Action handlers (21 real + 4 echo stubs)
- `hero.create` — adopt wanderer + culture filter + `[BLink]` prefix +
  StripEquipment (anti T5-T6 wanderer template) + SetHasMet (no fog-of-war)
- `hero.set_class` — apply class equipment + gear_tier aware
  (FindTieredItem BLT pattern)
- `hero.upgrade_gear` — 6-tier replace (Hero.Gold cost)
- `hero.add_skill` — random skill XP boost
- `hero.add_focus` — tier-based focus point per skill (Hero.Gold 30K-75K)
- `hero.add_attribute` — flat 50K Hero.Gold per attribute point
- `hero.recruit_troops` — basic OR elite retinue (is_elite flag, 3× cost)
- `hero.create_clan` — `Clan.CreateClan` + culture + banner + 50 renown (1M💰)
- `hero.create_kingdom` — `KingdomManager.CreateKingdom` + 2K влияния + 2M wallet (5M💰)
- `hero.create_party` — `MobilePartyHelper.SpawnLordParty` + retinue + starting loot (200K💰)
- `hero.leave_clan` — hero.Clan = null + place в random town (free)
- `hero.leave_kingdom` — `ChangeKingdomAction.ApplyByLeaveKingdom` (free)
- `hero.join_clan` — fuzzy match Clan.All → set hero.Clan (50K💰)
- `hero.join_kingdom` — `ChangeKingdomAction.ApplyByJoinToKingdom` (100K💰)
- `hero.join_tournament` — добавление в очередь (5K💰)
- `player.spawn` — summon (ally/enemy), force-heal + party.AddMember +
  SetPlayerFormationPreference + retinue re-spawn если hero auto-entered
- `player.heal` — restore HP в Mission
- `player.give_item` — Hero.Gold +5K/25K/100K
- `player.equip_item` — random T4+ weapon/armor/horse (Hero.Gold)
- `player.modify_attribute` — single point boost
- `power.activate` — 4 active powers
- `tournament.bet` — backend-only (charge крустиков)
- Stubs: `player.respawn` / `hero.set_culture` / `hero.set_faction` /
  `world.broadcast_message` / `world.trigger_event`

### Campaign + Mission behaviors

- **MainCampaignBehavior:**
  - HeroKilledEvent → player.died
  - HeroLevelledUp → HeroStateSync.Push (full state с focus/attributes/clan/kingdom info)
  - OnSessionLaunched + OnGameLoadFinished — push session_start + heroes_snapshot
  - MigrateLegacyHeroNames (add [BLink] prefix retroactively)
  - CleanupOpaqueHeroes (strip [BLink] от opaque-ID heroes — JWT bug legacy)
  - IntroduceAdoptedHeroes (retroactive SetHasMet для existing adopted)

- **PowersMissionBehavior:**
  - OnAgentBuild → apply passive HP/scale
  - OnMissionTick → ActiveBuffState.RemoveExpired (slow-tick)
  - OnEndMission → ActiveBuffState.Clear

- **KillRewardBehavior** (MissionLogic):
  - OnAgentBuild — track participants in `_participants` dict (по [BLink] prefix)
  - OnAgentRemoved — +50💰/+25XP per trooper kill, ×0.25 на mount, **×10 на Hero kill** (500/200)
  - Retinue kills credit owner'у ×0.5 (через static `_retinueOwners` registry,
    populated SummonHeroHandler'ом)
  - Static `_partyRestores` registry — restore hero в original party на OnEndMission
    (BLT pattern, party.AddMember для proper spawn integration)
  - OnEndMission → +200💰/+100XP всем alive participants если PlayerVictory
  - OnMissionTick → push `battle.stats_snapshot` каждые 1.5s (overlay)

- **TournamentQueueBehavior** + **TournamentMissionBehavior** — Sprint 5.3,
  16-man bracket с Harmony patches на FightTournamentGame.GetParticipantCharacters
  + TournamentBehavior.EndCurrentMatch

### Harmony patches
- `DamageHookPatch` — Mission.RegisterBlow Prefix (passive ignore_armor + damage_reflect)
- `IsSideDepletedPatch` — reinforcement keep-alive пока adopted hero alive
- `TournamentParticipantsPatch` — viewer tournament roster injection

### Helpers
- `HeroNaming.cs` — [BLink] prefix conventions
- `HeroLookup.cs` — find hero by username (StringComparison.OrdinalIgnoreCase)
- `PowerCache.cs` — class+power dict singleton (DB-synced)
- `ActiveBuffState.cs` — timed buffs ConcurrentDictionary
- `HeroStateSync.cs` — full state push (gold/level/clan/kingdom/skills/attributes/clan_info/kingdom_info)
- `EquipmentSync.cs` — push 11 slots equipment snapshot

### Backend
- `routes/bannerlord.py` — 11 endpoints, `_fetch_hero_gold` helper для price checks
- `modules/bannerlord/_adapter.py` — 22 event handler types,
  in-memory state (`_last_seen`, `_active_buffs`, `_cooldowns`, `_battle_stats`)
- Server-side price maps:
  - `RANDOM_EQUIP_HERO_GOLD`: weapon=50K / armor=25K / horse=80K
  - `SPAWN_PRICES`: player=100⦷ / enemy=200⦷
  - `HERO_GOLD_TIER_COSTS`: 50K→1.5M
  - `GIVE_GOLD_PRESETS`: 1K⦷→5K💰 / 5K⦷→25K💰 / 20K⦷→100K💰 (1:5)
  - `ADD_SKILL_XP_PRESETS`: 500⦷→50XP / 1K⦷→100XP / 5K⦷→500XP
  - `RECRUIT_TIER_COSTS`: 5K/10K/20K/30K/50K/80K (× 3 для elite)
  - `FOCUS_TIER_COSTS`: 30K/40K/50K/60K/75K
  - `ATTRIBUTE_COST`: 50K
  - `CLAN_CREATE_COST`: 1M / `KINGDOM_CREATE_COST`: 5M
  - `CLAN_JOIN_COST`: 50K / `KINGDOM_JOIN_COST`: 100K
  - `PARTY_CREATE_COST`: 200K
  - `TOURNAMENT_ENTRY_FEE_GOLD`: 5K

### Frontend (`viewer.js` ~3500 строк после cleanup)

**Hero card layout:**
- Header: name + alive/prisoner badge + culture + location
- Stats grid: 💰 Динары / ⭐ Уровень / 🛡 Снаряжение (T1-T6 ★) с inline ⚒ upgrade button /
  🏰 Клан ⚙ (clickable) / 👑 Королевство ⚙ (clickable) / 🛡 Броня summary
- Battle banner (когда in_battle) — HP bar + state + kills + gold_earned + xp_earned
- Buff HUD (active power timers с countdown)
- Class picker (dropdown, 13 классов)
- Active power buttons (heal_burst / shield_break / rage / retribution — disabled при cooldown / active)
- Summon buttons (📯 Призвать за / ⚔️ Против — 100/200⦷)
- **🎯 Прогрессия** button → modal с **grouped layout** (attribute → 3 child skills с per-row + buttons)
- Equipment details (collapsible, persisted state)
- Свита details (collapsible) — **2 кнопки**: ➕ basic / ★ elite

**Shop card:** теперь только 2 блока (после cleanup):
1. 🎁 Случайный товар (weapon=50K💰 / armor=25K💰 / horse=80K💰)
2. 💰 Динары + 📚 Опыт конверсии (3 пресета каждая)

**Modals:**
- Progression — attribute groups + skills + per-row "+" buttons
- Clan management — info block (leader/tier/renown/fiefs/parties/kingdom)
  + actions (create/join/leave/create-party)
- Kingdom management — info block + actions (create/join/leave)
- Create clan / create kingdom — input для имени + confirm
- Join clan / join kingdom — fuzzy-match dialog
- Tournament join + bet modal

**Polling:**
- `/api/bannerlord/status` — 8s (online badge)
- `/api/bannerlord/my-hero` — 8s (full state)
- `/api/bannerlord/shop` — 8s
- `/api/bannerlord/classes` — 8s
- `/api/bannerlord/my-buffs` — 2.5s (HUD)
- `/api/bannerlord/tournament` — 3s
- `/api/bannerlord/battle-status` — 2s

**Overlay (overlay.html):**
- BLT-style cards bottom-row: HP-bar background + side color (blue/red) +
  state glow (active/routed/unconscious/killed) + compact numbers + sort by side+kills
- Polls `/api/overlay/bannerlord/summoned` каждые 1s

### Mobile (`mobile.html`)
Parity с `extension.html` — hero card / shop / tournament card. Логика единая в viewer.js.

---

## Open / pending

**🔴 Production blockers:**
- **Sprint 5.2 — Compliance rebrand** перед public Twitch release
  (audit class_keys / power_keys / numeric values vs BLT LGPL,
  NOTICE.md, Extension submission)
- **Test 19 extend** — `test_multi_tenant_isolation.py` assertions
  для новых fields (gear_tier / level / clan_name / clan_info_json /
  focus / attributes / retinue.is_elite)

**🟠 Features в очереди:**
- **Auto-summon 30 мин подписка** — viewer покупает window auto-spawn'a в каждый battle (~3 часа работы, обсуждено в Sprint 5.16)
- **Transfer clan leadership** — для leaders которые хотят покинуть клан
- **Party order commands** (BLT-level): siege/defend/patrol/raid/garrison
- **Party disband / stats inline**

**🟡 Tech debt / polish:**
- **Sprint 4.10 Balancing** — после live data: cooldowns + active power values + tier costs
- **Adapter cache invalidate** — re-sync state при смене clan/kingdom in-game
- 20 handlers share username-extract pattern → `ActionHandlerBase`
- `KillRewardBehavior` accumulates 2 unrelated static registries
  (`_retinueOwners`, `_partyRestores`) — split на `MissionStateBehavior`?
- `bannerlord_buy_action` — 750-строчная мега-функция, можно dispatch table

**🔵 Wild ideas:**
- AI Advisors (rule-based MVP — Trade Advisor)
- Hero relations system (приятели/соперники между adopted heroes)
- Custom prize items в турнирах

---

## Stack
- **C# mod:** .NET Framework 4.8 net472 x64, Bannerlord 1.3.15
- **References:** TaleWorlds.{Core / Library / MountAndBlade / CampaignSystem /
  CampaignSystem.AgentOrigins / CampaignSystem.Party / CampaignSystem.Actions /
  Engine / Localization / ObjectSystem / DotNet}, Bannerlord.Harmony,
  Newtonsoft.Json, **SandBox** (для TournamentBehavior)
- **Build:** `dotnet build` (~1-2 сек), output в
  `Modules/Shedoy23.BannerlordLink/bin/Win64_Shipping_Client/`

## File structure (mod)

```
X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\
└── Modules\Shedoy23.BannerlordLink\
    ├── SubModule.xml          ← module declaration
    ├── config.json            ← module_token + channel_id (gitignored)
    ├── src\
    │   ├── BannerlordLink.csproj
    │   ├── BannerlordLinkModule.cs   ← MBSubModuleBase entry
    │   ├── MainThreadDispatcher.cs
    │   ├── Net\
    │   │   ├── BackendConfig.cs / BackendClient.cs / ActionPoller.cs
    │   │   ├── PowerCache.cs / ActiveBuffState.cs
    │   ├── Actions\ (21 real handlers + EchoHandler + Registry)
    │   ├── Behaviors\
    │   │   ├── MainCampaignBehavior.cs
    │   │   ├── PowersMissionBehavior.cs
    │   │   ├── KillRewardBehavior.cs
    │   │   ├── TournamentQueueBehavior.cs
    │   │   └── TournamentMissionBehavior.cs
    │   ├── Patches\
    │   │   ├── DamageHookPatch.cs
    │   │   ├── IsSideDepletedPatch.cs
    │   │   └── TournamentParticipantsPatch.cs
    │   └── Util\
    │       ├── HeroNaming.cs / HeroStateSync.cs / EquipmentSync.cs
```

Git mirror: `BannerlordLink/` (sync через `cp` после правок). Verified
0-drift с X:\ source via md5 hash comparison (Sprint 5.18 audit).

---

## Build + deploy cycle

```cmd
# C# build (mirror в production folder)
cd "X:\SteamLibrary\steamapps\common\Mount & Blade II Bannerlord\Modules\Shedoy23.BannerlordLink\src"
dotnet build

# Restart Bannerlord (нет hot-reload).
type "C:\Users\Edward\Documents\Mount and Blade II Bannerlord\Configs\ModLogs\bannerlordlink_*.txt"

# Sync обратно в git-репо
cd C:\Users\Edward\Desktop\work\.claude\worktrees\<...>
cp "X:\SteamLibrary\...\Shedoy23.BannerlordLink\src\<file>.cs" BannerlordLink\src\<...>\

# Backend + frontend deploy на прод
cd Расширение
tar -cz backend frontend | ssh root@31.130.132.224 \
  'cd /root/twitch-extension && tar -xz && supervisorctl restart twitchbot'
```

## Лицензия BLT (важно!)

**BLT (LGPL 2.1)** — используем как **reference только**, не copy-paste.
- ✅ Идеи / архитектурные паттерны / API discovery / 5-10 строчные idioms
- ❌ Целые классы / method bodies / identical names+numbers

Наш `BannerlordLink/` — clean-room re-impl. Numeric values отличаются от BLT
(например retinue costs, attribute cost, kingdom prestige bonus). Имена
наших классов независимы (Tank/Archer/Psycho/Berserk/Knight). **Перед public
release** (Sprint 5.2) — полный audit для финального compliance.

## Тестирование

См. `CONTEXT.md` §«Тестирование» — те же flows работают:
- `/dev` login + extension preview
- `curl /api/admin/dev/jwt` для preview tokens
- `TESTING_BYPASS_STREAM_LIVE=true` для actions без go-live

**Module test данные:**
- Channel: 98319857 (shedoy23)
- Module token в `Modules/Shedoy23.BannerlordLink/config.json` (gitignored)

## Repo

- **GitHub:** `Shedoy23/shedstream` (private)
- **Files:** `BannerlordLink/` (mirror mod), `Расширение/backend/`
  ({routes/bannerlord.py, migrations/m14-m28, modules/bannerlord/}),
  `Расширение/frontend/{viewer.js,extension.html,mobile.html,overlay.html}`,
  `Расширение/docs/BANNERLORD_*.md`

---

**Использование для нового чата:** скинуть этот файл + сказать
*«Читай CONTEXT_BANNERLORD.md, продолжаем Bannerlord-модуль»*.
