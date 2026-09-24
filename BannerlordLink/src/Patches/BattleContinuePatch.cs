using HarmonyLib;
using TaleWorlds.CampaignSystem.Encounters;

namespace BannerlordLink.Patches
{
    /// <summary>Проиграл сцену — проиграл и бой (24.09.2026, решение владельца).
    ///
    /// После победы в сцене игра (PlayerEncounter.CheckIfBattleShouldContinueAfterBattleMissionInternal)
    /// продолжает бой, если у проигравших остался хоть один здоровый — те, кто сбежал
    /// с поля, — и снова открывает «Атаковать»: второй бой с остатками, который на
    /// стриме выглядит как «только что победили — и опять бой». Здесь: полевой бой,
    /// выигранный в сцене, считается выигранным — дальше штатный DoWait засчитывает
    /// победу (SetOverrideWinner), судьбу сбежавших решает обычный расчёт итогов.
    /// Наш проигрыш, осады, убежища и морские бои — по правилам игры.
    /// Выключатель: имя класса в SKIP_PATCH_NAMES.</summary>
    [HarmonyPatch(typeof(PlayerEncounter), "CheckIfBattleShouldContinueAfterBattleMissionInternal")]
    internal static class BattleContinuePatch
    {
        [HarmonyPostfix]
        public static void Postfix(CampaignBattleResult campaignBattleResult, ref bool __result)
        {
            if (!__result || campaignBattleResult == null || !campaignBattleResult.PlayerVictory) return;
            var battle = PlayerEncounter.Battle;
            if (battle == null || !battle.IsFieldBattle || battle.IsSiegeAssault
                || battle.IsHideoutBattle || battle.IsNavalMapEvent) return;
            __result = false;
            BannerlordLinkModule.Log("[BattleContinue] победа в сцене — второй бой с бежавшими не запускаем, победа засчитана");
        }
    }
}
