using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Party.PartyComponents;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Library;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 GAP-4 (BLT-parity) — real handler для world.trigger_event.
    ///
    /// Replaces EchoHandler stub. Spawns engine-native event near MainHero
    /// (или near target hero если username provided).
    ///
    /// Supported kinds:
    ///   looters         — spawn LooterParty (8-12 looters) near hero
    ///   bandits_easy    — spawn weak BanditParty (10-15 culture-local bandits)
    ///   bandits_strong  — spawn strong BanditParty (20-30 bandits)
    ///
    /// Payload:
    ///   kind            — required (one of above)
    ///   target_username — optional, default Hero.MainHero
    ///   distance        — optional float, default 5.0 map units offset
    ///
    /// NB: requires Campaign-mode active (no Mission). Engine refuses spawn
    /// если Hero не на world map (e.g. в town menu / Mission).
    /// </summary>
    public class TriggerWorldEventHandler : IActionHandler
    {
        public string ActionType => "world.trigger_event";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string kind = (data["kind"]?.ToString() ?? "looters").Trim().ToLowerInvariant();
            string targetUser = (data["target_username"]?.ToString() ?? "").Trim().ToLowerInvariant();
            float distance = 5.0f;
            try { distance = (float)(data["distance"]?.ToObject<double>() ?? 5.0); } catch { }
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[trigger_event ENTRY] kind={kind} target=@{targetUser} distance={distance:F1} " +
                $"action_id={actionId}");

            MainThreadDispatcher.Enqueue(() => Apply(kind, targetUser, distance, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string kind, string targetUser, float distance, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    BannerlordLinkModule.Log("[trigger_event REFUSE] no Campaign");
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                // Resolve anchor hero.
                Hero anchor = null;
                if (!string.IsNullOrEmpty(targetUser))
                {
                    anchor = HeroLookup.FindByUsername(targetUser);
                }
                if (anchor == null) anchor = Hero.MainHero;
                if (anchor?.PartyBelongedTo == null)
                {
                    BannerlordLinkModule.Log(
                        $"[trigger_event REFUSE] anchor hero has no MobileParty (in settlement?)");
                    ActionFeedback.PostFailed(actionId, "no_party");
                    return;
                }

                var anchorParty = anchor.PartyBelongedTo;
                Vec2 pos = anchorParty.GetPosition2D;
                // Offset randomly: pick a direction по unit circle.
                float angle = (float)(new Random().NextDouble() * Math.PI * 2.0);
                var spawnPos = new Vec2(
                    pos.x + (float)Math.Cos(angle) * distance,
                    pos.y + (float)Math.Sin(angle) * distance);

                // Find nearest settlement (для looter homeSettlement parameter).
                Settlement nearest = null;
                float bestDist = float.MaxValue;
                foreach (var s in Settlement.All)
                {
                    if (s == null) continue;
                    Vec2 sp;
                    try { sp = s.GatePosition.ToVec2(); } catch { continue; }
                    float d = sp.Distance(pos);
                    if (d < bestDist) { bestDist = d; nearest = s; }
                }

                MobileParty spawned = null;
                switch (kind)
                {
                    case "looters":
                        spawned = SpawnLooters(spawnPos, nearest, anchorParty);
                        break;
                    case "bandits_easy":
                    case "bandits":
                        spawned = SpawnBandits(spawnPos, anchorParty, easy: true);
                        break;
                    case "bandits_strong":
                        spawned = SpawnBandits(spawnPos, anchorParty, easy: false);
                        break;
                    default:
                        BannerlordLinkModule.Log(
                            $"[trigger_event REFUSE] unknown kind='{kind}' (looters/bandits/bandits_strong)");
                        ActionFeedback.PostFailed(actionId, "unknown_kind");
                        return;
                }

                if (spawned == null)
                {
                    BannerlordLinkModule.Log(
                        $"[trigger_event REFUSE] spawn returned null kind={kind}");
                    ActionFeedback.PostFailed(actionId, "spawn_failed");
                    return;
                }

                BannerlordLinkModule.Log(
                    $"[trigger_event EXIT-OK] spawned {spawned.StringId} (kind={kind}) " +
                    $"near @{anchor.Name?.ToString()} at pos=({spawnPos.x:F1},{spawnPos.y:F1})");
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[trigger_event] CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }

        private static MobileParty SpawnLooters(Vec2 pos, Settlement homeSettlement,
                                                   MobileParty anchorParty)
        {
            // LooterParty wants a "looter clan" (Clan.BanditFactions, кулbure-independent).
            Clan looterClan = null;
            try
            {
                looterClan = Clan.BanditFactions?.FirstOrDefault(
                    c => c?.StringId?.ToLowerInvariant().Contains("looter") ?? false);
                if (looterClan == null)
                    looterClan = Clan.BanditFactions?.FirstOrDefault();
            }
            catch { }
            if (looterClan == null) return null;

            // Get LooterParty template (per clan's default).
            var template = looterClan.DefaultPartyTemplate;
            if (template == null) return null;

            // Need a string ID — generate unique.
            string id = $"blink_event_looters_{Guid.NewGuid():N}".Substring(0, 32);
            try
            {
                var cpos = new TaleWorlds.CampaignSystem.CampaignVec2(pos, true);
                var party = BanditPartyComponent.CreateLooterParty(
                    id, looterClan, homeSettlement, false, template, cpos);
                return party;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[trigger_event] CreateLooterParty crashed: {ex.Message}");
                return null;
            }
        }

        private static MobileParty SpawnBandits(Vec2 pos, MobileParty anchorParty, bool easy)
        {
            // Pick bandit clan matching anchor's culture if possible (forest_bandit / sea_raider etc.)
            Clan banditClan = null;
            try
            {
                banditClan = Clan.BanditFactions?.FirstOrDefault();
            }
            catch { }
            if (banditClan == null) return null;
            var template = banditClan.DefaultPartyTemplate;
            if (template == null) return null;

            // Need a Hideout — pick any (bandit parties в 1.3.x ссылаются на hideout).
            // Если нет hideout — fallback к LooterParty creation.
            Hideout hideout = null;
            foreach (var s in Settlement.All)
            {
                if (s?.IsHideout == true) { hideout = s.Hideout; break; }
            }
            if (hideout == null)
            {
                // No hideout — fall back to looter spawn (no hideout dependency).
                Settlement near = null;
                foreach (var s in Settlement.All)
                {
                    if (s?.IsTown == true) { near = s; break; }
                }
                return SpawnLooters(pos, near, anchorParty);
            }

            string id = $"blink_event_bandit_{Guid.NewGuid():N}".Substring(0, 32);
            try
            {
                var cpos = new TaleWorlds.CampaignSystem.CampaignVec2(pos, true);
                return BanditPartyComponent.CreateBanditParty(
                    id, banditClan, hideout, false, template, cpos);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[trigger_event] CreateBanditParty crashed: {ex.Message}");
                return null;
            }
        }
    }
}
