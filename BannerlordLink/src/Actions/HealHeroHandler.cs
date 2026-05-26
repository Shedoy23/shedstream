using System;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `player.heal` — лечит hero до full HP.
    ///
    /// API: Hero.Heal(amount, addXp) — vanilla, без BLT.
    /// </summary>
    public class HealHeroHandler : IActionHandler
    {
        public string ActionType => "player.heal";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[player.heal] REFUSE @{username}: hero не найден");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[player.heal] REFUSE @{username}: hero мёртв");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_dead");
                        return;
                    }
                    int before = hero.HitPoints;
                    int max = hero.MaxHitPoints;
                    hero.Heal(max - before, addXp: false);
                    BannerlordLinkModule.Log(
                        $"[player.heal] @{username} HP {before} → {hero.HitPoints}/{max}");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[player.heal] @{username} CRASHED: {ex.Message}");
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
