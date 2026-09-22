using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Util
{
    internal static class HeirEligibility
    {
        internal static bool CanCreateVassal(Hero parent, Hero child)
        {
            return parent != null && parent.IsAlive && parent.Clan != null
                && !parent.Clan.IsEliminated && parent.Clan.Leader == parent
                && child != null && child.IsAlive && !child.IsChild && !child.IsPrisoner
                && (child.Father == parent || child.Mother == parent)
                && child.Clan == parent.Clan && child != parent.Clan.Leader
                && !HeroNaming.IsAdopted(child.Name?.ToString() ?? "");
        }
    }
}
