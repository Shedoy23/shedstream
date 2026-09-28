using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.Library;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 GAP-2 (BLT-parity) — real handler для world.broadcast_message.
    ///
    /// Replaces EchoHandler stub. InformationManager.DisplayMessage показывает
    /// announcement в-game (top-left toast area).
    ///
    /// Payload:
    ///   text       — message body (required)
    ///   color      — info / success / warning / event (optional, default info)
    ///   prefix     — optional prefix label (e.g. "📢 STREAMER:")
    ///
    /// Use case (BLT-parity): стример анонсит viewer'ам что-то prominent,
    /// например "@kuro_gothic стал королём Вландии!" или "💥 EVENT: ambush в 3...2...1".
    /// </summary>
    public class BroadcastMessageHandler : IActionHandler
    {
        public string ActionType => "world.broadcast_message";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string text = (data["text"]?.ToString() ?? "").Trim();
            string colorKey = (data["color"]?.ToString() ?? "info").Trim().ToLowerInvariant();
            string prefix = data["prefix"]?.ToString() ?? "";

            BannerlordLinkModule.Log(
                $"[broadcast ENTRY] color={colorKey} prefix='{prefix}' text='{Truncate(text, 60)}'");

            if (string.IsNullOrEmpty(text))
            {
                BannerlordLinkModule.Log("[broadcast REFUSE] empty text");
                return Task.FromResult<(bool, string)>((false, "text required"));
            }
            // Anti-spam: cap message length (engine может обрезать иначе).
            if (text.Length > 240) text = text.Substring(0, 240) + "...";

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    Color color = ResolveColor(colorKey);
                    string full = string.IsNullOrEmpty(prefix) ? text : $"{prefix} {text}";
                    InformationManager.DisplayMessage(new InformationMessage(full, color));
                    BannerlordLinkModule.Log(
                        $"[broadcast EXIT-OK] '{Truncate(full, 80)}' color={colorKey}");
                    ActionFeedback.PostApplied(actionId);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[broadcast] CRASHED: {ex.GetType().Name}: {ex.Message}");
                    ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
                }
            });
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static Color ResolveColor(string key)
        {
            switch (key)
            {
                case "success": return new Color(0.4f, 0.95f, 0.4f);     // green
                case "warning": return new Color(0.95f, 0.7f, 0.2f);     // orange
                case "danger":
                case "error":   return new Color(0.95f, 0.3f, 0.3f);     // red
                case "event":   return new Color(0.6f, 0.4f, 0.95f);     // purple
                case "gold":    return new Color(0.95f, 0.85f, 0.3f);    // gold
                case "info":
                default:        return new Color(0.85f, 0.85f, 0.95f);   // light grey/blue
            }
        }

        private static string Truncate(string s, int n)
        {
            if (s == null) return "";
            return s.Length <= n ? s : s.Substring(0, n) + "...";
        }
    }
}
