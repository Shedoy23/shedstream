using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Roster;

namespace BannerlordLink.Util
{
    /// <summary>Инвентарь героя-зрителя — только инвентарь отряда, который он САМ ведёт
    /// (багрепорт #66, 24.09.2026).
    ///
    /// Было: `hero.PartyBelongedTo.ItemRoster` — отряд, где герой сейчас числится.
    /// Призванный в бой стримера или идущий в чужом отряде герой покупал «в инвентарь»
    /// и снимал вещи в ЧУЖОЙ инвентарь: 22.09 легендарная булава (60 000💎 перековки)
    /// ушла так и пропала. Теперь в чужом отряде герой — как герой без отряда:
    /// покупка сразу в слот, снятое сдаётся в зачёт, чужой инвентарь не трогается.</summary>
    internal static class OwnPartyInventory
    {
        internal static ItemRoster Of(Hero hero)
        {
            if (hero == null || hero.IsPrisoner) return null;
            var party = hero.PartyBelongedTo;
            return party != null && party.LeaderHero == hero ? party.ItemRoster : null;
        }
    }
}
