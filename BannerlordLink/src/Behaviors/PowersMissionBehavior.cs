using System;
using System.Reflection;
using BannerlordLink.Net;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.Library;
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
    /// Damage-modifying powers (ignore_armor_pct / armor_bypass_pct /
    /// damage_reflect_pct) обрабатываются Harmony-patch'ем на
    /// Mission.RegisterBlow — см. Patches/DamageHookPatch.cs (Sprint 4.4).
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

            // ── body_scale (Sprint 4.2.5) ─────────────────────────────────
            // Agent.AgentScale read-only → through reflection на private
            // Agent.SetInitialAgentScale. BLT использовал тот же подход.
            var scale = PowerCache.GetPowerValue(username, "body_scale");
            if (scale.HasValue && Math.Abs(scale.Value - 1.0) > 0.001)
            {
                TrySetAgentScale(agent, (float)scale.Value);
            }

            BannerlordLinkModule.Log(
                $"[PowersMission] @{username} ({hc.Value.classKey} L{hc.Value.level}): " +
                $"hp×{hp ?? 1.0:F2} scale×{scale ?? 1.0:F2}");
        }

        /// <summary>Reflection call на private Agent.SetInitialAgentScale.
        /// Cached MethodInfo, no expensive lookup per spawn.</summary>
        private static MethodInfo _setScaleMethod;
        private static bool _setScaleResolved;

        private static void TrySetAgentScale(Agent agent, float scale)
        {
            if (!_setScaleResolved)
            {
                _setScaleResolved = true;
                try
                {
                    _setScaleMethod = typeof(Agent).GetMethod(
                        "SetInitialAgentScale",
                        BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance);
                    if (_setScaleMethod == null)
                    {
                        BannerlordLinkModule.Log(
                            "[PowersMission] SetInitialAgentScale method not found via reflection");
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[PowersMission] scale reflection error: {ex.Message}");
                }
            }
            if (_setScaleMethod == null) return;
            try
            {
                _setScaleMethod.Invoke(agent, new object[] { scale });
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[PowersMission] SetInitialAgentScale call failed: {ex.Message}");
            }
        }

    }
}
