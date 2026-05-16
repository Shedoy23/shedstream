using System;
using System.Linq;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Helper: найти Hero в игре по viewer's username (имя hero совпадает
    /// с viewer_login после `hero.create` adoption).
    ///
    /// Источник: Campaign.Current.AliveHeroes (включая wanderer'ов в towns).
    /// MBObjectManager.GetObjectTypeList<Hero>() возвращал null —
    /// Hero registers иначе чем CharacterObject.
    /// </summary>
    public static class HeroLookup
    {
        public static Hero FindByUsername(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            if (Campaign.Current == null) return null;

            // AliveHeroes — все живые heroes (wanderers + nobles + companions).
            // Для dead heroes — будет TODO Sprint 3.3+ когда понадобится respawn.
            var alive = Campaign.Current.AliveHeroes;
            if (alive == null) return null;

            foreach (var h in alive)
            {
                if (h?.Name == null) continue;
                if (string.Equals(h.Name.ToString(), username,
                        StringComparison.OrdinalIgnoreCase))
                    return h;
            }
            return null;
        }
    }
}
