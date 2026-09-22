using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.GameComponents;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Reduce only battle mortality to 5% of the native risk. Both mission combat
    /// and map-event simulation consume GetSurvivalChance; the engine owns the
    /// single random roll. Campaign ageing/execution and horse protection are unchanged.
    /// </summary>
    [HarmonyPatch(typeof(DefaultPartyHealingModel), "GetSurvivalChance")]
    internal static class ViewerBattleMortalityPatch
    {
        [HarmonyPostfix]
        [HarmonyPriority(Priority.Last)]
        public static void Postfix(CharacterObject character, ref float __result)
        {
            if (!HeroNaming.IsAdopted(character?.HeroObject)) return;
            // Preserve guaranteed survival. Do not turn non-finite or out-of-range
            // results from another model patch into a new game rule.
            if (float.IsNaN(__result) || __result < 0f || __result > 1f) return;
            __result = 1f - (1f - __result) * 0.05f;
        }
    }
}
