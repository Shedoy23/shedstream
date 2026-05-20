using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.12 — `hero.join_clan` action. Hero вступает в существующий
    /// clan (BLT pattern, ClanManagement.cs HandleJoinCommand).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • hero NOT clan leader (нельзя бросить свой clan)
    ///   • clan_name найден (case-insensitive partial match)
    ///   • clan не достиг лимита членов (10 BLT default)
    ///   • Hero.Gold >= JOIN_COST
    ///
    /// data: {target, clan_name}
    ///
    /// Cost: 50K Hero.Gold (BLT default).
    /// </summary>
    public class JoinClanHandler : IActionHandler
    {
        public string ActionType => "hero.join_clan";

        private const int JOIN_COST = 50_000;
        private const int MAX_HEROES_PER_CLAN = 10;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string clanName = (data["clan_name"]?.ToString() ?? "").Trim();
            if (string.IsNullOrEmpty(clanName))
                return Task.FromResult<(bool, string)>((false, "clan_name required"));

            MainThreadDispatcher.Enqueue(() => Apply(username, clanName));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string clanName)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) return;
                if (hero.IsPrisoner) return;
                if (hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: ты лидер '{hero.Clan?.Name}', сначала покинь свой clan");
                    return;
                }

                // Find target clan — exact match first, then fuzzy contains
                var all = Clan.All;
                if (all == null) return;
                var target = all.FirstOrDefault(c => c != null &&
                    string.Equals(c.Name?.ToString(), clanName, StringComparison.OrdinalIgnoreCase));
                if (target == null)
                {
                    target = all.FirstOrDefault(c => c != null && c.Name != null
                        && c.Name.ToString().IndexOf(clanName, StringComparison.OrdinalIgnoreCase) >= 0);
                }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: clan '{clanName}' не найден");
                    return;
                }
                if (target == hero.Clan)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: ты уже в '{target.Name}'");
                    return;
                }
                if (target.IsEliminated)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: clan '{target.Name}' уничтожен");
                    return;
                }
                if ((target.Heroes?.Count ?? 0) >= MAX_HEROES_PER_CLAN)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: clan '{target.Name}' полный ({MAX_HEROES_PER_CLAN}/{MAX_HEROES_PER_CLAN})");
                    return;
                }
                if (hero.Gold < JOIN_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: not enough gold ({hero.Gold} < {JOIN_COST})");
                    return;
                }

                string oldClanName = hero.Clan?.Name?.ToString() ?? "none";
                GiveGoldAction.ApplyBetweenCharacters(hero, null, JOIN_COST, true);
                hero.Clan = target;
                if (hero.Occupation != Occupation.Lord)
                    hero.SetNewOccupation(Occupation.Lord);

                BannerlordLinkModule.Log(
                    $"[join_clan] @{username}: '{oldClanName}' → '{target.Name}' " +
                    $"(-{JOIN_COST}💰)");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    clan_name = target.Name?.ToString(),
                    old_clan_name = oldClanName,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.clan_joined", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[join_clan] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
