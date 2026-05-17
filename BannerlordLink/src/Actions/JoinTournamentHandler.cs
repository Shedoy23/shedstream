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
    /// Flow:
    ///   1. Backend enqueue'ит action {target: username, hero_gold_cost: 5000}
    ///   2. Mod main-thread: find hero, check Hero.Gold ≥ entry_fee
    ///   3. Deduct gold + AddToQueue(username, fee)
    ///   4. Push event tournament.joined → backend INSERT в queue table
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

            int entryFee = (int?)data["hero_gold_cost"]
                        ?? TournamentQueueBehavior.ENTRY_FEE_GOLD;

            MainThreadDispatcher.Enqueue(() => Join(username, entryFee));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Join(string username, int entryFee)
        {
            try
            {
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] @{username}: skip — нельзя в Mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] @{username}: hero не найден / мёртв");
                    return;
                }

                if (hero.Gold < entryFee)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] @{username}: not enough gold " +
                        $"({hero.Gold} < {entryFee})");
                    return;
                }

                var queue = TournamentQueueBehavior.Current;
                if (queue == null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] @{username}: TournamentQueueBehavior null");
                    return;
                }

                var (ok, message) = queue.AddToQueue(username, entryFee);
                if (!ok)
                {
                    BannerlordLinkModule.Log(
                        $"[join_tournament] @{username}: {message}");
                    return;
                }

                // Deduct Hero.Gold
                GiveGoldAction.ApplyBetweenCharacters(hero, null, entryFee, true);

                // Push event tournament.joined → backend mirror
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    entry_fee = entryFee,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "tournament.joined", evtData));

                // Push hero state sync — gold changed
                HeroStateSync.Push(hero);

                BannerlordLinkModule.Log(
                    $"[join_tournament] @{username} joined queue " +
                    $"(-{entryFee}💰, gold={hero.Gold}, {message})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[join_tournament] @{username} CRASHED: " +
                    $"{ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
