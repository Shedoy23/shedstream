using System;
using System.Reflection;
using HarmonyLib;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-07-20 — «Упрямый штурм»: атакующие в осаде не откатываются от стены,
    /// пока не понесут по-настоящему катастрофические потери.
    ///
    /// ПРОБЛЕМА (репорт владельца): «атакующие начинают отступать, когда не могут
    /// подняться на стены» — штурм буксует, ИИ откатывает всех, потом собирается
    /// снова, и так по кругу.
    ///
    /// ПРИЧИНА (декомпайл TacticBreachWalls):
    ///   ShouldRetreat = (Team.QuerySystem.RemainingPowerRatio / StartingPowerRatio)
    ///                    &lt; GetRetreatThresholdRatio(lanes, insideFormationCount)
    /// а порог считается ОТ ПРОГРЕССА штурма и стартует с 1.0, снижаясь за достижения:
    ///   −1.0/кол-во направлений  за каждую формацию, ЗАБРАВШУЮСЯ наверх;
    ///   −0.7/кол-во              за каждое ОТКРЫТОЕ направление;
    ///   −0.4/кол-во              за каждое существующее, но закрытое.
    /// Итог: пока никто не залез и путь закрыт, порог держится ~0.6 — и хватает
    /// потери всего ~40% относительной силы, чтобы вся тактика ушла в отступление.
    /// То есть «не можем залезть» → «нет прогресса» → «порог высокий» → быстрый откат.
    /// Механика вменяемая по замыслу («не кидать людей на неприступную стену»), но
    /// на практике даёт буксующие штурмы.
    ///
    /// РЕШЕНИЕ: фиксированный низкий порог вместо прогресс-зависимого. Штурм идёт до
    /// конца; отступление остаётся только как предохранитель от полного истребления
    /// (иначе бой мог бы длиться вечно при нулевых шансах).
    ///
    /// Реализация — prefix, полностью заменяющий расчёт. Использует ТОЛЬКО публичный
    /// API (TacticComponent.Team, TeamQuerySystem.RemainingPowerRatio), без доступа к
    /// приватному _indicators — так патч переживает обновления игры. Version-safe:
    /// если метод не резолвится, patch тихо пропускается (TargetMethod → null).
    ///
    /// Область действия: ЛЮБАЯ осада в игре (не только с участием зрителей) — это
    /// сознательный выбор владельца: «штурм начался — идёт до конца».
    /// Kill-switch: SKIP_PATCH_NAMES в BannerlordLinkModule.
    /// </summary>
    [HarmonyPatch]
    public static class StubbornAssaultPatch
    {
        /// <summary>Доля ОСТАВШЕЙСЯ силы, ниже которой штурм всё-таки сворачивается.
        /// 0.25 = отступают, только потеряв ~75% — то есть практически «до конца».
        /// Крутилка баланса: поднять (0.35–0.4) если резня выглядит бессмысленной,
        /// опустить (0.15) если хочется совсем упрямых.</summary>
        private const float STUBBORN_RETREAT_RATIO = 0.25f;

        public static MethodBase TargetMethod()
        {
            MethodBase m = null;
            try { m = AccessTools.Method(typeof(TacticBreachWalls), "ShouldRetreat"); }
            catch { }
            if (m == null)
            {
                BannerlordLinkModule.Log(
                    "[StubbornAssault] TacticBreachWalls.ShouldRetreat не найден — patch skip");
            }
            return m;
        }

        [HarmonyPrefix]
        public static bool Prefix(TacticBreachWalls __instance, ref bool __result)
        {
            try
            {
                var team = __instance?.Team;
                if (team?.QuerySystem == null) return true;   // не смогли — отдаём ваниле

                float remaining = team.QuerySystem.RemainingPowerRatio;
                __result = remaining < STUBBORN_RETREAT_RATIO;
                return false;   // ваниль пропускаем: порог теперь наш, прогресс не важен
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[StubbornAssault] prefix warn: {ex.Message}");
                return true;    // любая неожиданность → ванильное поведение
            }
        }
    }
}
