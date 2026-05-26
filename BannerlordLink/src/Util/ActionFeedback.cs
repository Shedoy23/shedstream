using System;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Sprint 5.29 / BLT-parity #3 — feedback channel для refund.
    ///
    /// Проблема:
    ///   IActionHandler.ExecuteAsync возвращает (success, error) синхронно ДО
    ///   реального Apply (Apply идёт через MainThreadDispatcher.Enqueue на main
    ///   thread). ActionPoller ACK'ает success=true сразу. Когда Apply на main
    ///   thread обнаруживает что нельзя (Mission active, dead hero, нет gold)
    ///   и тихо return'ит — backend уже думает что всё хорошо, viewer уже
    ///   списал крустики, refund не происходит.
    ///
    /// Решение:
    ///   Handler в refuse path вызывает `ActionFeedback.PostFailed(actionId, reason)`.
    ///   Это пушит event `action.failed { action_id, reason }` на backend.
    ///   Backend handler ищет original module_actions row, refund'ит price
    ///   обратно в viewers.points, marks action as refunded.
    ///
    /// Action_id передаётся handler'у через скрытое поле `_action_id` в data dict
    /// (inject'ится в ActionPoller.ProcessActionAsync перед handler call).
    ///
    /// Usage:
    ///   private static void Apply(JObject data) {
    ///       string actionId = data["_action_id"]?.ToString();
    ///       if (Mission.Current != null) {
    ///           ActionFeedback.PostFailed(actionId, "in_mission");
    ///           return;
    ///       }
    ///   }
    ///
    /// Если actionId пустой — silent skip (legacy code или manual invocation).
    /// </summary>
    public static class ActionFeedback
    {
        /// <summary>Push action.failed event для refund. Fire-and-forget.</summary>
        public static void PostFailed(string actionId, string reason)
        {
            if (string.IsNullOrEmpty(actionId)) return;
            try
            {
                string json = JsonConvert.SerializeObject(new
                {
                    action_id = actionId,
                    reason = reason ?? "unspecified",
                });
                Task.Run(async () =>
                {
                    try
                    {
                        await BannerlordLinkModule.Backend
                            .PostEventAsync("bannerlord", "action.failed", json);
                        BannerlordLinkModule.Log(
                            $"[ActionFeedback] REFUND request action_id={actionId} reason={reason}");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[ActionFeedback] post failed: {ex.Message}");
                    }
                });
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[ActionFeedback] PostFailed serialize error: {ex.Message}");
            }
        }

        /// <summary>Extract action_id из JObject (helper). Возвращает "" если нет.</summary>
        public static string GetActionId(JObject data)
        {
            try { return data?["_action_id"]?.ToString() ?? ""; }
            catch { return ""; }
        }
    }
}
