using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.12 — `hero.leave_clan` action. Hero выходит из своего clan'а
    /// и возвращается в pool wanderer'ов (BLT pattern, ClanManagement.cs
    /// HandleLeaveCommand).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • hero in clan
    ///   • hero NOT clan leader (BLT-style — leaders can't leave own clan)
    ///   • hero not в battle (party not in MapEvent)
    ///
    /// Steps:
    ///   1. Remove governor role if any
    ///   2. Remove from party member roster
    ///   3. Set occupation Wanderer
    ///   4. hero.Clan = null
    ///   5. Place в random town
    ///
    /// Free action (no Hero.Gold cost).
    /// </summary>
    public class LeaveClanHandler : IActionHandler
    {
        public string ActionType => "hero.leave_clan";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            MainThreadDispatcher.Enqueue(() => Apply(username));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[leave_clan] @{username}: hero не найден / мёртв");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[leave_clan] @{username}: пленник, отказ");
                    return;
                }
                if (hero.Clan == null)
                {
                    BannerlordLinkModule.Log($"[leave_clan] @{username}: уже без клана");
                    return;
                }
                if (hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{username}: ты лидер клана '{hero.Clan.Name}' — " +
                        "сначала передай лидерство (TBD)");
                    return;
                }

                var oldParty = hero.PartyBelongedTo;
                if (oldParty != null && oldParty.MapEvent != null)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_clan] @{username}: hero в битве, отказ");
                    return;
                }

                if (hero.GovernorOf != null)
                {
                    try { ChangeGovernorAction.RemoveGovernorOf(hero); } catch { }
                }

                if (oldParty != null)
                {
                    try
                    {
                        bool wasLeader = oldParty.LeaderHero == hero;
                        oldParty.MemberRoster.RemoveTroop(hero.CharacterObject, 1,
                            default(UniqueTroopDescriptor), 0);
                        if (wasLeader && oldParty.IsLordParty)
                            DisbandPartyAction.StartDisband(oldParty);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[leave_clan] @{username}: party remove warn: {ex.Message}");
                    }
                }

                var oldClanName = hero.Clan.Name?.ToString() ?? "?";
                hero.SetNewOccupation(Occupation.Wanderer);
                hero.Clan = null;

                // Place в random town
                try
                {
                    var towns = Settlement.All?.Where(s => s != null && s.IsTown).ToList();
                    if (towns != null && towns.Count > 0)
                    {
                        var target = towns[new Random().Next(towns.Count)];
                        EnterSettlementAction.ApplyForCharacterOnly(hero, target);
                    }
                }
                catch { }

                BannerlordLinkModule.Log(
                    $"[leave_clan] @{username}: left '{oldClanName}' → wanderer");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    old_clan_name = oldClanName,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.clan_left", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[leave_clan] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
