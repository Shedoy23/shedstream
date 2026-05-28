using System;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Util
{
    /// <summary>
    /// 2026-05-29 Stage 1 (BLT-RC22 pattern adoption) — struct helper для
    /// one-shot particle + sound trigger. Pattern из reference/BLT_RC22/
    /// BannerlordTwitch/BannerlordTwitch/Helpers/OneShotEffect.cs.
    ///
    /// Purpose:
    ///   - Inline activation/deactivation cues для timed buffs.
    ///   - НЕ для repeated re-burst (то что Phase 1 убрал — главная FMOD problem).
    ///   - Каждый Trigger() = ровно ОДНА Mission.MakeSound + ОДНА
    ///     Scene.CreateBurstParticle. Both могут быть пустыми (no-op).
    ///
    /// Difference from раньше:
    ///   Раньше: PowerVisualFx.PlaySound / PlayParticle scattered методы,
    ///   вызываемые независимо. PlayActivation дёргал оба + потом BuffsTicker
    ///   каждые 2 сек re-bursted.
    ///   Сейчас: OneShotEffect group particle+sound в один atomic call.
    ///   Используется для entry cue (Activate) + exit cue (Expire). Между ними
    ///   AgentPfx persistent particle делает visual reinforcement без bursts.
    ///
    /// Usage:
    ///   var activate = new OneShotEffect {
    ///       Particle = "psys_game_burning_agent",
    ///       Sound = "event:/mission/combat/melee/swing"  // optional
    ///   };
    ///   activate.Trigger(agent);
    ///
    /// Audio-mute respect:
    ///   PowerVisualFx.AudioEnabled global flag (Stage 0 Phase 1) — если false,
    ///   Sound пропускается, particle всё-равно играется. Это позволяет
    ///   visual feedback без FMOD pressure.
    /// </summary>
    public struct OneShotEffect
    {
        /// <summary>Particle system name (psys_...). Empty/null → skip particle.</summary>
        public string Particle;

        /// <summary>Sound event path (event:/...). Empty/null → skip sound.
        /// Также respects PowerVisualFx.AudioEnabled global mute flag.</summary>
        public string Sound;

        public OneShotEffect(string particle, string sound)
        {
            Particle = particle;
            Sound = sound;
        }

        /// <summary>Trigger effect at agent's visuals position. No-op если
        /// agent null/inactive или AgentVisuals null.</summary>
        public void Trigger(Agent agent)
        {
            if (agent == null || !agent.IsActive()) return;
            var visuals = agent.AgentVisuals;
            if (visuals == null) return;

            try
            {
                Trigger(visuals.GetGlobalFrame(), agent.Index);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[OneShotEffect] Trigger(agent) error pfx='{Particle}' snd='{Sound}': {ex.Message}");
            }
        }

        /// <summary>Trigger effect at arbitrary world frame. relatedAgentIndex
        /// used для positional audio attribution (-1 = no source agent).</summary>
        public void Trigger(MatrixFrame location, int relatedAgentIndex = -1)
        {
            // Particle (always — visual feedback не зависит от audio mute).
            if (!string.IsNullOrEmpty(Particle))
            {
                try
                {
                    int psysId = ParticleSystemManager.GetRuntimeIdByName(Particle);
                    if (psysId >= 0 && Mission.Current?.Scene != null)
                    {
                        Mission.Current.Scene.CreateBurstParticle(psysId, location);
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[OneShotEffect] particle '{Particle}' failed: {ex.Message}");
                }
            }

            // Sound — respects PowerVisualFx.AudioEnabled global mute (Stage 0 P1.1).
            if (!string.IsNullOrEmpty(Sound) && PowerVisualFx.AudioEnabled)
            {
                try
                {
                    int soundId = SoundEvent.GetEventIdFromString(Sound);
                    if (soundId >= 0 && Mission.Current != null)
                    {
                        Mission.Current.MakeSound(
                            soundId, location.origin, false, true, relatedAgentIndex, -1);
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[OneShotEffect] sound '{Sound}' failed: {ex.Message}");
                }
            }
        }
    }
}
