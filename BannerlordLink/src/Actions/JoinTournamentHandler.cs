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
    /// Sprint 5.28 change: цена перенесена с in-game динаров на extension
    /// крустики (backend списывает 1000 крустиков с viewer ДО enqueue
    /// action'а). Мод больше НЕ проверяет hero.Gold и НЕ списывает
    /// денары — все записавшиеся попадают в очередь.
    ///
    /// Раньше: viewer кликал «записаться» → списались крустики на backend
    /// → мод проверял hero.Gold ≥ 5000 → если нет, отказ, но крустики
    /// уже списались. Result: 5-6 «записались», только 2 попали в турнир.
    ///
    /// Flow:
    ///   1. Backend списывает 1000 крустиков + enqueue'ит action {target: username}
    ///   2. Mod main-thread: find hero (alive) → AddToQueue
    ///   3. Push event tournament.joined → backend INSERT в queue table
    ///
    /// Если viewer вне Mission (overworld OK), queue работает; в Mission
    /// — skip (нельзя в бою).
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

                // Push event tournament.joined → backend mirror
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    entry_fee = 0,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "tournament.joined", evtData));

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
