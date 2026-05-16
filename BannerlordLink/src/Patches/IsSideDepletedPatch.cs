using System;
using BannerlordLink.Net;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 5.1a — Harmony Postfix на MissionAgentSpawnLogic.IsSideDepleted.
    ///
    /// Зачем: после `Mission.SpawnTroop(..., isReinforcement:true)` (summon
    /// viewer hero), Bannerlord's reinforcement spawn logic чекает
    /// IsSideDepleted перед dispatch'ом next wave. Если все vanilla troops
    /// уже мертвы — side считается depleted, summons прекращаются.
    ///
    /// Наш fix: если на side ЕСТЬ adopted hero (имя совпадает с known
    /// viewer'ом в PowerCache) — side НЕ depleted. Reinforcement waves
    /// продолжают идти пока хотя бы один наш hero alive.
    ///
    /// BLT pattern (BLTSummonBehavior строка 1081-1083): аналогичный postfix
    /// — наша clean-room re-impl. API names identical т.к. это public TaleWorlds
    /// type.
    ///
    /// Edge case: BattleSideEnum может не resolve'ся в текущем reference set.
    /// Если так — patch class не build'ится, мы катимся без него (existing
    /// vanilla behavior сохранится).
    /// </summary>
    [HarmonyPatch(typeof(MissionAgentSpawnLogic), "IsSideDepleted")]
    public static class IsSideDepletedPatch
    {
        [HarmonyPostfix]
        public static void Postfix(BattleSideEnum side, ref bool __result)
        {
            if (!__result) return;          // already not depleted — nothing to do
            if (Mission.Current == null) return;

            try
            {
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || !a.IsActive() || !a.IsHuman) continue;
                    if (a.Team == null || a.Team.Side != side) continue;
                    var hero = (a.Character as CharacterObject)?.HeroObject;
                    if (hero?.Name == null) continue;
                    string name = Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                    if (string.IsNullOrEmpty(name)) continue;
                    if (PowerCache.GetHeroClass(name) != null)
                    {
                        __result = false;
                        return;
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[IsSideDepleted] {ex.Message}");
            }
        }
    }
}
