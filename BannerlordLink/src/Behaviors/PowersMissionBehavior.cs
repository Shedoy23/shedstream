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
    ///
    /// Active timed buffs (rage / retribution_toggle) живут в
    /// ActiveBuffState — этот MissionLogic вызывает RemoveExpired каждые
    /// 2 сек (slow-tick) и Clear на end-mission (Sprint 4.5).
    /// </summary>
    public class PowersMissionBehavior : MissionLogic
    {
        private const float BUFF_TICK_INTERVAL = 2.0f;
        private float _buffTickAcc;

        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            try { ApplyPassivePowers(agent); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] OnAgentBuild error: {ex.Message}");
            }
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            _buffTickAcc += dt;
            if (_buffTickAcc < BUFF_TICK_INTERVAL) return;
            _buffTickAcc = 0f;

            // Sprint 5.33 (BLT-parity FX) — RemoveExpired теперь returns list.
            // Caller react'ит на specific expirations (berserker_charge — reset
            // speed back to 1.0×; poison_dot — engine cleanup).
            try
            {
                var expired = ActiveBuffState.RemoveExpired();
                if (expired.Count > 0) HandleExpiredBuffs(expired);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] buff cleanup error: {ex.Message}");
            }

            // Sprint 5.33 (BLT-parity FX) — apply DoT damage to poisoned agents.
            // Каждый tick (~2 сек) — damage = damagePerSec × BUFF_TICK_INTERVAL.
            try { ApplyDotTicks(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] DoT tick error: {ex.Message}");
            }

            // Sprint 5.30 #41 — periodic re-burst для timed buffs (subtle visual
            // reinforcement что buff active). Iterate all (username, buff) и
            // play tick particle на agent если найден в Mission.
            try { PlayBuffTickParticles(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] buff tick fx error: {ex.Message}");
            }
        }

        /// <summary>Sprint 5.33 (BLT-parity FX) — react на specific buff expirations.
        /// berserker_charge → reset agent speed back to 1.0×.
        /// poison_dot → engine cleanup (target.Index больше не tick'ается).</summary>
        private static void HandleExpiredBuffs(
            System.Collections.Generic.List<(string username, string powerKey, double value)> expired)
        {
            foreach (var (username, powerKey, _) in expired)
            {
                try
                {
                    if (powerKey == "berserker_charge")
                    {
                        var agent = FindAgentByUsername(username);
                        if (agent != null && agent.IsActive())
                        {
                            agent.SetMaximumSpeedLimit(1f, true);
                            BannerlordLinkModule.Log(
                                $"[FX expire] @{username} berserker_charge → speed reset 1.0×");
                        }
                    }
                    // poison_dot expire — no agent-side cleanup needed (we don't
                    // mutate engine state on each tick, just RegisterBlow).
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[FX expire] @{username} {powerKey} cleanup warn: {ex.Message}");
                }
            }
        }

        /// <summary>Sprint 5.33 (BLT-parity FX) — apply DoT damage to poisoned
        /// agents. Each tick (~BUFF_TICK_INTERVAL sec): damage = dps × interval.
        /// Lookup agent by index — может быть dead/disposed → skip.</summary>
        private static void ApplyDotTicks()
        {
            if (Mission.Current == null) return;
            var dots = ActiveBuffState.SnapshotDotTargets();
            if (dots.Count == 0) return;

            int applied = 0;
            foreach (var (agentIdx, dps, _) in dots)
            {
                try
                {
                    Agent target = null;
                    // Iterate Mission.Current.Agents — find by Index.
                    foreach (var a in Mission.Current.Agents)
                    {
                        if (a == null) continue;
                        if (a.Index == agentIdx) { target = a; break; }
                    }
                    if (target == null || !target.IsActive()) continue;
                    int dmg = (int)Math.Max(1.0, dps * BUFF_TICK_INTERVAL);
                    var blow = new Blow(-1)
                    {
                        InflictedDamage = dmg,
                        DamageType = DamageTypes.Pierce,
                        DamageCalculated = true,
                        BlowFlag = BlowFlags.None,
                        BoneIndex = target.Monster?.ThoraxLookDirectionBoneIndex ?? (sbyte)0,
                        GlobalPosition = target.Position,
                        Direction = TaleWorlds.Library.Vec3.Forward,
                        SwingDirection = TaleWorlds.Library.Vec3.Forward,
                    };
                    AttackCollisionData cd = default;
                    target.RegisterBlow(blow, cd);
                    applied++;
                    // Visual: re-pulse poison particle.
                    BannerlordLink.Util.PowerVisualFx.PlayBuffTick(target, "poison_dot");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[FX DoT] agent idx={agentIdx} tick warn: {ex.Message}");
                }
            }
            if (applied > 0)
            {
                BannerlordLinkModule.Log(
                    $"[FX DoT] applied {applied}/{dots.Count} poison ticks this round");
            }
        }

        /// <summary>Sprint 5.30 #41 — для каждого active buff, найти agent
        /// и проиграть subtle particle. Делается каждые BUFF_TICK_INTERVAL.
        /// Все exceptions per-buff catched — один сбой не валит весь tick.</summary>
        private static void PlayBuffTickParticles()
        {
            if (Mission.Current == null) return;
            var actives = BannerlordLink.Net.ActiveBuffState.SnapshotActive();
            if (actives == null || actives.Count == 0) return;
            foreach (var (username, powerKey) in actives)
            {
                Agent agent = FindAgentByUsername(username);
                if (agent == null) continue;
                BannerlordLink.Util.PowerVisualFx.PlayBuffTick(agent, powerKey);
            }
        }

        private static Agent FindAgentByUsername(string username)
        {
            try
            {
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || !a.IsHuman || !a.IsActive()) continue;
                    var hero = (a.Character as CharacterObject)?.HeroObject;
                    if (hero?.Name == null) continue;
                    var extracted = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                    if (string.Equals(extracted, username, StringComparison.OrdinalIgnoreCase))
                        return a;
                }
            }
            catch { }
            return null;
        }

        protected override void OnEndMission()
        {
            base.OnEndMission();
            ActiveBuffState.Clear();
        }

        private static void ApplyPassivePowers(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return;

            // Резолв hero для agent через CharacterObject.HeroObject.
            // Это работает для любых hero agents (party leaders, companions,
            // wanderers в towns, etc.) без cast'ов на specific Origin types.
            Hero hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero == null) return;

            string username = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name?.ToString());
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
