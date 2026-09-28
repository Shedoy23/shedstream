using System.Text.RegularExpressions;

namespace RimLink.Utils
{
    /// <summary>
    /// Общие утилиты для работы со строками пешек и дефов.
    /// </summary>
    internal static class PawnUtils
    {
        private static readonly Regex TagRegex = new Regex(@"<[^>]+>", RegexOptions.Compiled);

        /// <summary>
        /// Удаляет XML/Unity rich-text теги из строки (например &lt;color=#fff&gt;текст&lt;/color&gt;).
        /// </summary>
        public static string StripTags(string s)
        {
            if (string.IsNullOrEmpty(s)) return s ?? "";
            s = TagRegex.Replace(s, "");
            s = s.Replace("&lt;", "<").Replace("&gt;", ">").Replace("&amp;", "&").Replace("&quot;", "\"");
            return s.Trim();
        }
    }
}
