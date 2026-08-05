using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.12 — `hero.join_kingdom` action. Clan-leader присоединяет
    /// свой clan к существующему королевству (BLT pattern,
    /// KingdomManagement.cs HandleJoinCommand).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • hero — лидер клана
    ///   • clan не в королевстве уже
    ///   • kingdom_name найден
    ///   • Hero.Gold >= JOIN_COST
    ///
    /// Engine API: ChangeKingdomAction.ApplyByJoinToKingdom(clan, kingdom)
    ///
    /// data: {target, kingdom_name}
    /// Cost: 100K Hero.Gold (вступление вассалом).
    /// </summary>
    public class JoinKingdomHandler : IActionHandler
    {
        public string ActionType => "hero.join_kingdom";

        private const int JOIN_COST = 100_000;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string kingdomName = (data["kingdom_name"]?.ToString() ?? "").Trim();
            if (string.IsNullOrEmpty(kingdomName))
                return Task.FromResult<(bool, string)>((false, "kingdom_name required"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, kingdomName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string kingdomName, string actionId)
        {
            Hero chargedHero = null;
            bool charged = false;
            bool committed = false;
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    ActionFeedback.PostFailed(actionId, "hero_prisoner");
                    return;
                }
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: must be clan leader");
                    ActionFeedback.PostFailed(actionId, "not_clan_leader");
                    return;
                }
                if (hero.Clan.Kingdom != null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: уже в kingdom '{hero.Clan.Kingdom.Name}'");
                    ActionFeedback.PostFailed(actionId, "already_in_kingdom");
                    return;
                }

                var all = Kingdom.All;
                if (all == null)
                {
                    ActionFeedback.PostFailed(actionId, "kingdom_list_unavailable");
                    return;
                }
                var target = all.FirstOrDefault(k => k != null &&
                    string.Equals(k.Name?.ToString(), kingdomName, StringComparison.OrdinalIgnoreCase));
                if (target == null)
                {
                    target = all.FirstOrDefault(k => k != null && k.Name != null
                        && k.Name.ToString().IndexOf(kingdomName, StringComparison.OrdinalIgnoreCase) >= 0);
                }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: kingdom '{kingdomName}' не найден");
                    ActionFeedback.PostFailed(actionId, "kingdom_not_found");
                    return;
                }
                if (target.IsEliminated)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: kingdom '{target.Name}' уничтожен");
                    ActionFeedback.PostFailed(actionId, "kingdom_eliminated");
                    return;
                }
                if (hero.Gold < JOIN_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: not enough gold ({hero.Gold} < {JOIN_COST})");
                    ActionFeedback.PostFailed(actionId, "not_enough_gold");
                    return;
                }

                GiveGoldAction.ApplyBetweenCharacters(hero, null, JOIN_COST, true);
                chargedHero = hero;
                charged = true;
                try
                {
                    ChangeKingdomAction.ApplyByJoinToKingdom(hero.Clan, target,
                        showNotification: false);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: ApplyByJoinToKingdom failed: {ex.Message}");
                    RefundCharge(chargedHero, JOIN_COST, username);
                    charged = false;
                    ActionFeedback.PostFailed(actionId, "join_engine_failed");
                    return;
                }

                if (hero.Clan?.Kingdom != target)
                {
                    RefundCharge(chargedHero, JOIN_COST, username);
                    charged = false;
                    ActionFeedback.PostFailed(actionId, "join_postcondition_failed");
                    return;
                }

                // The game mutation is committed once the postcondition holds.
                // Telemetry/home-settlement cleanup must never turn a successful
                // join into a refund.
                charged = false;
                committed = true;

                // 2026-05-31 (audit) — после join у безфиефного клана HomeSettlement
                // остаётся null → роняет ванильный daily-tick. Пешим вьюхам почти
                // всегда 0 фиефов. Reconcile как в BLT KingdomManagement.
                try
                {
                    if (hero.Clan != null && hero.Clan.Fiefs.Count == 0)
                    {
                        hero.Clan.ConsiderAndUpdateHomeSettlement();
                        foreach (var h in hero.Clan.Heroes) h.UpdateHomeSettlement();
                    }
                }
                catch (Exception hsEx)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: home-settlement reconcile warn: {hsEx.Message}");
                }

                BannerlordLinkModule.Log(
                    $"[join_kingdom] @{username}: clan '{hero.Clan.Name}' joined '{target.Name}' " +
                    $"(-{JOIN_COST}💰)");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    kingdom_name = target.Name?.ToString(),
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.kingdom_joined", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                if (charged) RefundCharge(chargedHero, JOIN_COST, username);
                BannerlordLinkModule.Log(
                    $"[join_kingdom] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                if (!committed)
                    ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
            }
        }

        private static void RefundCharge(Hero hero, int amount, string username)
        {
            if (hero == null || amount <= 0) return;
            try
            {
                GiveGoldAction.ApplyBetweenCharacters(null, hero, amount, true);
                BannerlordLinkModule.Log(
                    $"[join_kingdom] @{username}: compensated +{amount} gold after failed join");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[join_kingdom] @{username}: GOLD COMPENSATION FAILED: {ex.Message}");
            }
        }
    }
}
