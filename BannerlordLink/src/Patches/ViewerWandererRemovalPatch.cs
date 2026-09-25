using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Герой зрителя без клана не исчезает «сам» (25.09.2026).
    ///
    /// Героя зрителя мод создаёт из шаблона странника (AdoptHeroHandler,
    /// Occupation.Wanderer). Пока у него нет клана, игра считает его ненанятым
    /// странником: CompanionsCampaignBehavior.DailyTick → TryKillCompanion раз в
    /// игровой день с шансом 10% убирает такого через KillCharacterAction.ApplyByRemove
    /// (причина Lost, без сообщения). 25.09 так исчезли logistick1 (14:11) и
    /// kuro_gothic (14:54, 966 тыс.💰) — на дневном тике, без боя; раньше это
    /// скрывало бессмертие зрителей, выключенное 22.09.
    ///
    /// Блокируем только «убрать» (Lost) героя зрителя БЕЗ клана. Смерть в бою,
    /// от старости, казнь и уход вместе с уничтоженным кланом не трогаем —
    /// это решение владельца 22.09 (смерть настоящая).
    /// </summary>
    [HarmonyPatch(typeof(KillCharacterAction), nameof(KillCharacterAction.ApplyByRemove))]
    internal static class ViewerWandererRemovalPatch
    {
        internal static bool Blocks(bool adopted, bool hasClan, bool isAlive) => adopted && !hasClan && isAlive;

        [HarmonyPrefix]
        public static bool Prefix(Hero victim)
        {
            if (victim == null || !Blocks(HeroNaming.IsAdopted(victim), victim.Clan != null, victim.IsAlive)) return true;
            BannerlordLinkModule.Log(
                $"[ViewerWanderer] BLOCKED: игра хотела убрать героя зрителя без клана '{victim.Name}' (ApplyByRemove, как ненанятого странника)");
            return false;
        }
    }
}
