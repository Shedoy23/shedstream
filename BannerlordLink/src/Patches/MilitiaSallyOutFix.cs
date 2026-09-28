using System;
using System.Collections.Generic;
using HarmonyLib;
using TaleWorlds.CampaignSystem.MapEvents;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-05-29 Stage 4 (BLT-RC22 engine bug fix) — vanilla Town.GetDefenderParties
    /// omits militia из SallyOut defender list. Result: when garrison sallies
    /// out против besiegers, garrison militia (большая часть defending force
    /// для small/medium towns) не participates → garrison weaker than expected.
    ///
    /// Pattern из BLT HarmonyPatches.cs:801-826 (Town_GetDefenderParties_Patch).
    ///
    /// Engine behavior (vanilla):
    ///   ```
    ///   foreach (MobileParty mobileParty in town.Settlement.Parties) {
    ///       if (mp.MapFaction.IsAtWarWith(besieger.MapFaction)
    ///           && mp.IsActive
    ///           && !mp.IsVillager
    ///           && !mp.IsCaravan
    ///           && !mp.IsMilitia)  // ← BUG: excludes militia
    ///       {
    ///           yield return mp.Party;
    ///       }
    ///   }
    ///   ```
    ///
    /// Our fix:
    ///   ```
    ///   && (!mp.IsMilitia || !town.InRebelliousState)  // include militia
    ///   ```
    ///   Только в rebellious state militia не sally (rebel militia не
    ///   trustworthy). В normal состоянии militia sallies с regular garrison.
    ///
    /// Why we adopt this:
    ///   - Affects siege gameplay correctness — defenders teoreticheски
    ///     stronger than engine actually fields
    ///   - Pure correctness fix — no crash potential, no FMOD impact
    ///   - BLT-RC22 ships this fix as standard
    ///
    /// Implementation pattern:
    ///   Mirror BLT — Prefix returns false (skip vanilla), assigns ref __result
    ///   к own IEnumerable. We re-implement the iteration with corrected
    ///   filter.
    /// </summary>
    [HarmonyPatch(typeof(Town), "GetDefenderParties")]
    internal static class Town_GetDefenderParties_MilitiaFix
    {
        // 2026-05-29 INCIDENT — DISABLED pending RCA. Воспроизводимый нативный
        // вылет на РАЗВЁРТЫВАНИИ осады за защитную сторону. Этот Prefix целиком
        // ПОДМЕНЯЕТ Town.GetDefenderParties ленивым итератором, который движок
        // перечисляет ВНЕ нашего try/catch, игнорирует battleType и пересекается
        // с другими garrison/siege-модами (ImprovedGarrisons, SiegeFix,
        // AutoDeploySiegeEngines) → битый список защитников → краш в нативном
        // коде сборки осадных формирований. Prepare()=false → Harmony НЕ
        // применяет патч, движок использует ванильный GetDefenderParties.
        // Цена: militia не sally-out (мелкий correctness-fix) — приемлемо.
        public static bool Prepare() => false;

        [HarmonyPrefix]
        public static bool Prefix(
            Town __instance,
            MapEvent.BattleTypes battleType,
            ref IEnumerable<PartyBase> __result)
        {
            try
            {
                if (__instance == null) return true;  // let vanilla run на edge case
                __result = GetDefenderPartiesWithMilitia(__instance, battleType);
                return false;  // skip original
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[MilitiaSallyOutFix] Prefix error: {ex.Message} — allowing vanilla");
                return true;
            }
        }

        // Mirror BLT BLT_GetDefenderPartiesWithMilitia. Yields:
        //   1. Town.Settlement.Party (settlement itself — always defender)
        //   2. Все mobile parties at settlement which:
        //      - At war с besieger
        //      - IsActive
        //      - NOT villager / caravan
        //      - Militia INCLUDED unless town InRebelliousState
        private static IEnumerable<PartyBase> GetDefenderPartiesWithMilitia(
            Town town, MapEvent.BattleTypes battleType)
        {
            yield return town.Settlement.Party;

            var siegeEvent = town.Settlement.SiegeEvent;
            if (siegeEvent?.BesiegerCamp?.MapFaction == null) yield break;
            var besiegerFaction = siegeEvent.BesiegerCamp.MapFaction;

            foreach (MobileParty mobileParty in town.Settlement.Parties)
            {
                if (mobileParty == null) continue;
                if (!mobileParty.MapFaction.IsAtWarWith(besiegerFaction)) continue;
                if (!mobileParty.IsActive) continue;
                if (mobileParty.IsVillager) continue;
                if (mobileParty.IsCaravan) continue;
                // KEY FIX: include militia unless town InRebelliousState.
                // Vanilla excluded militia always (the bug).
                if (mobileParty.IsMilitia && town.InRebelliousState) continue;

                yield return mobileParty.Party;
            }
        }
    }
}
