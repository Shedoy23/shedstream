using System;
using System.Linq;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Find Hero by viewer's username. Adopted heroes named "[BLink] {login}"
    /// (M22 v3). HeroNaming.ExtractUsername strip'ит prefix → match lowercase
    /// viewer login.
    ///
    /// Backwards compat: heroes без префикса тоже match'атся (legacy).
    /// </summary>
    public static class HeroLookup
    {
        public static Hero FindByUsername(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            if (Campaign.Current == null) return null;

            // Sprint 5.32 (BLT-parity M9) — first attempt через persistent dict.
            // HeroIdentityBehavior сохраняет heroId→username через SyncData,
            // что resilient к engine rename (clan promotion / retirement /
            // vanilla переименования). Если dict содержит mapping — instant
            // hit без linear scan AliveHeroes (O(1)).
            try
            {
                var dictHero = BannerlordLink.Behaviors.HeroIdentityBehavior.Instance
                    ?.FindByUsername(username);
                if (dictHero != null) return dictHero;
            }
            catch { /* fallback к name-scan ниже */ }

            // Legacy / fallback path: scan через name-substring. Покрывает
            // saves до 5.32 пока bootstrap не отработал, плюс safety net
            // если registration в AdoptHeroHandler не сработал.
            var alive = Campaign.Current.AliveHeroes;
            if (alive == null) return null;

            string target = username.ToLowerInvariant();
            foreach (var h in alive)
            {
                if (h?.Name == null) continue;
                var extracted = HeroNaming.ExtractUsername(h.Name.ToString());
                if (string.Equals(extracted, target, StringComparison.OrdinalIgnoreCase))
                    return h;
            }
            return null;
        }
    }
}
