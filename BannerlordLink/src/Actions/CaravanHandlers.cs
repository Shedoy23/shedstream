using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Helpers;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Party.PartyComponents;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity CARAVAN) — mobile passive income trilogy closer.
    ///
    /// BuyCaravanHandler:
    ///   - Resolve viewer.Hero + home Settlement (Town).
    ///   - Create caravan via CaravanPartyComponent.CreateCaravanParty(
    ///       owner=viewerHero, home=settlement, template=random by culture).
    ///   - Push event hero.caravan_created с {caravan_id (backend row), party_id (engine StringId)}.
    ///
    /// SellCaravanHandler:
    ///   - Find caravan owned by viewer (filter MobileParty.AllCaravanParties).
    ///   - TransferCaravanOwnership к Hero.MainHero (engine refund handled).
    /// </summary>
    public class BuyCaravanHandler : IActionHandler
    {
        public string ActionType => "hero.buy_caravan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            int caravanId = 0;
            try { caravanId = data["caravan_id"]?.ToObject<int>() ?? 0; } catch { }
            string homeId = (data["home_settlement_id"]?.ToString() ?? "").Trim();
            string homeName = data["home_settlement_name"]?.ToString() ?? homeId;
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[caravan-buy ENTRY] @{username} home='{homeName}' (id={homeId}) " +
                $"caravan_row={caravanId} action_id={actionId}");

            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(homeId) || caravanId <= 0)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy REFUSE] missing fields (user='{username}' home='{homeId}' caravanId={caravanId})");
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            }

            MainThreadDispatcher.Enqueue(() =>
                Apply(username, caravanId, homeId, homeName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, int caravanId,
            string homeId, string homeName, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }

                Settlement home = null;
                try { home = MBObjectManager.Instance.GetObject<Settlement>(homeId); }
                catch { }
                if (home == null)
                {
                    string needle = (homeName ?? "").ToLowerInvariant();
                    if (needle.Length >= 3)
                    {
                        foreach (var s in Settlement.All)
                        {
                            if (s?.IsTown != true) continue;
                            if ((s.Name?.ToString() ?? "").ToLowerInvariant().Contains(needle))
                            { home = s; break; }
                        }
                    }
                }
                if (home == null || !home.IsTown)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] REFUSE @{username}: town '{homeId}' not found");
                    ActionFeedback.PostFailed(actionId, "town_not_found");
                    return;
                }

                // Get random caravan template для culture home settlement'а.
                PartyTemplateObject template = null;
                try
                {
                    template = CaravanHelper.GetRandomCaravanTemplate(
                        home.Culture, false, false);
                }
                catch (Exception tEx)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] template fetch failed: {tEx.Message}");
                }
                if (template == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_template");
                    return;
                }

                // Create caravan party. Signature 1.3.x:
                // CreateCaravanParty(owner, home, template, isElite, ownerLeader, itemRoster, isInitial)
                MobileParty caravan = null;
                try
                {
                    caravan = CaravanPartyComponent.CreateCaravanParty(
                        hero, home, template, false, null, null, false);
                }
                catch (Exception cEx)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-buy] CreateCaravanParty crashed: {cEx.Message}");
                    ActionFeedback.PostFailed(actionId, "create_failed");
                    return;
                }
                if (caravan == null)
                {
                    ActionFeedback.PostFailed(actionId, "create_returned_null");
                    return;
                }

                BannerlordLinkModule.Log(
                    $"[caravan-buy] @{username} → caravan id={caravan.StringId} home={home.Name}");

                // Push event с engine StringId → backend backfill.
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    caravan_id = caravanId,
                    party_id   = caravan.StringId,
                    owner      = username,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.caravan_created", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-buy] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── SellCaravanHandler ─────────────────────────────────────────────────────
    public class SellCaravanHandler : IActionHandler
    {
        public string ActionType => "hero.sell_caravan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string partyId = (data["party_id"]?.ToString() ?? "").Trim();
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[caravan-sell ENTRY] @{username} party_id={partyId} action_id={actionId}");

            if (string.IsNullOrEmpty(username))
            {
                BannerlordLinkModule.Log("[caravan-sell REFUSE] no username");
                return Task.FromResult<(bool, string)>((false, "no username"));
            }

            MainThreadDispatcher.Enqueue(() => Apply(username, partyId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string partyId, string actionId)
        {
            try
            {
                if (Campaign.Current == null) { ActionFeedback.PostFailed(actionId, "no_campaign"); return; }
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }

                MobileParty target = null;
                foreach (var mp in MobileParty.AllCaravanParties)
                {
                    if (mp == null || !mp.IsCaravan) continue;
                    if (!string.IsNullOrEmpty(partyId) && mp.StringId != partyId) continue;
                    if (mp.LeaderHero == hero || mp.Owner == hero)
                    { target = mp; break; }
                }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-sell] REFUSE @{username}: caravan не найден (party_id={partyId})");
                    ActionFeedback.PostFailed(actionId, "not_found");
                    return;
                }

                try
                {
                    // Transfer ownership to MainHero — engine refund logic.
                    var homeS = target.HomeSettlement;
                    CaravanPartyComponent.TransferCaravanOwnership(
                        target, Hero.MainHero, homeS);
                    BannerlordLinkModule.Log(
                        $"[caravan-sell] @{username} → transfer to MainHero (home={homeS?.Name})");
                }
                catch (Exception sx)
                {
                    BannerlordLinkModule.Log(
                        $"[caravan-sell] crashed: {sx.Message}");
                    ActionFeedback.PostFailed(actionId, "transfer_failed");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[caravan-sell] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── PayCaravanRescueHandler — backend-only side, but mod может pre-validate.
    // (Actually pay_ransom/pay_caravan_rescue handled fully backend-side; no mod
    // action needed. Backend re-issues hero.buy_caravan when pool full.)
    // Removed — no C# handler registered for hero.pay_caravan_rescue.
}
