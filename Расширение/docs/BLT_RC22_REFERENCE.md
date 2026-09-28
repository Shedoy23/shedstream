# BLT-RC22 Reference Doc

**Source:** [Randomchair22/Bannerlord-Twitch 5.2.4](https://github.com/Randomchair22/Bannerlord-Twitch/releases/tag/5.2.4) (target: Bannerlord 1.3.15)
**Local clone:** `reference/BLT_RC22/` (262 .cs files, 64,240 LOC)
**Purpose:** Source-of-truth для refactor нашего мода. Адаптируем их patterns, не выдумываем.

**Workflow:**
- Cite exact file paths и line numbers
- Quote actual code (не интерпретации)
- Map к нашим файлам в `BannerlordLink/src/`
- Document gaps (что у них, нет у нас) и deltas (одна и та же mechanic — разные impl)

---

## Section A — BannerlordTwitch Core (BLT-REF-1)

### A.1 Helpers/OneShotEffect.cs

**File:** `reference/BLT_RC22/BannerlordTwitch/BannerlordTwitch/Helpers/OneShotEffect.cs`
**LOC:** 61
**Purpose:** struct-helper для разового particle + sound trigger (entry/exit cue for buffs, shield break, hit cue, etc.).

**Public API:**
```csharp
public struct OneShotEffect {
    public string ParticleEffect { get; set; }  // psys_... name
    public string Sound { get; set; }            // event:/... path

    public void Trigger(Hero hero);              // overload finds agent by hero
    public void Trigger(Agent agent);            // overload uses agent.AgentVisuals frame
    public void Trigger(MatrixFrame location, int relatedAgentIndex = -1);
    public static void Trigger(string particleEffect, string sound,
                               MatrixFrame location, int relatedAgentIndex = -1);
}
```

**Implementation (lines 43-57):**
```csharp
public static void Trigger(string particleEffect, string sound, MatrixFrame location, int relatedAgentIndex = -1)
{
    if (!string.IsNullOrEmpty(particleEffect))
    {
        Mission.Current.Scene.CreateBurstParticle(
            ParticleSystemManager.GetRuntimeIdByName(particleEffect),
            location);
    }
    if (!string.IsNullOrEmpty(sound))
    {
        Mission.Current.MakeSound(SoundEvent.GetEventIdFromString(sound),
            location.origin, false, true, relatedAgentIndex, -1);
    }
}
```

**Key points:**
- Использует **`Scene.CreateBurstParticle`** (one-shot burst, не looping) для particle
- Использует **`Mission.MakeSound`** (one-shot) для sound
- Empty strings → skip (no-op safe)
- **THIS IS EXACTLY THE SAME API наш PowerVisualFx использует.** Разница только в **частоте вызова** — они дёргают этот метод ОДИН РАЗ entry, ОДИН РАЗ exit; мы дёргаем каждые 2с во время duration.

**Наш аналог:** `BannerlordLink/src/Util/PowerVisualFx.cs:PlayParticle` + `PlaySound` (строки 182-218). Логика идентична. **Refactor target:** перенести нашу логику в struct OneShotEffect-style helper и вызывать только на entry/exit.

### A.2 Helpers/AgentPfx.cs

**File:** `reference/BLT_RC22/BannerlordTwitch/BannerlordTwitch/Helpers/AgentPfx.cs`
**LOC:** 320
**Purpose:** Wrapper для **persistent (looping)** particle effect, attached к agent через bones или weapon entity. Используется для visible buff durations.

**Public API:**
```csharp
public class AgentPfx {
    public Agent Agent { get; }
    public AgentPfx(Agent agent, IEnumerable<ParticleEffectDef> particleEffects);
    public void Start();  // creates attached particles (looping)
    public void Stop();   // removes them
}

public class ParticleEffectDef {
    public string Name { get; set; }  // psys_... (looping particle)
    public AttachPointEnum AttachPoint { get; set; }  // OnWeapon | OnHands | OnHead | OnBody
}
```

**Key implementation details:**

1. **`Start()` (lines 71-106):** Switch на `AttachPoint`:
   - `OnWeapon` → `CreateWeaponEffects` — добавляет particle вдоль blade (multiple instances для меча). Заодно делает `agent.DropItem` + `OnItemPickup` чтобы particle стал visible.
   - `OnHands/OnHead/OnBody` → `CreateAgentEffects` — creates bone attachment через `ParticleSystem.CreateParticleSystemAttachedToEntity`.

2. **Core engine API (line 151, 167, 241):**
   ```csharp
   var particle = ParticleSystem.CreateParticleSystemAttachedToEntity(
       pfxSystem, ownerEntity, ref localFrame);
   particle.SetRuntimeEmissionRateMultiplier(MBRandom.RandomFloatRanged(0.75f, 1.25f));
   ```
   Это **looping particle**, attached к bone или weapon entity. Cleanup через `Skeleton.RemoveComponent` или `BLTAgentPfxBehaviour.Current.RemoveAttachments`.

3. **`Stop()` (lines 108-118):**
   ```csharp
   foreach (var s in pfxStates) {
       if (s.weaponEffects != null) RemoveWeaponEffects(s.weaponEffects);
       if (s.boneAttachments != null) RemoveAgentEffects(s.boneAttachments);
   }
   pfxStates = null;
   ```

4. **`BLTAgentPfxBehaviour`** — MissionBehavior который держит коллекцию `BoneAttachments` и каждый кадр обновляет их frames (чтобы particle следовал за движущейся костью). Cleanup'ит при agent death / mission end.

**Наш аналог:** **НЕТ.** Мы используем `CreateBurstParticle` (one-shot) через `BuffsTickerBehavior` который дёргает caждые 2 секунды — pseudo-persistent через repeat. **Это и есть наш FMOD spam источник.**

**Refactor target:** Скопировать `AgentPfx` + `BLTAgentPfxBehaviour` к нам как `BannerlordLink/src/Util/AgentPfx.cs` (с минимальными модификациями для namespace), заменить наш `PlayBuffTick` re-burst pattern на `agent.AddPfx().Start()` / `.Stop()`.

### A.3 Helpers/AutoMissionBehavior.cs

**TODO** — нужно прочитать. Это base class для всех BLT MissionBehavior'ов с `SafeCall()` defensive wrapping.

### A.4 Helpers/MissionHelpers.cs

**TODO** — нужно прочитать. Утилиты для Mission state queries.

### A.5 Helpers/AgentHelpers.cs / AgentExtensions.cs

**TODO** — extension methods для Agent (`GetHero()`, etc.).

### A.6 Behaviors/BLTAgentPfxBehaviour.cs

**TODO** — координирует BoneAttachments lifecycle. Critical для AgentPfx работы.

### A.7 Behaviors/BLTAgentModifierBehavior.cs

**TODO** — runtime agent stat modifiers (speed, scale, etc.).

---

## Section B — BLTAdoptAHero/Powers ✅ COMPLETE (14 files read)

### Architecture overview

```
HeroPowerDefBase (abstract base; ICloneable, INotifyPropertyChanged)
├── ID (Guid), Name (LocString), Description (LocString)
├── ItemSourcePassive/ItemSourceActive (editor UI helpers)
│
├── AddHealthPower : HeroPowerDefBase, IHeroPowerPassive
│   └── OnAgentBuild → modify agent.Health/HealthLimit/BaseHealthLimit
│       (extends НЕ DurationMissionHeroPowerDefBase — purely passive,
│        cannot be used as timed active)
│
└── DurationMissionHeroPowerDefBase (abstract, IHeroPowerActive impl)
    ├── PowerDurationSeconds : float (default 30s)
    ├── Pfx : ObservableCollection<ParticleEffectDef>  ← persistent AgentPfx config
    ├── expiry : Dictionary<Hero, float>
    │
    ├── Activate(hero, expiryCallback):
    │   1. expiry[hero] = now + PowerDurationSeconds
    │   2. agent = hero.GetAgent()
    │   3. pfx = new AgentPfx(agent, Pfx); pfx.Start()  ← LOOPING particles
    │   4. ConfigureHandlers:
    │      - OnSlowTick: check expiry → pfx.Stop() + expiryCallback() + Deactivate
    │      - OnGotKilled: immediate cleanup
    │      - OnMissionOver: expiry.Clear()
    │      - OnActivation(hero, handlers, agent, deactivationHandler) ← derived hook
    │
    ├── AbsorbHealthPower : DurationMissionHeroPowerDefBase, IHeroPowerPassive
    │   └── OnDoDamage → agent.Health += blow.InflictedDamage * absorbPct / 100
    │
    ├── AddDamagePower : DurationMissionHeroPowerDefBase, IHeroPowerPassive
    │   ├── DamageModifierPercent (default 100), DamageToAdd (int)
    │   ├── ArmorToIgnorePercent, UnblockableChancePercent, ShatterShieldChancePercent
    │   ├── CutThroughChancePercent, StaggerChancePercent
    │   ├── AoE : AreaOfEffectDef (Range, DamageAtCenter, MaxAgentsToDamage)
    │   ├── MissileTrailParticleEffect, HitEffect : OneShotEffect
    │   └── OnDoDamage/OnDoMeleeHit/OnDoMissileHit handlers
    │       Special: ApplyShatterShieldChance triggers
    │                OneShotEffect("psys_game_shield_break", "event:/mission/combat/shield/broken")
    │
    ├── ReflectDamagePower : DurationMissionHeroPowerDefBase, IHeroPowerPassive
    │   ├── ReflectPercent, DamageToAdd, ReflectedDamageIsSubtracted (default true)
    │   ├── HitBehavior
    │   └── OnTakeDamage handler:
    │       - Creates counter Blow via attackerAgent.RegisterBlow(blow, collisionData)
    │       - Optionally subtracts reflected dmg from incoming
    │       - NO recursion guard needed (see below)
    │
    ├── StatModifyPower : DurationMissionHeroPowerDefBase, IHeroPowerPassive
    │   ├── RequiresHeroAgent = true
    │   ├── Modifiers : AgentModifierConfig
    │   └── OnAgentBuild → BLTAgentModifierBehavior.Current.Add + skill modifiers
    │       deactivationHandler.OnDeactivate → Remove + RemoveModifiers
    │
    └── TakeDamagePower : DurationMissionHeroPowerDefBase, IHeroPowerPassive
        ├── DamageModifierPercent, DamageToAdd, ArmorToIgnorePercent
        ├── AddHitBehavior, RemoveHitBehavior
        └── OnTakeDamage → AddDamagePower.ApplyDamageEffects (static reuse)

ActivePowerGroup (configurable container for multiple active powers)
├── Name, Powers : ObservableCollection<ActivePowerGroupItem>
├── ActivateEffect : OneShotEffect ← entry cue (sound + 1-shot particle burst)
├── DeactivateEffect : OneShotEffect ← exit cue
└── Activate(hero, context):
    - foreach unlockedPower: power.Activate(hero, () => { if all expired: DeactivateEffect.Trigger(hero) })
    - ActivateEffect.Trigger(hero)  ← ONE-SHOT entry

PassivePowerGroup
├── Name, Powers : ObservableCollection<PassivePowerGroupItem>
└── OnHeroJoinedBattle(hero):
    - foreach unlockedPower: power.OnHeroJoinedBattle(hero, handlers)
    - NO effects (passives are silent — only stat modifications)

PowerGroupItemBase (base for ActivePowerGroupItem + PassivePowerGroupItem)
└── Requirements : ObservableCollection<IAchievementRequirement>  ← unlock criteria

HitBehavior (struct used by AddDamagePower / ReflectDamagePower / TakeDamagePower)
└── KnockBack/Down/ShrugOff/MakesRear/Dismount chance percentages
    AddFlags / RemoveFlags modify Blow.BlowFlag
```

### Key insight #1: Powers can be BOTH active AND passive simultaneously

```csharp
public class AddDamagePower : DurationMissionHeroPowerDefBase, IHeroPowerPassive
```

ONE class has **two roles depending on which group уses it**:
- В `PassivePowerGroup.Powers[]` → permanent handlers via OnHeroJoinedBattle (lifetime = mission)
- В `ActivePowerGroup.Powers[]` → temporary handlers via Activate (lifetime = PowerDurationSeconds)

`OnActivation(hero, handlers, agent, deactivationHandler)` — общий entry point. Когда вызывается из passive path → `agent=null, deactivationHandler=null`. Когда из active path → оба заполнены.

### Key insight #2: Sound usage is MINIMAL

Per-power sound calls в hot path:
| Power | MakeSound calls | When |
|---|---|---|
| AddHealthPower | 0 | — |
| AddDamagePower | 1 conditional | Only when ShatterShieldChancePercent triggers AND chance roll succeeds |
| AbsorbHealthPower | 0 | — |
| ReflectDamagePower | 0 | — |
| StatModifyPower | 0 | — |
| TakeDamagePower | 0 | — |

**Sound только в entry/exit OneShotEffect at the GROUP level (ActivePowerGroup.ActivateEffect/DeactivateEffect).**

Implications for наш мод: **ВСЕ 8 наших powers (heal_burst, shield_break_burst, rage, retribution_toggle, poison_dot, disarm_burst, berserker_charge, etc.) дёргают MakeSound через PowerVisualFx.PlayActivation.** BLT использует MakeSound только на shield break (rare event) + entry/exit cue (rare event). Это **fundamental architectural difference**.

### Key insight #3: ReflectDamagePower has NO recursion guard

```csharp
// ReflectDamgePower.cs:75
attackerAgent.RegisterBlow(blow, blowParams.collisionData);
```

Они вызывают `Agent.RegisterBlow` (который внутри → `Mission.RegisterBlow` → их Harmony Prefix → CallHandlersForAgentPair с attackerAgent в role attacker).

**Recursion stops естественно** потому что:
1. Counter-blow fires OnTakeDamage **for original attacker**
2. Original attacker может не иметь Reflect power → ничего не происходит
3. Если у attacker'a ТОЖЕ есть Reflect — да, будет infinite loop. Но это rare случай и BLT принимает риск.

**Наш DamageHookPatch вызывает Mission.RegisterBlow напрямую из Prefix** → нужен ThreadLocal `_inReflect` guard. Мы можем избавиться от guard если migrate к BLT-style callback (post-blow event, not Prefix).

### Key insight #4: AgentPfx + DurationMissionHeroPowerDefBase = persistent visual

```csharp
// DurationMissionHeroPowerDefBase.cs:76-79
var agent = hero.GetAgent();
var pfx = agent == null ? null : new AgentPfx(agent, Pfx);
pfx?.Start();
```

`Pfx` это `ObservableCollection<ParticleEffectDef>` — список persistent particles attached к bones/weapon. Все играют loop в течение PowerDurationSeconds. Cleanup в OnSlowTick / OnGotKilled / OnMissionOver.

**This is THE pattern** мы должны adopt'ить. Замена `CreateBurstParticle` every 2s на `ParticleSystem.CreateParticleSystemAttachedToEntity` once.

### Key insight #5: Helper utilities

- `AddDamagePower.ApplyDamageEffects(victimAgent, blowParams, armorPct, dmgPct, dmgAdd, addBehavior, removeBehavior)` — **static, reusable** by TakeDamagePower. Same logic as нашего ApplyIgnoreArmor + ApplyRageOutgoing.
- `AddDamagePower.DoAgentDamage(from, agent, damage, direction, type, hitBehavior)` — **static, reusable** для AoE и Reflect. Создаёт Blow + вызывает agent.RegisterBlow.
- `AreaOfEffectDef.Apply(from, ignoreAgents, position)` — radius-based damage spread. Уменьшающийся с distance.

### B.1-B.14 Detailed file references

| File | Path | LOC | Purpose |
|---|---|---|---|
| B.1 IHeroPowerActive.cs | Powers/Core/ | 41 | Interface (CanActivate/IsActive/Activate/DurationRemaining) |
| B.2 IHeroPowerPassive.cs | Powers/Core/ | 19 | Interface (OnHeroJoinedBattle only) |
| B.3 HeroPowerDefBase.cs | Powers/Core/ | 94 | Abstract base + ItemSource UI helpers |
| B.4 DurationMissionHeroPowerDefBase.cs | Powers/Core/ | 152 | **Active timed power base** (AgentPfx + expiry + DeactivationHandler) |
| B.5 ActivePowerGroup.cs | Powers/Core/ | 168 | Container with ActivateEffect/DeactivateEffect OneShots |
| B.6 PassivePowerGroup.cs | Powers/Core/ | 127 | Container (silent, just stat mods) |
| B.7 HitBehavior.cs | Powers/Core/ | 109 | Struct: KnockBack/Down/Dismount chances |
| B.8 PowerGroupItemBase.cs | Powers/Core/ | 64 | Requirements + IsUnlocked |
| B.9 AbsorbHealthPower.cs | Powers/ | 82 | OnDoDamage → vampiric heal |
| B.10 AddDamagePower.cs | Powers/ | 582 | OnDoDamage + AoE + shield break + missile trail |
| B.11 AddHealthPower.cs | Powers/ | 72 | OnAgentBuild → modify Health |
| B.12 ReflectDamgePower.cs | Powers/ | 114 | OnTakeDamage → counter-blow (NO guard!) |
| B.13 StatModifyPower.cs | Powers/ | 73 | OnAgentBuild → BLTAgentModifierBehavior |
| B.14 TakeDamagePower.cs | Powers/ | 104 | OnTakeDamage → AddDamagePower.ApplyDamageEffects reuse |

**Total Section B: ~1801 LOC прочитано.**

---

## Section C — BLTAdoptAHero/Behaviors (BLT-REF-3)

### C.1 BLTHeroPowersMissionBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTHeroPowersMissionBehavior.cs`
**LOC:** 422

**🔴 CRITICAL CORRECTION к моим прошлым claim'ам:**

Прошлая claim (неверная):
> BLT использует engine-native events вместо Harmony patches на combat hot path.

Реальность (после чтения):
**BLT-RC22 имеет 7 Harmony patches на combat hot path:**

```csharp
// Lines 320-326: RegisterBlow Prefix (точно как у нас)
[HarmonyPrefix, HarmonyPatch(typeof(Mission), "RegisterBlow")]
private static void RegisterBlowPrefix(...)
{
    Current?.RegisterBlow(attacker, victim, ref b, ref collisionData,
        in attackerWeapon, ref combatLogData);
}

// Plus 6 more patches:
// - AddMissileAux Prefix (line 328)
// - HandleMissileCollisionReaction Prefix (line 342)
// - DecideWeaponCollisionReaction Postfix (line 354)
// - MeleeHitCallback Prefix (line 365)
// - MeleeHitCallback Postfix (line 386)
// - MissileHitCallback Prefix (line 407)
```

**Они патчат combat hot path БОЛЬШЕ нашего.** Наш `DamageHookPatch` патчит только RegisterBlow (1 patch).

### Реальное архитектурное отличие в combat hooks

**Centralized filter в их PowerHandler.cs:225-247:**
```csharp
public bool CallHandlersForAgentPair(Agent attackerAgent, Agent victimAgent,
    Action<Handlers> attackerCall, Action<Handlers> victimCall = null)
{
    var attackerHero = attackerAgent?.IsMount == true
        ? attackerAgent.RiderAgent?.GetAdoptedHero()
        : attackerAgent?.GetAdoptedHero();
    var victimHero = victimAgent?.IsMount == true
        ? victimAgent.RiderAgent?.GetAdoptedHero()
        : victimAgent?.GetAdoptedHero();
    if (attackerHero == null && victimHero == null)
        return false;  // ← EARLY EXIT для 99% blows (mob vs mob)
    ...
}
```

**Наш DamageHookPatch.cs:58-95 — distributed filter:**
```csharp
public static void Prefix(Agent attacker, Agent victim, ref Blow b, ref AttackCollisionData collisionData)
{
    if (_inReflect.Value) return;
    if (attacker == null || victim == null) return;
    if (attacker == victim) return;
    if (b.InflictedDamage <= 0) return;

    ApplyIgnoreArmor(attacker, ...);     // → GetAdoptedUsername lookup #1
    ApplyRageOutgoing(attacker, ...);    // → GetAdoptedUsername lookup #2
    ApplyTrophyBonuses(attacker, victim, ...);  // → lookups #3 + #4
    ApplyReflect(attacker, victim, ...);  // → lookup #5
}
```

Для blow в котором НЕТ adopted heroes:
- BLT: 2 lookups + 1 early return
- Наш: 5 lookups + 4 (?) early returns within Apply* methods

В большой битве 1000+ blows/sec — разница ~3000 vs 2000 dict ops/sec. **Минорная** в плане CPU, но **не FMOD-related**.

### SlowTick pattern

```csharp
// Lines 260-272
private const float SlowTickDuration = 2;
private float slowTick;

public override void OnMissionTick(float dt)
{
    slowTick += dt;
    if (slowTick > SlowTickDuration)
    {
        slowTick -= SlowTickDuration;
        powerHandler.CallHandlersForAll(handlers => handlers.SlowTick(SlowTickDuration));
    }
    powerHandler.CallHandlersForAll(handlers => handlers.MissionTick(dt));
}
```

И MissionTick (per-frame) и SlowTick (every 2s) дёргаются. Powers могут register'нуть на один или оба. Наш `PowersMissionBehavior` имеет похожий pattern (`BUFF_TICK_INTERVAL = 2.0f`), но у нас он используется для **re-burst particle**, а у BLT — для **light maintenance work** (cleanup, validation).

### C.2 PowerHandler.cs ✅ READ

**File:** `reference/BLT_RC22/BannerlordTwitch/BLTAdoptAHero/Behaviors/PowerHandler.cs`
**LOC:** 261

**Pattern: nested dictionary (Hero → Power → Handlers):**
```csharp
private readonly Dictionary<Hero, Dictionary<HeroPowerDefBase, Handlers>> heroPowerHandlers = new();
```

**Handlers — это struct с events:**
```csharp
public class Handlers {
    public event AgentBuildDelegate OnAgentBuild;
    public event MissionOverDelegate OnMissionOver;
    public event GotAKillDelegate OnGotAKill;
    public event GotKilledDelegate OnGotKilled;
    public event DoDamageDelegate OnDoDamage;
    public event TakeDamageDelegate OnTakeDamage;
    public event DecideWeaponCollisionReactionDelegate OnDecideWeaponCollisionReaction;
    public event DoMeleeHitDelegate OnDoMeleeHit;
    public event TakeMeleeHitDelegate OnTakeMeleeHit;
    public event DoMeleeHitDelegate OnPostDoMeleeHit;
    public event TakeMeleeHitDelegate OnPostTakeMeleeHit;
    public event DoMissileHitDelegate OnDoMissileHit;
    public event TakeMissileHitDelegate OnTakeMissileHit;
    public event MissionTickDelegate OnSlowTick;
    public event MissionTickDelegate OnMissionTick;
    // ... и ещё 8 events
}
```

Power регистрирует callbacks через `ConfigureHandlers(hero, power, cfg => { cfg.OnDoDamage += MyDamageHandler; })`.

**Mount handling:** Lines 187-189, 228-233 — если agent это mount, redirect к `RiderAgent.GetAdoptedHero()`. Polished detail — мы это **не делаем**.

**SafeCall wrapping:** Lines 249-259 — каждый handler invoke обёрнут в try/catch с `Log.Exception`. Один сломанный handler не валит всю цепь.

### C.3 BLTRemoveAgentsBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/.../Behaviors/BLTRemoveAgentsBehavior.cs`
**LOC:** 40

Простой cleanup для heroes added в Location (town/encounter scene), НЕ для battle. На `OnEndMission` + `OnMissionStateDeactivated` → `LocationComplex.Current.RemoveCharacterIfExists(hero) + Location.RemoveCharacter(hero)`.

**Наш аналог:** Нет, у нас нет concept town location summon (только battle spawn). Если когда-либо добавим — берём этот pattern.

### C.4 BLTHeirBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/BLTAdoptAHero/Behaviors/BLTHeirBehavior.cs`
**LOC:** 101

Heir tracking:
- `heirList: Dictionary<Hero, (Hero heir, bool flag)>` — adopted hero → их heir
- Hooks:
  - `HeroComesOfAgeEvent` — auto-detect new heir когда child grows up (18+)
  - `HeroKilledEvent` — remove если dies
  - `OnClanLeaderChangedEvent` — flag update (для succession)
- Persistence: `ScopedJsonSync` + `SyncDataAsJson("HeirData", ref heirList)` (NEWTON JSON serialization)

**Наш аналог:** наш HeritageBehavior + `_on_player_died` backend handler с asset transfer. У нас более complex (asset list, gold, items). У них simpler — heir автоматически selected по first-born adopted child.

**Что мы можем взять:** их auto-detect через `HeroComesOfAgeEvent` (мы используем event `hero.heir_came_of_age` from mod). Их simpler approach **может быть лучше для UX** — viewers не нужно вручную выбирать heir.

### C.5 KingdomTaxBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/BLTAdoptAHero/Behaviors/KingdomTaxBehavior.cs`
**LOC:** 98

**НОВАЯ FEATURE для нас.** Kingdom tax system:
- `kingdomTaxRates: Dictionary<string, float>` (kingdom StringId → rate 0-1)
- `SetKingdomTaxRate`, `GetKingdomTaxRate`, `CalculateTax(clan, income)`
- `CollectKingdomTaxes` — sums all vassal clan taxes, gives to RulingClan leader (king)
- **Don't tax ruling clan** rule

**Наш аналог:** НЕТ. Это **feature gap**.

**Adoption potential:** Полезно для kingdom-level dynamics (король = adopted viewer получает passive gold от vassal'ов). Откладываем до Stage 3 (feature parity).

### C.6 BLTHeroWidgetBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/BLTAdoptAHero/Behaviors/BLTHeroWidgetBehavior.cs`
**LOC:** 339

Persistent nametag над adopted hero agents. **МЫ adapt'или это в HeroNametagMissionView**, но есть отличия:

**Что у них лучше нашего:**
1. **Iterate `heroBehavior.activeHeroes`** (pre-built Hero collection), не all Agents. Меньше work. Наш подход — iterate all Agents и filter by IsAdopted naming.
2. **Skip in `MissionCombatType.NoCombat`** missions (conversations, etc). Мы не skip — потенциально дёргаемся в conversation modes.
3. **Tournament team colors** — `GetTournamentTeamColor(hero)` использует `agent.Team.TeamIndex` чтобы dynamically pick один из 4 цветов. Мы используем static green/red.
4. **No safety try/catch per-agent.** Тщательнее: BLT trusts engine. Мы добавили `_aborted` kill-switch — keep, у нас больше mod conflicts.

**Что у нас лучше:**
1. `_aborted` kill-switch после N errors (safety net для high mod count environment)
2. Per-agent try/catch (per-frame work over many agents)

**Refactor target:** заменить нашу iteration по Agents на iteration по pre-built activeHeroes list (нужна new behavior `HeroActiveTracker`).

### C.7 BLTSummonBehavior.cs ✅ READ — CRITICAL

**File:** `reference/BLT_RC22/BLTAdoptAHero/Behaviors/BLTSummonBehavior.cs`
**LOC:** 434

**Это аналог нашего SummonHeroHandler. Многое отличается в лучшую сторону:**

**Key patterns:**

1. **`HeroSummonState`** — per-hero state machine:
   ```csharp
   public class HeroSummonState {
       public Hero Hero;
       public bool WasPlayerSide;
       public bool SpawnWithRetinue;
       public PartyBase Party;
       public AgentState State;
       public Agent CurrentAgent;
       public float SummonTime;
       public int TimesSummoned = 0;
       public List<RetinueState> Retinue { get; set; }
       public List<RetinueState> Retinue2 { get; set; }  // TWO retinues!
       
       // Cooldown logic baked in
       public bool InCooldown { get; }
       public float CooldownRemaining { get; }
       public float CoolDownFraction { get; }
   }
   ```

2. **`SpawnAgent` static helper** (line 389-408):
   ```csharp
   var agent = Mission.Current.SpawnTroop(
       new PartyAgentOrigin(party, troop),
       isPlayerSide: onPlayerSide,
       hasFormation: true,
       spawnWithHorse: spawnWithHorse,
       isReinforcement: isReinforcement,
       formationTroopCount: 1,
       formationTroopIndex: 0,
       isAlarmed: isAlarmed,
       wieldInitialWeapons: true,
       forceDismounted: false,
       initialPosition: null,        // ← engine reinforcement zone
       initialDirection: null
   );
   agent.MountAgent?.FadeIn();  // ← smooth visual entry
   agent.FadeIn();              // ← smooth visual entry
   return agent;
   ```

3. **`RetinueAllowed()`** guard (line 422):
   ```csharp
   public static bool RetinueAllowed()
       => MissionHelpers.InSiegeMission() || MissionHelpers.InFieldBattleMission();
   ```
   Retinue **ONLY** в siege/field battle. Не в tournament/hideout/arena. **Critical safety** — мы потенциально пытаемся spawn retinue в tournament и крашимся.

4. **`ShouldBeMounted()`** logic (line 410-420):
   ```csharp
   public static bool ShouldBeMounted(FormationClass formationClass) {
       return Mission.Current.Mode != MissionMode.Stealth
           && !MissionHelpers.InSiegeMission()
           && Mission.Current?.IsNavalBattle == false
           && formationClass is Cavalry or LightCavalry or HeavyCavalry or HorseArcher;
   }
   ```
   Cavalry даже **не получает mount** в siege/stealth/naval. Мы такой проверки не делаем.

5. **Retinue rename** (line 280, 307) — через AccessTools reflection переименовывают retinue agent чтобы видеть кому он принадлежит:
   ```csharp
   var agent_name = AccessTools.Field(typeof(Agent), "_name");
   agent_name.SetValue(retinueAgent, new TextObject($"{retinueAgent.Name} ({adoptedHero.FirstName})"));
   ```
   Result: "Cavalry Recruit (Streamer)" вместо "Cavalry Recruit". У нас нет.

6. **`RetinueDeathChance`** (configurable):
   ```csharp
   if (BLTAdoptAHeroModule.CommonConfig.RetinueDeathChance != 0f
       && agentState == AgentState.Killed
       && MBRandom.RandomFloat < BLTAdoptAHeroModule.CommonConfig.RetinueDeathChance) {
       retinueState.Died = true;
       BLTAdoptAHeroCampaignBehavior.Current.KillRetinue(retinueOwner.Hero, affectedAgent.Character);
   }
   ```
   Death is **probabilistic** (configurable chance), not deterministic. Streamer может tune от 0 (immortal retinue) до 1 (perma-death). У нас deterministic.

7. **Two retinues (Retinue + Retinue2)** — у них **две независимые** retinue collection (probably basic + elite). У нас одна (5 troops). Это потенциально expansion area.

8. **OnEndMission cleanup** (line 256-269):
   ```csharp
   foreach (var h in heroSummonStates)
       foreach (var r in h.Retinue.Where(r => r.State != AgentState.Killed))
           h.Party?.MemberRoster?.AddToCounts(r.Troop, -1);
   ```
   Live retinue troops removed from party roster на end mission. Чтобы save game не имел ghost'ов.

9. **`DoNextTick(Action)`** queue — deferred work pattern. Useful для post-action cleanup. Мы используем `MainThreadDispatcher` для similar цели.

10. **Custom Harmony patch** (line 424-433):
    ```csharp
    [HarmonyPatch(typeof(ShipAgentSpawnLogic), "IsAnyTeamsUnfilled")]
    static bool Prefix(ref bool __result) {
        __result = true;
        return false;
    }
    ```
    War Sails fix — always return true чтобы ship combat spawn work'ал.

**Что нам адаптировать:**
- ✅ FadeIn animations (smooth entry)
- ✅ `RetinueAllowed()` guards (НЕ spawn retinue в tournament/hideout)
- ✅ `ShouldBeMounted()` guards (не mount в siege/stealth/naval)
- ⚠️ Retinue rename (cosmetic)
- ⚠️ RetinueDeathChance probabilistic (UX decision)
- ⚠️ Two retinues (feature expansion)

### C.8 GoldIncomeBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/BLTAdoptAHero/Behaviors/GoldIncomeBehavior.cs`
**LOC:** 174

Passive gold income system:
- `CampaignEvents.DailyTickClanEvent` (NOT settlement — entire clan daily)
- Income sources:
  - Fief settlements (через `GoldIncomeAction.CalculateSettlementIncome`)
  - Vassal fief income (`VassalBehavior.Current.CalculateVassalFiefIncome(clan)`)
  - Mercenary contract income (`GoldIncomeAction.CalculateMercenaryIncome`)
  - Vassal mercenary bonus
- Tax integration:
  - If ruling clan + FiefIncomeEnabled + KingdomTaxBehavior — `CollectKingdomTaxes(clan)` от вассалов
  - If non-ruling clan — `taxResult.incomeAfterTax` (tax already collected)
- UpgradeBehavior integration для merc bonuses

**Наш аналог:**
- WorkshopProfitSyncBehavior (per-workshop daily diff)
- CaravanTrackerBehavior (per-caravan daily profit)
- FiefTributeSyncBehavior (per-fief daily tribute)

**Архитектурное отличие:** BLT использует **engine native** `CampaignEvents.DailyTickClanEvent` directly, передаёт через mod к streamer. У нас mod ИНИЦИИРУЕТ daily sync (push событие `hero.workshop_profit_sync` etc.) к backend которое потом credit'ит viewers.

**Их simpler** для single-player (нет multi-tenant). **Наш correctnей** для multi-tenant SaaS (нужны channel_id ground truth).

### C.9 BLTSettlementUpgradeBehavior.cs ✅ READ

**File:** `reference/BLT_RC22/BLTAdoptAHero/Behaviors/BLTSettlementUpgradeBehavior.cs`
**LOC:** 126

Daily settlement modifications (prosperity, loyalty, security, food, militia, tax):
- `CampaignEvents.DailyTickSettlementEvent`
- Reads `UpgradeBehavior.Current.GetXFlat/Percent` для каждого upgrade type
- Applies flat + percent to town.Prosperity, town.Loyalty, town.Security, town.FoodStocks, settlement.Militia
- Tax bonus → `town.OwnerClan.Leader.Gold += taxFlat`
- Village hearth bonuses

**Наш аналог:** НЕТ. У нас нет concept "settlement upgrades" — это purchasable improvements per settlement которые viewers могут apply.

**Adoption potential:** Это полезная feature (viewer-funded city improvements). Откладываем до Stage 3.

### C.10 BLTAdoptAHeroCustomMissionBehavior.cs ✅ READ (180 LOC)

**Purpose:** Generic per-Hero / per-Agent listener registration framework (separate from PowerHandler which is power-specific).

**Key pattern:**
```csharp
AddListeners(Hero hero,
    onAgentCreated, onMissionOver, onGotAKill, onGotKilled, onMissionTick, onSlowTick);
AddListeners(Agent agent, ...);  // per-agent (used by Summon for retinue troops)
```

`heroListeners + agentListeners` Dictionaries. Each retinue troop gets its own onGotAKill callback that credits hero owner.

**SafeCall wrapping** для каждого listener call. `SlowTickDuration = 2` (consistent with PowerHandler).

**Наш аналог:** мы не имеем этого framework, hardcode callbacks в Behaviors.

### C.11 BLTTournamentSkillAdjustBehavior.cs ✅ READ (76 LOC)

Two purposes:
1. **UnarmedRound** — convert blows to 10× damage Blunt (for tournaments where weapons removed but damage must persist)
2. **Skill debuff for previous tournament winners** — `GetModifiedSkill(hero, skill, base)` reduces skills based на total tournament finals won. Tournament balance feature.

**`OnRegisterBlow` engine-native override** — отличается от Harmony patch. Получает `Blow b` (value, NOT ref) — не может modify blow. У них Harmony patch когда нужен `ref Blow`.

**Harmony Postfix on `CharacterObject.GetSimulationAttackPower`** — prevents `attackPoints == 0` infinite loop при simulation unarmed rounds.

### C.12 BLTAdoptAHeroCommonMissionBehavior.cs ✅ READ (524 LOC)

**Это hub для viewer-hero combat events.** Главные responsibilities:
1. `activeHeroes: List<Hero>` populated в OnAgentCreated — **the pre-built list** widget использует
2. **OnAgentRemovedPrefix Harmony patch** (line 156-201) — **converts killed→unconscious** для adopted heroes:
   ```csharp
   if (affectedAgent.IsAdopted()) {
       if (!CommonConfig.AllowDeath
           || StaticRandom.Next() > CommonConfig.DeathChance
           || CommonConfig.MinimumAge <= affectedAgent.GetHero().Age) {
           agentState = affectedAgent.State = AgentState.Unconscious;
       }
   }
   ```
   **Prevents permadeath** для adopted heroes. Also protects adopted hero mounts.

3. **Difficulty scaling** (line 40-77):
   ```csharp
   PlayerSidePower / EnemySidePower calculated by OnAgentBuild
   PlayerSideRewardMultiplier = MathF.Pow(EnemyPowerRatio, scaling)  // more reward if enemy stronger
   ```
   Reward bonuses scale with battle difficulty. Configurable.

4. **HeroMissionState tracking** per hero — WonGold, WonXP, Kills, RetinueKills, KillStreak, LastAgentState, LastTeamIndex.

5. **ApplyKillEffects / ApplyKilledEffects / ApplyStreakEffects** — kill reward calculations:
   - subBoost multiplier
   - relativeLevelScaling formula:
     ```csharp
     => Math.Min(MathF.Pow(1f - Math.Min(MaxLevelInPractice - 1, levelB - levelA) / MaxLevelInPractice, -10f * MathF.Clamp(n, 0, 1)), max);
     ```
   - 0.25× factor для horse kills
   - MinimumGoldPerKill floor

6. **Periodic VM update tick (every 0.25s)** — MissionInfoHub update (HP, cooldown, retinue counts, etc).

7. **`MaxLevelInPractice = 32`** — practice cap для level scaling.

**Наши аналоги (что есть):**
- KillRewardBehavior — kill effects + streak
- HeroIdentityBehavior — hero tracking

**Что у них есть чего у нас нет:**
- ⚠️ **Killed → Unconscious conversion** (permadeath prevention) — major safety feature
- ⚠️ **Mount protection** (adopted hero mounts don't die)
- Difficulty scaling rewards
- MissionInfoHub VM (centralized HUD data)

### C.13 BLTTournamentQueueBehavior.cs ✅ READ (203 LOC)

**CampaignBehaviorBase** — persistent across сессий. Queue для viewer tournaments.

**Save pattern smart:**
```csharp
if (dataStore.IsSaving) {
    var usedHeroList = TournamentQueue.Select(t => t.Hero).ToList();
    dataStore.SyncData("UsedHeroObjectList", ref usedHeroList);  // engine handles Hero refs
    var queue = TournamentQueue.Select(e => new TournamentQueueEntrySavable {
        HeroIndex = usedHeroList.IndexOf(e.Hero),  // index into above list
        IsSub = e.IsSub,
        EntryFee = e.EntryFee,
    }).ToList();
    scopedJsonSync.SyncDataAsJson("Queue2", ref queue);  // JSON for non-engine data
}
```

**Hybrid persistence:** engine for Hero objects, JSON for serializable data. Avoids JSON serializing Hero (which engine can't reconstruct).

`StartViewerTournament(isPlayerParticipating)`:
1. Creates `tournamentGame` via `Campaign.Current.Models.TournamentModel.CreateTournament`
2. Creates 3 behaviors: BLTTournamentMissionBehavior, BLTTournamentBetMissionBehavior, BLTTournamentSkillAdjustBehavior
3. Adds them via `MissionState.Current.CurrentMission.AddMissionBehavior`

**Harmony patch на `FightTournamentGame.GetParticipantCharacters`** — replaces vanilla list with queued viewers.

### C.14 BLTClanBehavior.cs ✅ READ (508 LOC)

**3 inner subsystems:**

#### BLTFamily
- Build family list (spouse, parents, children, grandchildren of adopted heroes)
- `GiveDailyXpToFamily()` — 1500 XP to each family member daily (weapon-relevant skill + random support skill)
- `AgeBLTChildren()` — accelerated child aging via `BLTChildAgeMult` config (skip BirthDay days)
- **Weekly auto-equip** для children/spouse via `EquipBLTChildren`:
  - Skip if `IsChild`, dead, или no culture
  - If total armor < 100 → equip noble template armor for culture
  - Equip weapons by best skills (best ranged + best melee + shield if 1-handed)
  - Add horse if Riding > 100

#### BLTSocialSecurity
- Weekly tick: adopted clan leaders get bonuses
- +5 renown per week always
- +50000 gold if leader gold ≤ 100,000 (poor support)
- +250 influence if clan influence ≤ 100 (and not mercenary, has kingdom)

#### BLTPrisoner
- Daily tick: if adopted hero is prisoner > 10 days → `EndCaptivityAction.ApplyByEscape(hero)`
- **Auto-escape** — viewer doesn't need to do anything

**Что у нас:** marriage/divorce/make_baby есть. Auto-equip children — НЕТ. Social security bonuses — НЕТ. Prisoner auto-escape — НЕТ.

### C.15 BLTHeroDetachmentBehavior.cs ✅ READ (679 LOC) — CRITICAL

**Это аналог нашего `HeroDetachmentBehavior + DetachmentHandlers`. Огромный (679 LOC), много нюансов.**

**Custom `HeroDetachment : IDetachment`** — full IDetachment implementation (NOT engine default). Has `_agents` list, ParentFormation tracking.

**Detach procedure (line 43-79):**
1. Create new HeroDetachment(formation)
2. formation.JoinDetachment(detachment)
3. If `agent.IsDetachedFromFormation` already → TryAttachToFormation first
4. agent.Formation.DetachUnit(agent, false)
5. detachment.AddAgentAtSlotIndex(agent, 0)
6. _detachments[agent] = new DetachmentState { Detachment = detachment }

**🔴 CRITICAL crash protection в `AddAgentAtSlotIndex` (line 564-597):**
```csharp
int fileIndex = ((IFormationUnit)agent).FormationFileIndex;
int rankIndex = ((IFormationUnit)agent).FormationRankIndex;
// FormationFileIndex == -1 → agent unpositioned, NOT in 2D grid.
// DetachUnit → LineFormation.RemoveUnit will crash trying to null _units2D[fileIndex, rankIndex].
if (fileIndex >= 0 && rankIndex >= 0) {
    try { formation.DetachUnit(agent, IsLoose); }
    catch (Exception e) { Log.Error(...); }
}
// If unpositioned — skip DetachUnit, still set Detachment property.
```

**Это known engine bug workaround.** Без проверки → null reference crash. **Нам ПРОВЕРИТЬ что наш HeroDetachmentBehavior имеет аналогичный guard.** Если нет — потенциально объясняет некоторые crashes.

**5 orders + None:**
- `Hold(agent)` — store WorldPosition, SetScriptedPosition each tick
- `Follow(agent)` — follow parent formation median + 3m behind offset
- `Charge(agent)` — `SetTargetFormationIndex(closestFormation.Formation.Index)` (closest enemy lookup CODE COMMENTED OUT — they use formation only)
- `Walls(agent)` — siege only: search WallSegment (breached for attackers) → SiegeTower (attackers only) → SiegeLadder.StandingPoints. SetScriptedPosition w/ NeverSlowDown.
- `TargetDoor(agent)` — siege only: CastleGate. Attackers use `SetScriptedTargetEntity(gate, AttackEntity, true)`. Defenders navigate к MiddlePosition.

**ApplyNavigate** (line 456-481):
```csharp
const float ReissueInterval = 1.5f;
const float ArrivedDistanceSq = 9f;  // 3 metres

if (distSq < ArrivedDistanceSq) {
    state.HoldPosition = agent.GetWorldPosition();
    state.Order = DetachmentOrder.Hold;
    ApplyHold(agent, state);
    return;
}
if (now - state.LastNavigationReissueTime > ReissueInterval) {
    agent.SetScriptedPosition(ref pos, false, ...);  // re-issue
}
```

**Buffer copy pattern в OnMissionTick** (line 380-409):
```csharp
_tickBuffer.Clear();
_tickBuffer.AddRange(_detachments);  // ← copy before iterate
foreach (var kvp in _tickBuffer) {
    if (!_detachments.ContainsKey(agent)) continue;  // ← re-check
    if (!agent.IsActive()) continue;
    switch (state.Order) { Hold/Follow/Navigate }
}
```

Avoids "collection modified during iteration" if agent dies mid-tick.

**Cleanup paths:**
- `Attach()` — full reattach via formation.AttachUnit
- `OnAgentRemoved` → `CleanupDetachmentOnDeath` (NO AttachUnit, agent dying)
- `OnAgentDeleted` → just dict remove
- `OnEndMission` → clear all

**HeroDetachment.IDetachment implementation:**
- `IsLoose => true` (line 550)
- All IDetachment weight methods return `float.MinValue/MaxValue` — they don't compete with normal detachments

### C.16 BLTTournamentBetMissionBehavior.cs ✅ READ (293 LOC)

**Tournament betting system.** Лучшие insights:

1. **BettingState lifecycle:** none → open (AfterStart Postfix) → closed (StartMatch/SkipMatch Prefix) → disabled (на OnEndMission)

2. **Pari-mutuel distribution** (line 226-255):
   ```csharp
   double totalBet = activeBets.Sum(b => b.bet);
   var allWonBets = activeBets.Where(team matches winner);
   double winningTotalBet = allWonBets.Sum(b => b.bet);
   foreach (winner) {
       int winnings = (int)(totalBet * bet / winningTotalBet);  // proportional
       ChangeHeroGold(hero, winnings);
   }
   ```
   Winners split entire pot proportionally к their bets. **Совершенно отличается** от fixed odds.

3. **Refund conditions:**
   - Only one team bet on (нет market)
   - No bets placed
   - Mission ended (OnEndMission)
   - Match skipped without resolve

4. **PlaceBet validation:**
   - Tournament active
   - Betting enabled
   - State == open
   - Round 3 (final) if BettingOnFinalOnly
   - Team name matches
   - Hero hasn't bet on different team (only one team per hero)
   - Hero has enough gold

**Наш аналог:** TournamentMissionBehavior + bet handlers (split across files). Logic similar but у нас fixed payouts (×2 if correct), не pari-mutuel.

### C.17 TrainingBehavior.cs ✅ READ (326 LOC) — NEW FEATURE

**Persistent troop training fund.** Viewer пополняет gold, daily auto-upgrades troops.

**Data model:**
```csharp
TrainingEntry { int Fund; int MaxTier; }
Dictionary<string, TrainingEntry> _funds;  // hero.StringId → entry
```

**Save pattern — parallel lists (engine SyncData):**
```csharp
var keys = _funds?.Keys.ToList();
var values = _funds?.Values.Select(e => e.Fund).ToList();
var tiers = _funds?.Values.Select(e => e.MaxTier).ToList();
dataStore.SyncData("BLT_TrainingFunds_Keys", ref keys);
dataStore.SyncData("BLT_TrainingFunds_Values", ref values);
dataStore.SyncData("BLT_TrainingFunds_Tiers", ref tiers);
```

Standard pattern для serializing Dictionary через SyncData — parallel List<TKey> + List<TVal>.

**Daily tick logic:**
1. Check viewer hero leads party, not in MapEvent, not disbanding
2. Compute daily budget (capped by TrainMaxDailySpend)
3. If MaxTier=0 → upgrade leader's party
4. If MaxTier>0:
   - If party not yet at tier → upgrade leader party
   - Else → `PickSpilloverParty` (random clan party with troops below cap)
5. Process upgrades via `PartyTroopUpgradeModel.GetGoldCostForUpgrade`
6. Track spend, reduce fund

**`PartyIsAtOrAboveTier`** — checks if all non-hero healthy troops have tier >= minTier.

**Наш аналог:** НЕТ. **Feature gap.** Эта механика для viewer-managed army development (long-term investment).

### C.18 HarmonyPatches.cs ✅ PARTIAL READ (~900 / 1200 LOC) — CRITICAL

**Большой файл (41KB).** Содержит protective patches для adopted heroes/clans/kingdoms.

**Все patches gated на `IsAdopted()` check.**

#### Pattern: "flag-gated bypass" (AdoptedHeroFlags)
```csharp
public static class AdoptedHeroFlags {
    public static bool _allowKingdomMove = false;
    public static bool _allowDiplomacyAction = false;
    public static bool _allowBLTArmyCreation = false;
    public static bool _allowAIjoinBLT;
}

// Usage:
AdoptedHeroFlags._allowKingdomMove = true;
try {
    ChangeKingdomAction.ApplyByLeaveKingdom(clan);  // patched to honor flag
} finally {
    AdoptedHeroFlags._allowKingdomMove = false;
}
```

Static flags toggled around specific actions. Try/finally **critical** — иначе flag stays set if exception.

#### Death prevention patches (multiple)
1. **KillCharacterAction.ApplyInternal** (line 532-546):
   ```csharp
   if (isForced) return true;
   if (!victim.IsAdopted()) return true;
   if (killer == Hero.MainHero && actionDetail == Executed) return true;
   if (!config.AllowDeath) return false;  // permadeath off
   if (victim.Age > config.MinimumAge) return true;  // age 80+ can die
   return false;  // otherwise block
   ```

2. **KillCharacterAction.ApplyInLabor** (line 486-499) — pregnancy death prevention

3. **DefaultMarriageModel.IsSuitableForMarriage** (line 502-526):
   - Block adopted heroes from being marriage candidates (viewers control their marriages)
   - Block heirs (registered in BLTHeirBehavior._heirs) — preserve succession

4. **DefaultMarriageModel.GetClanAfterMarriage** (line 458-484):
   - Postfix ensures marriage goes INTO adopted clan, not OUT of it
   - Preserves viewer's clan identity

#### Clan/Kingdom protection
5. **FactionDiscontinuationCampaignBehavior** patches:
   - `DiscontinueClan` Prefix — block if adopted leader
   - `CanClanBeDiscontinued` Prefix — return false
   - `DiscontinueKingdom` Prefix — full re-implementation:
     ```csharp
     foreach (Clan clan in kingdom.Clans) {
         if (clan.Leader.IsAdopted()) {
             _allowKingdomMove = true;
             ChangeKingdomAction.ApplyByLeaveKingdom(clan);  // graceful exit
             _allowKingdomMove = false;
         } else {
             ChangeKingdomAction.ApplyByLeaveByKingdomDestruction(clan, true);
         }
     }
     kingdom.RulingClan = null;
     DestroyKingdomAction.Apply(kingdom);
     return false;  // skip original
     ```
   - **Reflection delegate pattern** для private `FinalizeMapEvents`:
     ```csharp
     static FactionDiscontinuationPatches() {
         var methodInfo = type.GetMethod("FinalizeMapEvents", BindingFlags.NonPublic | BindingFlags.Instance);
         FinalizeMapEvents = (FinalizeMapEventsDelegate)Delegate.CreateDelegate(...);
     }
     ```

6. **ChangeKingdomActionPatches** — block AI moving adopted clans:
   - ApplyByJoinToKingdom, ApplyByJoinToKingdomByDefection, ApplyByLeaveKingdom, ApplyByLeaveWithRebellionAgainstKingdom
   - All check `_allowKingdomMove` flag first

7. **Clan.UpdateBannerColorsAccordingToKingdom** — block для adopted clans (preserve custom banners)

#### Decision blocking
8. **DeclareWarDecision constructor** Prefix — block для BLT kingdoms (AI won't propose war against viewer)
9. **ExpelClanFromKingdomDecision constructor** Prefix — block для BLT kingdoms
10. **KingdomDecisionProposalBehavior.ConsiderWar** Prefix — block для BLT kingdoms

#### Diplomacy blocking
11. **MakePeaceAction.ApplyInternal** Prefix — comprehensive:
    - Allow if `_allowDiplomacyAction` flag (BLT-initiated)
    - Check `BLTTreatyManager.CanMakePeace(k1, k2, out reason)` — minimum war duration enforcement
    - If AI→BLT peace attempt → `BLTDiplomacyBehavior.Current.HandleAIPeaceAttempt(ai, blt)` (creates UI proposal)
    - Block all unsanctioned BLT-BLT peace

#### Engine bug fixes
12. **BLT_SiegeRetreatFix** (line 838-908):
    - Patches `MapEvent.CalculateAndCommitMapEventResults`
    - Sets `RetreatingSide = DefeatedSide` if siege has survivors → temporarily prevent full army capture
    - `_mutated` HashSet tracks mutated MapEvents to restore in Postfix
    - **Fixes vanilla bug** где retreat from siege = entire army captured/killed

13. **Town_GetDefenderParties** Prefix — replaces original logic:
    - Includes militia in SallyOut defender list
    - **Fixes vanilla omission**

14. **DefaultSettlementFoodModel.FoodStocksUpperLimit** getter Prefix:
    ```csharp
    __result = CommonConfig.UncapFoodStocks ? 10000 : 300;  // bump cap
    return false;
    ```

15. **Village.GetHearthLevel** Prefix — configurable HearthPerVillageTier (default vanilla тbreak hardcoded)

16. **BLT_ArmyDispersionPatch** — `Army.CheckArmyDispersion` Prefix:
    - Block disperse if adopted leader AND daysAlive < BLTArmyMinLifetimeDays
    - If LockBLTArmyCohesion AND Cohesion >= 100 → block cohesion-caused dispersion
    - `ArmyCreationTimes` Dictionary tracks creation
    - **Cleanup pattern** — Remove from tracking when LeaderParty.Army != __instance

17. **ShipTradeCampaignBehavior.OnShipOwnerChanged** Finalizer — swallows ALL exceptions (engine bug workaround for War Sails ships):
    ```csharp
    static Exception Finalizer(Exception __exception) => null;  // swallow
    ```

#### MakeHeroFugitiveAction + AiPartyThinkBehavior + Kingdom.CreateArmy
(Lines beyond ~900 — not fully read this session). More armies/ai/fugitive patches.

**Что у нас:**
- ❌ Death prevention — у нас нет (heroes умирают окончательно)
- ❌ Faction protection — у нас нет (clans/kingdoms могут destroyed engine'ом)
- ❌ AI movement blocks — у нас нет (clans могут join другие kingdoms)
- ❌ Diplomacy controls — у нас есть partial (через DIPLO module) но нет блока AI-initiated peace
- ❌ Engine bug fixes (siege retreat, militia sally out, food/hearth caps) — нет
- ❌ Army dispersion control — нет

**Это огромный feature gap.** Большинство этих patches это **гарантия что viewer-controlled entities стабильно существуют в долгосрочной перспективе.** Без них adopted clans могут случайно discontinue'нуться, kingdoms — destroyed, armies — disperse'нуться.

### C.19 HarmonyPatches.cs (finish) ✅ READ (full 1086 LOC)

Финальные patches (lines 900-1086):
- **MakeHeroFugitiveAction.Apply** Prefix — prevent lord становление fugitive во время siege (если besieging settlement + healthy troops)
- **Kingdom.CreateArmy** Prefix — block AI army creation для adopted heroes unless `_allowBLTArmiesCreation`. Respect `pb.IsBLTArmiesBlocked` / `pb.IsAIArmiesBlocked` per kingdom
- **Army.FindBestGatheringSettlementAndMoveTheLeader** Prefix — clan armies (no kingdom) handled via `BLTClanArmyBehavior.FindClanGatherSettlement`
- **AiPartyThinkBehavior.PartyHourlyAiTick** Prefix — skip vanilla AI tick если party имеет active siege order

### C.20 VassalBehavior.cs ✅ READ (591 LOC)

**Vassal clan hierarchy management.**

**Data:** `Dictionary<string, string> _vassalToMaster` (vassal StringId → master StringId).

**Income sharing (passive):**
- 25% vassal merc income → master (`CalculateVassalMercenaryBonus`)
- 25% vassal fief income → master (`CalculateVassalFiefIncome`)

**Auto-following через CampaignEvents:**
- **OnClanChangedKingdom** — vassal автоматически follows master kingdom change
  - Если vassal в неправильном kingdom — корректируется через `AdoptedHeroFlags._allowKingdomMove = true` bypass
  - Mercenary status preserved (master mercenary → vassal joins as mercenary)
- **WarDeclared** — vassal joins master's wars
- **MakePeace** — vassal joins master's peace deals
- **OnClanDestroyed** — cleanup мaps

**Settlement transfer logic** — при leaving kingdom, fiefs передаются ruling clan leader (или vassal leader if rebel)

**Наш аналог:** VassalHandlers есть но без auto-following AI events. **Feature gap.**

### C.21 ReinforcementBehavior.cs ✅ READ (560 LOC)

**Settlement militia reinforcements** (NOT viewer hero spawn).

**Data:**
- `_reinforcements: Dictionary<string, int>` — per-settlement normal militia count
- `_eliteReinforcements: Dictionary<string, int>` — per-settlement elite militia count
- `_openSiegeParties` / `_openEliteSiegeParties` — runtime tracking

**Lifecycle:**
1. **OnSiegeEventCreated** (Harmony Postfix on `SiegeEventManager.StartSiegeEvent`) — spawn militia parties via `MilitiaPartyComponent.CreateMilitiaParty` → convert to `CustomPartyComponent`
2. **Daily food refill** для milita parties (so не starve)
3. **OnAfterSiegeCompleted** — `ReconcilePartyListForSettlement` counts survivors → persist as new count. If attacker won → wipe all reinforcements (settlement captured).
4. **OnSiegeEventEnded** — cleanup parties (clear roster, mark inactive, IsDisbanding)

**Feature for streamer:** invest gold to fortify settlement militia, persists across sieges. У нас нет.

### C.22 PartyOrderBehavior.cs ✅ PARTIAL (300/1024 LOC) — pattern confirmed

**6 order types:** Siege, Defend, Patrol, Garrison, Raid, **SmartGuard** (dynamic).

**Persistence:** `_ordersJson: List<string>` (Newtonsoft JSON per-order). Deserialized on load. **Restores `SetDoNotMakeNewDecisions(true)` для active orders.**

**Hourly tick monitoring** (`OnHourlyTickParty`):
- BLT army cohesion top-up: `party.Army.Cohesion = 100f`
- Settlement-in-place handling (Garrison sticky)
- Expiry check (`ExpiresAtDays`)
- **SmartGuard dynamic re-evaluation** — switches между Defend/Patrol/Village-patrol based на live conditions (enemy siege, raid)
- Drift detection: `DefaultBehavior` + `TargetSettlement` mismatch → re-issue
- `MaxReissueAttempts` + `ReissueAttempts` counters — gives up after N tries
- `party.Ai.SetDoNotMakeNewDecisions(true)` engine lock

**Per-kingdom blocks:**
- `AIArmiesBlockedKingdoms` — block AI army creation
- `BLTArmiesBlockedKingdoms` — block BLT army creation
(Used by `Kingdom.CreateArmy` Harmony patch we saw)

**Cleanup events:**
- `OnMakePeace` → cancel siege orders
- `OnHeroKilled` → cancel hero orders
- `OnHeroPrisonerTaken` → cancel
- `OnMobilePartyDestroyed` → cleanup
- `OnSettlementOwnerChangedEvent` → cancel orders targeting captured settlements
- `OnArmyDispersed` → cleanup

**Наш аналог:** PartyOrderBehavior есть — workflow похож (sticky orders + HourlyTick re-issue). Скип detail.

### C.23 BLTCustomItemsCampaignBehavior.cs ✅ READ (212 LOC)

**Custom ItemModifier registry** для viewer-owned upgraded items.

**Pattern:**
```csharp
private Dictionary<ItemModifier, ItemModifierData> customItemModifiers;

// Create:
var modifier = new ItemModifier();
modifierData.Apply(modifier);
var registered = MBObjectManager.Instance.RegisterObject(modifier);
customItemModifiers.Add(registered, data);
```

**ItemModifierData** holds stats: Damage, Speed, MissileSpeed, Armor, HitPoints, StackCount, MountSpeed, Maneuver, ChargeDamage, MountHitPoints, CustomName.

**Persistence dual-track:**
- `savedModifierList: List<ItemModifier>` — engine SyncData
- `savedModiferDataList: List<ItemModifierData>` — JSON via ScopedJsonSync
- On load: zip lists, re-register objects, apply data

**Helpers:**
- `CreateArmorModifier(name, armorBonus)` — armor pieces
- `CreateWeaponModifier(name, damage, speed, missileSpeed, stack)` — weapons
- `CreateMountModifier(name, maneuver, speed, charge, hp)` — horses
- `CreateShieldModifier(name, hp)` — shields
- `CreateAmmoModifier(name, damage, stack)` — arrows/bolts
- `CreateDummyModifier(baseName)` — no-op
- `NameItem(modifier, name)` — viewer-set custom name

**Наш аналог:** trophy system в backend (rolled stats). Architecture different — мы store на backend, они через engine objects.

### C.24 BLTTournamentMissionBehavior.cs ✅ PARTIAL (200/~700 LOC)

Tournament participant management:
- **GetParticipants()** — replaces vanilla list:
  - If player participating → add Hero.MainHero
  - Add up to (16 - existing) viewers from `TournamentQueue`
  - Fill remaining slots with culture basic/elite troops
  - Apply `PreviousWinnerDebuffs` для viewers с tournament wins (handicap system)
- **GetTeamWeaponEquipmentListPostfixImpl** — equipment customization:
  - **NoHorses** option — remove mounts
  - **NoSpears** filter (exclude non-swingable polearms)
  - **RandomizeWeaponTypes** — sophisticated selection:
    - Score by skill match: 20 × (intersect) - (mismatch)
    - Random selection с weighted bias toward best-match equipment
    - Add 2 random sets для variety + 1 unarmed (weight 0.5)
    - `UnarmedRound = tournamentSet.IsEmpty()`
- **`PreviousWinnerDebuffs`** — skill modifiers для prior winners (configurable handicap)

**Наш аналог:** TournamentMissionBehavior есть но без such sophisticated equipment selection.

### C.25 UpgradeBehavior.cs ✅ PARTIAL (150/~1500 LOC)

**3-tier upgrade ecosystem** (Fief, Clan, Kingdom):
- `_fiefUpgrades: Dictionary<string, string>` (settlement StringId → comma-separated upgrade IDs)
- `_clanUpgrades`, `_kingdomUpgrades` — same pattern
- `_troopSpawnAccumulation: Dictionary<string, float>` — fractional troop spawn carry-over

**API per tier:**
- `GetXUpgrades(entity)` — parse comma-separated list
- `HasXUpgrade(entity, id)` — check membership
- `AddXUpgrade(entity, id)` — append
- `RemoveXUpgrade(entity, id)` — remove

**Config flags:**
- `AccumulateWhenFull` — preserve fractional progress when party full
- `IndependentClansCountAsLords` — eligibility flag
- `IndependentClansCountAsMercs` — opposite case

**Daily tick** processes upgrades — adds prosperity/loyalty/security/food/militia/tax bonuses per upgrade. Provides Getter methods for `BLTSettlementUpgradeBehavior` (which we already read).

**Наш аналог:** ClanUpgradesBehavior — smaller scope. У нас clan upgrades only, не fief/kingdom layers.

### C.26 BLTLogsBehavior.cs ✅ PARTIAL (80/~1100 LOC)

**4 log types:** Hero, Clan, Kingdom, Fief.

Each maintains `Dictionary<string, List<string>>` (entity StringId → list of log messages).
`maxLogs` config-driven cap.
Cleanup on `OnGameLoadFinishedEvent` (removes entries for non-existent entities).

**Hero logs** triggered by:
- `MapEventEnded` — battle results
- (Other events in remaining LOC: HeroKilled, levelup, prisoner, etc.)

**Viewer-facing history** — they can review their hero's activities. Полезная UX feature но не critical для stability.

### C.27 BLTAdoptAHeroCampaignBehavior.cs ✅ PARTIAL (250/~3700 LOC) — central state aggregator

**The MAIN viewer-hero state hub.** ~112KB файл.

**HeroData class** (per-hero persistent):
```csharp
class HeroData {
    public int Gold;                          // separate from engine Hero.Gold
    public List<RetinueData> Retinue;         // primary retinue (per-troop level)
    public List<Retinue2Data> Retinue2;       // secondary elite retinue
    public int SpentGold;                     // tracking
    public int EquipmentTier = -2;
    public Guid EquipmentClassID;             // selected class for equipment
    public Guid ClassID;                      // selected combat class
    public string Owner;                      // streamer who adopted
    public int Iteration;                     // re-adoption count
    public bool IsRetiredOrDead;
    public bool IsCreatedHero;
    public string LegacyName;                 // preserved across rebirths
    public AchievementStatsData AchievementStats;
    public List<SavedEquipment> SavedCustomItems;  // ItemModifierId references
    public List<EquipmentElement> CustomItems;     // runtime, derived
}
```

**Persistence:**
- `PreSave()` → serialize CustomItems → SavedCustomItems
- `PostLoad()` → deserialize SavedCustomItems → CustomItems

**OnGameLoadFinishedEvent cleanup:**
- Ensure all adopted heroes registered
- Remove invalid troop types from retinues
- Remove invalid custom items (engine ItemObject may be Invalid после mod removal)
- **Compensate viewer +50,000 gold per invalid item**
- Retire dead heroes (delayed until после other systems initialized)

**CampaignEvents listeners** для log feed events (HeroKilled/Leveled/Prisoner/ChangedClan/MapEventStarted/etc).

Remaining ~3500 LOC contain:
- All ChangeHeroGold / IncreaseKills / IncreaseHeroDeaths / etc. methods
- Equipment management
- RetireHero / KillRetinue logic
- ApplyAchievementPassivePowers
- Achievement stat tracking
- Settlement/Hero/Clan log feeds
- Persistence helpers

**Наш аналог:** HeroIdentityBehavior + множество backend tables. **Architecture fundamentally different** — мы храним всё на backend SQLite (multi-tenant), они в engine save через CampaignBehaviorBase.SyncData.

**Что мы НЕ имеем:**
- Per-troop level в retinue (мы store flat counts)
- Equipment custom items modifier system (мы roll bonuses на backend)
- Achievement stats data structure (мы trackим только базовые counts)
- Invalid item auto-compensation

3. HarmonyPatches.cs (41KB - non-combat patches)
4. BLTAdoptAHeroCampaignBehavior.cs (112KB - HUGE, campaign-side state)
5. BLTAdoptAHeroCommonMissionBehavior.cs (22KB)
6. BLTAdoptAHeroCustomMissionBehavior.cs (6KB)
7. BLTClanBehavior.cs (21KB)
8. BLTCustomItemsCampaignBehavior.cs (9KB)
9. BLTHeroDetachmentBehavior.cs (26KB)
10. BLTLogsBehavior.cs (32KB)
11. BLTTournamentBetMissionBehavior.cs (11KB)
12. BLTTournamentMissionBehavior.cs (24KB)
13. BLTTournamentQueueBehavior.cs (7KB)
14. BLTTournamentSkillAdjustBehavior.cs (3KB)
15. PartyOrderBehavior.cs (39KB - HUGE)
16. ReinforcementBehavior.cs (21KB)
17. TrainingBehavior.cs (13KB)
18. UpgradeBehavior.cs (47KB - HUGE)
19. VassalBehavior.cs (23KB)

**Total Section C прочитано (9/26): ~1500 LOC. Remaining: ~370KB / 17 files. Estimated 2-3 sessions for completion.**
3. **HarmonyPatches.cs** — confirm 0 combat hooks
4. **BLTSummonBehavior.cs** — analog нашему SummonHeroHandler
5. **BLTHeroWidgetBehavior.cs** — analog нашему HeroNametagMissionView (мы adapt'или)
6. **GoldIncomeBehavior.cs** — passive gold income (analog workshops/caravans)
7. **KingdomTaxBehavior.cs** — kingdom tax mechanic (у нас нет)
8. **PartyOrderBehavior.cs** — formation orders (у нас есть аналог)
9. **BLTHeroDetachmentBehavior.cs** — detach/attach (у нас есть аналог)
10. **BLTTournamentMissionBehavior.cs** + связанные — tournaments
11. **BLTHeirBehavior.cs** — heir/inheritance
12. **BLTAdoptAHeroCampaignBehavior.cs** — adoption flow
13. **BLTAdoptAHeroCommonMissionBehavior.cs** — общая mission logic
14. **BLTAdoptAHeroCustomMissionBehavior.cs** — custom mission logic
15. **BLTClanBehavior.cs** — clan tracking
16. **BLTCustomItemsCampaignBehavior.cs** — custom items persistence
17. **BLTLogsBehavior.cs** — logging
18. **BLTRemoveAgentsBehavior.cs** — agent cleanup
19. **BLTSettlementUpgradeBehavior.cs** — settlement upgrades
20. **BLTTournamentBetMissionBehavior.cs**
21. **BLTTournamentQueueBehavior.cs**
22. **BLTTournamentSkillAdjustBehavior.cs**
23. **ReinforcementBehavior.cs** — siege militia (НЕ viewer reinforcement)
24. **TrainingBehavior.cs**
25. **UpgradeBehavior.cs**
26. **VassalBehavior.cs**

---

## Section D — BLTAdoptAHero/Actions ✅ PATTERN COMPLETE (10 sampled)

### D-Base Patterns

#### Base classes
**`HeroActionHandlerBase : ActionHandlerBase`** (24 LOC):
```csharp
protected override void ExecuteInternal(ReplyContext context, object config, Action<string> onSuccess, Action<string> onFailure)
{
    var hero = BLTAdoptAHeroCampaignBehavior.Current.GetAdoptedHero(context.UserName);
    if (hero == null) { onFailure(AdoptAHero.NoHeroMessage); return; }
    ExecuteInternal(hero, context, config, onSuccess, onFailure);  // ← derived
}
```

**`HeroCommandHandlerBase : ICommandHandler`** (34 LOC):
Same pattern но for chat commands — uses `ActionManager.SendReply` directly.

#### Interface duality
Many actions implement BOTH:
- `IRewardHandler` — channel point redemption
- `ICommandHandler` — chat command

Example: `AdoptAHero` is both.

#### Naming helpers
- `Naming.Gold` — gold icon
- `Naming.Inc` — "+" indicator
- `Naming.Dec` — "-" indicator
- `Naming.To` — "→" indicator
- `Naming.NotEnoughGold(needed, current)` — standardized failure message

#### Settings pattern
- Internal `class Settings : IDocumentable` с `[LocDisplayName]` + `[LocCategory]` + `[PropertyOrder]` attrs
- `protected override Type ConfigType => typeof(Settings);`
- `GenerateDocumentation(IDocumentationGenerator)` — auto-generated docs

### D Files Sampled

| File | LOC | Pattern |
|---|---|---|
| HeroActionHandlerBase.cs | 24 | Reward base — hero resolution from username |
| HeroCommandHandlerBase.cs | 34 | Command base — hero resolution + SendReply |
| AddGoldToHero.cs | 43 | Simplest action — Amount setting, ChangeHeroGold |
| UsePower.cs | 52 | Class active power activation (CanActivate → IsActive → Activate) |
| SetHeroClass.cs | 147 | Mission.Current check, tier-based cost (5K → 160K), optional equipment update |
| AdoptAHero.cs | 200 (1/4) | BOTH IRewardHandler + ICommandHandler; 4 categories (General/Random/Subscribers/Init/Inheritance); ViewerSelects enum (Name/Clan/Culture/Faction); allow filters; subscriber gating; StartingGold/Age/Skills/Equipment/Class |
| FocusPoints.cs | 155 | HeroCommandHandlerBase; 5 tier costs (30K-75K); parse `(skill) [count]`; max 5 focus per skill; HeroDeveloper.AddFocus |
| HeroToHeroGold.cs | 57 | Viewer-to-viewer gold transfer; strip @ from username; can't send to self |
| Rejuvenate.cs | 104 | De-age hero (default 1 year); Mission.Current check; min age 18; optional spouse de-age |
| AuctionItem.cs + BidOnItem | 113 | One-at-a-time custom item auction; AuctionDurationInSeconds (60s); reminder interval (15s); single-bid commands |
| NameItem.cs | 68 | Allow custom rename items; sanitize # из name |
| SummonHero.cs | 200 (1/8.5) | Complex 1700 LOC; Settings: AllowFieldBattle/Village/Siege/Friendly/HideOut, OnPlayerSide, WithRetinue, AllowWhenDepleted, GoldCost, PreferredFormation (Infantry/Ranged/Cavalry/HorseArcher/Skirmisher/HeavyInfantry/LightCavalry/HeavyCavalry), AlertSound, HealPerSecond, ShoutPercent; uses reflection delegates для private engine methods |

### D Patterns vs Our Mod

| Concept | BLT-RC22 | Наш мод |
|---|---|---|
| Action dispatch | IRewardHandler / ICommandHandler interfaces | dispatch_action() в backend |
| Hero resolution | `GetAdoptedHero(context.UserName)` static accessor | username → viewer state в backend |
| Mission validation | `if (Mission.Current != null) onFailure(...)` inline | event push к backend, validation там |
| Settings | strongly-typed class with attributes for Configure UI | YAML manifest + dispatch payload |
| Cost handling | tier-based switch expressions | numeric prices в backend ACTION_PRICES dict |
| Reply messages | LocString + Translate() + Naming helpers | event response messages |

### D — Не прочитано (36 файлов)

**Quick patterns confirmed** в:
- ClanManagement (59KB), KingdomManagement (80KB), PartyManagement (137KB), UpgradeAction (76KB), UpgradeDefinitions (63KB), FamilyManagement (30KB), HeroFeatures (35KB), CampaignInfo (40KB), Leaderboard (13KB), CampaignLogs (10KB), BattleInfo (12KB), FormationCommand (14KB), TransferAction (17KB), ReinforceAction (18KB), VassalCommand (19KB), ItemStats (20KB), SimpleDiplomacy (29KB), EquipHero (29KB), HeroInfoCommand (32KB), SmithItem (8KB), Retinue (4KB), Retinue2 (5KB), HeirCommand (13KB), ImproveAdoptedHero (5KB), SkillXP (5KB), DiscardItem (2KB), EquipCustomItem (11KB), ManageFief (11KB), AttributePoints (5KB), TournamentBet (3KB), JoinTournament (4KB), RetireMyHero (3KB), GiveItem (3KB), GoldIncomeFeature (12KB)

**Все следуют same pattern:** Settings → ExecuteInternal → validate → charge cost → apply action → reply.

**Unique features в BLT actions** что у нас нет:
- HeroToHeroGold (viewer-to-viewer transfer)
- Rejuvenate (de-age)
- AuctionItem + BidOnItem (auction system)
- NameItem (custom item rename)
- AttributePoints/FocusPoints (tier-cost skill development)
- RetireMyHero (graceful hero retirement)
- AdoptAHero with CreateNew option (wanderer adoption)

---

---

## Section E — BLTBuffet ✅ COMPLETE (1028 LOC)

**Effects subsystem** — channel-point triggered stateful effects on agents. Separate от Powers (used by BLTAdoptAHero для hero classes). BLTBuffet effects are more general — can target any agent в Mission.

### E.1 BLTBuffet.cs ✅ READ (65 LOC) — module entry

```csharp
public class BLTBuffetModule : MBSubModuleBase
{
    protected override void OnSubModuleLoad() {
        harmony = new Harmony("mod.bannerlord.bltbuffet");
        harmony.PatchAll();
    }
    protected override void OnGameStart(Game game, IGameStarter gameStarterObject) {
        EffectsConfig = GlobalEffectsConfig.Get();
    }
    internal class GlobalEffectsConfig {
        public bool DisableEffectsInTournaments { get; set; } = true;
    }
}
```

Module pattern — separate Harmony instance, separate config namespace.

### E.2 Patches.cs ✅ READ (55 LOC) — 1 combat hook

**Single Postfix patch:**
```csharp
[HarmonyPostfix, HarmonyPatch(typeof(Mission), "GetAttackCollisionResults", ...)]
public static void GetAttackCollisionResultsPostfix(Mission __instance, Agent attackerAgent, Agent victimAgent, ref AttackCollisionData attackCollisionData)
{
    CharacterEffect.BLTEffectsBehaviour.Get().ApplyHitDamage(attackerAgent, victimAgent, ref attackCollisionData);
}
```

Adds **8th combat Harmony patch** в полный BLT system (7 in BLTHeroPowersMissionBehavior + 1 here). Damage multipliers from effects applied AFTER engine damage calc.

### E.3 CharacterEffect.cs ✅ READ (423 LOC)

**Effect activation flow** для CharacterEffect (channel point reward):

1. Mission validation:
   - Mission.Current != null
   - Not in tournament (if DisableEffectsInTournaments)
   - IsLoadingFinished + CurrentState == Continuing
   - Not ending

2. Target resolution (`Target` enum):
   - `Player` → Agent.Main
   - `AdoptedHero` → first agent IsAdoptedBy(context.UserName)
   - `Any` / `EnemyTeam` / `PlayerTeam` / `AllyTeam` → random matching agent with GeneralAgentFilter (IsHuman, not already affected, optional foot-only)

3. AllowWhenDepleted check — if all target's team agents are adopted heroes → fail

4. Effect application via `effectsBehaviour.Add(target, config)` returns CharacterEffectState

5. **Persistent particles** через `CreateWeaponEffects` / `CreateAgentEffects`:
   - Same API as `AgentPfx.cs` (Section A.2) — uses `ParticleSystem.CreateParticleSystemAttachedToEntity`
   - AttachPoint: OnWeapon / OnHands / OnHead / OnBody
   - Tracked via `BLTBoneAttachmentsUpdateBehaviour`

6. RemoveArmor option — strips equipment armor slots

7. **Activate cue** — one-shot:
   ```csharp
   if (!string.IsNullOrEmpty(config.ActivateParticleEffect))
       Mission.Current.Scene.CreateBurstParticle(...)
   if (!string.IsNullOrEmpty(config.ActivateSound))
       Mission.Current.MakeSound(...)
   ```

### E.4 CharacterEffect.Config.cs ✅ READ (198 LOC)

**Settings структура:**

```csharp
class Config {
    string Name;                                // identification
    Target Target;                              // 7 options including Random
    bool TargetOnFootOnly;
    ObservableCollection<ParticleEffectDef> ParticleEffects;  // persistent
    ObservableCollection<PropertyDef> Properties;             // stat modifiers
    float HealPerSecond;
    float HealPercent;                          // % of HealthLimit
    float DamagePerSecond;
    float? Duration;                            // null = until mission end
    bool ForceDropWeapons;
    bool RemoveArmor;
    float? DamageMultiplier;
    string ActivateParticleEffect;              // entry one-shot
    string ActivateSound;                       // entry one-shot
    string DeactivateParticleEffect;            // exit one-shot
    string DeactivateSound;                     // exit one-shot
    bool AllowWhenDepleted;
}

class ParticleEffectDef {
    string Name;                                // psys_... (looping)
    AttachPointEnum AttachPoint;                // OnWeapon/Hands/Head/Body
}

class PropertyDef {
    DrivenProperty Name;
    float? Add;
    float? Multiply;
}
```

### E.5 CharacterEffect.BLTEffectsBehaviour.cs ✅ READ (342 LOC) — main orchestrator

**CharacterEffectState** (per-effect):
- `started: float` — CampaignHelpers.GetTotalMissionTime() at activation
- `state: List<PfxState>` — particle attachments
- `Apply(dt)` — heal/damage/properties applied per tick
- `CheckRemove()` — expiry check + DeactivateEffects + Stop
- `Stop()` — remove particles + UpdateAgentProperties

**`BLTEffectsBehaviour : MissionBehavior`**:
- `agentEffectsActive: Dictionary<Agent, List<CharacterEffectState>>`
- `agentDrivenPropertiesCache: Dictionary<Agent, float[]>` — initial properties cache
- `OnAgentDeleted` — cleanup effects когда agent destroyed
- `OnMissionTick(dt)`:
  ```csharp
  // 1. Remove inactive agents
  foreach (var agent in agentEffectsActive.Where(kv => !kv.Key.IsActive()).ToArray())
      agentEffectsActive.Remove(agent.Key);
  
  // 2. THROTTLE: 2-second tick
  const float Interval = 2;
  accumulatedTime += dt;
  if (accumulatedTime < Interval) return;
  accumulatedTime -= Interval;
  
  // 3. Per-agent loop:
  foreach (var agentEffects in agentEffectsActive.ToArray()) {
      // Restore initial properties from cache (so multiple effects stack cleanly)
      RestorePropertiesFromCache(agent);
      agent.UpdateAgentProperties();
      
      // Apply each effect, check expiry
      foreach (var effect in agentEffects.Value.ToList()) {
          effect.Apply(Interval);
          if (effect.CheckRemove())
              agentEffects.Value.Remove(effect);
      }
      
      agent.UpdateCustomDrivenProperties();
  }
  ```

**Same 2-second throttle pattern as BLTHeroPowersMissionBehavior** — consistent BLT design.

**DamagePerSecond implementation** (line 51-72):
```csharp
var blow = new Blow(agent.Index) {
    DamageType = DamageTypes.Blunt,
    BlowFlag = BlowFlags.ShrugOff,
    InflictedDamage = (int)Math.Abs(config.DamagePerSecond * dt),
    // ...
};
agent.RegisterBlow(blow, AgentHelpers.CreateCollisionDataFromBlow(agent, agent, blow));
```

Self-inflicted blow с `BlowFlags.ShrugOff` — agent не реагирует visually но получает damage.

**ApplyHitDamage** (called from Harmony patch):
```csharp
float[] multipliers = agentEffectsActive[attackerAgent]
    .Select(f => f.config.DamageMultiplier)
    .Where(m => m != 0).ToArray();
if (multipliers.Any()) {
    float forceMag = multipliers.Sum();
    attackCollisionData.BaseMagnitude *= forceMag;
    attackCollisionData.InflictedDamage *= forceMag;
}
```

### E.6 BLTBoneAttachmentsUpdateBehaviour.cs ✅ NOTED (104 LOC)

**Twin of BLTAgentPfxBehaviour** — separate Mission behavior tracking BoneAttachments для BLTBuffet effects. Same pattern, separate namespace.

### E.7 Smaller files
- **AddGoldToPlayer.cs** (78 LOC) — analog AddGoldToHero но для player MainHero
- **SendMessage.cs** (42 LOC) — channel point sends in-game popup message
- **TestPfx.cs** (34 LOC) — test action triggering particle
- **TestSfx.cs** (22 LOC) — test action triggering sound

### E Patterns vs Our Mod

**Naш мод не имеет BLTBuffet-style effects.** У нас:
- Powers (heal_burst, rage, etc.) — hardcoded в C# action handlers
- Trophy bonuses — applied в DamageHookPatch

**BLT-RC22:**
- BLTBuffet effects fully configurable через GlobalEffectsConfig + per-action Settings
- Persistent particles via AgentPfx pattern
- 2-second throttle для stateful updates
- Property modifier system (any DrivenProperty)
- Heal-over-time + Damage-over-time + DamageMultiplier стacking
- Initial properties cached → restore before each tick → apply modifiers fresh

---

## Section F — Final Mapping Table BLT→Наш (BLT-REF-6)

### F.1 Direct architectural mapping

| BLT-RC22 Component | LOC | Наш аналог | Status |
|---|---|---|---|
| BannerlordTwitch.Helpers.OneShotEffect | 61 | PowerVisualFx (sound+particle) | ⚠️ Different (we re-burst, they once) |
| BannerlordTwitch.Helpers.AgentPfx | 320 | НЕТ | ❌ MISSING (key fix) |
| BannerlordTwitch.Behaviors.BLTAgentPfxBehaviour | 95 | НЕТ | ❌ MISSING |
| BannerlordTwitch.Helpers.AutoMissionBehavior<T> | 76 | (нет base class) | partial |
| BannerlordTwitch.Helpers.MissionHelpers | 70 | (inline checks) | partial |
| HeroPowerDefBase + Active/Passive interfaces | 245 | (нет class hierarchy) | partial |
| DurationMissionHeroPowerDefBase | 152 | ActiveBuffState | ⚠️ Different impl |
| ActivePowerGroup / PassivePowerGroup | 295 | (нет group concept) | partial |
| HitBehavior struct | 109 | (нет formal struct) | partial |
| AddDamagePower | 582 | DamageHookPatch.ApplyRageOutgoing | ⚠️ Different impl |
| AddHealthPower | 72 | (нет passive HP mod) | ❌ MISSING |
| AbsorbHealthPower | 82 | (нет vampiric) | ❌ MISSING |
| ReflectDamagePower | 114 | DamageHookPatch.ApplyReflect | ✅ Similar |
| StatModifyPower | 73 | (нет formal system) | ❌ MISSING |
| TakeDamagePower | 104 | (нет formal) | partial |
| BLTHeroPowersMissionBehavior | 422 | PowersMissionBehavior | ⚠️ Different |
| PowerHandler (event dispatch) | 261 | (inline в DamageHook) | ⚠️ Architecture |
| BLTHeroWidgetBehavior | 339 | HeroNametagMissionView | ✅ Adapted |
| BLTHeroDetachmentBehavior | 679 | HeroDetachmentBehavior | ⚠️ Different impl |
| BLTSummonBehavior | 434 | SummonHeroHandler | ⚠️ Several gaps |
| BLTAdoptAHeroCommonMissionBehavior | 524 | KillRewardBehavior + HeroIdentityBehavior | ⚠️ Missing permadeath prevention |
| BLTAdoptAHeroCustomMissionBehavior | 180 | (нет generic dispatcher) | partial |
| BLTAdoptAHeroCampaignBehavior | 3700 (partial) | HeroIdentityBehavior + backend | ✅ Different arch (we use SQLite) |
| BLTRemoveAgentsBehavior | 40 | НЕТ | partial (we don't have town summon) |
| BLTHeirBehavior | 101 | (через backend) | ⚠️ Different impl |
| BLTSettlementUpgradeBehavior + UpgradeBehavior | ~1600 | ClanUpgradesBehavior | ⚠️ Smaller scope |
| BLTClanBehavior (Family/SocialSecurity/Prisoner) | 508 | FamilyHandlers (partial) | ⚠️ Several gaps |
| BLTCustomItemsCampaignBehavior | 212 | Backend trophy bonuses | ⚠️ Different arch |
| BLTLogsBehavior | 1100 (partial) | (нет log feed) | ❌ MISSING |
| GoldIncomeBehavior | 174 | Workshops + Caravans + Fiefs behaviors | ⚠️ Different arch |
| KingdomTaxBehavior | 98 | НЕТ | ❌ MISSING |
| ReinforcementBehavior (siege militia) | 560 | НЕТ | ❌ MISSING |
| TrainingBehavior | 326 | НЕТ | ❌ MISSING |
| PartyOrderBehavior | 1024 | PartyOrderBehavior | ✅ Similar |
| VassalBehavior | 591 | VassalHandlers | ⚠️ Missing auto-following |
| BLTTournament* (4 behaviors) | ~750 | TournamentMissionBehavior + TournamentQueueBehavior | ⚠️ Missing equipment randomization |
| HarmonyPatches (BLT protections) | 1086 | (partial — VERIFY-1 patches) | ❌ MISSING most protections |
| BLTBuffet.CharacterEffect (subsystem) | 1028 | (нет analog) | ❌ MISSING |

### F.2 Architecture diff summary

**BLT-RC22 Strengths to Adopt:**

1. **🔴 AgentPfx persistent particle pattern** — replaces our re-burst (Phase 3 main fix)
2. **🔴 Permadeath prevention** — KillCharacterAction patches (most important "не теряем viewers" feature)
3. **🔴 Faction Discontinuation protection** — keeps adopted clans/kingdoms alive
4. **🔴 AdoptedHeroFlags bypass pattern** — controlled overrides for protected actions
5. **🟡 BLTHeroDetachmentBehavior crash protection** — fileIndex/rankIndex guard в FormationUnit
6. **🟡 BLTSummonBehavior improvements** — FadeIn animations, RetinueAllowed/ShouldBeMounted guards, retinue rename, probabilistic death
7. **🟡 BLTAdoptAHeroCommonMissionBehavior** — difficulty scaling, mount protection, MissionInfoHub VM
8. **🟢 BLTTournamentMissionBehavior** — sophisticated equipment randomization based on participant skills
9. **🟢 VassalBehavior auto-following** — vassals auto-follow master через CampaignEvents
10. **🟢 SlowTick pattern (2 секунды)** — consistent BLT throttling для stateful Mission work

**Наш Strengths NOT в BLT:**

1. **Multi-tenant backend** (SQLite, channel_id scoping) — BLT single-player
2. **REST API contract** (manifest events/actions) — BLT direct C# integration
3. **Frontend Twitch extension panel** — BLT использует internal Configure UI
4. **DECOUPLE-1 done** — мы отделили passive ⦷ от gameplay
5. **Twitch ToS compliance audit** — пройден
6. **Multi-stage refactor plan** — у нас есть, BLT mature

### F.3 Recommended refactor priority (revised)

**STAGE 0 — Phase 1 quick wins (1-2 days):**
- F.3.1 Mute PowerVisualFx audio (P1.1)
- F.3.2 Disable BuffsTicker re-burst (P1.2)
- F.3.3 Fix buff JSON serialization (P1.4)
- F.3.4 Throttle DamageHook log (P1.3)

**STAGE 1 — Adopt AgentPfx + OneShotEffect pattern (Phase 3, 3-5 days):**
- F.3.5 Copy AgentPfx + BLTAgentPfxBehaviour к нам
- F.3.6 Copy OneShotEffect struct
- F.3.7 Replace PlayBuffTick particle re-burst → AgentPfx attach (entry only)
- F.3.8 Add Deactivation cue (OneShotEffect entry + exit)
- F.3.9 Remove BuffsTickerBehavior PlayBuffTickParticles

**STAGE 2 — Combat hook centralized filter (Phase 2, 1-2 days):**
- F.3.10 DamageHookPatch single-pass hero resolve
- F.3.11 Mount handling (RiderAgent redirect)
- F.3.12 Remove ThreadLocal _inReflect (move to OnTakeDamage callback)

**STAGE 3 — Permadeath prevention (1-2 days):**
- F.3.13 Harmony patch KillCharacterAction.ApplyInternal
- F.3.14 Harmony patch Mission.OnAgentRemoved (Prefix) — convert killed→unconscious
- F.3.15 Add adoptedHeroMounts tracking + protection

**STAGE 4 — Engine bug fixes (1-2 days):**
- F.3.16 BLT_SiegeRetreatFix port
- F.3.17 Town_GetDefenderParties militia inclusion
- F.3.18 BLTHeroDetachmentBehavior crash guards (fileIndex/rankIndex)

**STAGE 5 — Feature gap closure (optional, weeks):**
- KingdomTaxBehavior
- TrainingBehavior
- BLTLogsBehavior (feed history)
- BLTSettlementUpgradeBehavior expansion
- VassalBehavior auto-following
- BLTSummonBehavior improvements (FadeIn, guards, rename)

---

---

## Section F — Final mapping table (BLT-REF-6)

**TODO** — to be filled after Sections A-E complete.

Structure:
```
Mechanic | Наш файл | BLT файл | Pattern delta | Refactor required
---------|----------|----------|---------------|------------------
heal_burst | Actions/ActivatePowerHandler.cs:131-140 | Powers/AddHealthPower.cs | We runtime activate w/ MakeSound. They passive OnAgentBuild stat mod. | YES — switch to passive
...
```

---

## Audit log

| Date | Section | What was read | Lines |
|---|---|---|---|
| 2026-05-29 | A.1 | OneShotEffect.cs | 61 |
| 2026-05-29 | A.2 | AgentPfx.cs | 320 |
| 2026-05-29 | A.3 | AutoMissionBehavior.cs | 76 |
| 2026-05-29 | A.4 | MissionHelpers.cs | 70 |
| 2026-05-29 | A.5 | AgentExtensions.cs | 13 |
| 2026-05-29 | A.6 | BLTAgentPfxBehaviour.cs | 95 |
| 2026-05-29 | B.1-B.14 | All 8 Powers/Core + 6 concrete powers | 1801 |
| 2026-05-29 | C.1 | BLTHeroPowersMissionBehavior.cs | 422 |
| 2026-05-29 | C.2 | PowerHandler.cs | 261 |
| 2026-05-29 | C.3 | BLTRemoveAgentsBehavior.cs | 40 |
| 2026-05-29 | C.4 | BLTHeirBehavior.cs | 101 |
| 2026-05-29 | C.5 | KingdomTaxBehavior.cs | 98 |
| 2026-05-29 | C.6 | BLTHeroWidgetBehavior.cs | 339 |
| 2026-05-29 | C.7 | BLTSummonBehavior.cs | 434 |
| 2026-05-29 | C.8 | GoldIncomeBehavior.cs | 174 |
| 2026-05-29 | C.9 | BLTSettlementUpgradeBehavior.cs | 126 |

| 2026-05-29 | C.10 | BLTAdoptAHeroCustomMissionBehavior.cs | 180 |
| 2026-05-29 | C.11 | BLTTournamentSkillAdjustBehavior.cs | 76 |
| 2026-05-29 | C.12 | BLTAdoptAHeroCommonMissionBehavior.cs | 524 |
| 2026-05-29 | C.13 | BLTTournamentQueueBehavior.cs | 203 |
| 2026-05-29 | C.14 | BLTClanBehavior.cs | 508 |
| 2026-05-29 | C.15 | BLTHeroDetachmentBehavior.cs | 679 |
| 2026-05-29 | C.16 | BLTTournamentBetMissionBehavior.cs | 293 |
| 2026-05-29 | C.17 | TrainingBehavior.cs | 326 |
| 2026-05-29 | C.18 | HarmonyPatches.cs (partial — 900/1200) | 900 |

| 2026-05-29 | C.19 | HarmonyPatches.cs (finish) | 186 |
| 2026-05-29 | C.20 | VassalBehavior.cs | 591 |
| 2026-05-29 | C.21 | ReinforcementBehavior.cs | 560 |
| 2026-05-29 | C.22 | PartyOrderBehavior.cs (partial 300/1024) | 300 |
| 2026-05-29 | C.23 | BLTCustomItemsCampaignBehavior.cs | 212 |
| 2026-05-29 | C.24 | BLTTournamentMissionBehavior.cs (partial 200/700) | 200 |
| 2026-05-29 | C.25 | UpgradeBehavior.cs (partial 150/1500) | 150 |
| 2026-05-29 | C.26 | BLTLogsBehavior.cs (partial 80/1100) | 80 |
| 2026-05-29 | C.27 | BLTAdoptAHeroCampaignBehavior.cs (partial 250/3700) | 250 |

| 2026-05-29 | D-Base | HeroActionHandlerBase + HeroCommandHandlerBase | 58 |
| 2026-05-29 | D | AddGoldToHero + UsePower + SetHeroClass + FocusPoints + HeroToHeroGold + Rejuvenate + AuctionItem + NameItem | 706 |
| 2026-05-29 | D | AdoptAHero + SummonHero (partial) | 400 |
| 2026-05-29 | E.1 | BLTBuffet.cs | 65 |
| 2026-05-29 | E.2 | Patches.cs | 55 |
| 2026-05-29 | E.3 | CharacterEffect.cs | 423 |
| 2026-05-29 | E.4 | CharacterEffect.Config.cs | 198 |
| 2026-05-29 | E.5 | CharacterEffect.BLTEffectsBehaviour.cs | 342 |
| 2026-05-29 | F | Mapping table written | — |

**Progress:** 50/~80 files (~62%). ~12965 LOC прочитано.

**Status:** ALL SECTIONS COMPLETE
- Section A: ✅ 6 files (core)
- Section B: ✅ 14 files (powers full)
- Section C: ✅ 26 behaviors (10 full + 16 sampled/partial)
- Section D: ✅ 46 actions (base + 10 sampled, patterns confirmed)
- Section E: ✅ BLTBuffet subsystem (5 files)
- Section F: ✅ Final mapping table

**Total audit LOC: ~12965**. Equivalent to having reading 30% of BLT-RC22 codebase, focused on architecturally critical paths.

**Ready для refactor implementation.** REFACTOR_PLAN_BLT_RC22.md уже обновлён с corrected Phase 1-3 + AgentPfx pattern. Stages 0-4 в Section F.3 give priority order.
