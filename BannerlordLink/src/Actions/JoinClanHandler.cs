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

            string actionId = data["_action_id"]?.ToString();
            MainThreadDispatcher.Enqueue(() => Apply(username, clanName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        /// <summary>
        /// 2026-07-31, пост-стрим-триаж. Все отказы здесь были голым `return`.
        /// Бэкенд ACK'ает успех ещё ДО того, как этот код выполнится (см.
        /// `ActionFeedback`), поэтому молчаливый отказ = зритель видит «готово»
        /// и не видит ничего. За вечер один зритель нажал семь раз подряд,
        /// перебирая названия («Сарацины», «Сараниды», «южная империя» — это
        /// вообще королевства, а не кланы), и ни разу не узнал, почему не
        /// вышло. Денег он не потерял (динары списываются последним шагом,
        /// крустиков у действия нет), но механика для него была мёртвой.
        /// Теперь каждый отказ называет причину.
        /// </summary>
        private static void Apply(string username, string clanName, string actionId)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    ActionFeedback.PostFailed(actionId, "hero_is_prisoner");
                    return;
                }
                if (hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: ты лидер '{hero.Clan?.Name}', сначала покинь свой clan");
                    ActionFeedback.PostFailed(actionId, "is_clan_leader");
                    return;
                }

                // Find target clan — exact match first, then fuzzy contains
                var all = Clan.All;
                if (all == null)
                {
                    ActionFeedback.PostFailed(actionId, "clans_unavailable");
                    return;
                }
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
                    ActionFeedback.PostFailed(actionId, "clan_not_found");
                    return;
                }
                if (target == hero.Clan)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: ты уже в '{target.Name}'");
                    ActionFeedback.PostFailed(actionId, "already_in_this_clan");
                    return;
                }
                if (target.IsEliminated)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: clan '{target.Name}' уничтожен");
                    ActionFeedback.PostFailed(actionId, "clan_eliminated");
                    return;
                }
                // 2026-06-10 — нельзя вступить в клан ИГРОКА: движок блокирует выход
                // (Clan=null) для члена клана игрока → зритель залипает навсегда
                // (баг klut12 в 'Gray'). Лучше не пускать, чем потом не выпускать.
                if (target == Clan.PlayerClan)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: вступление в клан игрока '{target.Name}' запрещено (из него не выйти)");
                    ActionFeedback.PostFailed(actionId, "player_clan_forbidden");
                    return;
                }
                if ((target.Heroes?.Count ?? 0) >= MAX_HEROES_PER_CLAN)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: clan '{target.Name}' полный ({MAX_HEROES_PER_CLAN}/{MAX_HEROES_PER_CLAN})");
                    ActionFeedback.PostFailed(actionId, "clan_full");
                    return;
                }
                if (hero.Gold < JOIN_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[join_clan] @{username}: not enough gold ({hero.Gold} < {JOIN_COST})");
                    ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
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
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[join_clan] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
            }
        }
    }
}
