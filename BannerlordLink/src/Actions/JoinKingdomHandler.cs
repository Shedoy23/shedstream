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

            MainThreadDispatcher.Enqueue(() => Apply(username, kingdomName));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string kingdomName)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) return;
                if (hero.IsPrisoner) return;
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: must be clan leader");
                    return;
                }
                if (hero.Clan.Kingdom != null)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: уже в kingdom '{hero.Clan.Kingdom.Name}'");
                    return;
                }

                var all = Kingdom.All;
                if (all == null) return;
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
                    return;
                }
                if (target.IsEliminated)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: kingdom '{target.Name}' уничтожен");
                    return;
                }
                if (hero.Gold < JOIN_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: not enough gold ({hero.Gold} < {JOIN_COST})");
                    return;
                }

                GiveGoldAction.ApplyBetweenCharacters(hero, null, JOIN_COST, true);
                try
                {
                    ChangeKingdomAction.ApplyByJoinToKingdom(hero.Clan, target,
                        showNotification: false);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[join_kingdom] @{username}: ApplyByJoinToKingdom failed: {ex.Message}");
                    return;
                }

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
                BannerlordLinkModule.Log(
                    $"[join_kingdom] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
