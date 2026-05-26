using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Helpers;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.13 — `hero.create_party` action. Hero создаёт собственный
    /// MobileParty и появляется на карте как AI-controlled lord
    /// (BLT pattern, ClanManagement.cs HandleCreate / PartyManagement.cs).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • Hero State != Released/Traveling/Fugitive
    ///   • hero в clan (не player clan)
    ///   • hero не имеет party уже
    ///   • clan.WarPartyComponents.Count < CommanderLimit
    ///   • Hero.Gold >= CREATE_COST
    ///
    /// Steps:
    ///   1. Remove governor role if any
    ///   2. SpawnLordParty(hero, spawn settlement gate, radius)
    ///   3. ChangePartyLeader + ActualClan
    ///   4. Add retinue troops в MemberRoster
    ///   5. Add starting food + horses из близких деревень
    ///   6. InitializeMobilePartyAtPosition
    ///
    /// Cost: 200K Hero.Gold (purchase oborona / start food).
    /// </summary>
    public class CreatePartyHandler : IActionHandler
    {
        public string ActionType => "hero.create_party";

        private const int CREATE_COST = 200_000;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            // Backend pass'ит retinue snapshot (для добавления troops в party).
            JArray retinueJson = data["retinue"] as JArray;
            var retinueIds = retinueJson?
                .Select(t => t?["troop_id"]?.ToString())
                .Where(s => !string.IsNullOrEmpty(s))
                .ToList() ?? new System.Collections.Generic.List<string>();

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, retinueIds, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username,
            System.Collections.Generic.List<string> retinueIds, string actionId)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[create_party] REFUSE @{username}: hero не найден / мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[create_party] REFUSE @{username}: пленник");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "is_prisoner");
                    return;
                }
                if (hero.HeroState == Hero.CharacterStates.Released ||
                    hero.HeroState == Hero.CharacterStates.Traveling ||
                    hero.HeroState == Hero.CharacterStates.Fugitive)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] REFUSE @{username}: hero state {hero.HeroState}");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "bad_state:" + hero.HeroState);
                    return;
                }
                if (hero.Clan == null)
                {
                    BannerlordLinkModule.Log($"[create_party] REFUSE @{username}: hero без clan");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_clan");
                    return;
                }
                if (hero.Clan == Clan.PlayerClan)
                {
                    BannerlordLinkModule.Log($"[create_party] REFUSE @{username}: в player clan нельзя");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_player_clan");
                    return;
                }
                if (hero.PartyBelongedTo != null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] REFUSE @{username}: уже в party '{hero.PartyBelongedTo.Name}'");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "already_in_party");
                    return;
                }
                if (!hero.IsClanLeader &&
                    (hero.Clan.WarPartyComponents?.Count ?? 0) >= hero.Clan.CommanderLimit)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] REFUSE @{username}: clan party limit " +
                        $"({hero.Clan.WarPartyComponents.Count}/{hero.Clan.CommanderLimit})");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "clan_party_limit");
                    return;
                }
                if (hero.Gold < CREATE_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] REFUSE @{username}: not enough hero gold ({hero.Gold} < {CREATE_COST})");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                if (hero.GovernorOf != null)
                {
                    try { ChangeGovernorAction.RemoveGovernorOfIfExists(hero.GovernorOf); } catch { }
                }

                // Find spawn settlement
                Settlement spawn = null;
                try
                {
                    spawn = SettlementHelper.GetBestSettlementToSpawnAround(hero);
                }
                catch { }
                if (spawn == null) spawn = hero.CurrentSettlement ?? hero.HomeSettlement;
                if (spawn == null)
                {
                    spawn = Settlement.All?.Where(s => s != null && s.IsTown
                            && s.Culture == hero.Culture).FirstOrDefault()
                        ?? Settlement.All?.FirstOrDefault(s => s != null && s.IsTown);
                }
                if (spawn == null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] @{username}: no spawn settlement");
                    return;
                }

                float radius = 1f;
                try
                {
                    radius = Campaign.Current.GetAverageDistanceBetweenClosestTwoTownsWithNavigationType(
                                MobileParty.NavigationType.Default) / 2f;
                }
                catch { }

                MobileParty newParty;
                try
                {
                    newParty = MobilePartyHelper.SpawnLordParty(hero, spawn.GatePosition, radius);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] @{username}: SpawnLordParty failed: {ex.Message}");
                    return;
                }
                if (newParty == null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] @{username}: SpawnLordParty вернул null");
                    return;
                }

                try
                {
                    if (newParty.LeaderHero != hero) newParty.ChangePartyLeader(hero);
                    if (newParty.ActualClan != hero.Clan) newParty.ActualClan = hero.Clan;
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[create_party] @{username}: leader/clan set warn: {ex.Message}");
                }

                // Add retinue troops to MemberRoster
                int retinueAdded = 0;
                if (retinueIds != null && retinueIds.Count > 0 && newParty.MemberRoster != null)
                {
                    foreach (var troopId in retinueIds)
                    {
                        var troop = MBObjectManager.Instance.GetObject<CharacterObject>(troopId);
                        if (troop != null)
                        {
                            try
                            {
                                newParty.MemberRoster.AddToCounts(troop, 1);
                                retinueAdded++;
                            }
                            catch { }
                        }
                    }
                }

                // Starting food + horses from nearby villages (BLT pattern)
                try { BootstrapPartyLoot(newParty); } catch { }

                try { newParty.InitializeMobilePartyAtPosition(spawn.GatePosition); } catch { }

                GiveGoldAction.ApplyBetweenCharacters(hero, null, CREATE_COST, true);

                BannerlordLinkModule.Log(
                    $"[create_party] @{username}: party created → " +
                    $"name={newParty.Name}, spawn={spawn.Name}, retinue={retinueAdded}, " +
                    $"-{CREATE_COST}💰");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    party_name = newParty.Name?.ToString(),
                    party_id = newParty.StringId,
                    spawn_settlement = spawn.Name?.ToString(),
                    retinue_added = retinueAdded,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.party_created", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[create_party] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>BLT pattern: добавить food и horses из близких деревень
        /// чтобы party не голодала в первые дни.</summary>
        private static void BootstrapPartyLoot(MobileParty party)
        {
            if (party == null || Campaign.Current == null) return;
            float range = 2f * Campaign.Current.EstimatedAverageLordPartySpeed
                          * (float)CampaignTime.HoursInDay;
            foreach (var settlement in Campaign.Current.Settlements)
            {
                if (settlement == null || !settlement.IsVillage) continue;
                float dist;
                try
                {
                    dist = Campaign.Current.Models.MapDistanceModel.GetDistance(
                        party, settlement, false, party.NavigationCapability, out _);
                }
                catch { continue; }
                if (dist >= range) continue;
                if (settlement.Village?.VillageType?.Productions == null) continue;

                foreach (var (item, prod) in settlement.Village.VillageType.Productions)
                {
                    if (item == null) continue;
                    float weight = 0f;
                    if (item.ItemType == ItemObject.ItemTypeEnum.Horse
                        && item.HorseComponent != null
                        && item.HorseComponent.IsRideable
                        && !item.HorseComponent.IsPackAnimal)
                        weight = 7f;
                    else if (item.IsFood)
                        weight = 0.1f;
                    if (weight <= 0) continue;
                    float sizeF = ((float)party.MemberRoster.TotalManCount + 2f) / 200f;
                    int n = MBRandom.RoundRandomized(
                        weight * prod * (1f - dist / range) * sizeF);
                    if (n > 0 && party.ItemRoster != null)
                    {
                        try { party.ItemRoster.AddToCounts(item, n); } catch { }
                    }
                }
            }
        }
    }
}
