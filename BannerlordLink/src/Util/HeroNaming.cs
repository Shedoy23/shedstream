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

        /// <summary>
        /// Извлекает viewer login (lowercase) из adopted hero name.
        /// Поддерживает оба формата для backwards-compat:
        ///   "[BLink] Shedoy23" → "shedoy23"
        ///   "shedoy23"          → "shedoy23"  (old style без prefix)
        /// Используется во всех handlers/behaviors которые resolve username
        /// из agent.Character.HeroObject.Name.
        /// </summary>
        public static string ExtractUsername(string displayName)
        {
            if (string.IsNullOrEmpty(displayName)) return null;
            string trimmed = displayName.Trim();
            if (trimmed.StartsWith(PREFIX, StringComparison.Ordinal))
                trimmed = trimmed.Substring(PREFIX.Length).Trim();
            return trimmed.ToLowerInvariant();
        }
    }
}
