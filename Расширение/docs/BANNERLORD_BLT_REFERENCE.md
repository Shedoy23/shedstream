# BLT Reference — Lait96/Bannerlord-Twitch-lait

**Authoritative source-of-truth для Bannerlord modding patterns.**

```
https://github.com/Lait96/Bannerlord-Twitch-lait
```

## Правило работы (обязательное)

При реализации **любой** Bannerlord-related фичи в нашем моде
(`Modules/Shedoy23.BannerlordLink/`) — **сначала проверять как
это сделано в Lait BLT** перед написанием своего кода.

**НЕ выдумывать** engine API, **не копировать построчно**, а:

1. **Read** — открыть аналогичный файл/behavior в Lait BLT
2. **Understand** — понять подход, какие engine API он использует,
   какие edge-cases обрабатывает
3. **Adapt** — переписать под нашу архитектуру (наш naming, наш
   `HeroNaming.IsAdopted([BLink])` filter, наши Action handlers и т.д.)
4. **Cite** — добавить ссылку на исходник Lait в комментарии к
   соответствующему .cs файлу

## Почему именно Lait96 fork

- **Активный** maintenance под Bannerlord 1.3.x (current)
- **billw2012/Bannerlord-Twitch** (оригинал) частично legacy, не все
  patterns updated под current engine
- **jazz-ttv/Bannerlord-Twitch** — fork с разовыми фичами, не systematic
- Lait добавил: BLTHeroWidgetBehavior (наш HeroNametag pattern),
  IndependentsOverhaul, Capital (workshop persistent income), Diplomacy
  (kingdom politics) — все эти патtterns мы уже имитировали

## Mapping: BLT файл → наш файл

| BLT (Lait) | Наш analog | Pattern source |
|------------|------------|----------------|
| `BLTAdoptAHero/Behaviors/BLTHeroWidgetBehavior.cs` | `BannerlordLink/src/Behaviors/HeroNametagMissionView.cs` | MissionView + Gauntlet layer (2026-05-28) |
| `BLTAdoptAHero/_Module/GUI/Prefabs/BLTHeroNametag.xml` | `BannerlordLink/GUI/Prefabs/BLinkHeroNametag.xml` | Gauntlet UI prefab |
| `BLTAdoptAHero/Behaviors/BLTSummonBehavior.cs` | `BannerlordLink/src/Actions/SummonHeroHandler.cs` | Player spawn logic (initial Sprint 5.0+) |
| `BLTAdoptAHero/Behaviors/BLTTournamentMissionBehavior.cs` | `BannerlordLink/src/Behaviors/TournamentMissionBehavior.cs` | Tournament queue (Sprint 5.3) |
| `BLTAdoptAHero/Behaviors/ReinforcementBehavior.cs` | (not implemented) | TODO if user requests |
| `BLTAdoptAHero/Behaviors/GoldIncomeBehavior.cs` | `BannerlordLink/src/Behaviors/WorkshopProfitSyncBehavior.cs` | Workshop / Caravan / Fief passive (Sprint 5.33) |
| `BLTAdoptAHero/Behaviors/BLTHeirBehavior.cs` | `BannerlordLink/src/Actions/ActivateHeirHandler.cs` | Heir inheritance (Sprint 5.33 HERITAGE) |
| `BLTAdoptAHero/Behaviors/KingdomTaxBehavior.cs` | `BannerlordLink/src/Behaviors/FiefTributeSyncBehavior.cs` | Fief tribute (Sprint 5.33 FIEF) |
| `BLTAdoptAHero/Behaviors/BLTHeroPowersMissionBehavior.cs` | `BannerlordLink/src/Behaviors/PowersMissionBehavior.cs` | Combat powers (Sprint 4.4-4.5) |
| `BLTAdoptAHero/Util/AgentExtensions.cs` | `BannerlordLink/src/Util/HeroNaming.cs` | Hero name resolution |
| `BLTAdoptAHero/Util/HeroExtensions.cs` | (inline в наших handlers) | Hero state helpers |

