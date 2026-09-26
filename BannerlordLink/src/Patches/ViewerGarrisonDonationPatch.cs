using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem.CampaignBehaviors;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Отряд зрителя не раздаёт бойцов в гарнизоны (26.09.2026).
    ///
    /// Ваниль 1.4.8 (GarrisonTroopsCampaignBehavior.OnSettlementEntered): любой
    /// ИИ-отряд лорда, заходя в крепость СВОЕГО королевства, отдаёт бойцов в
    /// гарнизон, если тот меньше «идеального», и оставляет себе минимум 30
    /// (PartyMinMenNumberAfterDonation). Исключены только крепости клана игрока.
    /// 26.09 замок Гаронтор голосованием ушёл клану зрителя shedoy23 — это
    /// единственная крепость королевства, и отряд shedoy23 после каждого набора
    /// по деревням сдавал бойцов туда: было 100, через несколько дней 30.
    /// Бойцов зритель нанимает за свои динары, а жалование гарнизона тоже идёт
    /// из его золота: замок ни разу с захвата не дал дохода больше нуля.
    ///
    /// Блокируем только отдачу бойцов отрядом героя зрителя. Забор из гарнизона
    /// и отдачу бойцов обычными лордами игры не трогаем.
    /// </summary>
    [HarmonyPatch(typeof(GarrisonTroopsCampaignBehavior), "LeaveTroopsToGarrison")]
    internal static class ViewerGarrisonDonationPatch
    {
        [HarmonyPrefix]
        public static bool Prefix(MobileParty mobileParty, Settlement settlement, int numberOfTroopsToLeave)
        {
            if (mobileParty?.LeaderHero == null || !HeroNaming.IsAdopted(mobileParty.LeaderHero)) return true;
            BannerlordLinkModule.Log(
                $"[GarrisonDonation] BLOCKED: отряд '{mobileParty.LeaderHero.Name}' ({mobileParty.MemberRoster?.TotalManCount} чел.) хотел отдать {numberOfTroopsToLeave} бойцов в гарнизон '{settlement?.Name}'");
            return false;
        }
    }
}
