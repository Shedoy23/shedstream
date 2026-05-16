using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Helper: найти Hero в игре по viewer's username (имя hero совпадает
    /// с viewer_login после `hero.create` adoption).
    ///
    /// Cache не нужен — Hero.All размер O(хундреди) у поздних саваов,
    /// поиск O(n) acceptable. Если станет hot path — поставим Dictionary.
    /// </summary>
    public static class HeroLookup
    {
        /// <summary>Найти Hero по name == username (case-insensitive).
        /// Returns null если не найден.</summary>
        public static Hero FindByUsername(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            if (Campaign.Current == null) return null;

            return MBObjectManager.Instance
                .GetObjectTypeList<Hero>()
                .FirstOrDefault(h =>
                    h != null &&
                    h.Name != null &&
                    string.Equals(
                        h.Name.ToString(),
                        username,
                        System.StringComparison.OrdinalIgnoreCase));
        }
    }
}
