using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 03.10.2026 21:39:56 — вылет на карте: NRE в ванильном `Army.IsAnotherEnemyBesiegingTarget`
    /// (из `Army.HourlyTick`, только для армий, которые ведёт НЕ игрок). Метод первой строкой
    /// делает `(Settlement)AiBehaviorObject` и читает `.IsUnderSiege` — если лидер армии «осаждает»,
    /// а цель армии пустая, игра падает. Ваниль такое сочетание не создаёт: при смене владельца
    /// крепости она обнуляет цель и останавливает лидера (`AiPartyThinkBehavior`). Его создают
    /// приказы лидеру напрямую — например, наш приказ зрителя «осада» до 03.10 не ставил цель
    /// армии при первой выдаче (исправлено в `PartyOrderHandlers`); могут и чужие моды армий.
    ///
    /// Патч ЧИНИТ вход, а не глушит ошибку: цель армии = цель лидера, ваниль работает дальше.
    /// Если и у лидера цели нет — штатно «другой осаждающий не найден» (false) и запись в лог
    /// с именем лидера, чтобы найти виновника. Kill-switch: имя класса в `SKIP_PATCH_NAMES`.
    /// </summary>
    [HarmonyPatch]
    public static class ArmyObjectiveGuardPatch
    {
        private static MethodBase TargetMethod() =>
            AccessTools.Method(typeof(Army), "IsAnotherEnemyBesiegingTarget");

        private static bool Prepare() => TargetMethod() != null;

        private static bool Prefix(Army __instance, ref bool __result)
        {
            if (__instance == null || __instance.AiBehaviorObject is Settlement) return true;
            var leader = __instance.LeaderParty;
            Settlement target = leader?.TargetSettlement;
            string who = leader?.LeaderHero?.Name?.ToString() ?? leader?.Name?.ToString() ?? "?";
            if (target != null)
            {
                __instance.AiBehaviorObject = target;
                BannerlordLinkModule.Log($"[army-guard] у армии «{who}» лидер осаждает «{target.Name}», а цель армии пустая — "
                    + "цель армии восстановлена (иначе ванильный HourlyTick падает NRE)");
                return true;
            }
            BannerlordLinkModule.Log($"[army-guard] у армии «{who}» лидер в режиме осады без цели и цель армии пустая — "
                + "проверка «другой осаждающий» пропущена (false)");
            __result = false;
            return false;
        }
    }
}
