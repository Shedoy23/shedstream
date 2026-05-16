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
                ApplyIgnoreArmor(attacker, ref b, ref collisionData);
                ApplyRageOutgoing(attacker, ref b, ref collisionData);
                ApplyReflect(attacker, victim, ref b, ref collisionData);

                if (!_firstHitLogged)
                {
                    _firstHitLogged = true;
                    BannerlordLinkModule.Log(
                        "[DamageHook] Mission.RegisterBlow patched, first blow processed");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DamageHook] {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static void ApplyIgnoreArmor(Agent attacker, ref Blow b, ref AttackCollisionData cd)
        {
            string user = GetAdoptedUsername(attacker);
            if (user == null) return;

            double pct = ResolvePct(user, "ignore_armor_pct", "armor_bypass_pct");
            if (pct <= 0) return;
            if (b.AbsorbedByArmor <= 0) return;

            float bypass = (float)(b.AbsorbedByArmor * pct / 100.0);
            if (bypass <= 0) return;

            b.AbsorbedByArmor -= (int)bypass;
            cd.AbsorbedByArmor = (int)b.AbsorbedByArmor;
            b.BaseMagnitude += bypass;
            cd.BaseMagnitude = b.BaseMagnitude;
            b.InflictedDamage += (int)bypass;
            cd.InflictedDamage = b.InflictedDamage;
        }

        // Sprint 4.5 — rage active power. Multiplies outgoing damage.
        // Накладывается ПОСЛЕ ignore_armor чтобы multi применялся к итоговому
        // InflictedDamage (включая броне-bypass). Кэп 5x чтобы не было overflow.
        private static void ApplyRageOutgoing(Agent attacker, ref Blow b, ref AttackCollisionData cd)
        {
            string user = GetAdoptedUsername(attacker);
            if (user == null) return;

            var rage = ActiveBuffState.GetValue(user, "rage");
            if (!rage.HasValue) return;

            double multi = Math.Max(1.0, Math.Min(5.0, rage.Value));
            if (multi <= 1.0) return;

            float baseMag = (float)(b.BaseMagnitude * multi);
            int inflicted = (int)(b.InflictedDamage * multi);

            b.BaseMagnitude = baseMag;
            cd.BaseMagnitude = baseMag;
            b.InflictedDamage = inflicted;
            cd.InflictedDamage = inflicted;
        }

        private static void ApplyReflect(
            Agent attacker, Agent victim, ref Blow b, ref AttackCollisionData cd)
        {
            string user = GetAdoptedUsername(victim);
            if (user == null) return;

            double passive = ResolvePct(user, "damage_reflect_pct");
            double retribution = ActiveBuffState.GetValue(user, "retribution_toggle") ?? 0.0;
            // Suma capped at 95% чтобы не было > 100% (heroes неубиваемые) +
            // оставить минимальный финальный damage attacker→victim.
            double pct = Math.Min(95.0, passive + retribution);
            if (pct <= 0) return;

            int reflected = (int)(b.InflictedDamage * pct / 100.0);
            if (reflected <= 0) return;

            int newInflicted = Math.Max(0, b.InflictedDamage - reflected);
            b.InflictedDamage = newInflicted;
            cd.InflictedDamage = newInflicted;

            _inReflect.Value = true;
            try
            {
                var counter = new Blow(victim.Index)
                {
                    AttackType = attacker.IsMount
                        ? AgentAttackType.Collision
                        : AgentAttackType.Standard,
                    DamageType = attacker.IsMount ? DamageTypes.Blunt : b.DamageType,
                    BoneIndex = attacker.Monster?.ThoraxLookDirectionBoneIndex ?? (sbyte)0,
                    GlobalPosition = attacker.Position,
                    BlowFlag = BlowFlags.None,
                    BaseMagnitude = 0f,
                    InflictedDamage = reflected,
                    SwingDirection = attacker.LookDirection.NormalizedCopy(),
                    Direction = attacker.LookDirection,
                    DamageCalculated = true,
                    WeaponRecord = new() { AffectorWeaponSlotOrMissileIndex = -1 },
                };
                attacker.RegisterBlow(counter, cd);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DamageHook] reflect counter-blow failed: {ex.Message}");
            }
            finally
            {
                _inReflect.Value = false;
            }
        }

        private static string GetAdoptedUsername(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return null;
            var hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero?.Name == null) return null;
            string user = hero.Name.ToString()?.ToLowerInvariant();
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
