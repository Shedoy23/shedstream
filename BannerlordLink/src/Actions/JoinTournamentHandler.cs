using System;
using System.Threading.Tasks;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.3 — `hero.join_tournament` action handler.
    ///
    /// Registration is free. AddToQueue acknowledges existing membership and
    /// publishes the game-owned queue; retries never duplicate a hero.
    /// New registrations require the campaign map (not a running mission).
    /// </summary>
    public class JoinTournamentHandler : IActionHandler
    {
        public string ActionType => "hero.join_tournament";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString()
                            ?? data["initiated_by"]?.ToString()
                            ?? "").Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Join(username, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Join(string username, string actionId)
        {
            try
            {
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] REFUSE @{username}: нельзя в Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] REFUSE @{username}: hero не найден / мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                var queue = TournamentQueueBehavior.Current;
                if (queue == null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] REFUSE @{username}: TournamentQueueBehavior null");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "queue_unavailable");
                    return;
                }

                var (ok, message) = queue.AddToQueue(username, 0);
                if (!ok)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] REFUSE @{username}: {message}");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "queue_reject:" + message);
                    return;
                }

                BannerlordLinkModule.Log(
                    $"[join_tournament] @{username} joined queue ({message})");
                BannerlordLink.Util.ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[join_tournament] @{username} CRASHED: " +
                    $"{ex.GetType().Name}: {ex.Message}");
                BannerlordLink.Util.ActionFeedback.PostFailed(
                    actionId, "exception:" + ex.GetType().Name);
            }
        }
    }
}
