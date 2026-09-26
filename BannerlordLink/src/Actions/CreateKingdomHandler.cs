using System;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using BannerlordLink.Behaviors;
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
        public const int REQUIRED_REBELLION_SUPPORTERS = 2;
        public const int MIN_REBELLION_RELATION = 50;

        /// <summary>
        /// Clans which will back a rebellion right now. Viewer-created vassals
        /// are loyal by definition; regular clans require relation >= 50.
        /// Only clans from the founder's current kingdom can participate.
        /// </summary>
        public static List<Clan> GetRebellionSupporters(Hero hero)
        {
            var result = new List<Clan>();
            var founderClan = hero?.Clan;
            var oldKingdom = founderClan?.Kingdom;
            if (oldKingdom == null) return result;

            var personal = VassalAutoFollowBehavior.Current?
                .GetVassalsOfMaster(founderClan) ?? new List<Clan>();

            foreach (var clan in oldKingdom.Clans ?? Enumerable.Empty<Clan>())
            {
                if (clan == null || clan == founderClan || clan == oldKingdom.RulingClan ||
                    clan.IsEliminated || clan.IsUnderMercenaryService || clan.Leader == null)
                    continue;

                bool isPersonal = personal.Contains(clan);
                int relation = 0;
                try { relation = clan.Leader.GetRelation(hero); } catch { }
                if (isPersonal || relation >= MIN_REBELLION_RELATION)
                    result.Add(clan);
            }
            return result;
        }

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string desiredName = (data["kingdom_name"]?.ToString() ?? "").Trim();

            // actionId нужен, чтобы отказ доехал до зрителя возвратом крустиков
            string actionId = ActionFeedback.GetActionId(data);
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
                    BannerlordLinkModule.Log($"[create_kingdom] @{username}: hero не найден / мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log($"[create_kingdom] @{username}: пленник, отказ");
                    ActionFeedback.PostFailed(actionId, "prisoner");
                    return;
                }
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: must be clan leader (Clan={hero.Clan?.Name?.ToString() ?? "null"})");
                    ActionFeedback.PostFailed(actionId, "not_clan_leader");
                    return;
                }
                var oldKingdom = hero.Clan.Kingdom;
                if (oldKingdom != null && oldKingdom.RulingClan == hero.Clan)
                {
                    ActionFeedback.PostFailed(actionId, "already_kingdom_ruler");
                    return;
                }

                var rebellionSupporters = oldKingdom != null
                    ? GetRebellionSupporters(hero)
                    : new List<Clan>();
                if (oldKingdom != null && rebellionSupporters.Count < REQUIRED_REBELLION_SUPPORTERS)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: rebellion needs {REQUIRED_REBELLION_SUPPORTERS} supporters, " +
                        $"eligible={rebellionSupporters.Count}");
                    ActionFeedback.PostFailed(actionId, "rebellion_support_required");
                    return;
                }
                // ═══ 2026-07-31: ЗДЕСЬ БЫЛ ОТКАЗ «ты уже в королевстве» ═══
                //
                // Он и был причиной жалоб «не могу получить поселение».
                // Цепочка (доказана декомпилем, не догадка):
                //   1. чтобы основать королевство, зритель был обязан СНАЧАЛА
                //      выйти из своего;
                //   2. выход идёт через `ChangeKingdomAction.ApplyByLeaveKingdom`,
                //      а там движок ЯВНО отбирает всё нажитое:
                //          foreach (Settlement s in clan.Settlements)
                //              ChangeOwnerOfSettlementAction.ApplyByLeaveFaction(kingdom.Leader, s);
                //   3. зритель терял замок в пользу бывшего короля и основывал
                //      ПУСТОЕ королевство за 5 млн.
                //
                // При этом движок УМЕЕТ делать правильно: `KingdomManager.CreateKingdom`
                // внутри зовёт `ChangeKingdomAction.ApplyByCreateKingdom`, а эта
                // ветка выводит клан из старого королевства и владений НЕ трогает.
                // То есть «уходит и забирает своё» — штатное поведение, мы его
                // сами себе запрещали.
                //
                // Теперь основывать королевство можно, НЕ выходя заранее.

                // Product rule: a viewer may found a landless kingdom. Bannerlord's
                // KingdomManager supports it; future conquest supplies the fiefs.
                if (hero.Gold < CREATE_COST)
                {
                    BannerlordLinkModule.Log(
                        $"[create_kingdom] @{username}: not enough gold ({hero.Gold} < {CREATE_COST})");
                    ActionFeedback.PostFailed(actionId, "not_enough_gold");
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
                    ActionFeedback.PostFailed(actionId, "kingdom_name_taken");
                    return;
                }

                if (FactionChangeGuard.TouchesPlayerBattle(hero.Clan, hero.Clan.Kingdom))
                {
                    BannerlordLinkModule.Log($"[create_kingdom] REFUSE @{username}: идёт бой стримера с участием затронутых сторон");
                    ActionFeedback.PostFailed(actionId, "in_battle");
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

                // VassalAutoFollow may already have moved personal vassals in
                // response to the founder's kingdom-change event. Transfer the
                // remaining friendly clans by defection; this native path keeps
                // their settlements and emits the proper campaign events.
                foreach (var supporter in rebellionSupporters)
                {
                    if (supporter?.Kingdom == newKingdom) continue;
                    try
                    {
                        ChangeKingdomAction.ApplyByJoinToKingdomByDefection(
                            supporter, oldKingdom, newKingdom, default(CampaignTime), false);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[create_kingdom] @{username}: supporter {supporter?.Name} transfer warn: {ex.Message}");
                    }
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
                    rebellion = oldKingdom != null,
                    supporters = rebellionSupporters.Select(c => c.StringId).ToArray(),
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.kingdom_created", evtData));

                HeroStateSync.Push(hero);

                // Явный успех: королевство создано и проверено выше по коду.
                // Без этого вызова исход был бы «успех по умолчанию» — то же
                // самое, что видел бы зритель при молчаливом отказе.
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[create_kingdom] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
