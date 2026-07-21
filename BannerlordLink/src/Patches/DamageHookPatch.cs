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
                    // 2026-05-29 (BLT-parity) — вампиризм: лечим атакующего на %
                    // финального урона (после armor-bypass + rage). Передаём
                    // attackerSrc (mount-redirect к rider'у) — лечим hero, не коня.
                    ApplyLifesteal(attackerUser, attackerSrc, b.InflictedDamage);
                    // 2026-05-29 (BLT-parity AoE) — взрывные стрелы: на missile-
                    // хите при активном буффе наносим AoE по ближайшим врагам
                    // через отложенную очередь (FMOD-safe).
                    ApplyExplosiveArrows(attackerUser, attackerSrc, victim, ref collisionData);
                    // 2026-06-10 (мили-баланс) — рассечение: на МИЛИ-хите по шансу
                    // splash-AoE по соседним врагам (замена мёртвого CleavePatch),
                    // через ту же безопасную отложенную очередь, что explosive_arrows.
                    ApplyMeleeCleave(attackerUser, attackerSrc, victim, ref b, ref collisionData);
                    // 2026-07-20 (редизайн активок) — «работает от удара»:
                    // щит ломается у того, кого ударил; яд вешается на того, в кого попал.
                    ApplyShieldBreakOnHit(attackerUser, attackerSrc, victim, ref collisionData);
                    ApplyPoisonOnHit(attackerUser, attackerSrc, victim);
                    // 2026-07-21 — «ударил и растворился»: фиксируем удар невидимки,
                    // на окно раскрытия тик перестаёт срывать врагам захват (жадность
                    // в свалке наказуема). См. docs/SPEC_ASSASSIN_INVIS.md.
                    NoteStealthHit(attackerUser);
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
                    // 2026-06-10 (мили-баланс) — анти-стан: по шансу stagger_immunity_pct
                    // ставим ShrugOff на входящий удар, чтобы милишник не застревал
                    // в стане. Только флаг (без RegisterBlow) — безопасно.
                    ApplyStaggerImmunity(victimUser, ref b);
                    // 2026-05-29 (BLT-parity TakeDamagePower) — железная кожа:
                    // снижаем входящий урон ДО reflect (reflect считается от
                    // уже сниженного значения).
                    ApplyDamageReduction(victimUser, ref b, ref collisionData);
                    ApplyReflect(victimUser, ref b, ref collisionData);
                }

                // AUDIT 2026-05-29 (fix #8): final defensive clamp на mutated
                // damage values. История нативных крашей связана с RegisterBlow +
                // shared AttackCollisionData; в движок подаём только sane,
                // неотрицательные, не-NaN, не-переполненные значения. DMG_CAP
                // заведомо выше любого реального удара (>100k = corruption).
                // Только когда мы реально модифицировали (одна из сторон adopted —
                // гарантировано выше по early-exit).
                const int DMG_CAP = 100000;
                if (float.IsNaN(b.BaseMagnitude) || float.IsInfinity(b.BaseMagnitude))
                    b.BaseMagnitude = 0f;
                if (b.BaseMagnitude < 0f) b.BaseMagnitude = 0f;
                else if (b.BaseMagnitude > DMG_CAP) b.BaseMagnitude = DMG_CAP;
                collisionData.BaseMagnitude = b.BaseMagnitude;

                if (b.InflictedDamage < 0) b.InflictedDamage = 0;
                else if (b.InflictedDamage > DMG_CAP) b.InflictedDamage = DMG_CAP;
                collisionData.InflictedDamage = b.InflictedDamage;

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

            double multi = Math.Max(1.0, Math.Min(8.0, rage.Value));   // 2026-06-05 кап 5→8 (BLT-parity)
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

        // 2026-05-29 (BLT-parity AbsorbHealthPower) — вампиризм. Лечим
        // атакующего на % нанесённого урона. Passive lifesteal_pct (PowerCache,
        // per class+level) + active lifesteal_burst (ActiveBuffState, timed).
        // Per-hit heal capped (anti-degenerate при rage×5) + clamp к HealthLimit.
        private static void ApplyLifesteal(string user, Agent attackerSrc, int inflictedDamage)
        {
            if (attackerSrc == null || !attackerSrc.IsActive()) return;
            if (inflictedDamage <= 0) return;

            double passive = ResolvePct(user, "lifesteal_pct");
            double burst = ActiveBuffState.GetValue(user, "lifesteal_burst") ?? 0.0;
            double pct = Math.Min(100.0, passive + burst);
            if (pct <= 0) return;

            float limit = attackerSrc.HealthLimit;
            if (attackerSrc.Health >= limit) return;

            float heal = (float)(inflictedDamage * pct / 100.0);
            if (heal <= 0) return;
            if (heal > 250f) heal = 250f;            // per-hit cap (2026-06-05 100→250, HP теперь 2.5×)
            float before = attackerSrc.Health;
            float after = Math.Min(limit, before + heal);
            attackerSrc.Health = after;
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook LIFESTEAL] @{user} {pct:F1}% → +{(after - before):F0} hp " +
                $"({before:F0}→{after:F0})");
        }

        // 2026-07-20 — «Разбить щит» как БАФФ от удара: пока активен, МИЛИ-попадание
        // ломает щит жертве. Раньше была мгновенная AoE-вспышка по радиусу, которая
        // чаще всего ломала 0 щитов (нужны щитоносцы рядом) → зритель платил за ноль.
        // Теперь эффект привязан к попаданию: ударил щитовика — щит разлетелся, видно.
        private static void ApplyShieldBreakOnHit(
            string user, Agent attackerSrc, Agent victim, ref AttackCollisionData cd)
        {
            if (attackerSrc == null || victim == null) return;
            if (cd.IsMissile) return;                  // ломаем щит в ближнем бою
            var v = ActiveBuffState.GetValue(user, "shield_break_burst");
            if (!v.HasValue) return;
            if (BannerlordLink.Actions.ActivatePowerHandler.TryBreakShield(victim))
            {
                BannerlordLinkModule.LogVerbose(() =>
                    $"[DamageHook SHIELD-BREAK] @{user} сломал щит агенту idx={victim.Index}");
            }
        }

        // 2026-07-20 — «Яд» как БАФФ от удара: пока активен, ЛЮБОЕ попадание (мили или
        // стрела) вешает DoT на того, в кого попал. Раньше активка травила СЛУЧАЙНОГО
        // врага в 15м — зритель не видел кого, а без врагов рядом уходила в ноль.
        // Тик урона делает PowersMissionBehavior.ApplyDotTicks по ключу dot_target_{idx}.
        private static void ApplyPoisonOnHit(string user, Agent attackerSrc, Agent victim)
        {
            if (attackerSrc == null || victim == null) return;
            if (!victim.IsActive() || !victim.IsHuman) return;
            var dps = ActiveBuffState.GetValue(user, "poison_dot");
            if (!dps.HasValue || dps.Value <= 0) return;
            // Перевешиваем/обновляем DoT на этой цели (Activate — upsert по ключу).
            ActiveBuffState.Activate(
                $"dot_target_{victim.Index}", "poison_dot", 45f, dps.Value);
            BannerlordLink.Util.PowerVisualFx.PlayBuffTick(victim, "poison_dot");
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook POISON] @{user} отравил агента idx={victim.Index} ({(int)dps.Value} dmg/s)");
        }

        // 2026-05-29 (BLT-parity AddDamagePower AoE) — взрывные стрелы.
        // На missile-хите при активном буффе explosive_arrows наносим AoE по
        // ближайшим врагам вокруг точки попадания. Урон в центре = value буффа,
        // дальше затухает по обратному квадрату расстояния (наш вариант записан
        // как center·R²/(d+R)² — стандартный inverse-square falloff).
        //
        // FMOD-safety: НЕ вызываем RegisterBlow inline — кладём в ту же
        // отложенную очередь что reflect (EnqueueReflect → DrainPendingReflects:
        // BlowFlags.NoSound + троттл ≤3/тик). Звуковых событий не плодим.
        private const float EXPLOSIVE_RADIUS = 5.0f;     // 2026-06-05 3.5→5м
        private const int EXPLOSIVE_MAX_TARGETS = 4;     // 2026-06-05 3→4 (наш баланс)
        private static void ApplyExplosiveArrows(
            string user, Agent attackerSrc, Agent victim, ref AttackCollisionData cd)
        {
            if (attackerSrc == null || victim == null) return;
            if (!cd.IsMissile) return;                 // только стрелы/болты
            var center = ActiveBuffState.GetValue(user, "explosive_arrows");
            if (!center.HasValue || center.Value <= 0) return;
            if (Mission.Current == null) return;

            double damageAtCenter = center.Value;
            var pos = victim.Position;
            var hits = new System.Collections.Generic.List<(Agent a, float d)>();
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || a == attackerSrc || a == victim) continue;
                if (!a.IsActive() || !a.IsHuman) continue;
                if (!a.IsEnemyOf(attackerSrc)) continue;
                float dist = a.Position.Distance(pos);
                if (dist > EXPLOSIVE_RADIUS) continue;
                hits.Add((a, dist));
            }
            if (hits.Count == 0) return;
            hits.Sort((x, y) => x.d.CompareTo(y.d));
            int n = Math.Min(EXPLOSIVE_MAX_TARGETS, hits.Count);
            for (int i = 0; i < n; i++)
            {
                // inverse-square: center·R²/(d+R)². При d=0 → center; растёт d → спад.
                float falloffDen = (hits[i].d + EXPLOSIVE_RADIUS) * (hits[i].d + EXPLOSIVE_RADIUS);
                int dmg = (int)(damageAtCenter * EXPLOSIVE_RADIUS * EXPLOSIVE_RADIUS / falloffDen);
                if (dmg <= 0) continue;
                // 2026-05-31 FIX — порядок агентов. Drain делает
                // req.Attacker.RegisterBlow(Blow(owner=req.Victim)): бьёт
                // req.Attacker, «источник» = req.Victim. Для AoE урон должен
                // получить ВРАГ (hits[i].a), источник = стрелок (attackerSrc).
                // Раньше было (attackerSrc, hits[i].a) → взрыв бил САМОГО
                // стрелка, врагам ноль → «не работало». BLT DoAgentDamage:
                // target.RegisterBlow(Blow(from.Index)) — та же семантика.
                EnqueueReflect(hits[i].a, attackerSrc, dmg, DamageTypes.Blunt);
            }
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook EXPLOSIVE] @{user} AoE center={damageAtCenter:F0} → {n} targets");
        }

        // 2026-06-10 → 2026-06-17 (#15) — рассечение (мили splash-AoE). Замена
        // мёртвого CleavePatch (cut-through через WeaponCollisionReaction крашил
        // 1.3.15): splash'им долю урона ≤3 ближайшим врагам вокруг жертвы через ту
        // же безопасную отложенную очередь (EnqueueReflect → DrainPendingReflects:
        // BlowFlags.NoSound + троттл ≤3/тик), что explosive_arrows — НЕ зовём
        // RegisterBlow инлайн (FMOD-safe). 2026-06-17: переведено из ПАССИВА
        // (always-on cleave_chance_pct) в АКТИВКУ — splash только в окне буффа
        // `cleave` (зеркало explosive_arrows), value буффа = доля урона.
        private const float CLEAVE_RADIUS = 2.5f;          // мили-дуга вокруг жертвы
        private const int CLEAVE_MAX_TARGETS = 3;
        private static void ApplyMeleeCleave(
            string user, Agent attackerSrc, Agent victim,
            ref Blow b, ref AttackCollisionData cd)
        {
            if (attackerSrc == null || victim == null) return;
            if (cd.IsMissile) return;                       // только мили-удары
            if (b.InflictedDamage <= 0) return;
            // Активка: splash идёт только пока активен буфф `cleave`; value = доля урона.
            var frac = ActiveBuffState.GetValue(user, "cleave");
            if (!frac.HasValue || frac.Value <= 0) return;
            if (Mission.Current == null) return;

            int splash = (int)(b.InflictedDamage * frac.Value);
            if (splash <= 0) return;
            var dt = b.DamageType;
            var pos = victim.Position;

            var hits = new System.Collections.Generic.List<(Agent a, float d)>();
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || a == attackerSrc || a == victim) continue;
                if (!a.IsActive() || !a.IsHuman) continue;
                if (!a.IsEnemyOf(attackerSrc)) continue;
                float dist = a.Position.Distance(pos);
                if (dist > CLEAVE_RADIUS) continue;
                hits.Add((a, dist));
            }
            if (hits.Count == 0) return;
            hits.Sort((x, y) => x.d.CompareTo(y.d));
            int n = Math.Min(CLEAVE_MAX_TARGETS, hits.Count);
            for (int i = 0; i < n; i++)
            {
                // Семантика как у explosive_arrows: враг ПОЛУЧАЕТ удар (1-й арг),
                // источник = наш герой (2-й арг). Drain: arg1.RegisterBlow(Blow(arg2)).
                EnqueueReflect(hits[i].a, attackerSrc, splash, dt);
            }
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook CLEAVE] @{user} splash={splash} → {n} targets");
        }

        // 2026-06-10 (мили-баланс) — анти-стан. По шансу stagger_immunity_pct
        // ставим ShrugOff на входящий удар → милишник не прерывает свою атаку
        // (BLT TakeDamagePower AddHitBehavior=ShrugOff). Только флаг, без
        // RegisterBlow. stagger_immunity_pct сидится только мили-классам.
        private static void ApplyStaggerImmunity(string user, ref Blow b)
        {
            double pct = ResolvePct(user, "stagger_immunity_pct");
            if (pct <= 0) return;
            if (TaleWorlds.Core.MBRandom.RandomFloat * 100.0 >= pct) return;
            // BLT-парность (HitBehavior.AddFlags): ShrugOff взаимоисключающий с
            // нокбэком/нокдауном — ставим ShrugOff И гасим их в том же действии.
            // Раньше было только |= ShrugOff (флаги отброса оставались) → герой
            // всё равно «станился»/отлетал в толпе. Только флаги на Blow (без
            // collision-reaction) — безопасно на 1.3.15.
            b.BlowFlag = (b.BlowFlag & ~(BlowFlags.KnockBack | BlowFlags.KnockDown))
                         | BlowFlags.ShrugOff;
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook SHRUG] @{user} ({pct:F0}%) → ShrugOff (no knockback)");
        }

        // 2026-05-29 (BLT-parity TakeDamagePower) — железная кожа. Снижаем
        // входящий урон на %. Passive damage_reduction_pct (PowerCache) + active
        // ironskin_toggle (ActiveBuffState). Cap 80% чтобы hero не был неубиваем.
        private static void ApplyDamageReduction(string user, ref Blow b, ref AttackCollisionData cd)
        {
            double passive = ResolvePct(user, "damage_reduction_pct");
            double toggle = ActiveBuffState.GetValue(user, "ironskin_toggle") ?? 0.0;
            double pct = Math.Min(90.0, passive + toggle);   // 2026-06-05 кап 80→90%
            if (pct <= 0) return;

            int reduced = (int)(b.InflictedDamage * pct / 100.0);
            if (reduced <= 0) return;

            int beforeDmg = b.InflictedDamage;
            int newInflicted = Math.Max(0, b.InflictedDamage - reduced);
            b.InflictedDamage = newInflicted;
            cd.InflictedDamage = newInflicted;
            BannerlordLinkModule.LogVerbose(() =>
                $"[DamageHook IRONSKIN] @{user} -{pct:F1}% dmg {beforeDmg}→{newInflicted}");
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
        /// <summary>2026-07-21 — «Невидимость»: помечаем, что невидимка ударил.
        /// Дешёвый ранний выход — у 99.9% атакующих буффа нет.</summary>
        private static void NoteStealthHit(string user)
        {
            if (ActiveBuffState.GetValue(user, "retribution_toggle") == null) return;
            var m = Mission.Current;
            if (m == null) return;
            BannerlordLink.Net.StealthState.NoteHit(user, m.CurrentTime);
        }

        private static void ApplyReflect(
            string user, ref Blow b, ref AttackCollisionData cd)
        {
            // 2026-07-21 — активка retribution_toggle переиспользована под «Невидимость»
            // (docs/SPEC_ASSASSIN_INVIS.md): её value теперь окно раскрытия В СЕКУНДАХ,
            // а не процент отражения — складывать нельзя. Остаётся только пассивка.
            double passive = ResolvePct(user, "damage_reflect_pct");
            // Cap 95% чтобы не было > 100% (heroes неубиваемые) + оставить
            // минимальный финальный damage attacker→victim.
            double pct = Math.Min(95.0, passive);
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
