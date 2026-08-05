using System;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Bridges handler refusal paths into the tracked action result. While a
    /// game-thread callback is executing, PostFailed marks that callback's
    /// terminal outcome and ActionPoller sends a failure ACK only after Apply
    /// has returned. Calls made later, outside the action scope, fall back to a
    /// durable `action.failed` event for backend compensation.
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
        /// <summary>Capture a tracked failure, or durably queue delayed compensation.</summary>
        public static void PostFailed(string actionId, string reason)
        {
            if (string.IsNullOrEmpty(actionId)) return;

            // Normal path: Apply is currently running inside a tracked
            // MainThreadDispatcher scope. Fold the refusal into the handler
            // result so ActionPoller sends one authoritative failure ACK.
            // The HTTP event remains only for genuinely delayed failures which
            // occur after the original action scope has already completed.
            if (MainThreadDispatcher.TryReportActionFailure(actionId, reason))
            {
                BannerlordLinkModule.Log(
                    $"[ActionFeedback] action failure captured action_id={actionId} reason={reason}");
                return;
            }

            try
            {
                string json = JsonConvert.SerializeObject(new
                {
                    action_id = actionId,
                    reason = reason ?? "unspecified",
                });
                bool queued = BannerlordLinkModule.Backend != null
                    && BannerlordLinkModule.Backend.EnqueueDurableEvent(
                        "bannerlord", "action.failed", json);
                BannerlordLinkModule.Log(
                    $"[ActionFeedback] delayed REFUND request " +
                    $"{(queued ? "queued durably" : "QUEUE FAILED")} " +
                    $"action_id={actionId} reason={reason}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[ActionFeedback] PostFailed serialize error: {ex.Message}");
            }
        }

        /// <summary>2026-07-22 — итог заявки на закон королевства.
        ///
        /// Зачем отдельное событие: ActionPoller ACK'ает action success=true СРАЗУ,
        /// ещё до реальной работы (см. _on_action_failed в адаптере), поэтому по
        /// module_actions нельзя понять, применился закон или нет. Из-за этого
        /// заявки висели в статусе 'pending' вечно: зритель платил 1500💎, закон в
        /// игре принимался, а расширение показывало «на голосовании» и больше не
        /// давало нажать (уникальный индекс по pending). Багрепорт #23.
        ///
        /// enacted=true — закон принят, false — снят (мод работает переключателем).
        /// ВАЖНО: событие обязано быть объявлено в manifest.yaml, иначе бэкенд
        /// отбросит его как event_not_in_manifest ещё до хендлера.</summary>
        public static void PostPolicyResult(string actionId, string policyId, bool enacted)
        {
            if (string.IsNullOrEmpty(actionId)) return;
            try
            {
                string json = JsonConvert.SerializeObject(new
                {
                    action_id = actionId,
                    policy_id = policyId ?? "",
                    enacted = enacted,
                });
                bool queued = BannerlordLinkModule.Backend != null
                    && BannerlordLinkModule.Backend.EnqueueDurableEvent(
                        "bannerlord", "hero.policy_result", json);
                BannerlordLinkModule.Log(
                    $"[ActionFeedback] policy_result " +
                    $"{(queued ? "queued durably" : "QUEUE FAILED")} " +
                    $"action_id={actionId} policy={policyId} enacted={enacted}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[ActionFeedback] PostPolicyResult serialize error: {ex.Message}");
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
