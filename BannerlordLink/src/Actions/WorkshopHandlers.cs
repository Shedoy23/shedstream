using System;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Settlements.Workshops;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity SHOP) — Workshops passive income loop.
    ///
    /// BuyWorkshopHandler:
    ///   1. Resolve viewer.Hero + target Settlement (Town) + WorkshopType.
    ///   2. Найти available Workshop slot в town (или re-purpose существующий).
    ///   3. ApplyByBankruptcy(workshop, viewerHero, type, initialCapital) —
    ///      cleanest path: sets arbitrary owner без MainHero hijack.
    ///   4. ChangeProductionTypeOfWorkshopAction.Apply (если type сменился).
    ///
    /// SellWorkshopHandler:
    ///   - Find workshop by viewer ownership + settlement + type.
    ///   - ApplyByPlayerSelling — engine refund handled.
    ///
    /// WorkshopProfitSyncBehavior:
    ///   - OnDailyTick: for each workshop owned by [BLink] heroes, compute
    ///     net profit since last sync, push event hero.workshop_profit_sync.
    /// </summary>
    public class BuyWorkshopHandler : IActionHandler
    {
        public string ActionType => "hero.buy_workshop";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string settlementId = (data["settlement_id"]?.ToString() ?? "").Trim();
            string settlementName = data["settlement_name"]?.ToString() ?? settlementId;
            string typeId = (data["workshop_type"]?.ToString() ?? "").Trim();
            string typeName = data["workshop_type_name"]?.ToString() ?? typeId;
            int backendWorkshopId = 0;
            try { backendWorkshopId = data["workshop_id"]?.ToObject<int>() ?? 0; } catch { }
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[shop-buy ENTRY] @{username} settlement='{settlementName}' (id={settlementId}) " +
                $"type='{typeName}' (id={typeId}) backend_row={backendWorkshopId} action_id={actionId}");

            if (string.IsNullOrEmpty(username) ||
                string.IsNullOrEmpty(settlementId) ||
                string.IsNullOrEmpty(typeId))
            {
                BannerlordLinkModule.Log("[shop-buy REFUSE] missing required fields");
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            }

            MainThreadDispatcher.Enqueue(() =>
                Apply(username, settlementId, settlementName, typeId, typeName,
                      backendWorkshopId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string settlementId,
            string settlementName, string typeId, string typeName,
            int backendWorkshopId, string actionId)
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

                Settlement settlement = null;
                try { settlement = MBObjectManager.Instance.GetObject<Settlement>(settlementId); }
                catch { }
                if (settlement == null)
                {
                    // Fuzzy fallback by name.
                    string needle = (settlementName ?? "").ToLowerInvariant();
                    if (needle.Length >= 3)
                    {
                        foreach (var s in Settlement.All)
                        {
                            if (s?.IsTown != true) continue;
                            if ((s.Name?.ToString() ?? "").ToLowerInvariant().Contains(needle))
                            { settlement = s; break; }
                        }
                    }
                }
                if (settlement == null || !settlement.IsTown || settlement.Town == null)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-buy] REFUSE @{username}: town '{settlementId}' not found");
                    ActionFeedback.PostFailed(actionId, "town_not_found");
                    return;
                }

                WorkshopType wsType = null;
                try { wsType = MBObjectManager.Instance.GetObject<WorkshopType>(typeId); }
                catch { }
                if (wsType == null)
                {
                    // Fuzzy fallback by name.
                    string needle = (typeName ?? "").ToLowerInvariant();
                    if (needle.Length >= 3)
                    {
                        foreach (var w in WorkshopType.All)
                        {
                            if ((w?.Name?.ToString() ?? "").ToLowerInvariant().Contains(needle))
                            { wsType = w; break; }
                        }
                    }
                }
                if (wsType == null)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-buy] REFUSE @{username}: workshop_type '{typeId}' not found");
                    ActionFeedback.PostFailed(actionId, "type_not_found");
                    return;
                }

                // Find available Workshop slot. Strategy:
                //   1) Pick first workshop в town not owned by Hero.MainHero / our clan
                //   2) ApplyByBankruptcy to transfer ownership to viewer's hero
                //   3) ChangeProductionType if differs
                Workshop target = null;
                foreach (var w in settlement.Town.Workshops)
                {
                    if (w == null) continue;
                    // Skip already owned by our viewers (anti-overlap).
                    if (w.Owner != null && (w.Owner.StringId?.StartsWith("blink_") ?? false))
                        continue;
                    target = w;
                    break;
                }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-buy] REFUSE @{username}: no available slot в {settlement.Name}");
                    ActionFeedback.PostFailed(actionId, "no_slot");
                    return;
                }

                // Compute initial capital — engine default.
                int initialCapital = 0;
                try
                {
                    initialCapital = Campaign.Current.Models.WorkshopModel?.InitialCapital ?? 1000;
                }
                catch { initialCapital = 1000; }

                // Transfer ownership via ApplyByBankruptcy (cleanest cross-hero path).
                try
                {
                    ChangeOwnerOfWorkshopAction.ApplyByBankruptcy(
                        target, hero, wsType, initialCapital);
                }
                catch (Exception ownEx)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-buy] ApplyByBankruptcy crashed: {ownEx.Message} — fallback reflection");
                    // Reflection fallback — direct set Owner + WorkshopType.
                    try
                    {
                        var fOwner = typeof(Workshop).GetField("_owner",
                            BindingFlags.NonPublic | BindingFlags.Instance);
                        fOwner?.SetValue(target, hero);
                    }
                    catch { }
                }
                // Ensure WorkshopType matches viewer choice.
                try
                {
                    if (target.WorkshopType != wsType)
                        ChangeProductionTypeOfWorkshopAction.Apply(target, wsType, false);
                }
                catch (Exception tEx)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-buy] ChangeProductionType warn: {tEx.Message}");
                }

                BannerlordLinkModule.Log(
                    $"[shop-buy] @{username} → «{wsType.Name}» в {settlement.Name} (capital={initialCapital})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[shop-buy] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── SellWorkshopHandler ────────────────────────────────────────────────────
    public class SellWorkshopHandler : IActionHandler
    {
        public string ActionType => "hero.sell_workshop";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string settlementId = (data["settlement_id"]?.ToString() ?? "").Trim();
            string typeId = (data["workshop_type"]?.ToString() ?? "").Trim();
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[shop-sell ENTRY] @{username} settlement={settlementId} type={typeId} " +
                $"action_id={actionId}");

            if (string.IsNullOrEmpty(username))
            {
                BannerlordLinkModule.Log("[shop-sell REFUSE] no username");
                return Task.FromResult<(bool, string)>((false, "no username"));
            }

            MainThreadDispatcher.Enqueue(() => Apply(username, settlementId, typeId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string settlementId,
            string typeId, string actionId)
        {
            try
            {
                if (Campaign.Current == null) { ActionFeedback.PostFailed(actionId, "no_campaign"); return; }
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }

                // Find workshop owned by viewer (filter by settlement + type if provided).
                Workshop target = null;
                foreach (var s in Settlement.All)
                {
                    if (s?.IsTown != true || s.Town == null) continue;
                    if (!string.IsNullOrEmpty(settlementId)
                        && s.StringId != settlementId) continue;
                    foreach (var w in s.Town.Workshops)
                    {
                        if (w?.Owner == hero)
                        {
                            if (!string.IsNullOrEmpty(typeId)
                                && w.WorkshopType?.StringId != typeId) continue;
                            target = w; break;
                        }
                    }
                    if (target != null) break;
                }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-sell] REFUSE @{username}: workshop not found");
                    ActionFeedback.PostFailed(actionId, "not_found");
                    return;
                }

                try
                {
                    // ApplyByPlayerSelling(workshop, newOwner Hero, newType WorkshopType).
                    // Engine handles refund.
                    var randomNotable = target.Settlement?.Notables?.FirstOrDefault();
                    if (randomNotable != null)
                    {
                        ChangeOwnerOfWorkshopAction.ApplyByPlayerSelling(
                            target, randomNotable, target.WorkshopType);
                    }
                    else
                    {
                        // Fallback: just clear ownership.
                        ChangeOwnerOfWorkshopAction.ApplyByBankruptcy(
                            target, Hero.MainHero, target.WorkshopType, 0);
                    }
                    BannerlordLinkModule.Log(
                        $"[shop-sell] @{username} sold workshop в {target.Settlement?.Name}");
                }
                catch (Exception sx)
                {
                    BannerlordLinkModule.Log(
                        $"[shop-sell] sell crashed: {sx.Message}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[shop-sell] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
