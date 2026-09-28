# Refactor Plan — BLT-RC22 patterns adoption

**Дата:** 2026-05-29
**Контекст:** 6 крашей за 1 день (2026-05-28), большинство FMOD pool exhaustion
**База сравнения:** [Randomchair22/Bannerlord-Twitch 5.2.4](https://github.com/Randomchair22/Bannerlord-Twitch/releases/tag/5.2.4) (target: Bannerlord 1.3.15 — same as нас)

---

## Executive Summary

**Цель:** Адаптировать архитектурные patterns BLT-RC22 к нашему моду **без полного rebuild**.
**Не цель:** Откатить features. Backend и frontend остаются нетронутыми.

**Причина:** Code review BLT-RC22 показал **2** ключевых архитектурных решения (исправлено 2026-05-29 после full local audit), которые делают их мод стабильнее в 1.3.15:

1. **Powers с persistent AgentPfx + OneShotEffect entry/exit cues** — НЕ re-burst каждые 2с. Active powers имеют `ActivateEffect.Trigger()` (start) + `AgentPfx.attach` (persistent для duration) + `DeactivateEffect.Trigger()` (end). Sound calls: 2 за активацию (start+end), не 16 (start + 15 re-bursts).
   - **AgentPfx** wraps `ParticleSystem.CreateParticleSystemAttachedToEntity` (looping particle, attached к bone) — auto-cleanup при `OnAgentDeleted` via `BLTAgentPfxBehaviour`.
   - **OneShotEffect** = struct {ParticleEffect, Sound} с `Trigger()` который дёргает `Mission.MakeSound` + `Scene.CreateBurstParticle` ОДИН РАЗ.
2. **Centralized filter в combat hook** — единственный hero resolve в начале, early return для blow без adopted heroes. Не дороже наш distributed filter (5 lookups vs 2), но cleaner architecture.

**🔴 Прошлые ОБОБЩЕНИЯ которые оказались НЕВЕРНЫМИ:**

- ❌ "Все BLT powers это passive stat modifiers" — реальность: ОБА есть (`IHeroPowerPassive` + `IHeroPowerActive`)
- ❌ "BLT использует engine-native MissionBehavior events вместо Harmony" — реальность: BLT имеет 7 Harmony patches на combat hot path (RegisterBlow, MeleeHitCallback, MissileHitCallback, etc.), мы имеем 1. Их БОЛЬШЕ.
- ❌ "SlowTick = главный throttling механизм" — реальность: и MissionTick (per-frame) и SlowTick (2s) оба дёргаются. SlowTick это **дополнительный** event, не замена per-frame.

У нас обратное:
- `PowerVisualFx.PlayActivation` дёргает `MakeSound` на каждую активацию (8+ powers × N viewers × N активаций)
- `BuffsTickerBehavior` каждые 2 секунды дёргает `PlayBuffTick` → `CreateBurstParticle` для всех активных buffs
- `DamageHookPatch` это **Harmony Prefix** на `Mission.RegisterBlow` — выполняется на **каждый blow в игре** (тысячи раз/сек в большой битве, включая mob vs mob)

---

## Что мы НЕ трогаем

✅ **Backend** (Расширение/backend) — multi-tenant, 58 миграций, 30+ endpoints, deployed. Работает.
✅ **Frontend** (Расширение/frontend) — currency UI, settlements dropdown, family/clan/kingdom panes. Работает.
✅ **Mod's high-level features** — clans, kingdoms, marriage, workshops, caravans, fiefs, vassals, diplomacy, party orders, heritage, tournaments. ВСЁ остаётся.
✅ **Manifest events/actions** — не меняем contract с backend.
✅ **Save compatibility** — refactor не trogает HeroIdentityBehavior persistence.

## Что мы трогаем

🔧 **3 файла в моде:**
1. `BannerlordLink/src/Util/PowerVisualFx.cs` (220 строк) — оптимизация sound usage
2. `BannerlordLink/src/Behaviors/PowersMissionBehavior.cs` (286 строк) — throttling, retire BuffsTickerBehavior particle pulse
3. `BannerlordLink/src/Patches/DamageHookPatch.cs` (370 строк) — рефакторнуть в MissionBehavior callbacks (Phase 2)
4. `BannerlordLink/src/Actions/ActivatePowerHandler.cs` (441 строк) — для phase 3 переход в passive pattern

---

## Phase 1 — Quick wins (1-2 дня, низкий риск)

**Цель:** Снизить FMOD pool pressure на 40-60% без архитектурных изменений.
**Эффект:** Время до краша должно вырасти с ~25 мин до ~50-60 мин активного боя.
**Риск:** Низкий. Все изменения — это `if (FEATURE_FLAG) skip` или `interval × 3`.

### P1.1 — Mute PowerVisualFx audio (BLT pattern)

**Файл:** `BannerlordLink/src/Util/PowerVisualFx.cs:199-218`

**Сейчас:** `PlaySound()` дёргается из `PlayActivation()` для каждого power (heal_burst/rage/shield_break_burst/...).

**Изменение:**
- Add `public static bool AudioEnabled = false;` — config flag (default OFF)
- `PlaySound()` first-line: `if (!AudioEnabled) return;`
- Sound paths остаются в CONFIG dict для будущего re-enable

**Что теряем:** Sound effect при активации powers. Popup и particle остаются.
**Что не теряем:** Vanilla combat sounds (sword swings, shield breaks от engine) — engine их сам играет.

**Affected powers (наши, не engine):** heal_burst, shield_break_burst, rage, retribution_toggle, poison_dot, disarm_burst, berserker_charge.

**Estimated FMOD reduction:** ~5-10% (наш direct contribution).

### P1.2 — Disable BuffsTicker re-burst particle

**Файл:** `BannerlordLink/src/Behaviors/PowersMissionBehavior.cs:170-181`

**Сейчас:** `PlayBuffTickParticles()` каждые `BUFF_TICK_INTERVAL=2.0s` для каждого активного buff'а дёргает `PowerVisualFx.PlayBuffTick(agent, powerKey)` → создаёт burst particle.

**Изменение:**
- Add `public const bool BUFF_TICK_PARTICLES_ENABLED = false;` в PowersMissionBehavior
- Wrap `PlayBuffTickParticles()` call: `if (!BUFF_TICK_PARTICLES_ENABLED) return;`
- `RemoveExpired` логика остаётся (это persistent state, не particle)

**Что теряем:** Подсветка зрителя в Mission что у него активен rage/retribution. Visible эффект только в начале активации.
**Что не теряем:** Сам buff (damage multi / reflect) продолжает работать. ActiveBuffState не трогаем.

**Estimated FMOD reduction:** ~5-10% (наш direct).

### P1.3 — Throttle DamageHook logging

**Файл:** `BannerlordLink/src/Patches/DamageHookPatch.cs`

**Сейчас:** На каждый blow логируем `[DamageHook] processed N blows total` каждые 200 blows. Это **stdout writes** в IO subsystem — не FMOD напрямую, но создаёт contention.

**Изменение:**
- Increase interval с 200 → 1000 blows
- Conditional verbose log only if `verbose.flag` enabled

**Affected:** Только log spam, не functional change.
**Estimated effect:** Minor (5% IO contention).

### P1.4 — Fix buff JSON serialization

**Файл:** `BannerlordLink/src/Net/ActiveBuffState.cs:162-182`

**Сейчас:** Ручная сборка JSON через `string.Format` с `:F3` для double. Newtonsoft потом парсит для validation и падает на "Path 'value', position 72" с "Unexpected character F".

**Изменение:**
- Заменить ручной `string.Format` на `JsonConvert.SerializeObject(new { username, power_key, duration_s, value })`
- Newtonsoft гарантирует корректный output

**Что фиксит:** `buff.activated` / `buff.expired` events перестают rejection'иться локально → доходят до backend → frontend HUD timer работает.
**Не связан с крашами**, но separate bug который видно в логах.

### P1 Deliverables
- 3 PRs (один за изменение для cleanly bisection если что-то ломается)
- Build + deploy + monitor 1-2 дня
- Метрика успеха: время до краша в comparable session (1+ час active combat)

---

## Phase 2 — Combat hook centralized filter (1-2 дня, низкий риск) [REVISED 2026-05-29]

**🔴 ВАЖНОЕ ИСПРАВЛЕНИЕ:** Изначально Phase 2 был сформулирован как "перенести Harmony patch на MissionBehavior native event". **Это было неправильно.** BLT-RC22 **ТОЖЕ** использует Harmony patch на `Mission.RegisterBlow` (см. `reference/BLT_RC22/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTHeroPowersMissionBehavior.cs:320` + 6 других combat hook patches). У них 7 combat Harmony patches, у нас 1.

**Реальная архитектурная разница:** не "Harmony vs native events", а **где и как делается filter**.

**Цель:** Адаптировать BLT centralized-filter pattern в наш `DamageHookPatch`.
**Эффект:** Уменьшить от 5 lookups → 2 lookups per blow (для blow без adopted heroes). Минорная CPU экономия. **НЕ FMOD-related.**
**Риск:** Низкий. Логика логически идентична, только refactor structure.

### P2.1 — Single-pass hero resolve

**Файл:** `BannerlordLink/src/Patches/DamageHookPatch.cs:58-95`

**Сейчас (distributed lookup):**
```csharp
public static void Prefix(Agent attacker, Agent victim, ref Blow b, ref AttackCollisionData collisionData) {
    if (_inReflect.Value) return;
    if (attacker == null || victim == null) return;
    if (attacker == victim) return;
    if (b.InflictedDamage <= 0) return;

    ApplyIgnoreArmor(attacker, ...);     // GetAdoptedUsername inside
    ApplyRageOutgoing(attacker, ...);    // GetAdoptedUsername inside
    ApplyTrophyBonuses(attacker, victim, ...);  // 2 lookups inside
    ApplyReflect(attacker, victim, ...);  // GetAdoptedUsername inside
}
```

**После (centralized BLT pattern):**
```csharp
public static void Prefix(Agent attacker, Agent victim, ref Blow b, ref AttackCollisionData collisionData) {
    if (_inReflect.Value) return;
    if (attacker == null || victim == null) return;
    if (attacker == victim) return;
    if (b.InflictedDamage <= 0) return;

    // Mirror BLT: PowerHandler.cs:225-237 centralized hero resolve
    string attackerUser = (attacker.IsMount ? attacker.RiderAgent : attacker)?.GetAdoptedUsername();
    string victimUser   = (victim.IsMount   ? victim.RiderAgent   : victim)?.GetAdoptedUsername();
    if (attackerUser == null && victimUser == null) return;  // EARLY EXIT

    if (attackerUser != null) {
        ApplyIgnoreArmor(attacker, attackerUser, ref b, ref collisionData);
        ApplyRageOutgoing(attacker, attackerUser, ref b, ref collisionData);
    }
    if (attackerUser != null || victimUser != null)
        ApplyTrophyBonuses(attacker, victim, attackerUser, victimUser, ref b, ref collisionData);
    if (victimUser != null)
        ApplyReflect(attacker, victim, victimUser, ref b, ref collisionData);
}
```

### P2.2 — Update Apply* signatures

Каждый `Apply*` method получает уже-resolved username как parameter, не делает lookup сам.

### P2.3 — Add Mount handling

**Pattern из BLT (PowerHandler.cs:187-189, 228-233):**
```csharp
agent?.IsMount == true ? agent.RiderAgent?.GetAdoptedHero() : agent?.GetAdoptedHero()
```

Если attacker — лошадь (трамплинг), redirect к её всаднику. Мы этого не делаем сейчас — упускаем damage modifications для blow'ов где зритель верхом.

### P2 Deliverables
- 1 PR (refactor одного файла)
- Time: 1-2 дня
- Метрика успеха: zero functional regression, ~30% сокращение lookups в большой битве

### P2 Risks
- **Mount handling может изменить behavior существующих setups** — viewers которые играют верхом теперь получают rage damage когда лошадь бьёт. Это **bug fix** (раньше теряли buff), но **functional change**.
- **Нет FMOD impact** — это покупка efficiency, не stability. **Не приоритет если crashes is цель.**

---

## Phase 3 — AgentPfx pattern для active powers (3-5 дней, низкий риск)

**[CORRECTED 2026-05-29]:** Изначально Phase 3 был сформулирован как "переход active → permanent passive". Это было неточно. BLT-RC22 имеет **оба** типа powers: `IHeroPowerPassive` (passive stat mods) **и** `IHeroPowerActive` (active с длительностью, timed buffs). Разница не в active vs passive, а в **HOW active реализован**.

**Цель:** Заменить наш `BuffsTickerBehavior` re-burst pattern на BLT-style `AgentPfx + OneShotEffect` pattern. **Без user-facing UX change.**
**Эффект:** ~94% reduction particle calls во время duration активного power'а.
**Риск:** Низкий. Не трогает backend, frontend, save format, viewer UX.

### Архитектура BLT-RC22 для active powers

```
IHeroPowerActive (interface)
└── DurationMissionHeroPowerDefBase (timed active base class)
    ├── PowerDurationSeconds         ← длительность buff'а
    ├── ActivateEffect: OneShotEffect ← Pfx+Sfx при START (1 раз)
    ├── DeactivateEffect: OneShotEffect ← Pfx+Sfx при END (1 раз)
    └── PfxList: AgentPfx[]           ← persistent particles attached to agent
                                       (созданы 1 раз, играют ВСЮ duration)
```

**Lifecycle активной power'ы в BLT:**
1. `Activate()` → `ActivateEffect.Trigger()` = 1 sound + 1 particle burst (entry cue)
2. AgentPfx attached к agent → persistent particle effect, **не recreated**
3. Duration N сек → **0 sound calls, 0 new particle calls**
4. Expire/death/mission_over → `pfx.Stop()` + `DeactivateEffect.Trigger()` = 1 sound + 1 particle burst (exit cue)

**Итог BLT за 30s rage:** 2 sound calls + 1 persistent particle attach.

### Наша текущая архитектура

```
PowerVisualFx
├── PlayActivation()    — MakeSound + CreateBurstParticle (1 раз при start)
├── PlayBuffTick()      — CreateBurstParticle (вызывается каждые 2с из BuffsTickerBehavior)
└── (deactivation cue)  — нет
```

**Lifecycle нашего active power:**
1. `power.activate` → `PlayActivation()` = 1 sound + 1 burst
2. Duration 30 сек → `BuffsTickerBehavior` каждые 2 сек → `PlayBuffTick` → **новый burst particle**
3. Expire → silent (нет deactivation cue)

**Итог за 30s rage:** 1 sound + **16 particle calls** (1 entry + 15 re-bursts).

### Comparison (per 30s rage activation)

| Метрика | BLT-RC22 | Наш мод | Разница |
|---|---|---|---|
| Sound calls | 2 | 1 | мы fewer |
| Particle calls | 1 (attach) | 16 (1 + 15 re-burst) | **BLT 16× меньше** |
| Persistent visible effect | Да (AgentPfx all 30s) | Нет (burst исчезает) | BLT лучше UX |
| Deactivation cue | Sound + particle | Нет | BLT лучше UX |

### P3.1 — Создать OneShotEffect-style helper

**Новый файл:** `BannerlordLink/src/Util/OneShotEffect.cs`

```csharp
public class OneShotEffect {
    public string ParticleName;   // psys_...
    public string SoundEventPath; // event:/...
    public void Trigger(Agent agent) {
        if (agent == null) return;
        // PlayParticle + PlaySound в одном вызове, properly guarded
    }
}
```

Pattern скопирован из BLT-RC22 `AddDamagePower.cs:ApplyShatterShieldChance` где используется `OneShotEffect.Trigger("psys_game_shield_break", "event:/mission/combat/shield/broken", ...)`.

### P3.2 — Replace BuffsTicker.PlayBuffTickParticles с AgentPfx attach

**Файл:** `BannerlordLink/src/Util/PowerVisualFx.cs:99-144` (PlayActivation)

**Сейчас:**
```csharp
public static void PlayActivation(Agent agent, string powerKey, ...) {
    // popup
    PlayParticle(cfg.ParticleName, frame);  // CreateBurstParticle (one-shot)
    PlaySound(cfg.SoundEventPath, frame, agent);
}
```

**После:**
```csharp
public static AgentPfx PlayActivation(Agent agent, string powerKey, ...) {
    // popup
    activateEffect.Trigger(agent);          // 1 sound + 1 burst (entry cue)
    var pfx = AttachPersistentParticle(agent, cfg.ParticleName);
    return pfx;  // caller сохраняет, чтобы Stop() при expire
}
```

`AttachPersistentParticle` использует engine API (точная methodология — нужно research):
- `agent.AgentVisuals.AddParticle(...)` или
- `Mission.Scene.AddBurstParticle(loopCount=infinite, frame)` или
- pure `AgentPfx` class из engine

**Research нужен:** какой именно engine API для persistent particle attached to agent в 1.3.15. BLT использует `AgentPfx` class — нужно проверить namespace и API.

### P3.3 — ActiveBuffState callback на expire → PlayDeactivation

**Файл:** `BannerlordLink/src/Net/ActiveBuffState.cs:78-103` (RemoveExpired)

Сейчас `RemoveExpired()` уже возвращает `List<(username, powerKey, value)>`. Caller (PowersMissionBehavior) дёргает уборку.

**Изменение:**
- При expire вызывать `PowerVisualFx.PlayDeactivation(agent, powerKey)` — играет deactivateEffect (1 sound + 1 burst exit cue) + останавливает AgentPfx

### P3.4 — Удалить BuffsTicker re-burst

**Файл:** `BannerlordLink/src/Behaviors/PowersMissionBehavior.cs:170-181`

Метод `PlayBuffTickParticles()` **удалить полностью** (или оставить как dead code с comment).

**Что остаётся:** DoT damage tick (через `ActiveBuffState.SnapshotDotTargets` + apply blow к target). Это логическая операция, не визуальная.

### P3.5 — Storage AgentPfx handles

**Новый dict в PowersMissionBehavior:** `Dictionary<string, AgentPfx> _activeParticles`
- Ключ: `username + "/" + powerKey`
- На Activate: сохранили pfx handle
- На Expire/AgentDeath/MissionOver: dequeue + `pfx.Stop()`

### P3 Deliverables
- 2-3 PRs:
  - PR1: OneShotEffect helper + PowerVisualFx refactor
  - PR2: BuffsTicker re-burst removal + AgentPfx storage
  - PR3: Deactivation cues
- Time: 3-5 дней
- Метрика успеха: 0 `CreateBurstParticle` calls после initial activation, время до FMOD краша вырастает x2-3

### P3 Risks
- **`AgentPfx` engine API в 1.3.15** — нужно research/spike. BLT использует, значит есть, но точный namespace нужно verify.
- **Persistent particle на agent после смерти** — нужно cleanup при agent.OnDeath, иначе particle висит над трупом.
- **Mission end cleanup** — все active AgentPfx нужно `Stop()` при `OnMissionRestart` / `OnEndMission`.

### P3 НЕ меняет
- ✅ User clicks "Активировать rage" — то же самое
- ✅ Платёж разовый за каждую активацию — то же
- ✅ 30 секунд buff duration — то же
- ✅ Backend events `buff.activated`/`buff.expired` — те же
- ✅ Frontend buttons — те же
- ✅ Cooldowns — те же
- ✅ UX feel — **улучшается** (persistent particle vs disappearing burst, + deactivation cue)

---

## Phase 4 — Mission-aware throttling (optional, 3-5 дней)

Если после Phase 1+2 краши всё ещё возникают в эпических битвах (1+ час).

### P4.1 — Mission-blow counter
- Behavior tracks `_totalBlowsThisMission`
- After 10,000 blows → broadcast in-game warning "Бой долгий, FMOD pool risk"
- Optional: streamer hotkey для force-end mission

### P4.2 — Agent count cap для retinue
- Если `Mission.Current.Agents.Count > 300` → новые retinue spawns refuse'ятся
- Освобождает FMOD pool для основных combat sounds

### P4.3 — Per-viewer cooldown enforcement
- 10s cooldown per viewer на любые actions involving spawn/sound
- Backend enforces, mod ignores actions без proper cooldown

---

## Что НЕ делаем (architectural debt но не приоритет)

❌ **Полный rebuild с BLT-RC22 как base.** BLT не имеет нашего backend integration, multi-tenant, и 50%+ features (workshops/caravans/fiefs/vassals/diplomacy/marriage). Rebuild = 2-3 месяца + потеря features.

❌ **Upgrade на 1.4.5.** Bannerlord 1.4.5 не fix'ит FMOD. Major version jump = high risk for our Harmony patches. Wait minimum 4 weeks для community feedback.

❌ **Adopt BLT codebase как dependency.** BLT licensed LGPL-2.1 — потребует disclosure нашего кода если linked.

---

## Decision Matrix [revised 2026-05-29 after BLT-REF-1+C audit]

| Что хочется | Phase 1 | Phase 1+3 | Phase 1+3+2 |
|---|---|---|---|
| Меньше FMOD pressure | -40% (mute audio, disable re-burst) | -85% (+ AgentPfx persistent) | -85% (+2 не меняет FMOD) |
| Время до краша (active battle) | 50 мин | 2-3 часа | 2-3 часа |
| Время работы | 1-2 дня | + 3-5 дней (Phase 3) | + 1-2 дня (Phase 2 sleek) |
| Risk сломать features | Низкий | Низкий (research engine API) | Низкий |
| Backend changes | 0 | 0 | 0 |
| Frontend changes | 0 | 0 | 0 |
| User-facing UX change | sound off (P1.1) | improvement (persistent pfx + deactivation cue) | bug fix (mount handling) |
| Кол-во PRs | 4 | 6-7 | 7-8 |
| Save compatibility | ✓ | ✓ | ✓ |

**Phase priority based on FMOD impact:** Phase 1 → Phase 3 → Phase 2.
**Phase 2 имеет ZERO FMOD impact** — это efficiency cleanup, не crash mitigation. Делать ПОСЛЕ Phase 1+3.

---

## Recommended Path

**1. Сначала Phase 1.4 (buff JSON fix)** — 30 минут, fix явного bug который маскирует наши events на backend.

**2. Затем Phase 1.1-1.3** — выходные. Mute PowerVisualFx audio + disable BuffsTicker particle + throttle DamageHook log. Deploy. Monitor 1-2 длинных stream сессии.

**3. Если Phase 1 не даёт стабильность** → Phase 2 (DamageHook refactor). Это уже неделя работы и средний риск, но architectural fix.

**4. Phase 3 — только если** Phase 1+2 не хватило. Это серьёзный UX change.

**5. Phase 4 — fallback** если все остальное не помогло.

---

## Open Questions (нужны ответы перед стартом)

1. **Audio off для всех powers или только heavy?** Можно оставить heal_burst sound (light), а shield_break_burst и disarm_burst — mute (heavy).
2. **BuffsTicker — отключить полностью или сделать interval=10s?** 10s reduces 80% load без полной потери visual feedback.
3. **Phase 2 viability:** есть ли engine API для blow modification из MissionBehavior? Нужно тест/spike.
4. **Phase 3 viewer communication:** как объяснить что rage теперь passive purchase не timed buff?

---

## Sources

- [BLT-RC22 5.2.4 release](https://github.com/Randomchair22/Bannerlord-Twitch/releases/tag/5.2.4)
- [BLTHeroPowersMissionBehavior.cs](https://github.com/Randomchair22/Bannerlord-Twitch/blob/5.2.4/BannerlordTwitch/BLTAdoptAHero/Behaviors/BLTHeroPowersMissionBehavior.cs) — SlowTick pattern
- [PowerHandler.cs](https://github.com/Randomchair22/Bannerlord-Twitch/blob/5.2.4/BannerlordTwitch/BLTAdoptAHero/Behaviors/PowerHandler.cs) — event-driven dispatch, 0 audio
- [AddHealthPower.cs](https://github.com/Randomchair22/Bannerlord-Twitch/blob/5.2.4/BannerlordTwitch/BLTAdoptAHero/Powers/AddHealthPower.cs) — passive HP modifier
- [AddDamagePower.cs](https://github.com/Randomchair22/Bannerlord-Twitch/blob/5.2.4/BannerlordTwitch/BLTAdoptAHero/Powers/AddDamagePower.cs) — passive damage modifier
- [HarmonyPatches.cs](https://github.com/Randomchair22/Bannerlord-Twitch/blob/5.2.4/BannerlordTwitch/BLTAdoptAHero/Behaviors/HarmonyPatches.cs) — 0 combat hooks
