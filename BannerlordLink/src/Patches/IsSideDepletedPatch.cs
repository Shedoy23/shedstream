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
    // Sprint 5.32 ROBUST FIX — было `[HarmonyPatch(typeof(MissionAgentSpawnLogic), "IsSideDepleted")]`.
    // Hard typeof reference throw'ит при load если type / method missing в текущей версии
    // TaleWorlds. Переписали на `[HarmonyPatch]` + `TargetMethods()` — gracefully skip
    // если method не resolved.
    [HarmonyPatch]
    public static class IsSideDepletedPatch
    {
        public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
            TargetMethods()
        {
            // 2026-09-02 (1.4.8): класс ПЕРЕИМЕНОВАН —
            // MissionAgentSpawnLogic → DefaultBattleMissionAgentSpawnLogic.
            // Метод и смысл те же: IsSideDepleted(BattleSideEnum).
            // Проверено списком классов сборки, а не догадкой: grep по бинарнику
            // находил старое имя как ПОДСТРОКУ нового и уводил в сторону.
            //
            // Имена перебираем по порядку — новое первым. Так мод остаётся
            // рабочим и на 1.3.15, если придётся откатить игру: откат мы держим
            // как реальный вариант (`BANNERLORD_COMPAT_MATRIX.md`).
            System.Type t = null;
            string resolvedName = null;
            foreach (var candidate in new[]
                     {
                         "TaleWorlds.MountAndBlade.DefaultBattleMissionAgentSpawnLogic", // 1.4.8+
                         "TaleWorlds.MountAndBlade.MissionAgentSpawnLogic",              // 1.3.15
                     })
            {
                t = AccessTools.TypeByName(candidate);
                if (t != null) { resolvedName = candidate; break; }
            }
            if (t == null)
            {
                BannerlordLinkModule.Log(
                    "[IsSideDepleted] ни DefaultBattleMissionAgentSpawnLogic, ни "
                    + "MissionAgentSpawnLogic не найдены — patch skip");
                yield break;
            }
            var m = AccessTools.Method(t, "IsSideDepleted");
            if (m == null)
            {
                BannerlordLinkModule.Log(
                    "[IsSideDepleted] method IsSideDepleted не найден — patch skip");
                yield break;
            }
            BannerlordLinkModule.Log(
                "[IsSideDepleted] postfix registered на " + resolvedName
                + " (anti-depletion для adopted heroes)");
            yield return m;
        }

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
