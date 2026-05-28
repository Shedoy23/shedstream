# BLT-Parity Audit: Hero Creation + Spawn in Mission

**Date:** 2026-05-28
**Reference:** [Lait96/Bannerlord-Twitch-lait](https://github.com/Lait96/Bannerlord-Twitch-lait) (per `BANNERLORD_BLT_REFERENCE.md`)

**Files compared:**

| Aspect | BLT-Lait | Наш analog |
|--------|----------|------------|
| Adopt | `BLTAdoptAHero/Actions/AdoptAHero.cs` | `BannerlordLink/src/Actions/AdoptHeroHandler.cs` |
| InitName | `BLTAdoptAHeroCampaignBehavior.InitAdoptedHero` | `HeroNaming.Format()` + `SetName` |
| Spawn | `BLTAdoptAHero/Behaviors/BLTSummonBehavior.cs` | `BannerlordLink/src/Actions/SummonHeroHandler.cs` |

---

## ① Hero Creation

### Flow comparison (step-by-step)

| Step | BLT-Lait | Наш AdoptHeroHandler | Verdict |
|------|----------|---------------------|---------|
| **1. Pool selection** | Filter by culture/type/faction/name/clan from existing heroes OR spawn new wanderer | Random wanderer from `MBObjectManager.GetObjectTypeList<CharacterObject>().Where(Occupation.Wanderer)`, optional culture filter | **≈** Similar; BLT has more filters но мы достаточны |
| **2. Duplicate guard** | Via `HeroData.Owner` lookup | `HeroLookup.FindByUsername` + `existing.IsAlive` check | ✅ Equivalent |
| **3. Create hero** | `HeroCreator.CreateSpecialHero(template)` | Same | ✅ |
| **4. Set state Active** | Implicit | Explicit `ChangeState(Active)` | ✅ |
| **5. Town placement** | Random town settlement (`Settlement.All.GetRandomElementWithPredicate`) | `WandererHome.PlaceInNearestTavern` (deterministic by nearest) | ⚠ Different — нет critical impact |
| **6. Age override** | ✅ `newHero.SetBirthDay(YearsFromNow(-AgeRange.Random()))` ensures **adult** age (>= HeroComesOfAge) | ❌ **MISSING** | 🔴 **GAP** |
| **7. ClearHero (skills/attrs to 0)** | ✅ + sets each skill в configured range randomly | ✅ + seeds `OneHanded=1` (BLT discovery: prevents save-load death) | ✅ |
| **8. InitializeDeveloper** | (implicit) | ✅ explicit | ✅ |
| **9. Strip equipment** | ❌ Keeps starting + has separate UpgradeEquipment(tier) action | ✅ Strips all 11 slots; viewer gets gear via `hero.set_class` | ⚠ Different design — наш forces explicit class pick (intended) |
| **10. Set class** | ✅ Via `SetClass()` immediately в adopt flow если class в config | ⚠ Separate action `hero.set_class` после adopt | ⚠ Two-step vs one-step UX |
| **11. Starting gold** | ✅ Configurable starting gold + inheritance from previous adoptions | ⚠ Not set explicitly (engine default) | 🟡 minor |
| **12. Name set** | `"{userName} [BLT]"` суффикс (or `[DEV]`) | `"[BLink] {username}"` префикс | ⚠ Cosmetic difference. **CONSISTENT** в обоих codebases |
| **13. Identity persistence** | `HeroData.Owner = userName` + `LegacyName` + `Iteration` counter for re-adopts | `HeroIdentityBehavior` dict + SyncData | ✅ Equivalent |
| **14. `IsRetiredOrDead` flag** | ✅ Tracks retirement separately from death (`/retire` command) | ❌ Missing — у нас только death | 🟡 minor (нет /retire feature) |
| **15. `Iteration` counter** | ✅ Increments на re-adopt после death | ❌ Missing | 🟡 для inheritance log полезно |
| **16. SetHasMet (unfog)** | ❌ Not present | ✅ Added Sprint 5.16 | 🟢 Our improvement |
| **17. Push event back** | (lobby/UI updates локально) | ✅ `player.linked` POST → backend upsert | 🟢 Our improvement (needed для multi-tenant) |

### Gaps identified

🔴 **CRITICAL (likely cause bugs):**
- **Age override missing**. Wanderer templates могут быть child (< 18) или elderly. Engine refuses many actions для children (clan ops, marriage, summon в Mission в некоторых modes). Возможный root-cause некоторых REFUSE'ов мы видели.

🟡 **MINOR (UX / feature parity):**
- No `Iteration` counter для re-adoption tracking (Heritage log полезно)
- No starting gold (но мы даём 0g, viewer тратит через extension currency converter)
- No `IsRetiredOrDead` flag (но `/retire` command нет в нашем катаgе)

🟢 **OUR IMPROVEMENTS:**
- `SetHasMet` — viewer hero видим в encyclopedia сразу
- `player.linked` event → backend persistence

---

## ② Spawn в Mission (player.spawn)

### Flow comparison

| Step | BLT (BLTSummonBehavior.cs) | Наш SummonHeroHandler.cs | Verdict |
|------|---------------------------|---------------------------|---------|
| **1. Refusal check** | `RetinueAllowed()` — only sieges/field battles | We check hideout, in-mission state, hero alive | ✅ Equivalent + наш более явный |
| **2. Hero resolve** | `agent.GetAdoptedHero()` (post-spawn lookup) или explicit | `HeroLookup.FindByUsername` | ⚠ Different timing — мы spawn потом lookup, BLT lookup потом spawn |
| **3. Side resolution** | `onPlayerSide: bool` parameter | Same flag через `isPlayerSide` | ✅ |
| **4. Formation pref** | `SetPlayerFormationPreference()` temp set + restore | Same через `SetPlayerFormationPreference` | ✅ |
| **5. Horse pref** | `ShouldBeMounted()` + class config | `ResolveWithHorse(username)` через PowerCache | ✅ |
| **6. initialPosition** | **`null`** (engine reinforcement zone) | **Sprint 5.33 (2026-05-28)**: ally → `Agent.Main.Position + perpOffset(3.5-6.5m)`, enemy → `null` | ⚠ **DEVIATION from BLT** |
| **7. initialDirection** | `null` | ally → `Agent.Main.LookDirection`, enemy → `null` | ⚠ DEVIATION |
| **8. isReinforcement** | `!DeploymentFlag` — true в обычном бою | `!heroSpawnPos.HasValue` — false если у нас override | ⚠ DEVIATION (false break engine reinforcement integration) |
| **9. SpawnTroop call** | `Mission.SpawnTroop(...)` с null pos | Same call, наш с override pos для ally | ✅ |
| **10. Retinue first-time only** | ✅ `TimesSummoned == 0` → spawn retinue too | ✅ Same logic (`heroAlreadySpawned` check) | ✅ |
| **11. Retinue2 (2nd tier)** | ✅ Separate Retinue2 list (premium tier viewers?) | ❌ Single retinue list | 🟡 minor |
| **12. Custom display name** | (BLT uses standard hero.Name) | `SetAgentDisplayName(agent, "@username")` via reflection | 🟢 Our improvement |
| **13. HP restore** | (not explicit в spawn — implicit by fresh agent) | `HP restored → max` лог | 🟢 Our improvement |

### Spawn position deep-dive

**BLT pattern:**
```csharp
initialPosition: null
initialDirection: null
isReinforcement: !DeploymentFlag
```

Engine MissionAgentSpawnLogic кладёт reinforcement в zone backline своей формации.

**Our pattern (Sprint 5.33 после user feedback):**
```csharp
if (isPlayerSide && Agent.Main != null) {
    heroSpawnPos = Agent.Main.Position + perpOffset(3.5-6.5m);
    heroSpawnDir = Agent.Main.LookDirection;
}
isReinforcement: !heroSpawnPos.HasValue   // false для override
```

Viewer spawn 3.5-6.5m от стримера, лицом туда же куда стример.

### Trade-offs analysis

**BLT pattern pros:**
- ✅ Корректная formation integration (AI commander видит как reinforcement)
- ✅ Не лепит viewer в стенку / occupied position
- ✅ Работает в siege / hideout / arena

**BLT pattern cons:**
- ❌ Viewer может spawn'нуться **очень далеко** (backline формации, behind hill)
- ❌ User feedback (2026-05-28): «спавн зрителей в бою далеко от мейн отряда»

**Наш pattern (perp offset) pros:**
- ✅ Viewer сразу в action рядом со стримером
- ✅ Стример сразу видит кто появился (visual cue)

**Наш pattern cons:**
- ❌ Может glitch в siege (walls) — try/catch fallback to null saves us
- ❌ Breaks formation reinforcement integration (`isReinforcement=false`)
- ❌ 5 viewer'ов могут лепиться в одну точку (мы randomized offset чтобы избежать)

### Verdict

**Не возвращаемся к BLT null.** Наш perp offset — улучшение UX, явная customization вопреки BLT default. **Документируем как "intentional deviation"**. 

Edge cases уже covered try/catch fallback to null (siege, hideout, transitions).

---

## Сводка fix priority

### 🔴 Apply now (likely real impact)
1. **Age override в AdoptHeroHandler** — `newHero.SetBirthDay(YearsFromNow(-(18-30 random)))` чтобы гарантировать adult hero

### 🟡 Apply later (nice-to-have)
2. **Iteration counter** для Heritage tracking (incrementally на re-adopt)
3. **Retinue2 (premium tier)** если введём sub-perks (после ToS clarification)
4. **Starting gold** small amount (1000 динаров) чтобы viewer мог что-то сразу купить в-game

### 🟢 Already better than BLT
- `SetHasMet` (no fog)
- `player.linked` event for multi-tenant DB sync
- `SetAgentDisplayName` `@username` (BLT использует raw hero name)
- HP restore на spawn

### ⚠ Intentional deviations (not bugs)
- Strip equipment vs keep+upgrade — наш forces explicit class pick
- Prefix `[BLink]` vs suffix `[BLT]` — наш более scannable для filter logic
- Spawn near Agent.Main vs reinforcement zone — UX preference user'а
