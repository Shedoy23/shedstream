using System;
using System.Collections.Generic;
using System.Linq;
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
        // Sprint 5.32 BUGFIX — раньше использовался compile-time
        // typeof(FightTournamentGame). В Bannerlord 1.3.x метод
        // GetParticipantCharacters остался, но Harmony patch не fired —
        // возможно сигнатура изменилась или есть несколько overload'ов.
        // Теперь используем TargetMethod() с диагностикой + патчим ВСЕ
        // методы с именем GetParticipantCharacters в TournamentGame
        // иерархии (base TournamentGame + subclasses).
        [HarmonyPatch]
        public static class GetParticipantCharactersHook
        {
            public static System.Reflection.MethodBase TargetMethod()
            {
                try
                {
                    // 1. Сначала пробуем direct FightTournamentGame.
                    var t = AccessTools.TypeByName(
                        "TaleWorlds.CampaignSystem.TournamentGames.FightTournamentGame");
                    var m = (t != null) ? AccessTools.Method(t, "GetParticipantCharacters") : null;
                    if (m != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[tournament:patch] target resolved: {t.FullName}.GetParticipantCharacters " +
                            $"(params: {string.Join(",", m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name))})");
                        return m;
                    }
                    // 2. Fallback: assembly scan для любого TournamentGame
                    //    наследника с этим методом.
                    // Sprint 5.32 BLT-parity FIX — раньше scan был EndsWith("TournamentGame"),
                    // который мог зацепить ABSTRACT base class TournamentGame или
                    // TournamentGameBase (engine-internal). Postfix регистрировался
                    // на пустышку — patch fired бы только если кто-то напрямую
                    // вызовет abstract method, что невозможно. Теперь точное Name match.
                    foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
                    {
                        Type[] types;
                        try { types = asm.GetTypes(); }
                        catch { continue; }
                        foreach (var ty in types)
                        {
                            if (ty == null) continue;
                            // STRICT: точное имя класса (BLT pattern — typeof(FightTournamentGame)).
                            if (ty.Name != "FightTournamentGame") continue;
                            var mm = AccessTools.Method(ty, "GetParticipantCharacters");
                            if (mm != null)
                            {
                                BannerlordLinkModule.Log(
                                    $"[tournament:patch] target resolved via scan: " +
                                    $"{ty.FullName}.GetParticipantCharacters " +
                                    $"(asm={asm.GetName().Name})");
                                return mm;
                            }
                        }
                    }
                    BannerlordLinkModule.Log(
                        "[tournament:patch] GetParticipantCharacters не найден — " +
                        "viewers не попадут в bracket. Версия TaleWorlds?");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[tournament:patch] TargetMethod error: {ex.Message}");
                }
                return null;
            }

            [HarmonyPostfix]
            public static void Postfix(Settlement settlement, ref List<CharacterObject> __result)
            {
                try
                {
                    // Sprint 5.32 BLT-parity — Postfix entry лог. BLT (Randomchair22)
                    // делает то же: проверяет live Settlement.CurrentSettlement
                    // в Postfix вместо хранения static settlement в behavior.
                    // Static у нас остаётся как primary (более строгий), но
                    // добавляем CurrentSettlement fallback против race condition
                    // (если ClearStartingFor отстрелил static ДО того как
                    // CreateTournament лениво вызвал GetParticipantCharacters).
                    BannerlordLinkModule.Log(
                        $"[tournament:patch] FIRED: settlement={settlement?.StringId ?? "?"}, " +
                        $"current={Settlement.CurrentSettlement?.StringId ?? "?"}, " +
                        $"static_starting={TournamentQueueBehavior.StartingSettlement?.StringId ?? "?"}, " +
                        $"static_beh={(TournamentQueueBehavior.StartingTournament != null ? "set" : "null")}");

                    var starting = TournamentQueueBehavior.GetStartingFor(settlement);
                    // BLT-parity fallback: если static check не сработал но Settlement
                    // matches live CurrentSettlement И у нас есть StartingTournament
                    // (просто без StartingSettlement) — apply anyway.
                    if (starting == null
                        && TournamentQueueBehavior.StartingTournament != null
                        && settlement != null
                        && settlement == Settlement.CurrentSettlement)
                    {
                        starting = TournamentQueueBehavior.StartingTournament;
                        BannerlordLinkModule.Log(
                            $"[tournament:patch] static settlement mismatch но " +
                            $"CurrentSettlement совпал → используем StartingTournament fallback");
                    }
                    if (starting == null)
                    {
                        if (TournamentQueueBehavior.StartingTournament != null)
                        {
                            BannerlordLinkModule.Log(
                                $"[tournament:patch] SKIPPED: settlement mismatch " +
                                $"(got={settlement?.StringId ?? "?"}, " +
                                $"expected={TournamentQueueBehavior.StartingSettlement?.StringId ?? "?"}, " +
                                $"current={Settlement.CurrentSettlement?.StringId ?? "?"})");
                        }
                        return;
                    }

                    var roster = starting.GetParticipantCharacters();
                    if (roster != null && roster.Count > 0)
                    {
                        __result.Clear();
                        __result.AddRange(roster);
                        BannerlordLinkModule.Log(
                            $"[tournament:patch] roster replaced: {roster.Count} participants " +
                            $"@ {settlement.StringId}");
                    }
                    else
                    {
                        BannerlordLinkModule.Log(
                            $"[tournament:patch] NO REPLACEMENT — roster empty " +
                            $"(starting set но GetParticipantCharacters вернул {roster?.Count ?? -1})");
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
