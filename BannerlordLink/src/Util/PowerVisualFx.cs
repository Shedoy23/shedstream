using System;
using System.Collections.Generic;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Sprint 5.30 #41 — Unified visual FX layer для активации powers.
    ///
    /// Раньше:
    ///   heal_burst → silent log
    ///   shield_break_burst → particle + sound (good!)
    ///   rage → silent log
    ///   retribution_toggle → silent log
    ///
    /// Теперь все powers получают:
    ///   1. InformationManager popup в top-left ленте (цветной по power)
    ///   2. Vanilla sound через Mission.MakeSound
    ///   3. Burst particle над agent головой
    ///   4. (Для timed buffs) periodic re-burst через BuffsTickerBehavior
    ///
    /// BLT pattern (DurationMissionHeroPowerDefBase.Pfx + ActivePowerGroup.
    /// ActivateEffect/DeactivateEffect) — мы упрощаем до one-shot на activate.
    /// Continuous AgentPfx attachment — future iteration (требует internal API).
    /// </summary>
    public static class PowerVisualFx
    {
        // 2026-05-29 P1.1 (Stage 0 Phase 1) — глобальный feature flag для
        // отключения Mission.MakeSound calls во всех PlayActivation/PlayBuffTick.
        // Default: false (audio off).
        //
        // Причина: code review BLT-RC22 (Section A.1 OneShotEffect, B.10 AddDamagePower)
        // показал что они дёргают MakeSound ОЧЕНЬ редко — только on shield shatter
        // (rare event) и через ActivePowerGroup.ActivateEffect (one-shot per buff).
        // У нас же КАЖДАЯ PlayActivation дёргает MakeSound для 7 powers ×
        // N viewers × M активаций = большой FMOD pool pressure.
        //
        // Phase 1: feature flag (cheap, reversible).
        // Phase 3 (refactor): adopt OneShotEffect struct + ActivateEffect/
        // DeactivateEffect pattern. Then re-enable selectively.
        //
        // См. Расширение/docs/REFACTOR_PLAN_BLT_RC22.md секцию Phase 1.1.
        public static bool AudioEnabled = true;   // 2026-06-05 on (one-shot per activation only; BUFF_TICK + persistent pfx остаются off → FMOD pressure низкий)

        // 2026-06-05 — persistent AgentPfx (looping particle, прикреплён к агенту
        // для timed powers rage/retribution/poison/berserker). Зрители видели:
        // «огонёк» оставался НА ЗЕМЛЕ весь бой и КОПИЛСЯ каждый каст → leak
        // GameEntity/ParticleSystem (проводка HeroPfxBehaviour+ActiveBuffState на
        // бумаге верна, но на практике не следует/не чистится) → подозрение на
        // краши в БОЛЬШИХ боях (много кастов × N зрителей). Отключаем — leak уходит.
        // Re-enable (BLT-корректно: bone attach + надёжный cleanup) — позже.
        public static bool PersistentPfxEnabled = false;

        // 2026-06-06 — entry/exit BURST ТОЖЕ оставлял «огонёк» НА ЗЕМЛЕ на месте
        // активации весь бой и копился каждый каст. Причина: rage/heal/poison/
        // berserker используют ДОЛГОИГРАЮЩИЙ psys_game_burning_agent как one-shot
        // CreateBurstParticle (PlayParticle) → частица-пламя не самоуничтожается.
        // Раньше думали entry-burst безопасен (коммент выше был неверен). Гасим
        // burst тоже → остаётся popup (+sound при AudioEnabled). NB: shield_break
        // (ActivatePowerHandler) и OneShotEffect — ДРУГИЕ короткие частицы, не тут.
        public static bool BurstPfxEnabled = false;

        public class PowerFxConfig
        {
            public string PopupText;       // "@user активировал Ярость"
            public TaleWorlds.Library.Color PopupColor;
            public string SoundEventPath;  // vanilla event:/... path
            public string ParticleName;    // psys_... or empty
        }

        // Per-power FX config. Если power_key не в dict — fallback на default
        // (gold popup, no sound, no particle).
        private static readonly Dictionary<string, PowerFxConfig> CONFIG =
            new Dictionary<string, PowerFxConfig>(StringComparer.OrdinalIgnoreCase)
            {
                ["heal_burst"] = new PowerFxConfig
                {
                    PopupText      = "💊 {user} лечится (+50 HP)",
                    PopupColor     = new TaleWorlds.Library.Color(0.32f, 0.83f, 0.45f), // green
                    SoundEventPath = "event:/mission/combat/horse/hit_player",  // safe fallback (не lethal — light)
                    ParticleName   = "psys_game_burning_agent",  // closest visual для healing
                },
                ["shield_break_burst"] = new PowerFxConfig
                {
                    PopupText      = "🛡 {user} разбивает щиты",
                    PopupColor     = new TaleWorlds.Library.Color(1.0f, 0.55f, 0.0f), // orange
                    SoundEventPath = "event:/mission/combat/shield/broken",
                    ParticleName   = "psys_game_shield_break",
                },
                ["rage"] = new PowerFxConfig
                {
                    PopupText      = "🔥 {user} в ярости — damage ×{value}",
                    PopupColor     = new TaleWorlds.Library.Color(1.0f, 0.13f, 0.13f), // red
                    SoundEventPath = "event:/mission/combat/melee/swing",
                    ParticleName   = "psys_game_burning_agent",
                },
                ["retribution_toggle"] = new PowerFxConfig
                {
                    // 2026-07-21 — ключ переиспользован под «Невидимость» ассасина.
                    // В расширении ярлык пока старый («Стойкость») — фронт заморожен на
                    // ревью Twitch; в ИГРЕ пишем правду, тут заморозки нет.
                    // Звук/партикл оставлены прежние (заведомо валидные имена ассетов) —
                    // подбор «дымного» эффекта отдельной правкой, чтобы не рисковать
                    // несуществующим psys_*. См. docs/SPEC_ASSASSIN_INVIS.md.
                    PopupText      = "🌫 {user} растворился в тенях",
                    PopupColor     = new TaleWorlds.Library.Color(0.62f, 0.55f, 0.85f), // dim violet
                    SoundEventPath = "event:/mission/combat/shield/hit",
                    ParticleName   = "psys_game_shield_block_spark",
                },
                // Sprint 5.33 (BLT-parity FX) — 3 character effects.
                ["poison_dot"] = new PowerFxConfig
                {
                    PopupText      = "☠ {user} отравил врага ({value} dmg/s)",
                    PopupColor     = new TaleWorlds.Library.Color(0.5f, 0.95f, 0.3f), // poisonous green
                    SoundEventPath = "event:/mission/combat/melee/hit",
                    ParticleName   = "psys_game_burning_agent",  // зеленоватый burn = poison visual stub
                },
                ["disarm_burst"] = new PowerFxConfig
                {
                    PopupText      = "💥 {user} обезоружил врага",
                    PopupColor     = new TaleWorlds.Library.Color(1.0f, 0.85f, 0.2f), // yellow flash
                    SoundEventPath = "event:/mission/combat/shield/broken",
                    ParticleName   = "psys_game_shield_break",
                },
                ["berserker_charge"] = new PowerFxConfig
                {
                    PopupText      = "💨 {user} берсерк-рывок +{value} speed",
                    PopupColor     = new TaleWorlds.Library.Color(1.0f, 0.4f, 0.0f), // orange-red
                    SoundEventPath = "event:/mission/combat/melee/swing",
                    ParticleName   = "psys_game_burning_agent",
                },
            };

        // 2026-05-29 Stage 1 (BLT-RC22 pattern) — set of power keys которые
        // имеют persistent visual via AgentPfx (looping particle attached to
        // agent). Activation cue = entry burst. Deactivation cue (на expire)
        // = exit burst. Persistent particle между ними — НЕ re-bursted.
        //
        // Powers НЕ в этом set'е → традиционный one-shot burst behavior:
        //   - heal_burst (instant heal)
        //   - shield_break_burst (instant AoE)
        //   - disarm_burst (instant AoE)
        //
        // Powers в этом set'е → AgentPfx persistent:
        //   - rage (timed damage buff)
        //   - retribution_toggle (timed reflect)
        //   - poison_dot (timed DoT)
        //   - berserker_charge (timed speed buff)
        private static readonly System.Collections.Generic.HashSet<string> TIMED_POWERS =
            new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "rage",
                "retribution_toggle",
                "poison_dot",
                "berserker_charge",
            };

        /// <summary>Public API: show activation cue для power'а на конкретном agent'е.
        /// Wraps все три steps (popup / sound / particle) в один try'ax-блок —
        /// каждый step может fail независимо без поломки остальных.
        ///
        /// 2026-05-29 Stage 1 — для timed powers (rage/retribution_toggle/
        /// poison_dot/berserker_charge) ДОПОЛНИТЕЛЬНО создаёт AgentPfx
        /// persistent particle и attach'ит к ActiveBuffState.BuffEntry для
        /// auto-cleanup на expire.</summary>
        public static void PlayActivation(Agent agent, string powerKey, string username,
            object valueDisplay = null)
        {
            if (!CONFIG.TryGetValue(powerKey ?? "", out var cfg))
            {
                // Sprint 5.31 #45c — раньше silent fallback, теперь логируем
                // чтобы streamer видел "viewer заплатил за новую способность,
                // FX feels generic" — это значит CONFIG нужно дополнить.
                BannerlordLinkModule.Log(
                    $"[PowerFx] no config for power '{powerKey}' — using default cue");
                cfg = new PowerFxConfig
                {
                    PopupText  = "✨ {user} активировал способность",
                    PopupColor = new TaleWorlds.Library.Color(1.0f, 0.84f, 0.18f), // gold
                };
            }

            // 1. Popup (всегда показываем, даже если agent disposed)
            try
            {
                string text = (cfg.PopupText ?? "{user} → power")
                    .Replace("{user}", "@" + (username ?? "?"))
                    .Replace("{value}", valueDisplay?.ToString() ?? "");
                InformationManager.DisplayMessage(
                    new InformationMessage(text, cfg.PopupColor));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowerFx] popup error: {ex.Message}");
            }

            // 2. Sound + 3. Particle (требуют живого agent + Mission.Scene)
            if (agent == null || !agent.IsActive() || Mission.Current?.Scene == null)
                return;

            // 2a. Entry cue — one-shot burst + sound (BLT ActivateEffect pattern).
            try
            {
                MatrixFrame frame = ResolveAgentFrame(agent);
                PlayParticle(cfg.ParticleName, frame);
                PlaySound(cfg.SoundEventPath, frame, agent);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowerFx] sfx error: {ex.Message}");
            }

            // 2b. Persistent AgentPfx — только для timed powers.
            //     Replaces старый BuffsTicker re-burst pattern (Stage 0 P1.2
            //     отключил его — теперь активно используем AgentPfx).
            if (PersistentPfxEnabled
                && !string.IsNullOrEmpty(username)
                && TIMED_POWERS.Contains(powerKey)
                && !string.IsNullOrEmpty(cfg.ParticleName))
            {
                try
                {
                    var pfx = new AgentPfx(agent, cfg.ParticleName);
                    pfx.Start();
                    if (pfx.IsActive)
                    {
                        BannerlordLink.Net.ActiveBuffState.AttachPfx(username, powerKey, pfx);
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[PowerFx] persistent pfx attach failed for {powerKey}: {ex.Message}");
                }
            }
        }

        /// <summary>2026-05-29 Stage 1 — exit cue для timed buff'а (mirror'ит
        /// BLT DeactivateEffect.Trigger). Вызывается из ActiveBuffState
        /// RemoveExpired или HandleExpiredBuffs когда buff истёк.
        ///
        /// Один-разовый burst + sound (если AudioEnabled) на agent's frame.
        /// AgentPfx persistent particle stops отдельно в ActiveBuffState.RemoveExpired.
        ///
        /// No-op если agent disposed или Mission scene null.</summary>
        public static void PlayDeactivation(Agent agent, string powerKey)
        {
            if (agent == null || !agent.IsActive() || Mission.Current?.Scene == null) return;
            if (!CONFIG.TryGetValue(powerKey ?? "", out var cfg)) return;

            try
            {
                MatrixFrame frame = ResolveAgentFrame(agent);
                // Используем тот же particle что и для activation — symmetric cue.
                // Sound тот же — viewer слышит entry + exit chime.
                PlayParticle(cfg.ParticleName, frame);
                PlaySound(cfg.SoundEventPath, frame, agent);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowerFx] deactivation error: {ex.Message}");
            }
        }

        /// <summary>DEPRECATED 2026-05-29 Stage 1. Раньше PowersMissionBehavior
        /// дёргал этот method каждые 2 секунды для re-burst particle. Теперь
        /// persistent AgentPfx (см. PlayActivation для timed powers) обеспечивает
        /// continuous visual indicator. Stage 0 P1.2 уже отключил callsite —
        /// этот метод остаётся как stub для compatibility (любые caller'ы получат
        /// silent no-op).
        ///
        /// Удалить полностью когда BuffsTicker полностью убран в Stage 2+.</summary>
        public static void PlayBuffTick(Agent agent, string powerKey)
        {
            // Intentional no-op. Replaced by persistent AgentPfx.
        }

        // ── Helpers ────────────────────────────────────────────────────────

        private static MatrixFrame ResolveAgentFrame(Agent agent)
        {
            // Predict глобальная позиция: agent.AgentVisuals frame если available,
            // иначе hand-built из Position. Particle/sound происходит у chest level.
            try
            {
                if (agent.AgentVisuals != null)
                    return agent.AgentVisuals.GetGlobalFrame();
            }
            catch { }
            return new MatrixFrame(Mat3.Identity, agent.Position);
        }

        private static void PlayParticle(string psysName, MatrixFrame frame)
        {
            if (!BurstPfxEnabled) return;   // 2026-06-06 leak-fix: пламя на месте каста
            if (string.IsNullOrEmpty(psysName)) return;
            try
            {
                int psysId = ParticleSystemManager.GetRuntimeIdByName(psysName);
                if (psysId >= 0)
                {
                    Mission.Current.Scene.CreateBurstParticle(psysId, frame);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowerFx] particle '{psysName}' failed: {ex.Message}");
            }
        }

        private static void PlaySound(string soundEvent, MatrixFrame frame, Agent agent)
        {
            // 2026-05-29 P1.1 (Stage 0 Phase 1) — global mute flag.
            // По умолчанию AudioEnabled=false (см. const declaration наверху файла).
            // Все 7 powers (heal_burst, shield_break_burst, rage, retribution_toggle,
            // poison_dot, disarm_burst, berserker_charge) больше не дёргают MakeSound.
            // Particle + popup остаются — visual feedback не теряется.
            if (!AudioEnabled) return;

            if (string.IsNullOrEmpty(soundEvent)) return;
            try
            {
                int soundId = SoundEvent.GetEventIdFromString(soundEvent);
                if (soundId >= 0)
                {
                    // Positional args — same as existing shield_break_burst FX
                    // (soundEventId, position, soundEventPlayInArea=false,
                    //  isReverbAffected=true, relatedAgentIndex, parentObjectIndex)
                    Mission.Current.MakeSound(
                        soundId, frame.origin, false, true, agent.Index, -1);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowerFx] sound '{soundEvent}' failed: {ex.Message}");
            }
        }
    }
}
