using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.Localization;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.12 — `hero.create_kingdom` action. Clan-leader создаёт
    /// собственное королевство (BLT pattern, KingdomManagement.cs).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • hero — лидер клана
    ///   • clan не в королевстве уже
    ///   • clan name unique для kingdom
    ///   • Hero.Gold >= CREATE_COST
    ///
    /// Engine API: Campaign.Current.KingdomManager.CreateKingdom(
    ///   name, name, culture, clan, null, null, null, null);
    ///
    /// Cost: 5M Hero.Gold (динаров) — больше чем clan'a из-за престижа.
    /// </summary>
    public class CreateKingdomHandler : IActionHandler
    {
        public string ActionType => "hero.create_kingdom";

        private const int CREATE_COST = 5_000_000;   // 5M динаров

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string desiredName = (data["kingdom_name"]?.ToString() ?? "").Trim();

            MainThreadDispatcher.Enqueue(() => Apply(username, desiredName));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string desiredName)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[create_kingdom] @{username}: hero не найден / мёртв");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[create_kingdom] @{username}: пленник, отказ");
                    return;
                }
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: must be clan leader (Clan={hero.Clan?.Name?.ToString() ?? "null"})");
                    return;
                }
                if (hero.Clan.Kingdom != null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: clan already в kingdom {hero.Clan.Kingdom.Name}");
                    return;
                }
                if (hero.Gold < CREATE_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: not enough gold ({hero.Gold} < {CREATE_COST})");
                    return;
                }

                string baseName = string.IsNullOrEmpty(desiredName)
                    ? $"{username}'s Kingdom"
                    : desiredName;
                string fullName = $"[BLink] {baseName}";

                // Uniqueness check
                bool exists = Kingdom.All?.Any(k => k != null &&
                    string.Equals(k.Name?.ToString(), fullName,
                                  StringComparison.OrdinalIgnoreCase)) ?? false;
                if (exists)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: kingdom '{fullName}' уже существует");
                    return;
                }

                // ── ENGINE: create kingdom ──
                var creator = Campaign.Current?.KingdomManager;
                if (creator == null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: KingdomManager == null");
                    return;
                }
                var nameText = new TextObject(fullName);
                creator.CreateKingdom(nameText, nameText, hero.Culture, hero.Clan,
                                      null, null, null, null);

                var newKingdom = hero.Clan.Kingdom;
                if (newKingdom == null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: kingdom создан но Clan.Kingdom == null?");
                    return;
                }

                // Bonus: stock влияния + budget + banner от clan
                try
                {
                    newKingdom.KingdomBudgetWallet = 2_000_000;
                    hero.Clan.Influence = Math.Max(hero.Clan.Influence, 2000f);
                    if (hero.Clan.Banner != null)
                    {
                        newKingdom.Banner = hero.Clan.Banner;
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: bonus init warn: {ex.Message}");
                }

                GiveGoldAction.ApplyBetweenCharacters(hero, null, CREATE_COST, true);

                BannerlordLinkModule.Log(
                    $"[create_kingdom] @{username}: kingdom '{fullName}' created → " +
                    $"culture={hero.Culture?.StringId}, " +
                    $"-{CREATE_COST}💰, gold={hero.Gold}");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    kingdom_name = fullName,
                    kingdom_id = newKingdom.StringId,
                    culture = hero.Culture?.StringId,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.kingdom_created", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[create_kingdom] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
