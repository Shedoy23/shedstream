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

            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[player.heal] @{username}: hero не найден");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[player.heal] @{username}: hero мёртв, heal skipped");
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
