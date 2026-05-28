using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Util;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// 2026-05-29 Stage 1 (BLT-RC22 pattern adoption) — lifecycle coordinator
    /// для AgentPfx instances. Pattern из reference/BLT_RC22/BannerlordTwitch/
    /// BannerlordTwitch/Behaviors/BLTAgentPfxBehaviour.cs.
    ///
    /// Responsibilities:
    ///   1. Регистрирует AgentPfx instances (через AgentPfx.Start()/Stop()).
    ///   2. Per-frame (OnPreDisplayMissionTick) — call Update() для each pfx
    ///      → keeps particle position synced to agent's visuals frame.
    ///   3. На OnAgentDeleted — auto-cleanup pfx для удалённых agents.
    ///   4. На OnEndMission — clear all (защита от leak в save game).
    ///
    /// Engine event sequence:
    ///   - OnAgentDeleted fires когда engine удаляет agent (after Killed/Routed
    ///     transition complete). У нас pfx-state Stop() здесь — освобождает
    ///     GameEntity holder + ParticleSystem.
    ///   - OnPreDisplayMissionTick fires per-frame (60+ FPS обычно) BEFORE
    ///     visual render. Мы updates holder positions здесь — particle всегда
    ///     синхронен с agent's visible position.
    ///
    /// Регистрация behaviour:
    ///   - Auto-add через MissionBehaviorCallbacks в BannerlordLinkModule
    ///     (OnMissionBehaviorInitialize). Альтернатива: manual add в Mission
    ///     при entry. Мы выбираем module-level register чтобы не пропустить.
    ///
    /// Defensive design:
    ///   - All public methods try/catch (защита от agent disposal races).
    ///   - ToList() перед iteration (collection может мутировать в Update).
    ///   - Current static accessor returns null если не зарегистрирован
    ///     → AgentPfx.Start() handles graceful no-op.
    /// </summary>
    public class HeroPfxBehaviour : MissionBehavior
    {
        private static HeroPfxBehaviour _cachedCurrent;

        /// <summary>Access from anywhere. Returns null если behaviour не attached
        /// к active Mission. AgentPfx.Register/Unregister handle null gracefully.</summary>
        public static HeroPfxBehaviour Current
        {
            get
            {
                if (Mission.Current == null) return null;
                // Cached lookup. Mission.GetMissionBehavior может быть O(N) по
                // behavior list, кешируем чтобы per-Start lookup не съел tick.
                if (_cachedCurrent == null || _cachedCurrent.Mission != Mission.Current)
                {
                    _cachedCurrent = Mission.Current.GetMissionBehavior<HeroPfxBehaviour>();
                }
                return _cachedCurrent;
            }
        }

        public override MissionBehaviorType BehaviorType => MissionBehaviorType.Other;

        private readonly List<AgentPfx> _attached = new();

        /// <summary>Register AgentPfx для per-frame Update. Called from
        /// AgentPfx.Start() after particle successfully created.</summary>
        public void Register(AgentPfx pfx)
        {
            if (pfx == null) return;
            if (_attached.Contains(pfx)) return;
            _attached.Add(pfx);
        }

        /// <summary>Unregister AgentPfx. Called from AgentPfx.Stop() before
        /// disposal.</summary>
        public void Unregister(AgentPfx pfx)
        {
            if (pfx == null) return;
            _attached.Remove(pfx);
        }

        public override void OnPreDisplayMissionTick(float dt)
        {
            // Iterate over copy — Update() может trigger Stop() → Unregister →
            // collection modification. ToList() snapshot гарантирует safety.
            try
            {
                foreach (var pfx in _attached.ToList())
                {
                    try { pfx.Update(); }
                    catch (Exception ex)
                    {
                        // Per-pfx error — log один раз per crash, не валим весь tick.
                        BannerlordLinkModule.Log(
                            $"[HeroPfxBehaviour] per-pfx Update error: {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroPfxBehaviour] OnPreDisplayMissionTick error: {ex.Message}");
            }
        }

        public override void OnAgentDeleted(Agent affectedAgent)
        {
            try
            {
                if (affectedAgent == null) return;
                var toRemove = _attached.Where(p => p.Agent == affectedAgent).ToList();
                foreach (var pfx in toRemove)
                {
                    try { pfx.Stop(); }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[HeroPfxBehaviour] OnAgentDeleted cleanup error: {ex.Message}");
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroPfxBehaviour] OnAgentDeleted error: {ex.Message}");
            }
        }

        protected override void OnEndMission()
        {
            try
            {
                foreach (var pfx in _attached.ToList())
                {
                    try { pfx.Stop(); } catch { /* swallow */ }
                }
                _attached.Clear();
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroPfxBehaviour] OnEndMission error: {ex.Message}");
            }
            finally
            {
                _cachedCurrent = null;
            }

            base.OnEndMission();
        }
    }
}
