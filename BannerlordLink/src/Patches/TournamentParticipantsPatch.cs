using System;
using System.Collections.Generic;
using BannerlordLink.Behaviors;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.TournamentGames;
using TaleWorlds.MountAndBlade;
using SandBox.Tournaments.MissionLogics;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 5.3 — Harmony patches для tournament integration.
    ///
    /// Два patch'а:
    ///   1. FightTournamentGame.GetParticipantCharacters Postfix —
    ///      перехватываем roster и заменяем на наш (queued adopted heroes
    ///      + filler troops). Срабатывает только если TournamentQueueBehavior
    ///      инициировал tournament (StartingTournament != null).
    ///
    ///   2. TournamentBehavior.EndCurrentMatch Postfix —
    ///      перехватываем end of round чтобы выдать per-round rewards
    ///      (Hero.Gold/XP для round winners) + push tournament.round_ended.
    ///
    /// Clean-room re-impl BLT pattern (BLT-v5.2.4 BLTTournamentMissionBehavior).
    /// Numeric values / structure отличаются.
    /// </summary>
    public static class TournamentParticipantsPatch
    {
        [HarmonyPatch(typeof(FightTournamentGame), nameof(FightTournamentGame.GetParticipantCharacters))]
        public static class GetParticipantCharactersHook
        {
            [HarmonyPostfix]
            public static void Postfix(Settlement settlement, ref List<CharacterObject> __result)
            {
                try
                {
                    var starting = TournamentQueueBehavior.StartingTournament;
                    if (starting == null) return;
                    if (Settlement.CurrentSettlement != settlement) return;

                    var roster = starting.GetParticipantCharacters();
                    if (roster != null && roster.Count > 0)
                    {
                        __result.Clear();
                        __result.AddRange(roster);
                        BannerlordLinkModule.Log(
                            $"[tournament:patch] roster replaced: {roster.Count} participants");
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[tournament:patch] GetParticipantCharacters error: {ex.Message}");
                }
            }
        }

        [HarmonyPatch(typeof(TournamentBehavior), "EndCurrentMatch")]
        public static class EndCurrentMatchHook
        {
            [HarmonyPostfix]
            public static void Postfix(TournamentBehavior __instance)
            {
                try
                {
                    if (Mission.Current == null) return;
                    var tb = Mission.Current.GetMissionBehavior<TournamentMissionBehavior>();
                    tb?.HandleMatchEnd(__instance);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[tournament:patch] EndCurrentMatch error: {ex.Message}");
                }
            }
        }
    }
}
