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
