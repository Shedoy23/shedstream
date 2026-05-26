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
            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);

            MainThreadDispatcher.Enqueue(() =>
                Activate(username, powerKey, durationOverride, valueOverride, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(
            string username, string powerKey,
            float? durationOverride, double? valueOverride, string actionId)
        {
            try
            {
                if (Mission.Current == null)
                {
                    BannerlordLinkModule.Log(
                        $"[power.activate] REFUSE @{username}: no active Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_active_mission");
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
                        $"[power.activate] REFUSE @{username}: hero не spawned как agent в Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_spawned");
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
                        ActivateRage(username, durationOverride, valueOverride, agent);
                        break;
                    case "retribution_toggle":
                        ActivateRetribution(username, durationOverride, valueOverride, agent);
                        break;
                    // Sprint 5.33 (BLT-parity FX) — 3 new character effects.
                    case "poison_dot":
                        ApplyPoisonDot(agent, username, durationOverride, valueOverride);
                        break;
                    case "disarm_burst":
                        ApplyDisarmBurst(agent, username);
                        break;
                    case "berserker_charge":
                        ApplyBerserkerCharge(agent, username, durationOverride, valueOverride);
                        break;
                    default:
                        BannerlordLinkModule.Log(
                            $"[power.activate] REFUSE @{username}: unknown power '{powerKey}'");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "unknown_power:" + powerKey);
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
            // Sprint 5.30 #41 — visible cue
            BannerlordLink.Util.PowerVisualFx.PlayActivation(agent, "heal_burst", username);
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
            // Sprint 5.30 #41 — popup (particle/sound на каждом victim уже идёт через
            // TryTriggerShieldBreakFx; здесь добавляем только activation popup для caster'а).
            BannerlordLink.Util.PowerVisualFx.PlayActivation(caster, "shield_break_burst", username, broken);
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

        private static void ActivateRage(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 30f;
            double multi = valueOverride
                ?? PowerCache.GetPowerValue(username, "rage")
                ?? 1.5;
            if (multi <= 1.0) multi = 1.5;  // защита от backend mis-config
            ActiveBuffState.Activate(username, "rage", duration, multi);
            BannerlordLinkModule.Log(
                $"[power.rage] @{username}: ×{multi:F2} dmg for {duration}s");
            // Sprint 5.30 #41 — popup + sound + burst particle
            BannerlordLink.Util.PowerVisualFx.PlayActivation(
                agent, "rage", username, $"{multi:F1}");
        }

        private static void ActivateRetribution(string username, float? durationOverride,
            double? valueOverride, Agent agent)
        {
            float duration = durationOverride ?? 60f;
            double pct = valueOverride
                ?? PowerCache.GetPowerValue(username, "retribution_toggle")
                ?? 30.0;
            ActiveBuffState.Activate(username, "retribution_toggle", duration, pct);
            BannerlordLinkModule.Log(
                $"[power.retribution] @{username}: +{pct:F0}% reflect for {duration}s");
            // Sprint 5.30 #41
            BannerlordLink.Util.PowerVisualFx.PlayActivation(
                agent, "retribution_toggle", username, (int)pct);
        }

        // ── Sprint 5.33 (BLT-parity FX) — 3 new character effects ────────────

        /// <summary>Poison DoT — random enemy в радиусе получает damage per second.
        /// Stores active state в `ActiveBuffState` keyed by victim agent index.
        /// DamageHookPatch / Mission tick реально применит ticks. MVP — мы делаем
        /// ОДНОРАЗОВЫЙ damage с popup; full periodic tick — followup.
        ///
        /// Value = damage per tick. Duration = 10s. Tick interval = 1s (handled
        /// by PowersMissionBehavior.OnMissionTick через ActiveBuffState).</summary>
        private static void ApplyPoisonDot(Agent caster, string username,
            float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 10f;
            double dps = valueOverride
                ?? PowerCache.GetPowerValue(username, "poison_dot")
                ?? 5.0;

            // Find random enemy в радиусе 15м.
            Agent target = FindRandomEnemyNearby(caster, 15f);
            if (target == null)
            {
                BannerlordLinkModule.Log(
                    $"[power.poison_dot] @{username}: no enemy in 15m range");
                return;
            }
            // Apply DoT — initial burst + register для periodic tick.
            // Store по target.Index — каждый tick через PowersMissionBehavior
            // будет drain'ить.
            int initial = (int)dps;
            try
            {
                var blow = new Blow(caster.Index)
                {
                    InflictedDamage = initial,
                    DamageType = DamageTypes.Pierce,
                    DamageCalculated = true,
                    BlowFlag = BlowFlags.None,
                    BoneIndex = target.Monster?.ThoraxLookDirectionBoneIndex ?? (sbyte)0,
                    GlobalPosition = target.Position,
                    Direction = caster.LookDirection,
                    SwingDirection = caster.LookDirection,
                };
                AttackCollisionData cd = default;
                target.RegisterBlow(blow, cd);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[power.poison_dot] initial blow warn: {ex.Message}");
            }

            // Register DoT в ActiveBuffState (per-target keyed). PowersMissionBehavior
            // tick читает и применяет каждую секунду.
            ActiveBuffState.Activate(
                $"dot_target_{target.Index}", "poison_dot", duration, dps);
            BannerlordLinkModule.Log(
                $"[power.poison_dot] @{username} → enemy idx={target.Index} " +
                $"{(int)dps} dmg/s for {duration}s (initial -{initial} HP)");
            BannerlordLink.Util.PowerVisualFx.PlayActivation(target, "poison_dot", username, (int)dps);
        }

        /// <summary>Disarm burst — random enemy роняет wielded weapon.
        /// Engine API: Agent.DropItem(EquipmentIndex). Instant, no duration.</summary>
        private static void ApplyDisarmBurst(Agent caster, string username)
        {
            Agent target = FindRandomEnemyNearby(caster, 15f);
            if (target == null)
            {
                BannerlordLinkModule.Log(
                    $"[power.disarm_burst] @{username}: no enemy in 15m range");
                return;
            }
            try
            {
                // GetWieldedItemIndex API нет в нашей версии engine — loop через
                // 4 weapon slots, drop first non-empty melee/ranged item.
                EquipmentIndex dropSlot = EquipmentIndex.None;
                for (int i = 0; i < 4; i++)
                {
                    var slot = (EquipmentIndex)i;
                    if (target.Equipment[slot].IsEmpty) continue;
                    dropSlot = slot;
                    break;
                }
                if (dropSlot == EquipmentIndex.None)
                {
                    BannerlordLinkModule.Log(
                        $"[power.disarm_burst] @{username} enemy idx={target.Index} " +
                        $"has no weapons to drop");
                    return;
                }
                target.DropItem(dropSlot);
                BannerlordLinkModule.Log(
                    $"[power.disarm_burst] @{username} → enemy idx={target.Index} " +
                    $"dropped weapon slot={dropSlot}");
                BannerlordLink.Util.PowerVisualFx.PlayActivation(target, "disarm_burst", username);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[power.disarm_burst] @{username} crash: {ex.Message}");
            }
        }

        /// <summary>Berserker charge — self movement speed bonus.
        /// Value = % bonus (e.g. 50 → 1.5× speed). Duration default 8s.
        /// Agent.SetMaximumSpeedLimit — engine API.</summary>
        private static void ApplyBerserkerCharge(Agent caster, string username,
            float? durationOverride, double? valueOverride)
        {
            float duration = durationOverride ?? 8f;
            double bonusPct = valueOverride
                ?? PowerCache.GetPowerValue(username, "berserker_charge")
                ?? 50.0;
            float mult = 1f + (float)(bonusPct / 100.0);

            // Register в buff state — PowersMissionBehavior tick применит / снимет.
            ActiveBuffState.Activate(username, "berserker_charge", duration, mult);

            // Apply immediate speed bonus.
            try
            {
                // SetMaximumSpeedLimit(speed, isMultiplier=true)
                caster.SetMaximumSpeedLimit(mult, true);
                BannerlordLinkModule.Log(
                    $"[power.berserker_charge] @{username} speed ×{mult:F2} for {duration}s");
                BannerlordLink.Util.PowerVisualFx.PlayActivation(
                    caster, "berserker_charge", username, $"+{(int)bonusPct}%");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[power.berserker_charge] speed limit warn: {ex.Message}");
            }
        }

        /// <summary>Helper — find random active enemy human within radius.
        /// Used by poison_dot + disarm_burst target resolution.</summary>
        private static Agent FindRandomEnemyNearby(Agent caster, float radius)
        {
            try
            {
                var candidates = new System.Collections.Generic.List<Agent>();
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || a == caster || !a.IsActive() || !a.IsHuman) continue;
                    if (!a.IsEnemyOf(caster)) continue;
                    float dist = a.Position.Distance(caster.Position);
                    if (dist > radius) continue;
                    candidates.Add(a);
                }
                if (candidates.Count == 0) return null;
                return candidates[TaleWorlds.Core.MBRandom.RandomInt(candidates.Count)];
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[FindRandomEnemyNearby] warn: {ex.Message}");
                return null;
            }
        }
    }
}
