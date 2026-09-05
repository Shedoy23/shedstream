using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.32 (BLT-parity Detachment) — viewer commands управления своим
    /// hero-agent'ом в Mission (6 базовых + 2026-06-17 рич-приказы skirmish/raid).
    /// Объединены в один файл потому что у всех
    /// идентичный shape: resolve agent → call behavior method → refund если REFUSE.
    ///
    /// Каждый handler:
    ///   1. ExecuteAsync: extract username + actionId; enqueue main-thread work.
    ///   2. Apply: resolve viewer's Hero (via HeroIdentityBehavior → HeroLookup
    ///      fallback), find agent в Mission.Current.Agents (only viewer's hero,
    ///      not retinue), call HeroDetachmentBehavior.Instance.X(agent), refund
    ///      if mission inactive / agent dead / behavior null.
    ///
    /// Pattern из Randomchair22-fork BLT (`BLTHeroDetachmentBehavior.Hold/Charge/...`).
    /// </summary>
    internal static class DetachmentHelper
    {
        /// <summary>Find live agent для viewer's Hero в текущем Mission. Returns
        /// null если viewer не в Mission'е, hero не найден, agent не active.</summary>
        public static Agent FindViewerAgent(string username, out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(username))
            {
                reason = "no_username";
                return null;
            }
            if (Mission.Current == null)
            {
                reason = "no_mission";
                return null;
            }
            var hero = HeroLookup.FindByUsername(username);
            if (hero == null)
            {
                reason = "hero_not_found";
                return null;
            }
            // Iterate Mission.Current.Agents — find hero's spawned agent.
            // Skip retinue (which has same parent username via attribution but
            // different character). Match: agent.Character == hero.CharacterObject.
            try
            {
                foreach (var agent in Mission.Current.Agents)
                {
                    if (agent == null) continue;
                    if (!agent.IsActive()) continue;
                    if (agent.Character == hero.CharacterObject)
                        return agent;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[detachment helper] agent scan crashed: {ex.Message}");
                reason = "scan_error";
                return null;
            }
            reason = "agent_not_spawned";
            return null;
        }

        public static void PostRefund(string actionId, string reason)
        {
            try { ActionFeedback.PostFailed(actionId, reason); }
            catch { }
        }
    }

    // ── 1. Detach ──────────────────────────────────────────────────────────────
    public class DetachHandler : IActionHandler
    {
        public string ActionType => "hero.detach";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null)
                {
                    BannerlordLinkModule.Log($"[detach] REFUSE @{username}: {reason}");
                    DetachmentHelper.PostRefund(actionId, reason);
                    return;
                }
                if (HeroDetachmentBehavior.Instance == null)
                {
                    BannerlordLinkModule.Log($"[detach] REFUSE @{username}: behavior null");
                    DetachmentHelper.PostRefund(actionId, "behavior_null");
                    return;
                }
                if (!HeroDetachmentBehavior.Instance.Detach(agent))
                {
                    DetachmentHelper.PostRefund(actionId, "detach_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 2. Attach ──────────────────────────────────────────────────────────────
    public class AttachHandler : IActionHandler
    {
        public string ActionType => "hero.attach";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null)
                {
                    DetachmentHelper.PostRefund(actionId, reason);
                    return;
                }
                if (HeroDetachmentBehavior.Instance == null)
                {
                    DetachmentHelper.PostRefund(actionId, "behavior_null");
                    return;
                }
                if (!HeroDetachmentBehavior.Instance.IsDetached(agent))
                {
                    BannerlordLinkModule.Log($"[attach] @{username}: уже в parent formation");
                    DetachmentHelper.PostRefund(actionId, "not_detached");
                    return;
                }
                HeroDetachmentBehavior.Instance.Attach(agent);
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 3. Hold ────────────────────────────────────────────────────────────────
    public class HoldHandler : IActionHandler
    {
        public string ActionType => "hero.detach_hold";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null) { DetachmentHelper.PostRefund(actionId, reason); return; }
                if (HeroDetachmentBehavior.Instance == null
                    || !HeroDetachmentBehavior.Instance.Hold(agent))
                {
                    DetachmentHelper.PostRefund(actionId, "hold_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 4. Charge ──────────────────────────────────────────────────────────────
    public class ChargeHandler : IActionHandler
    {
        public string ActionType => "hero.detach_charge";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null) { DetachmentHelper.PostRefund(actionId, reason); return; }
                if (HeroDetachmentBehavior.Instance == null
                    || !HeroDetachmentBehavior.Instance.Charge(agent))
                {
                    DetachmentHelper.PostRefund(actionId, "charge_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 4b. Skirmish (бой-на-расстоянии — standoff + auto-target) ───────────────
    public class SkirmishHandler : IActionHandler
    {
        public string ActionType => "hero.detach_skirmish";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null) { DetachmentHelper.PostRefund(actionId, reason); return; }
                if (HeroDetachmentBehavior.Instance == null
                    || !HeroDetachmentBehavior.Instance.Skirmish(agent))
                {
                    DetachmentHelper.PostRefund(actionId, "skirmish_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 4c. Raid (набег — конная орбита вокруг врага + auto-target) ─────────────
    public class RaidHandler : IActionHandler
    {
        public string ActionType => "hero.detach_raid";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null) { DetachmentHelper.PostRefund(actionId, reason); return; }
                if (HeroDetachmentBehavior.Instance == null
                    || !HeroDetachmentBehavior.Instance.Raid(agent))
                {
                    DetachmentHelper.PostRefund(actionId, "raid_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 5. Walls (siege only) ──────────────────────────────────────────────────
    public class WallsHandler : IActionHandler
    {
        public string ActionType => "hero.detach_walls";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null) { DetachmentHelper.PostRefund(actionId, reason); return; }
                if (HeroDetachmentBehavior.Instance == null
                    || !HeroDetachmentBehavior.Instance.Walls(agent))
                {
                    // Walls REFUSE специфичный — обычно siege_not_active / no_target.
                    // Точнее причину behavior уже залогировал.
                    DetachmentHelper.PostRefund(actionId, "walls_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }

    // ── 6. Gate (siege only) ───────────────────────────────────────────────────
    public class GateHandler : IActionHandler
    {
        public string ActionType => "hero.detach_gate";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                var agent = DetachmentHelper.FindViewerAgent(username, out string reason);
                if (agent == null) { DetachmentHelper.PostRefund(actionId, reason); return; }
                if (HeroDetachmentBehavior.Instance == null
                    || !HeroDetachmentBehavior.Instance.Gate(agent))
                {
                    DetachmentHelper.PostRefund(actionId, "gate_failed");
                    return;
                }
                ActionFeedback.PostApplied(actionId);
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
