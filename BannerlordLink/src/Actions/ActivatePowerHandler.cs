using System;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `power.activate` — triggered active ability для hero
    /// в текущей Mission. MVP single power: "heal_burst" (+50 HP мгновенно).
    ///
    /// data: { target, power_key }
    /// Поддерживаемые power_keys (Sprint 4.3 MVP):
    ///   heal_burst — +50 HP к active agent
    ///
    /// Future (Sprint 4.4+):
    ///   - shield_break_burst (immediate AoE shield break)
    ///   - rage (temporary damage modifier, 30s duration)
    ///   - retribution_toggle (active damage reflection ON)
    ///
    /// Все active powers требуют hero spawned как agent в Mission.Current.
    /// Иначе skipped с log "no active agent".
    /// </summary>
    public class ActivatePowerHandler : IActionHandler
    {
        public string ActionType => "power.activate";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string powerKey = (data["power_key"]?.ToString() ?? "heal_burst").Trim().ToLowerInvariant();

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            MainThreadDispatcher.Enqueue(() => Activate(username, powerKey));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(string username, string powerKey)
        {
            try
            {
                if (Mission.Current == null)
                {
                    BannerlordLinkModule.Log(
                        $"[power.activate] @{username}: no active Mission " +
                        "(hero не в battle)");
                    return;
                }

                // Find agent in current mission
                Agent agent = null;
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || !a.IsHuman || !a.IsActive()) continue;
                    var hero = (a.Character as TaleWorlds.CampaignSystem.CharacterObject)?.HeroObject;
                    if (hero?.Name == null) continue;
                    if (string.Equals(hero.Name.ToString(), username,
                            StringComparison.OrdinalIgnoreCase))
                    {
                        agent = a;
                        break;
                    }
                }

                if (agent == null)
                {
                    BannerlordLinkModule.Log(
                        $"[power.activate] @{username}: hero не spawned как agent в Mission");
                    return;
                }

                switch (powerKey)
                {
                    case "heal_burst":
                        ApplyHealBurst(agent, username);
                        break;
                    default:
                        BannerlordLinkModule.Log(
                            $"[power.activate] @{username}: unknown power '{powerKey}'");
                        break;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[power.activate] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static void ApplyHealBurst(Agent agent, string username)
        {
            const float BURST_AMOUNT = 50f;
            float before = agent.Health;
            float max = agent.HealthLimit;
            agent.Health = Math.Min(max, agent.Health + BURST_AMOUNT);
            BannerlordLinkModule.Log(
                $"[power.heal_burst] @{username}: HP {before:F0} → {agent.Health:F0} / {max:F0}");
        }
    }
}
