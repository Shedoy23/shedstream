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
                Task.Run(async () =>
                {
                    try
                    {
                        await BannerlordLinkModule.Backend
                            .PostEventAsync("bannerlord", "hero.policy_result", json);
                        BannerlordLinkModule.Log(
                            $"[ActionFeedback] policy_result action_id={actionId} " +
                            $"policy={policyId} enacted={enacted}");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[ActionFeedback] policy_result post failed: {ex.Message}");
                    }
                });
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
