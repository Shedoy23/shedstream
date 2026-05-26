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
using TaleWorlds.Localization;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.9 — `hero.create_clan` action. Viewer создаёт собственный clan
    /// под лидерством своего adopted hero. BLT pattern (ClanManagement.cs
    /// HandleCreateCommand).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • !hero.IsClanLeader (уже свой clan)
    ///   • clan name unique
    ///   • Hero.Gold >= CREATE_COST
    ///
    /// Steps:
    ///   1. Clan.CreateClan(name) — engine call
    ///   2. ChangeClanName + Culture + Banner + Kingdom=null
    ///   3. AddRenown — стартовая renown 50
    ///   4. SetInitialHomeSettlement — random of same culture
    ///   5. hero.Clan = newClan
    ///   6. hero.SetNewOccupation(Occupation.Lord)
    ///   7. newClan.SetLeader(hero), IsNoble=true
    ///   8. CampaignEventDispatcher.OnClanCreated
    ///
    /// Cost: 100K Hero.Gold (динаров). Конфигурируется в backend.
    /// Naming: "[BLink] {viewer}'s Clan" — соответствует hero naming.
    ///
    /// Future: hero.create_party — после clan можно делать LordParty
    /// (Sprint 5.9b).
    /// </summary>
    public class CreateClanHandler : IActionHandler
    {
        public string ActionType => "hero.create_clan";

        private const int CREATE_COST = 1_000_000;   // динаров (1M)
        private const int STARTING_RENOWN = 50;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string desiredName = (data["clan_name"]?.ToString() ?? "").Trim();

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, desiredName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string desiredName, string actionId)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[create_clan] REFUSE @{username}: hero не найден / мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[create_clan] REFUSE @{username}: пленник");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "is_prisoner");
                    return;
                }

                if (hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[create_clan] REFUSE @{username}: уже лидер clan '{hero.Clan?.Name}'");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "already_clan_leader");
                    return;
                }

                if (hero.Gold < CREATE_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[create_clan] REFUSE @{username}: not enough hero gold ({hero.Gold} < {CREATE_COST})");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                // Build full clan name: "[BLink] viewer's Clan" — fallback если
                // имя пусто или совпадает с existing.
                string baseName = string.IsNullOrEmpty(desiredName)
                    ? $"{username}'s Clan"
                    : desiredName;
                string fullClanName = $"[BLink] {baseName}";

                // Check uniqueness через Clan.All (vs BLT pattern AllHeroes —
                // engine API доступен напрямую, не нужен helper).
                bool exists = Clan.All?.Any(c => c != null &&
                    string.Equals(c.Name?.ToString(), fullClanName,
                                  StringComparison.OrdinalIgnoreCase)) ?? false;
                if (exists)
                {
                    BannerlordLinkModule.Log(
                        $"[create_clan] REFUSE @{username}: clan '{fullClanName}' уже существует");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "clan_name_exists");
                    return;
                }

                // ── ENGINE: create clan ──
                var newClan = Clan.CreateClan(fullClanName);
                if (newClan == null)
                {
                    BannerlordLinkModule.Log(
                        $"[create_clan] REFUSE @{username}: Clan.CreateClan вернул null");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "engine_create_clan_null");
                    return;
                }

                var nameText = new TextObject(fullClanName);
                newClan.ChangeClanName(nameText, nameText);
                newClan.Culture = hero.Culture;
                newClan.Banner = Banner.CreateRandomBanner();
                newClan.Kingdom = null;
                newClan.AddRenown(STARTING_RENOWN, false);

                // Initial home settlement — random of same culture (fallback any)
                var homeSettlement =
                    Settlement.All
                        ?.Where(s => s != null && s.Culture == hero.Culture && s.IsTown)
                        .ToList();
                Settlement home = null;
                if (homeSettlement != null && homeSettlement.Count > 0)
                    home = homeSettlement[new Random().Next(homeSettlement.Count)];
                else if (Settlement.All != null && Settlement.All.Count > 0)
                    home = Settlement.All[new Random().Next(Settlement.All.Count)];
                if (home != null)
                {
                    try { newClan.SetInitialHomeSettlement(home); } catch { }
                }

                hero.Clan = newClan;
                if (hero.Occupation != Occupation.Lord)
                {
                    hero.SetNewOccupation(Occupation.Lord);
                }
                newClan.SetLeader(hero);
                newClan.IsNoble = true;

                try
                {
                    CampaignEventDispatcher.Instance.OnClanCreated(newClan, false);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[create_clan] OnClanCreated dispatcher failed: {ex.Message}");
                }

                // Deduct cost
                GiveGoldAction.ApplyBetweenCharacters(hero, null, CREATE_COST, true);

                BannerlordLinkModule.Log(
                    $"[create_clan] @{username}: clan '{fullClanName}' created → " +
                    $"culture={hero.Culture?.StringId}, home={home?.Name}, " +
                    $"-{CREATE_COST}💰, gold={hero.Gold}");

                // Push event для backend mirror
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    clan_name = fullClanName,
                    clan_id = newClan.StringId,
                    culture = hero.Culture?.StringId,
                    home_settlement = home?.Name?.ToString(),
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.clan_created", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[create_clan] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
