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

        // 2026-05-29 P1.2 (Stage 0 Phase 1) — feature flag для отключения
        // per-tick particle re-burst. Сравнение с BLT-RC22 показало что они
        // создают particle ОДИН раз (AgentPfx persistent looping) и НЕ дёргают
        // CreateBurstParticle каждые 2 сек. См. docs/BLT_RC22_REFERENCE.md
        // секция A.2 и refactor plan Phase 3 — full AgentPfx adoption.
        //
        // Сейчас (Phase 1) — просто отключаем re-burst. Это убирает
        // 15 particle calls на каждые 30 сек активного buff'а на каждого
        // viewer'а с активным buff'ом. В большой battle с 5+ buff'ами это
        // 75+ particle calls сэкономлено за 30 сек. Понижает FMOD pressure
        // на ~5-10%.
        //
        // Phase 3 заменит этот flag на persistent AgentPfx (BLT pattern).
        private const bool BUFF_TICK_PARTICLES_ENABLED = false;

        // 2026-06-02 (BLT-parity POWER) — HP-множители в одном месте для тюнинга.
        private const float BASE_HP_MULT = 2.5f;     // герой baseline (2026-06-05: 2→2.5, BLT-parity)
        public  const float RETINUE_HP_MULT = 2f;     // свита (BLT StartRetinueHealthMultiplier=2)
        // Ставится SummonHeroHandler'ом ВОКРУГ retinue SpawnTroop; применяется
        // в OnAgentBuild (санкционированный тайминг — не крашит, в отличие от
        // старого inline post-spawn сеттера, dump 28004).
        public static float PendingRetinueHpMult = 1f;

        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            try { ApplyPassivePowers(agent); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] OnAgentBuild error: {ex.Message}");
            }
            // retinue HP×2 (pending-флаг от SummonHeroHandler) — к человеку-агенту.
            try { ApplyPendingRetinueHp(agent); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] retinue HP warn: {ex.Message}");
            }
        }

        private static void ApplyPendingRetinueHp(Agent agent)
        {
            float m = PendingRetinueHpMult;
            if (m <= 1f || agent == null || !agent.IsHuman) return;
            agent.BaseHealthLimit *= m;
            agent.HealthLimit     *= m;
            agent.Health          *= m;
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

            // 2026-06-10 — «умный боевой ИИ»: переприменяем AI-способности
            // блока/парри/атаки боевым героям (движок пересчитывает драйв-свойства).
            try { ApplyCombatAiTick(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowersMission] combat-AI tick error: {ex.Message}");
            }

            // Sprint 5.30 #41 — periodic re-burst для timed buffs.
            // 2026-05-29 P1.2 — отключено через BUFF_TICK_PARTICLES_ENABLED flag.
            // CreateBurstParticle каждые 2 сек = FMOD pool pressure. См.
            // комментарий у константы наверху файла.
            if (BUFF_TICK_PARTICLES_ENABLED)
            {
                try { PlayBuffTickParticles(); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[PowersMission] buff tick fx error: {ex.Message}");
                }
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
                            // 2026-06-10 — сбрасываем НЕ в 1.0×, а в пассивную
                            // скорость милишника (move_speed_pct), иначе berserk
                            // терял свой пассивный добег после берсерк-чарджа.
                            float restMult = GetPassiveSpeedMult(username);
                            agent.SetMaximumSpeedLimit(restMult, true);
                            BannerlordLinkModule.Log(
                                $"[FX expire] @{username} berserker_charge → speed reset ×{restMult:F2}");
                        }
                    }
                    // poison_dot expire — no agent-side cleanup needed (we don't
                    // mutate engine state on each tick, just RegisterBlow).

                    // 2026-05-29 Stage 1 (BLT-RC22 pattern) — exit cue для
                    // timed buffs. AgentPfx.Stop() уже произошёл в
                    // ActiveBuffState.RemoveExpired. Здесь play one-shot
                    // burst+sound chime чтобы viewer видел "buff закончился".
                    // No-op для buff'ов которые НЕ имели persistent pfx
                    // (instant powers — heal_burst/shield_break/disarm_burst
                    // не попадают в expired list т.к. их duration=0).
                    var pfxAgent = FindAgentByUsername(username);
                    if (pfxAgent != null && pfxAgent.IsActive())
                    {
                        BannerlordLink.Util.PowerVisualFx.PlayDeactivation(pfxAgent, powerKey);
                    }
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
                    // 2026-05-31 (audit) — не тикаем DoT в не-mortal/турнир/арена
                    // миссиях (DisableDying), иначе lethal урон там, где движок
                    // этого не ждёт (BLT BLTEffectsBehaviour gate'ит так же).
                    if (target.CurrentMortalityState != Agent.MortalityState.Mortal
                        || Mission.Current?.DisableDying == true) continue;
                    int dmg = (int)Math.Max(1.0, dps * BUFF_TICK_INTERVAL);
                    var blow = new Blow(target.Index)   // 2026-05-31 (audit): был Blow(-1) — невалидный owner-index
                    {
                        InflictedDamage = dmg,
                        DamageType = DamageTypes.Pierce,
                        DamageCalculated = true,
                        BlowFlag = BlowFlags.None,
                        BoneIndex = target.Monster?.ThoraxLookDirectionBoneIndex ?? (sbyte)0,
                        GlobalPosition = target.Position,
                        Direction = TaleWorlds.Library.Vec3.Forward,
                        SwingDirection = TaleWorlds.Library.Vec3.Forward,
                        WeaponRecord = new() { AffectorWeaponSlotOrMissileIndex = -1 },   // 2026-05-31 (audit): init weapon-record
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

        // 2026-06-10 — «умный боевой ИИ» (BLT StatModifyPower через
        // AgentDrivenProperties). Поднимаем AI-способности блока/парри/решений
        // атаки боевым героям, чтобы они реально воевали, а не стояли столбом.
        // Для мили это бой в гуще; для лучников — самозащита, когда враг
        // дошёл вплотную (скорострельность/точность НЕ трогаем — иначе лучники
        // станут ещё сильнее). ai_combat_pct (0..100) → 0..1 ability.
        // max() — никогда не занижаем естественно высокий навык героя.
        // Переприменяем на тике: движок пересчитывает driven-свойства.
        // AgentDrivenProperties — НЕ collision-reaction → безопасно (BLT-паттерн).
        private static readonly DrivenProperty[] _aiCombatProps = new[]
        {
            DrivenProperty.AIBlockOnDecideAbility,
            DrivenProperty.AIParryOnDecideAbility,
            DrivenProperty.AIAttackOnDecideChance,
            DrivenProperty.AIDecideOnAttackChance,
            DrivenProperty.AIParryOnAttackAbility,
        };

        private static void ApplyCombatAiTick()
        {
            if (Mission.Current == null) return;
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || !a.IsHuman || !a.IsActive()) continue;
                var hero = (a.Character as CharacterObject)?.HeroObject;
                if (hero?.Name == null) continue;
                string user = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                if (string.IsNullOrEmpty(user)) continue;
                var pct = PowerCache.GetPowerValue(user, "ai_combat_pct");
                if (!pct.HasValue || pct.Value <= 0) continue;
                float v = (float)Math.Min(1.0, pct.Value / 100.0);
                try
                {
                    var p = a.AgentDrivenProperties;
                    if (p == null) continue;
                    bool changed = false;
                    foreach (var prop in _aiCombatProps)
                    {
                        if (v > p.GetStat(prop)) { p.SetStat(prop, v); changed = true; }
                    }
                    if (changed) a.UpdateCustomDrivenProperties();
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[CombatAI] @{user} warn: {ex.Message}");
                }
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

            // 2026-06-02 (BLT-parity POWER) — безусловный baseline HP×2 для КАЖДОГО
            // [BLink]-героя на спавне (BLT StartHealthMultiplier=2, unconditional).
            // ДО class-check → даже classless adopted-герой получает живучесть.
            // Класс-power hp_multiplier (ниже) стэкается сверху (как BLT AddHealthPower).
            agent.BaseHealthLimit *= BASE_HP_MULT;
            agent.HealthLimit     *= BASE_HP_MULT;
            agent.Health          *= BASE_HP_MULT;

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

            // ── move_speed_pct (2026-06-10 мили-баланс) — добег / анти-кайт ──
            // Пеший милишник иначе не догоняет лучников и кайтящих конных.
            // SetMaximumSpeedLimit(mult, true) — тот же API, что у berserker_charge.
            var spd = PowerCache.GetPowerValue(username, "move_speed_pct");
            if (spd.HasValue && spd.Value > 0)
            {
                try { agent.SetMaximumSpeedLimit(1f + (float)(spd.Value / 100.0), true); }
                catch (Exception ex)
                { BannerlordLinkModule.Log($"[PowersMission] move_speed warn: {ex.Message}"); }
            }

            BannerlordLinkModule.Log(
                $"[PowersMission] @{username} ({hc.Value.classKey} L{hc.Value.level}): " +
                $"hp×{hp ?? 1.0:F2} scale×{scale ?? 1.0:F2} spd+{spd ?? 0.0:F0}%");
        }

        /// <summary>2026-06-10 (мили-баланс) — «покоящийся» множитель скорости
        /// героя (пассивный move_speed_pct). Чтобы при истечении berserker_charge
        /// сбрасывать НЕ в 1.0×, а в пассивную скорость милишника.</summary>
        public static float GetPassiveSpeedMult(string username)
        {
            var spd = PowerCache.GetPowerValue(username, "move_speed_pct");
            return (spd.HasValue && spd.Value > 0) ? 1f + (float)(spd.Value / 100.0) : 1f;
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
