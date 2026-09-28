using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem.MapEvents;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-06-02 — defensive finalizer против нативно-фатального
    /// IndexOutOfRangeException в vanilla MapEventParty.OnTroopWounded.
    ///
    /// Crash-дамп (2 краша подряд, 2026-06-02) дал стек:
    ///   TroopRoster.AddToCountsAtIndex(...)  ← IndexOutOfRange
    ///   ← MapEventParty.OnTroopWounded(UniqueTroopDescriptor)
    ///   ← MapEventSide/PartyGroupTroopSupplier.OnTroopWounded
    ///   ← PartyGroupAgentOrigin.SetWounded()
    ///   ← BattleAgentLogic.OnAgentRemoved → Agent.Die → HandleBlow
    ///   ← Mission_MeleeHitCallback (бой; боец умирает от мили-удара)
    ///
    /// Причина — рассинхрон MemberRoster партии с MapEvent: закэшированные
    /// индексы MapEventParty протухают, когда roster модифицируется ПОКА партия
    /// в активном MapEvent. У нас это mid-battle summon вьюверов + retinue
    /// (SummonHeroHandler), но roster могут менять и сторонние моды (crash_tags:
    /// SmartRecruit / AutoEquipCompanions / both_perks). Когда боец из такой
    /// партии получает ранение/гибнет → OnTroopWounded лезет по битому индексу.
    ///
    /// Лечим как остальные vanilla-bug краши (PregnancyModelPatch / Banner
    /// CampaignBehaviorPatch pattern): финалайзер глотает ТОЛЬКО
    /// IndexOutOfRangeException (учёт ранения ОДНОГО бойца скипается — не
    /// фатально, бой продолжается и резолвится), прочие исключения ре-кидаем.
    /// Защищает независимо от того, чей мод покорраптил roster.
    ///
    /// Version-safe TargetMethods: yield break если метод не резолвится.
    /// Автоподхват resilient-PatchAll'ом в BannerlordLinkModule.
    /// </summary>
    [HarmonyPatch]
    public static class MapEventWoundedPatch
    {
        public static IEnumerable<MethodBase> TargetMethods()
        {
            MethodBase m = null;
            try { m = AccessTools.Method(typeof(MapEventParty), "OnTroopWounded"); }
            catch { }
            if (m == null)
            {
                BannerlordLinkModule.Log(
                    "[MapEventWounded] MapEventParty.OnTroopWounded не найден — patch skip");
                yield break;
            }
            BannerlordLinkModule.Log(
                "[MapEventWounded] finalizer registered (swallows IndexOutOfRange — roster/MapEvent desync crash)");
            yield return m;
        }

        [HarmonyFinalizer]
        public static Exception Finalizer(Exception __exception)
        {
            if (__exception is IndexOutOfRangeException
                || __exception is ArgumentOutOfRangeException)
            {
                BannerlordLinkModule.Log(
                    "[MapEventWounded] SWALLOWED " + __exception.GetType().Name +
                    " в OnTroopWounded (roster/MapEvent desync; учёт ранения бойца " +
                    "skip'нут — не фатально, краш предотвращён)");
                return null;   // swallow — engine continues
            }
            return __exception;   // re-throw all other exception types
        }
    }
}
