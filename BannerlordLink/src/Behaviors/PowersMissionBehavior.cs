using System;
using BannerlordLink.Net;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// MissionLogic который применяет passive powers к hero'ям зрителей
    /// когда они spawn'ятся в Mission (battle/siege/tournament).
    ///
    /// Registered через BannerlordLinkModule.OnMissionBehaviorInitialize.
    /// Bannerlord auto-calls этот override на каждой новой Mission.
    ///
    /// Применяемые powers (Sprint 4.2 MVP):
    ///   - hp_multiplier  → agent.BaseHealthLimit × HealthLimit × Health
    ///   - body_scale     → agent.AgentScale (visual + reach)
    ///
    /// Powers требующие damage hook (armor_bypass / damage_reflect /
    /// ignore_armor) — Sprint 4.3.
    /// </summary>
    public class PowersMissionBehavior : MissionLogic
    {
        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            try { ApplyPassivePowers(agent); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] OnAgentBuild error: {ex.Message}");
            }
        }

        private static void ApplyPassivePowers(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return;

            // Резолв hero для agent через CharacterObject.HeroObject.
            // Это работает для любых hero agents (party leaders, companions,
            // wanderers в towns, etc.) без cast'ов на specific Origin types.
            Hero hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero == null) return;

            string username = hero.Name?.ToString()?.ToLowerInvariant();
            if (string.IsNullOrEmpty(username)) return;

            var hc = PowerCache.GetHeroClass(username);
            if (hc == null) return;  // adopted hero без выбранного класса

            // ── hp_multiplier ──────────────────────────────────────────────
            var hp = PowerCache.GetPowerValue(username, "hp_multiplier");
            if (hp.HasValue && Math.Abs(hp.Value - 1.0) > 0.001)
            {
                float ratio = (float)hp.Value;
                agent.BaseHealthLimit *= ratio;
                agent.HealthLimit *= ratio;
                agent.Health *= ratio;
            }

            // ── body_scale — Sprint 4.2.5 (требует reflection на
            // private Agent.SetInitialAgentScale). Skip для MVP.

            BannerlordLinkModule.Log(
                $"[PowersMission] @{username} ({hc.Value.classKey} L{hc.Value.level}): hp×{hp ?? 1.0:F2}");
        }
    }
}
