using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `power.activate` — triggered active ability для hero
    /// в текущей Mission.
    ///
    /// data: { target, power_key, [duration_s], [value] }
    /// Поддерживаемые power_keys:
    ///   heal_burst         — +50 HP к active agent (Sprint 4.3)
    ///   shield_break_burst — AoE: break shields всех врагов в радиусе (4.5)
    ///   rage               — timed outgoing damage multi, 30s default (4.5)
    ///   retribution_toggle — timed extra reflect %, 60s default (4.5)
    ///
    /// Timed powers держат state в ActiveBuffState (читается из DamageHookPatch).
    /// PowersMissionBehavior.OnMissionTick чистит expired каждые 2 сек.
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

            // Optional overrides — backend может передать кастомные value/duration.
            // Иначе берём дефолты из PowerCache (class+level value) и hard-coded duration.
            float? durationOverride = (float?)data["duration_s"];
            double? valueOverride = (double?)data["value"];

            MainThreadDispatcher.Enqueue(() => Activate(username, powerKey, durationOverride, valueOverride));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(
            string username, string powerKey,
            float? durationOverride, double? valueOverride)
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

                // Find agent in current mission. Match по extracted username
                // ([BLink] prefix stripped + lowercase).
                Agent agent = null;
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || !a.IsHuman || !a.IsActive()) continue;
                    var hero = (a.Character as TaleWorlds.CampaignSystem.CharacterObject)?.HeroObject;
                    if (hero?.Name == null) continue;
                    string extracted = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                    if (string.Equals(extracted, username, StringComparison.OrdinalIgnoreCase))
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
                    case "shield_break_burst":
                        ApplyShieldBreakBurst(agent, username, valueOverride);
                        break;
                    case "rage":
                        ActivateRage(username, durationOverride, valueOverride);
                        break;
                    case "retribution_toggle":
                        ActivateRetribution(username, durationOverride, valueOverride);
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

        // shield_break_burst — instant AoE: для всех живых enemy-агентов в
        // радиусе R от caster ломаем shield слот (ChangeWeaponHitPoints=0).
        // Radius — из valueOverride > PowerCache > 6m default.
        private static void ApplyShieldBreakBurst(Agent caster, string username, double? valueOverride)
        {
            float radius = (float)(
                valueOverride
                ?? PowerCache.GetPowerValue(username, "shield_break_burst")
                ?? 6.0);
            if (radius <= 0f) radius = 6f;

            int broken = 0;
            // Iterate Mission.Current.Agents — no allocation alternative для small N.
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || a == caster || !a.IsActive() || !a.IsHuman) continue;
                if (!a.IsEnemyOf(caster)) continue;
                float dist = a.Position.Distance(caster.Position);
                if (dist > radius) continue;
                if (TryBreakShield(a)) broken++;
            }

            BannerlordLinkModule.Log(
                $"[power.shield_break_burst] @{username} radius={radius}m: broke {broken} shield(s)");
        }

        // Search through weapon slots, find a shield, zero its hitpoints +
        // визуально дёрнуть native shield-break particle effect (4.6).
        // Particle через Mission.Scene.CreateBurstParticle — pure TaleWorlds API.
        // Sound пропускаем (4.6 scope: только particle).
        private static bool TryBreakShield(Agent agent)
        {
            try
            {
                for (int i = 0; i < (int)EquipmentIndex.NumAllWeaponSlots; i++)
                {
                    var idx = (EquipmentIndex)i;
                    var weapon = agent.Equipment[idx];
                    if (weapon.IsEmpty) continue;
                    var usage = weapon.CurrentUsageItem;
                    if (usage == null) continue;
                    if (usage.WeaponClass == WeaponClass.LargeShield
                        || usage.WeaponClass == WeaponClass.SmallShield)
                    {
                        agent.ChangeWeaponHitPoints(idx, 0);
                        TryTriggerShieldBreakFx(agent);
                        return true;
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shield_break] {ex.Message}");
            }
            return false;
        }

        // Native game-asset particle + sound у off-hand bone.
        // Frame = agent global frame * skeleton bone-local frame. AgentVisuals
        // может быть null если agent disposed — wrap try/catch и no-op fallback.
        // Sprint 4.9: sound через Mission.MakeSound (TaleWorlds public API).
        private static void TryTriggerShieldBreakFx(Agent agent)
        {
            try
            {
                if (agent?.AgentVisuals == null || Mission.Current?.Scene == null) return;
                var skel = agent.AgentVisuals.GetSkeleton();
                if (skel == null) return;
                sbyte bone = agent.Monster?.OffHandItemBoneIndex ?? (sbyte)-1;
                if (bone < 0) return;

                MatrixFrame frame = agent.AgentVisuals.GetGlobalFrame()
                                  * skel.GetBoneEntitialFrame(bone);
                int psysId = ParticleSystemManager.GetRuntimeIdByName("psys_game_shield_break");
                if (psysId >= 0)
                {
                    Mission.Current.Scene.CreateBurstParticle(psysId, frame);
                }

                // Sound — отдельный try/catch чтобы particle всегда срабатывал
                // даже если sound API дропнет (API нестабилен между 1.3.x patch'ами).
                try
                {
                    int soundId = SoundEvent.GetEventIdFromString(
                        "event:/mission/combat/shield/broken");
                    if (soundId >= 0)
                    {
                        // Positional args (BLT pattern, OneShotEffect.cs:54):
                        // soundEventId, position, soundEventPlayInArea, isReverbAffected,
                        // relatedAgentIndex, parentObjectIndex
                        Mission.Current.MakeSound(soundId, frame.origin, false, true, agent.Index, -1);
                    }
                }
                catch (Exception sx)
                {
                    BannerlordLinkModule.Log($"[shield_break sound] {sx.Message}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[shield_break fx] {ex.Message}");
            }
        }

        private static void ActivateRage(string username, float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 30f;
            double multi = valueOverride
                ?? PowerCache.GetPowerValue(username, "rage")
                ?? 1.5;
            if (multi <= 1.0) multi = 1.5;  // защита от backend mis-config
            ActiveBuffState.Activate(username, "rage", duration, multi);
            BannerlordLinkModule.Log(
                $"[power.rage] @{username}: ×{multi:F2} dmg for {duration}s");
        }

        private static void ActivateRetribution(string username, float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 60f;
            double pct = valueOverride
                ?? PowerCache.GetPowerValue(username, "retribution_toggle")
                ?? 30.0;
            ActiveBuffState.Activate(username, "retribution_toggle", duration, pct);
            BannerlordLinkModule.Log(
                $"[power.retribution] @{username}: +{pct:F0}% reflect for {duration}s");
        }
    }
}
