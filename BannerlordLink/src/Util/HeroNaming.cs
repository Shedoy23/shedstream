using System;
using TaleWorlds.Localization;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Standard naming для adopted hero'ев:
    ///   full name  = "[BLink] {viewer_login}"
    ///   first name = "{viewer_login}"
    ///
    /// Префикс [BLink] позволяет:
    ///   • Визуально различать наших heroes в-игре (encyclopedia, party screen)
    ///   • Filter'овать payload в heroes_snapshot (2000 vanilla heroes → 10
    ///     adopted) — резко меньше network noise
    ///   • Избежать false-positive collision если vanilla hero носит то же
    ///     имя что и viewer (e.g. реальный NPC "Sven" vs viewer "sven")
    ///
    /// FirstName остаётся без префикса — engine использует firstName в
    ///   menus / dialogs (видно "shedoy23" без [BLink] tag).
    /// </summary>
    public static class HeroNaming
    {
        public const string PREFIX = "[BLink] ";

        /// <summary>Format: (fullName "[BLink] username", firstName "username").</summary>
        public static (TextObject full, TextObject first) Format(string viewerLogin)
        {
            string clean = (viewerLogin ?? "").Trim();
            return (
                new TextObject(PREFIX + clean),
                new TextObject(clean));
        }

        /// <summary>True если display name начинается с [BLink] prefix.</summary>
        public static bool IsAdopted(string displayName)
        {
            return !string.IsNullOrEmpty(displayName)
                && displayName.StartsWith(PREFIX, StringComparison.Ordinal);
        }

        /// <summary>2026-05-29 Stage 3 (BLT-RC22 pattern) — Hero overload для
        /// permadeath prevention patches. Reads hero.Name.ToString() и применяет
        /// IsAdopted(string) check. Null-safe.
        ///
        /// Используется в Patches/AdoptedHeroDeathPatch.cs для filter на
        /// KillCharacterAction.ApplyInternal + Mission.OnAgentRemoved.</summary>
        public static bool IsAdopted(TaleWorlds.CampaignSystem.Hero hero)
        {
            if (hero?.Name == null) return false;
            return IsAdopted(hero.Name.ToString());
        }

        /// <summary>
        /// Извлекает viewer login (lowercase) из adopted hero name.
        /// Только для имён С [BLink] префиксом — возвращает null для vanilla NPC.
        ///
        /// Sprint 5.32 BUGFIX — раньше возвращал name.ToLowerInvariant() даже
        /// для НЕ-adopted heroes ("backwards-compat" с pre-Sprint 5.27 legacy
        /// без prefix). Эта лояльность ломала filter в OnHeroKilled и др.:
        ///   `if (string.IsNullOrEmpty(extracted)) skip` пропускал vanilla
        /// NPC через filter → пушился player.died event для случайных
        /// vanilla смертей ("Lost" detail). А legacy без префикса давно не
        /// существует — все adopted'ы с Sprint 5.27 имеют [BLink].
        ///
        /// Использование:
        ///   "[BLink] Shedoy23" → "shedoy23"
        ///   "Денос из Лартис"  → null  (vanilla NPC — skip)
        /// </summary>
        public static string ExtractUsername(string displayName)
        {
            if (string.IsNullOrEmpty(displayName)) return null;
            string trimmed = displayName.Trim();
            if (!trimmed.StartsWith(PREFIX, StringComparison.Ordinal))
                return null;   // не наш — vanilla NPC или что-то ещё
            string login = trimmed.Substring(PREFIX.Length).Trim();
            if (string.IsNullOrEmpty(login)) return null;
            return login.ToLowerInvariant();
        }
    }
}
