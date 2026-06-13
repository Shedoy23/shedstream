using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem.MapEvents;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-06-13 — defensive finalizer против нативно-фатального
    /// IndexOutOfRangeException в vanilla MapEventParty.OnTroopKilled.
    ///
    /// Crash-дамп (2026-06-13_19.31, в конце стрима) дал стек:
    ///   TroopRoster.AddToCountsAtIndex(...)  ← IndexOutOfRange
    ///   ← TroopRoster.RemoveTroop(...)
    ///   ← MapEventParty.OnTroopKilled(UniqueTroopDescriptor)
    ///   ← MapEventSide/PartyGroupTroopSupplier.OnTroopKilled
    ///   ← PartyGroupAgentOrigin.SetKilled()
    ///   ← BattleAgentLogic.OnAgentRemoved → Agent.Die → HandleBlow
    ///   ← Mission_MeleeHitCallback (бой; боец гибнет от мили-удара)
    ///
    /// ТОТ ЖЕ класс бага, что MapEventWoundedPatch, но на «убитом» пути.
    /// Раненый путь (OnTroopWounded) уже защищён — лог стрима показывает его
    /// рабочим (SWALLOWED ×2); убитый путь не был покрыт → крашнул. Причина та
    /// же: рассинхрон MemberRoster партии с MapEvent (mid-battle summon вьюверов
    /// + retinue, а roster могут менять и сторонние моды). Когда боец из такой
    /// партии гибнет → RemoveTroop лезет по битому индексу.
    ///
    /// Лечим как остальные vanilla-bug краши (Pregnancy/Banner/Wounded pattern):
    /// финалайзер глотает ТОЛЬКО IndexOutOfRange/ArgumentOutOfRange (учёт гибели
    /// ОДНОГО бойца скипается — не фатально, бой продолжается и резолвится),
    /// прочие исключения ре-кидаем.
    ///
    /// Version-safe TargetMethods: yield break если метод не резолвится.
    /// Автоподхват resilient-PatchAll'ом в BannerlordLinkModule.
    /// </summary>
    [HarmonyPatch]
    public static class MapEventKilledPatch
    {
        public static IEnumerable<MethodBase> TargetMethods()
        {
            MethodBase m = null;
            try { m = AccessTools.Method(typeof(MapEventParty), "OnTroopKilled"); }
            catch { }
            if (m == null)
            {
                BannerlordLinkModule.Log(
                    "[MapEventKilled] MapEventParty.OnTroopKilled не найден — patch skip");
                yield break;
            }
            BannerlordLinkModule.Log(
                "[MapEventKilled] finalizer registered (swallows IndexOutOfRange — roster/MapEvent desync crash)");
            yield return m;
        }

        [HarmonyFinalizer]
        public static Exception Finalizer(Exception __exception)
        {
            if (__exception is IndexOutOfRangeException
                || __exception is ArgumentOutOfRangeException)
            {
                BannerlordLinkModule.Log(
                    "[MapEventKilled] SWALLOWED " + __exception.GetType().Name +
                    " в OnTroopKilled (roster/MapEvent desync; учёт гибели бойца " +
                    "skip'нут — не фатально, краш предотвращён)");
                return null;   // swallow — engine continues
            }
            return __exception;   // re-throw all other exception types
        }
    }
}
