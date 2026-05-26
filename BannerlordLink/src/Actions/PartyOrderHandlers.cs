using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity SIEGE) — Party order strategic management.
    ///
    /// Backend payload: {order_type, target_settlement_id, target_settlement_name}.
    /// order_type: siege / defend / raid / garrison / patrol / release.
    ///
    /// Logic: resolve viewer.Hero → его MobileParty → engine SetMove* API.
    /// Если viewer не leader его clan'а — REFUSE. Если settlement не at war —
    /// REFUSE для siege/raid.
    ///
    /// Note: Bannerlord 1.3.x не имеет sticky-order API — мы выставляем move
    /// goal один раз, engine AI может дрейфовать на следующих ticks. Для
    /// настоящей persistent behavior нужен дополнительный MissionBehavior с
    /// hourly re-issue (PartyOrderBehavior — followup sprint).
    /// </summary>
    public class SetPartyOrderHandler : IActionHandler
    {
        public string ActionType => "hero.party_order_set";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string orderType = (data["order_type"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string targetId = (data["target_settlement_id"]?.ToString() ?? "").Trim();
            string targetName = data["target_settlement_name"]?.ToString() ?? targetId;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
                Apply(username, orderType, targetId, targetName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string orderType, string targetId,
            string targetName, string actionId)
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
                    BannerlordLinkModule.Log(
                        $"[party_order] REFUSE @{username}: hero не найден / мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }

                var mp = hero.PartyBelongedTo;
                if (mp == null)
                {
                    BannerlordLinkModule.Log(
                        $"[party_order] REFUSE @{username}: hero без MobileParty");
                    ActionFeedback.PostFailed(actionId, "no_party");
                    return;
                }

                Settlement target = null;
                // 1) Try direct StringId lookup (preferred, deterministic)
                if (!string.IsNullOrEmpty(targetId))
                {
                    try { target = MBObjectManager.Instance.GetObject<Settlement>(targetId); }
                    catch { }
                }
                // 2) Fuzzy-name fallback — user typed a settlement name like "Lycaron"
                //    instead of StringId. BLT-style: case-insensitive contains match.
                if (target == null)
                {
                    string needle = (targetName ?? targetId ?? "").Trim().ToLowerInvariant();
                    if (needle.Length >= 3)
                    {
                        try
                        {
                            foreach (var s in Settlement.All)
                            {
                                if (s == null) continue;
                                string nm = (s.Name?.ToString() ?? "").ToLowerInvariant();
                                if (nm.Equals(needle) || nm.Contains(needle))
                                {
                                    target = s;
                                    break;
                                }
                            }
                        }
                        catch { }
                    }
                }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[party_order] REFUSE @{username}: settlement '{targetId}'/'{targetName}' not found");
                    ActionFeedback.PostFailed(actionId, "settlement_not_found");
                    return;
                }

                // War check для siege/raid — если не воюем с владельцем, no-op.
                bool requiresWar = orderType == "siege" || orderType == "raid";
                if (requiresWar)
                {
                    try
                    {
                        var heroFaction = hero.MapFaction;
                        var targetFaction = target.MapFaction;
                        if (heroFaction != null && targetFaction != null
                            && !heroFaction.IsAtWarWith(targetFaction))
                        {
                            BannerlordLinkModule.Log(
                                $"[party_order] REFUSE @{username}: не воюем с '{targetName}' " +
                                $"({targetFaction.Name})");
                            ActionFeedback.PostFailed(actionId, "not_at_war");
                            return;
                        }
                    }
                    catch (Exception wEx)
                    {
                        BannerlordLinkModule.Log(
                            $"[party_order] war-check warn: {wEx.Message}");
                    }
                }

                // 1.3.x требует NavigationType — Default = ground-only, mod sane default.
                var navType = MobileParty.NavigationType.Default;
                switch (orderType)
                {
                    case "siege":
                        // Engine API: MobileParty.SetMoveBesiegeSettlement (1.3.x).
                        // Если не leader — engine REFUSE'нет на native side.
                        mp.SetMoveBesiegeSettlement(target, navType);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{username} → SIEGE '{targetName}'");
                        break;
                    case "defend":
                        // SetMoveDefendSettlement(settlement, isTargetingPort, navType)
                        mp.SetMoveDefendSettlement(target, false, navType);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{username} → DEFEND '{targetName}'");
                        break;
                    case "raid":
                        if (target.IsVillage)
                        {
                            mp.SetMoveRaidSettlement(target, navType);
                            BannerlordLinkModule.Log(
                                $"[party_order] @{username} → RAID '{targetName}'");
                        }
                        else
                        {
                            BannerlordLinkModule.Log(
                                $"[party_order] REFUSE @{username}: raid требует village ('{targetName}' — не village)");
                            ActionFeedback.PostFailed(actionId, "raid_needs_village");
                            return;
                        }
                        break;
                    case "garrison":
                        // SetMoveGoToSettlement(settlement, navType, isTargetingPort)
                        mp.SetMoveGoToSettlement(target, navType, false);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{username} → GARRISON '{targetName}'");
                        break;
                    case "patrol":
                        // Engine has dedicated SetMovePatrolAroundSettlement — perfect!
                        mp.SetMovePatrolAroundSettlement(target, navType, false);
                        BannerlordLinkModule.Log(
                            $"[party_order] @{username} → PATROL near '{targetName}'");
                        break;
                    default:
                        BannerlordLinkModule.Log(
                            $"[party_order] REFUSE @{username}: unknown order '{orderType}'");
                        ActionFeedback.PostFailed(actionId, "unknown_order");
                        return;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[party_order.set] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── ReleasePartyOrderHandler — clear AI behavior, fall back to default ─────
    public class ReleasePartyOrderHandler : IActionHandler
    {
        public string ActionType => "hero.party_order_release";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string actionId)
        {
            try
            {
                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null) return;
                var mp = hero.PartyBelongedTo;
                if (mp == null) return;
                try
                {
                    // Reset AI к default. Engine continues autonomous behavior.
                    mp.SetMoveModeHold();
                    BannerlordLinkModule.Log(
                        $"[party_order] @{username} → RELEASE (AI default)");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[party_order.release] warn: {ex.Message}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[party_order.release] crash: {ex.Message}");
            }
        }
    }
}
