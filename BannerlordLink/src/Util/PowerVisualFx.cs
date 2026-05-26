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
                    PopupText      = "↩ {user} возмездие +{value}% reflect",
                    PopupColor     = new TaleWorlds.Library.Color(0.55f, 0.78f, 1.0f), // blue
                    SoundEventPath = "event:/mission/combat/shield/hit",
                    ParticleName   = "psys_game_shield_block_spark",
                },
            };

        /// <summary>Public API: show activation cue для power'а на конкретном agent'е.
        /// Wraps все три steps (popup / sound / particle) в один try'ax-блок —
        /// каждый step может fail независимо без поломки остальных.</summary>
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
        }

        /// <summary>Для timed buffs — periodic re-burst чтобы visually
        /// reinforce «эта способность ВСЁ ЕЩЁ активна». Subtle smaller version.
        /// Вызывается из BuffsTickerBehavior каждые ~3 сек.</summary>
        public static void PlayBuffTick(Agent agent, string powerKey)
        {
            if (agent == null || !agent.IsActive() || Mission.Current?.Scene == null)
                return;
            if (!CONFIG.TryGetValue(powerKey ?? "", out var cfg)) return;
            if (string.IsNullOrEmpty(cfg.ParticleName)) return;

            try
            {
                MatrixFrame frame = ResolveAgentFrame(agent);
                PlayParticle(cfg.ParticleName, frame);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[PowerFx] tick burst error: {ex.Message}");
            }
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