## Anti-patterns (что мы делали неправильно)

### ❌ Harmony patch engine ViewModel types

**Failed approach** (3 итерации, Sprint 5.29 - 5.33):
```csharp
[HarmonyPatch(typeof(MissionNameMarkerTargetVM))]   // ← engine VM
public static class NameMarkerPatch { ... }
```

**Проблемы:**
- Engine VM types меняются между Bannerlord versions (1.2.x → 1.3.x:
  `MissionNameMarkerTargetVM` стал generic `1, добавился `BaseVM` split)
- `AccessTools.TypeByName` lookup ненадёжен из-за lazy assembly load
- Force-load Assembly.LoadFrom не помогает если CLR кэширует Type identity
- Каскадные failures: один failed Harmony patch ломает дальнейшие в PatchAll

**Правильный подход (BLT-Lait):**
```csharp
[DefaultView]
public class HeroNametagMissionView : MissionView {
    OnMissionScreenTick(dt) {
        // Свой Gauntlet layer, своя VM, своё rendering.
        // НЕ зависит от engine internal VM types.
    }
}
```

### ❌ Hardcoded engine StringIds в frontend dropdown

**Failed** (Sprint 5.33 SHOP): `silversmith` vs engine's `silversmithy`,
`wood_workshop` vs `wood_WorkshopType` (TaleWorlds typo).

**Правильно:** mod пушит engine catalog (Sprint 5.33 CATALOG-1),
frontend dropdown sourced from live engine state.

### ❌ Inline counter-blow в Harmony Prefix

**Failed** (Sprint 5.29 - 5.32): `attacker.RegisterBlow(counter, sharedCD)`
inline → corrupted shared AttackCollisionData ref → native crash ~3000 blows.

**Правильно (Sprint 5.32 fix):** queue `_pendingReflects`, drain в
`KillRewardBehavior.OnMissionTick` (fresh frame, fresh CD).

## Quick links для разработки

- Repo root: https://github.com/Lait96/Bannerlord-Twitch-lait
- Main behaviors: https://github.com/Lait96/Bannerlord-Twitch-lait/tree/main/BannerlordTwitch/BLTAdoptAHero/Behaviors
- Prefabs (Gauntlet XML): https://github.com/Lait96/Bannerlord-Twitch-lait/tree/main/BannerlordTwitch/BLTAdoptAHero/_Module/GUI/Prefabs
- Util helpers: https://github.com/Lait96/Bannerlord-Twitch-lait/tree/main/BannerlordTwitch/BLTAdoptAHero/Util

## Raw file URLs для fetch (быстрый доступ из агента)

Pattern: `https://raw.githubusercontent.com/Lait96/Bannerlord-Twitch-lait/main/{path}`

Example:
```
https://raw.githubusercontent.com/Lait96/Bannerlord-Twitch-lait/main/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTHeroWidgetBehavior.cs
```

## Workflow для новых фич

```
[user request: "добавь фичу X"]
       ↓
1. Reach for Lait BLT first:
   git/web fetch BLTAdoptAHero/Behaviors/*.cs grep "X-keyword"
       ↓
2. Read full implementation
       ↓
3. Identify:
   - Какие engine API использует
   - Какие edge-cases обрабатывает
   - Как persistence сделана (SyncData? in-memory?)
   - Threading model
       ↓
4. Adapt под нашу архитектуру:
   - HeroNaming.IsAdopted([BLink]) вместо BLT's IsAdopted
   - Наш ActionRegistry / IActionHandler pattern
   - Наш logging (BannerlordLinkModule.Log)
   - Наш backend event push (BannerlordLinkModule.Backend.PostEventAsync)
       ↓
5. Cite в commit message + .cs comment:
   «Pattern из Lait BLT BLTHeroWidgetBehavior.cs»
       ↓
6. Build + deploy + test
```
