using System;
using BannerlordLink.Net;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-05-29 (BLT-parity AddDamagePower cut-through) — рассечение (cleave).
    ///
    /// Postfix на Mission.MeleeHitCallback: с шансом `cleave_chance_pct`
    /// (passive, per class+level из PowerCache) выставляем
    /// colReaction = SlicedThrough — удар прорубается на следующего врага,
    /// вместо того чтобы застрять. Аналог BLTHeroPowersMissionBehavior /
    /// AddDamagePower.OnDecideWeaponCollisionReaction (RC22:347-350).
    ///
    /// БЕЗОПАСНОСТЬ:
    ///   • Только FLAG-set — НЕ создаём новых RegisterBlow / sound events,
    ///     поэтому FMOD pool не трогается (история крашей была про RegisterBlow).
    ///   • Не трогаем заблокированные удары (colReaction == Bounced) — блок
    ///     остаётся блоком, рассечение только для landed-хитов.
    ///   • Graceful TargetMethods() (паттерн IsSideDepletedPatch): если
    ///     Mission.MeleeHitCallback не резолвится в текущей версии engine —
    ///     patch тихо скипается, боёвка работает по-ванильному.
    ///   • Hot path (каждый melee-хит) — дешёвые early-exit'ы перед lookup'ом.
    /// </summary>
    [HarmonyPatch]
    public static class CleavePatch
    {
        public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
            TargetMethods()
        {
            var m = AccessTools.Method(typeof(Mission), "MeleeHitCallback");
            if (m == null)
            {
                BannerlordLinkModule.Log(
                    "[Cleave] Mission.MeleeHitCallback не найден — patch skip");
                yield break;
            }
            BannerlordLinkModule.Log(
                "[Cleave] postfix registered (cut-through для adopted heroes)");
            yield return m;
        }

        // Harmony биндит по имени — declare только нужные params (attacker +
        // ref colReaction). Имя `colReaction` должно совпадать с сигнатурой
        // Mission.MeleeHitCallback (см. BLT RC22 patch).
        [HarmonyPostfix]
        public static void Postfix(Agent attacker, ref MeleeCollisionReaction colReaction)
        {
            // Уже рассекает — нечего делать. Заблокированный удар (Bounced) —
            // не превращаем в рассечение (иначе блоки бесполезны).
            if (colReaction == MeleeCollisionReaction.SlicedThrough) return;
            if (colReaction == MeleeCollisionReaction.Bounced) return;
            if (attacker == null) return;

            try
            {
                // Mount redirect — charge/верховые атаки идут от mount Agent.
                Agent src = attacker.IsMount ? attacker.RiderAgent : attacker;
                if (src == null || !src.IsHuman) return;
                var hero = (src.Character as CharacterObject)?.HeroObject;
                if (hero?.Name == null) return;
                string user = Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                if (string.IsNullOrEmpty(user)) return;

                var chance = PowerCache.GetPowerValue(user, "cleave_chance_pct");
                if (!chance.HasValue || chance.Value <= 0) return;

                if (TaleWorlds.Core.MBRandom.RandomFloat * 100f < chance.Value)
                {
                    colReaction = MeleeCollisionReaction.SlicedThrough;
                    BannerlordLinkModule.LogVerbose(() =>
                        $"[Cleave] @{user} cut-through ({chance.Value:F0}% roll)");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[Cleave] {ex.Message}");
            }
        }
    }
}
