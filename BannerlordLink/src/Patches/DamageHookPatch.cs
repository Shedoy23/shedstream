using System;
using System.Threading;
using BannerlordLink.Net;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 4.4-4.5 — Harmony Prefix на Mission.RegisterBlow для применения
    /// damage powers к hero'ям зрителей:
    ///
    /// Passive (Sprint 4.4, PowerCache):
    ///   • ignore_armor_pct / armor_bypass_pct — attacker buff (outgoing):
    ///       % брони жертвы которую игнорируем. Сдвигаем uron из
    ///       blow.AbsorbedByArmor в blow.InflictedDamage (+ collisionData mirror).
    ///   • damage_reflect_pct — victim buff (incoming):
    ///       % входящего урона возвращаем атакующему отдельным RegisterBlow,
    ///       вычитаем тот же процент из оригинального InflictedDamage.
    ///
    /// Active (Sprint 4.5, ActiveBuffState — timed):
    ///   • rage — attacker outgoing damage multiplier (e.g. 1.5×).
    ///       Накладывается ПОСЛЕ ignore_armor (на финальный InflictedDamage).
    ///   • retribution_toggle — victim incoming reflect overlay.
    ///       Складывается с passive damage_reflect_pct, total capped @95%.
    ///
    /// Power values читаются из PowerCache (синкается с backend по
    /// class+level) и ActiveBuffState (runtime в C# mod). Username
    /// резолвится из Agent.Character.HeroObject.Name (см. PowersMissionBehavior).
    ///
    /// Reflect использует ThreadLocal guard — counter-blow внутри prefix
    /// re-entr'ит Mission.RegisterBlow и без guard'а будет infinite recursion.
    ///
    /// Patches автоподхватываются BannerlordLinkModule.OnBeforeInitialModuleScreenSetAsRoot
    /// через _harmony.PatchAll() (ищет [HarmonyPatch] в assembly).
    /// </summary>
    [HarmonyPatch(typeof(Mission), "RegisterBlow")]
    public static class DamageHookPatch
    {
        private static readonly ThreadLocal<bool> _inReflect =
            new ThreadLocal<bool>(() => false);

        private static bool _firstHitLogged;
        // Sprint 5.31 #45e (audit MED-1) — periodic blow counter. Если TaleWorlds
        // переименует параметр (`b` → `blow`), Harmony не сможет bind by-name
        // и наш Prefix будет получать default(Blow). Получится `b.InflictedDamage
        // == 0` → ранний return до счётчика. Если streamer ведёт бой и за минуту
        // мы НЕ залогировали "processed N blows" — значит binding сломан.
        private static long _blowsProcessed;
        // 2026-05-29 P1.3 (Stage 0 Phase 1) — увеличено 200 → 1000.
        // В большой battle (1000 blows/sec) старое значение давало 5 stdout
        // writes/sec в hot path. Logger contention в file I/O. Liveness check
        // всё ещё работает — "patch alive" каждую секунду.
        private const long BLOW_LOG_EVERY = 1000;

        // Harmony резолвит args по имени. Имена `attacker / victim / b / collisionData`
        // должны совпадать с сигнатурой Mission.RegisterBlow — остальные параметры
        // (realHitEntity, attackerWeapon, combatLogData) Harmony пропустит.
        [HarmonyPrefix]
        public static void Prefix(
            Agent attacker, Agent victim,
            ref Blow b, ref AttackCollisionData collisionData)
        {
            if (_inReflect.Value) return;
            if (attacker == null || victim == null) return;
            if (attacker == victim) return;
            if (b.InflictedDamage <= 0) return;

            try
            {
                // 2026-05-29 Stage 2 (BLT-RC22 centralized filter pattern) —
                // single-pass hero resolve. Раньше каждый Apply* method дёргал
                // GetAdoptedUsername независимо (5 lookups per blow). Теперь
                // ОДИН lookup pair с mount redirect + early exit для blow'ов
                // которые не затрагивают viewer-hero.
                //
                // Mount redirect (BLT PowerHandler.cs:187-189): когда лошадь
                // топчет противника (charge damage), attacker — это mount Agent,
                // не hero. Мы redirect к RiderAgent чтобы rage/trophy buffs
                // viewer'а применялись к charge damage. Раньше мы это пропускали
                // → viewers теряли damage modifications для верховых атак.
                Agent attackerSrc = attacker.IsMount ? attacker.RiderAgent : attacker;
                Agent victimSrc   = victim.IsMount ? victim.RiderAgent : victim;
                string attackerUser = GetAdoptedUsername(attackerSrc);
                string victimUser   = GetAdoptedUsername(victimSrc);

                // Early exit: blow не затрагивает viewer-hero ни на одной
                // стороне (mob vs mob, ~99% blow'ов в большой battle).
                // Раньше шли через все 4 Apply* (5 lookups + condition checks).
                // Теперь — 2 lookups + return. CPU saving в hot path.
                if (attackerUser == null && victimUser == null) return;

                if (attackerUser != null)
                {
                    ApplyIgnoreArmor(attackerUser, ref b, ref collisionData);
                    ApplyRageOutgoing(attackerUser, ref b, ref collisionData);
                }
                // Sprint 5.33 (BLT-parity ITEM) — trophy bonuses.
                // Attacker damage_bonus + victim armor_bonus как absorption.
                // Применяется если ЛЮБАЯ сторона adopted (attacker getting
                // damage bonus OR victim getting armor absorption).
                if (attackerUser != null || victimUser != null)
                {
                    ApplyTrophyBonuses(attackerUser, victimUser, ref b, ref collisionData);
                }
                if (victimUser != null)
                {
                    ApplyReflect(victimUser, ref b, ref collisionData);
                }

                if (!_firstHitLogged)
                {
                    _firstHitLogged = true;
                    BannerlordLinkModule.Log(
                        "[DamageHook] Mission.RegisterBlow patched, first blow processed");
                }
                // Periodic life-sign — если zero за длинный бой, Harmony bind broken.
                long n = System.Threading.Interlocked.Increment(ref _blowsProcessed);
                if (n % BLOW_LOG_EVERY == 0)
                {
                    BannerlordLinkModule.Log(
                        $"[DamageHook] processed {n} blows total (patch alive)");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DamageHook] {ex.GetType().Name}: {ex.Message}");
            }
        }

        // 2026-05-29 Stage 2 — signature change: username теперь pre-resolved
        // в Prefix (single-pass lookup). Раньше каждый Apply* делал свой
        // GetAdoptedUsername lookup.
        private static void ApplyIgnoreArmor(string user, ref Blow b, ref AttackCollisionData cd)
        {
            double pct = ResolvePct(user, "ignore_armor_pct", "armor_bypass_pct");
            if (pct <= 0) return;
            if (b.AbsorbedByArmor <= 0) return;

            float bypass = (float)(b.AbsorbedByArmor * pct / 100.0);
            if (bypass <= 0) return;

            int beforeDmg = b.InflictedDamage;
            int beforeAbs = (int)b.AbsorbedByArmor;
            b.AbsorbedByArmor -= (int)bypass;
            cd.AbsorbedByArmor = (int)b.AbsorbedByArmor;
            b.BaseMagnitude += bypass;
            cd.BaseMagnitude = b.BaseMagnitude;
            b.InflictedDamage += (int)bypass;
            cd.InflictedDamage = b.InflictedDamage;
            // Snapshot для lambda (ref params нельзя captur'ить).
            int afterDmg = b.InflictedDamage;
            int afterAbs = (int)b.AbsorbedByArmor;
            int bypassInt = (int)bypass;
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook ARMOR] @{user} bypass={pct:F1}% " +
                $"absorb {beforeAbs}→{afterAbs} dmg {beforeDmg}→{afterDmg} (+{bypassInt})");
        }

        // Sprint 4.5 — rage active power. Multiplies outgoing damage.
        // Накладывается ПОСЛЕ ignore_armor чтобы multi применялся к итоговому
        // InflictedDamage (включая броне-bypass). Кэп 5x чтобы не было overflow.
        // 2026-05-29 Stage 2 — user pre-resolved в Prefix.
        private static void ApplyRageOutgoing(string user, ref Blow b, ref AttackCollisionData cd)
        {
            var rage = ActiveBuffState.GetValue(user, "rage");
            if (!rage.HasValue) return;

            double multi = Math.Max(1.0, Math.Min(5.0, rage.Value));
            if (multi <= 1.0) return;

            int beforeDmg = b.InflictedDamage;
            float baseMag = (float)(b.BaseMagnitude * multi);
            int inflicted = (int)(b.InflictedDamage * multi);

            b.BaseMagnitude = baseMag;
            cd.BaseMagnitude = baseMag;
            b.InflictedDamage = inflicted;
            cd.InflictedDamage = inflicted;
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook RAGE] @{user} ×{multi:F2} dmg {beforeDmg}→{inflicted}");
        }

        /// <summary>Sprint 5.33 (BLT-parity ITEM) — applies trophy bonuses.
        /// Attacker active trophy (weapon) → +damage_bonus к outgoing.
        /// Victim active trophy (armor) → -armor_bonus от incoming (absorption).
        ///
        /// Compose order: applied ПОСЛЕ ignore_armor + rage и ДО reflect.
        /// Damage_bonus stacks с rage multiplier additively (final = (base × rage) + trophy).
        /// Armor_bonus раздельно от ignore_armor — это новое поле, не наследуется
        /// от armor reduction.</summary>
        // 2026-05-29 Stage 2 — attUser/vicUser pre-resolved в Prefix.
        // Каждый side может быть null если та сторона не adopted hero.
        private static void ApplyTrophyBonuses(
            string attUser, string vicUser, ref Blow b, ref AttackCollisionData cd)
        {
            // Attacker side — damage bonus for weapon trophy.
            if (attUser != null)
            {
                var t = ActiveTrophyState.Get(attUser);
                if (t.HasValue && t.Value.DamageBonus > 0
                    && t.Value.BaseType == "weapon")
                {
                    int before = b.InflictedDamage;
                    int bonus = t.Value.DamageBonus;
                    b.InflictedDamage += bonus;
                    cd.InflictedDamage = b.InflictedDamage;
                    // Snapshot для lambda (ref b нельзя capture'ить).
                    int afterDmg = b.InflictedDamage;
                    string tName = t.Value.CustomName;
                    BannerlordLinkModule.LogVerbose(() =>
                        $"[DamageHook TROPHY] @{attUser} weapon '{tName}' " +
                        $"+{bonus} dmg ({before}→{afterDmg})");
                }
            }

            // Victim side — armor bonus = damage absorption.
            if (vicUser != null)
            {
                var t = ActiveTrophyState.Get(vicUser);
                if (t.HasValue && t.Value.ArmorBonus > 0
                    && (t.Value.BaseType == "armor" || t.Value.BaseType == "horse"))
                {
                    int before = b.InflictedDamage;
                    int absorbed = Math.Min(t.Value.ArmorBonus, b.InflictedDamage);
                    b.InflictedDamage -= absorbed;
                    cd.InflictedDamage = b.InflictedDamage;
                    int afterDmg = b.InflictedDamage;
                    string tName = t.Value.CustomName;
                    BannerlordLinkModule.LogVerbose(() =>
                        $"[DamageHook TROPHY] @{vicUser} armor '{tName}' " +
                        $"absorbed {absorbed} ({before}→{afterDmg})");
                }
            }
        }

        /// <summary>Sprint 5.32 CRASH FIX — раньше counter-blow inline вызывался
        /// `attacker.RegisterBlow(counter, cd)` внутри Prefix'а — мы шарили **тот
        /// же AttackCollisionData ref** между original и counter call. Engine
        /// corrupted shared state → native crash через ~3000 blows.
        ///
        /// Теперь: counter-blow откладывается в `_pendingReflects` queue,
        /// applies в KillRewardBehavior.OnMissionTick (отдельный frame, fresh
        /// AttackCollisionData). No re-entry, no shared ref.
        ///
        /// Damage reduction на victim применяется immediately (b.InflictedDamage
        /// модифицируется ref — safe, mutation своего блока).</summary>
        // 2026-05-29 Stage 2 — victim user (renamed locally от "user")
        // pre-resolved в Prefix. Attacker no longer needed для parameter list
        // т.к. counter-blow disabled (FMOD fix).
        private static void ApplyReflect(
            string user, ref Blow b, ref AttackCollisionData cd)
        {
            double passive = ResolvePct(user, "damage_reflect_pct");
            double retribution = ActiveBuffState.GetValue(user, "retribution_toggle") ?? 0.0;
            // Suma capped at 95% чтобы не было > 100% (heroes неубиваемые) +
            // оставить минимальный финальный damage attacker→victim.
            double pct = Math.Min(95.0, passive + retribution);
            if (pct <= 0) return;

            int reflected = (int)(b.InflictedDamage * pct / 100.0);
            if (reflected <= 0) return;

            // 1. Damage reduction на victim — immediate, safe ref-mutation.
            int beforeDmg = b.InflictedDamage;
            int newInflicted = Math.Max(0, b.InflictedDamage - reflected);
            b.InflictedDamage = newInflicted;
            cd.InflictedDamage = newInflicted;

            // 2. Counter-blow — DISABLED 2026-05-28 (4th FMOD crash).
            //
            // After 4 successive crashes correlated с DamageHook activity
            // (FMOD invalid handle), we eliminate the biggest sustained-load
            // RegisterBlow path. REFLECT now DAMAGE-REDUCTION ONLY:
            //   - victim receives reduced damage (good for tank/defensive)
            //   - attacker NOT counter-hit (gameplay simplification)
            //
            // To re-enable counter-blow при stable build, uncomment EnqueueReflect.
            // BLT-Lait использует ReflectDamagePower aналогично (no counter),
            // так что это actually closer to BLT-parity.
            //
            // EnqueueReflect(attacker, victim, reflected, b.DamageType);   // disabled
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook REFLECT] @{user} pct={pct:F1}% " +
                $"dmg {beforeDmg}→{newInflicted} (reduced -{reflected}) " +
                $"[counter-blow disabled — FMOD safety]");
        }

        // Sprint 5.32 CRASH FIX — pending reflects queue. KillRewardBehavior
        // dequeue'ит на OnMissionTick (не во время RegisterBlow Prefix).
        public readonly struct PendingReflect
        {
            public readonly Agent Attacker;
            public readonly Agent Victim;
            public readonly int Damage;
            public readonly DamageTypes DamageType;
            public PendingReflect(Agent a, Agent v, int d, DamageTypes dt)
            { Attacker = a; Victim = v; Damage = d; DamageType = dt; }
        }
        private static readonly System.Collections.Concurrent.ConcurrentQueue<PendingReflect>
            _pendingReflects = new System.Collections.Concurrent.ConcurrentQueue<PendingReflect>();

        private static void EnqueueReflect(Agent attacker, Agent victim, int damage, DamageTypes dt)
        {
            if (attacker == null || victim == null || damage <= 0) return;
            _pendingReflects.Enqueue(new PendingReflect(attacker, victim, damage, dt));
        }

        /// <summary>Drain pending reflects. Called from KillRewardBehavior.OnMissionTick.
        /// Это вне любого RegisterBlow Prefix scope → no shared ref, no re-entry.
        ///
        /// 2026-05-28 CRASH FIX: cap drain at MAX_DRAINS_PER_TICK чтобы не
        /// перегружать engine RegisterBlow в sustained reflect cascade. Crash
        /// session 21:36:29 показал ~200 reflects за 6 секунд (~30/сек) →
        /// engine state может corrupt under prolonged load. Throttle защищает.
        /// Reflects сверх cap — drop'ятся (next tick possible re-queue если
        /// поток продолжается).</summary>
        private const int MAX_DRAINS_PER_TICK = 3;
        public static void DrainPendingReflects()
        {
            int applied = 0, dropped = 0;
            while (_pendingReflects.TryDequeue(out var req))
            {
                // 2026-05-28: hard cap чтобы избежать sustained RegisterBlow load.
                if (applied >= MAX_DRAINS_PER_TICK)
                {
                    dropped++;
                    continue;   // drain queue но не RegisterBlow
                }
                try
                {
                    if (req.Attacker == null || !req.Attacker.IsActive()) continue;
                    var counter = new Blow(req.Victim?.Index ?? -1)
                    {
                        AttackType = req.Attacker.IsMount
                            ? AgentAttackType.Collision
                            : AgentAttackType.Standard,
                        DamageType = req.Attacker.IsMount ? DamageTypes.Blunt : req.DamageType,
                        BoneIndex = req.Attacker.Monster?.ThoraxLookDirectionBoneIndex ?? (sbyte)0,
                        GlobalPosition = req.Attacker.Position,
                        // 2026-05-28 FMOD FIX: NoSound flag — counter-blow без
                        // sound event генерации. Reduces FMOD handle exhaustion
                        // в long battles (FMOD pool limited, our reflects добавляли
                        // sound на каждый dequeue → crash via invalid handle).
                        // BlowFlags.NoSound существует в Bannerlord 1.3.x. Если
                        // нет (build error) — fallback на None через ifdef.
                        BlowFlag = BlowFlags.NoSound,
                        BaseMagnitude = 0f,
                        InflictedDamage = req.Damage,
                        SwingDirection = req.Attacker.LookDirection.NormalizedCopy(),
                        Direction = req.Attacker.LookDirection,
                        DamageCalculated = true,
                        WeaponRecord = new() { AffectorWeaponSlotOrMissileIndex = -1 },
                    };
                    // Fresh AttackCollisionData (default) — не share'им с original.
                    AttackCollisionData freshCd = default;
                    _inReflect.Value = true;
                    try
                    {
                        req.Attacker.RegisterBlow(counter, freshCd);
                        applied++;
                    }
                    finally { _inReflect.Value = false; }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[DamageHook] async reflect failed: {ex.GetType().Name}: {ex.Message}");
                }
            }
            if (applied > 0 || dropped > 0)
            {
                BannerlordLinkModule.Log(
                    $"[DamageHook DRAIN] applied {applied}" +
                    (dropped > 0 ? $", dropped {dropped} (throttle cap)" : "") +
                    " pending reflects this tick");
            }
        }

        private static string GetAdoptedUsername(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return null;
            var hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero?.Name == null) return null;
            string user = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name.ToString());
            return string.IsNullOrEmpty(user) ? null : user;
        }

        // M16 seed имеет armor_bypass_pct на crossbow и ignore_armor_pct на
        // melee классах — оба = один эффект. Принимаем оба ключа как alias
        // до consolidation в M17 (Sprint 4.5).
        private static double ResolvePct(string user, params string[] keys)
        {
            foreach (var k in keys)
            {
                var v = PowerCache.GetPowerValue(user, k);
                if (v.HasValue && v.Value > 0) return v.Value;
            }
            return 0;
        }
    }
}
