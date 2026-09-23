using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.GameComponents;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// One flat battle death chance for every viewer hero, per knockdown.
    /// Native risk varies wildly: a hero with no party of his own gets 100%
    /// (GetSurvivalChance returns 0 without a MobileParty), a levelled one in
    /// armour well under 1%. Viewers re-summon 5-10 times per battle, so the
    /// flat chance is kept very small. Both mission combat and map-event
    /// simulation consume GetSurvivalChance; the engine owns the single roll.
    /// Campaign ageing/execution and horse protection are unchanged.
    /// </summary>
    [HarmonyPatch(typeof(DefaultPartyHealingModel), "GetSurvivalChance")]
    internal static class ViewerBattleMortalityPatch
    {
        // Owner decision 23.09.2026: 0.02% per knockdown. The busiest viewer
        // summons ~200 times per 13-14h stream -> ~4% per stream.
        internal const float ViewerDeathChance = 0.0002f;

        [HarmonyPostfix]
        [HarmonyPriority(Priority.Last)]
        public static void Postfix(CharacterObject character, ref float __result)
        {
            if (!HeroNaming.IsAdopted(character?.HeroObject)) return;
            // Preserve guaranteed survival (blunt, "Very Easy"). Do not turn
            // non-finite or out-of-range results from another model patch into
            // a new game rule.
            if (float.IsNaN(__result) || __result < 0f || __result >= 1f) return;
            __result = 1f - ViewerDeathChance;
        }
    }
}
