using System;
using System.Collections.Generic;
using BannerlordLink.Behaviors;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Util
{
    /// <summary>
    /// 2026-05-29 Stage 1 (BLT-RC22 pattern adoption) — persistent particle
    /// attached to agent. Pattern из reference/BLT_RC22/BannerlordTwitch/
    /// BannerlordTwitch/Helpers/AgentPfx.cs.
    ///
    /// КЛЮЧЕВАЯ РАЗНИЦА с нашим прошлым подходом:
    ///   Раньше: PowerVisualFx.PlayBuffTick → CreateBurstParticle каждые 2 сек
    ///   (≈15 burst particles за 30-сек buff'а). High FMOD pool pressure.
    ///   Сейчас: AgentPfx.Start() создаёт ОДИН looping particle attached к
    ///   agent через GameEntity holder. Per-frame frame sync.
    ///
    /// Workflow:
    ///   1. На Activate buff'а — new AgentPfx(agent, "psys_...").Start()
    ///   2. HeroPfxBehaviour.Current регистрирует pfx, per-frame дёргает Update()
    ///   3. Update() — sets holder GlobalFrame в текущий agent.AgentVisuals frame
    ///      (particle следует за agent'ом автоматически)
    ///   4. На Expire/death/mission_over — Stop()
    ///
    /// Simplified vs BLT-RC22 source:
    ///   - НЕТ weapon-specific attachment (BLT for blades/maces — мы skip)
    ///   - НЕТ per-bone offset (один particle на body level)
    ///   - НЕТ AttachPointEnum (один body-level position)
    ///   Этого достаточно для нашего use case (rage/retribution_toggle/poison_dot/
    ///   berserker_charge — все visual indicators "buff active").
    ///
    /// Engine API:
    ///   - ParticleSystem.CreateParticleSystemAttachedToEntity(name, entity, ref frame)
    ///     → LOOPING particle (NOT burst). Continues until entity removed.
    ///   - holderEntity.SetGlobalFrame(...) — moves particle в world space per tick.
    ///   - holderEntity.Scene.RemoveEntity(...) — cleanup on Stop().
    /// </summary>
    public class AgentPfx
    {
        /// <summary>Agent which this particle is following.</summary>
        public Agent Agent { get; }

        /// <summary>Particle system name (psys_...). E.g. "psys_game_burning_agent".</summary>
        public string PfxName { get; }

        /// <summary>Vertical offset from agent's visuals base (in metres).
        /// Default 1.2m — приблизительно над torso. BLT uses bone-based positioning,
        /// мы simplified до constant elevation.</summary>
        public float VerticalOffset { get; set; } = 1.2f;

        private GameEntity _holderEntity;
        private ParticleSystem _particle;
        private bool _started;

        public AgentPfx(Agent agent, string pfxName)
        {
            Agent = agent;
            PfxName = pfxName;
        }

        /// <summary>True if particle currently attached (between Start and Stop).</summary>
        public bool IsActive => _started && _holderEntity != null;

        /// <summary>Create particle and attach к scene. Idempotent — повторный
        /// Start no-op'ит. Auto-registers с HeroPfxBehaviour.Current если есть.</summary>
        public void Start()
        {
            if (_started) return;
            if (Agent == null || !Agent.IsActive()) return;
            if (string.IsNullOrEmpty(PfxName)) return;

            var agentVisuals = Agent.AgentVisuals;
            if (agentVisuals == null) return;

            var scene = agentVisuals.GetEntity()?.Scene;
            if (scene == null) return;

            try
            {
                // 1. Create empty holder entity in scene. We will move this entity
                //    per-frame to follow agent. Particle attached к этому holder'у.
                _holderEntity = GameEntity.CreateEmpty(scene);
                if (_holderEntity == null) return;

                // 2. Position holder at agent's visuals frame + vertical offset.
                var initialFrame = agentVisuals.GetGlobalFrame();
                _holderEntity.SetGlobalFrame(initialFrame);

                // 3. Create persistent looping particle attached к holder.
                //    Local frame = small upward offset чтобы particle над torso.
                var localFrame = MatrixFrame.Identity.Elevate(VerticalOffset);
                _particle = ParticleSystem.CreateParticleSystemAttachedToEntity(
                    PfxName, _holderEntity, ref localFrame);

                if (_particle == null)
                {
                    // Particle creation failed (invalid pfx name?) — cleanup holder.
                    try { scene.RemoveEntity(_holderEntity, 85); } catch { /* swallow */ }
                    _holderEntity = null;
                    return;
                }

                _started = true;

                // 4. Register с lifecycle coordinator (auto-update + auto-cleanup).
                HeroPfxBehaviour.Current?.Register(this);
            }
            catch (Exception ex)
            {
                // Cleanup partial state on failure.
                try { if (_holderEntity != null) scene.RemoveEntity(_holderEntity, 85); }
                catch { /* swallow */ }
                _holderEntity = null;
                _particle = null;
                _started = false;
                BannerlordLinkModule.Log($"[AgentPfx] Start error pfx='{PfxName}': {ex.Message}");
            }
        }

        /// <summary>Update holder position to follow agent. Called per-frame by
        /// HeroPfxBehaviour.OnPreDisplayMissionTick. No-op if not started or agent
        /// inactive.</summary>
        public void Update()
        {
            if (!_started || _holderEntity == null) return;
            if (Agent == null || !Agent.IsActive()) return;

            try
            {
                var agentVisuals = Agent.AgentVisuals;
                if (agentVisuals == null) return;
                _holderEntity.SetGlobalFrame(agentVisuals.GetGlobalFrame());
            }
            catch (Exception ex)
            {
                // Update failure (agent disposed mid-frame?) — auto-stop защитa.
                BannerlordLinkModule.Log(
                    $"[AgentPfx] Update error pfx='{PfxName}': {ex.Message} — stopping");
                Stop();
            }
        }

        /// <summary>Remove particle + holder entity. Idempotent — повторный Stop
        /// no-op'ит. Auto-unregisters из HeroPfxBehaviour.Current.</summary>
        public void Stop()
        {
            if (!_started) return;

            try
            {
                if (_holderEntity != null)
                {
                    var scene = _holderEntity.Scene;
                    try { _holderEntity.ClearComponents(); }
                    catch { /* swallow — entity may already be partially disposed */ }
                    try { scene?.RemoveEntity(_holderEntity, 85); }
                    catch { /* swallow */ }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[AgentPfx] Stop error pfx='{PfxName}': {ex.Message}");
            }
            finally
            {
                _holderEntity = null;
                _particle = null;
                _started = false;
                HeroPfxBehaviour.Current?.Unregister(this);
            }
        }
    }
}
