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
    /// Sprint 5.12 — `hero.leave_kingdom` action. Clan-leader выводит clan
    /// из королевства (clan становится независимым).
    ///
    /// Pre-checks:
    ///   • hero alive, not prisoner
    ///   • hero — лидер клана
    ///   • clan в королевстве
    ///
    /// Engine API: ChangeKingdomAction.ApplyByLeaveKingdom(clan, byOwnDecision: true)
    ///
    /// Free action (no cost).
    /// </summary>
    public class LeaveKingdomHandler : IActionHandler
    {
        public string ActionType => "hero.leave_kingdom";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
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
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (hero.IsPrisoner)
                {
                    ActionFeedback.PostFailed(actionId, "hero_prisoner");
                    return;
                }
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_kingdom] @{username}: must be clan leader");
                    ActionFeedback.PostFailed(actionId, "not_clan_leader");
                    return;
                }
                var kingdom = hero.Clan.Kingdom;
                if (kingdom == null)
                {
                    ActionFeedback.PostFailed(actionId, "not_in_kingdom");
                    BannerlordLinkModule.Log(
                        $"[leave_kingdom] @{username}: clan не в королевстве");
                    return;
                }
                string oldKingdomName = kingdom.Name?.ToString() ?? "?";
                // 2026-07-19 — если клан САМ правитель этого королевства, «выйти» через
                // ApplyByLeaveKingdom НЕЛЬЗЯ: ваниль (ChangeKingdomAction, деталь LeaveKingdom)
                // лишь ставит clan.Kingdom=null, но королевство НЕ распускает → оно висит
                // сиротой в мире, а клан потом вступает в другое = «клан в двух королевствах»
                // (репорт: kuro создал королевство → сразу вышел королём → сирота). Правитель
                // выходит = королевство распускается штатным DestroyKingdomAction.
                bool isRuler = kingdom.RulingClan == hero.Clan;

                try
                {
                    if (isRuler)
                    {
                        // 2026-07-24 ИНЦИДЕНТ: DestroyKingdomAction ванильно проходит
                        // по ВСЕМ кланам королевства и зовёт DestroyClanAction на
                        // каждом → KillCharacterAction.ApplyByRemove убивает ВСЕХ их
                        // героев (смерть "Lost"). На стриме роспуск королевства
                        // slopkom'ом убил ещё двух зрителей (dorongh1, fikoos418) —
                        // членов его королевства. Подтверждено декомпилем
                        // DestroyKingdomAction/DestroyClanAction.
                        // Фикс: сначала вывести ВСЕ кланы (ApplyByLeaveKingdom смертей
                        // НЕ содержит — проверено), тогда королевство пустое и
                        // DestroyKingdomAction никого не убивает, лишь деактивирует
                        // и снимает войны. Прочие зрители становятся независимы, живы.
                        var rulerClan = hero.Clan;
                        foreach (var member in kingdom.Clans.ToList())
                        {
                            if (member != rulerClan && !member.IsEliminated)
                                ChangeKingdomAction.ApplyByLeaveKingdom(member, false);
                        }
                        ChangeKingdomAction.ApplyByLeaveKingdom(rulerClan, false);
                        DestroyKingdomAction.Apply(kingdom);   // пустое → без смертей
                    }
                    else
                        ChangeKingdomAction.ApplyByLeaveKingdom(hero.Clan, true);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_kingdom] @{username}: leave/destroy failed: {ex.Message}");
                    ActionFeedback.PostFailed(actionId, "leave_engine_failed");
                    return;
                }

                if (hero.Clan?.Kingdom != null)
                {
                    ActionFeedback.PostFailed(actionId, "leave_postcondition_failed");
                    return;
                }

                BannerlordLinkModule.Log(
                    $"[leave_kingdom] @{username}: {(isRuler ? "РАСПУЩЕНО королевство (был правитель)" : "left")} " +
                    $"'{oldKingdomName}', clan '{hero.Clan.Name}' независим");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    old_kingdom_name = oldKingdomName,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.kingdom_left", evtData));

                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[leave_kingdom] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
            }
        }
    }
}
