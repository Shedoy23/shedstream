using System;
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

            MainThreadDispatcher.Enqueue(() => Apply(username));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) return;
                if (hero.IsPrisoner) return;
                if (hero.Clan == null || !hero.IsClanLeader)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_kingdom] @{username}: must be clan leader");
                    return;
                }
                var kingdom = hero.Clan.Kingdom;
                if (kingdom == null)
                {
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
                        DestroyKingdomAction.Apply(kingdom);
                    else
                        ChangeKingdomAction.ApplyByLeaveKingdom(hero.Clan, true);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[leave_kingdom] @{username}: leave/destroy failed: {ex.Message}");
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
            }
        }
    }
}
