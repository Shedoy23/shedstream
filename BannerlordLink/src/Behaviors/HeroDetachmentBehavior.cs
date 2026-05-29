using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Linq;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// Sprint 5.32 (BLT-parity Detachment) — viewer-controlled in-battle commands.
    ///
    /// 2026-05-29 DET-FIX — РЕФАКТОР control механизма. Раньше приказы шли через
    /// отдельную solo-Formation + Formation.SetMovementOrder(). ПРОБЛЕМА:
    /// приказами формаций владеет TeamAI (генерал команды) — он каждый кадр
    /// переотдаёт ордера формациям и ПЕРЕБИВАЛ наш re-issue раз в 0.5с → герой
    /// игнорировал команды ("не реагирует").
    ///
    /// ТЕПЕРЬ (BLT-RC22 C.15 pattern): скриптуем самого AGENT'а, минуя TeamAI:
    ///   - Hold:   agent.SetScriptedPosition(holdPos, NeverSlowDown) — стоять
    ///   - Charge: DisableScriptedMovement + SetAutomaticTargetSelection(true) +
    ///             SetTargetFormationIndex(nearestEnemyFormation) — в бой
    ///   - Walls/Gate (siege): SetScriptedPosition(navTarget)
    ///   - Attach: DisableScriptedMovement[+Combat] — вернуть AI-контроль
    /// Re-issue каждые ~0.5с (engine иногда сбрасывает scripted state на stagger).
    ///
    /// Никаких formation-переносов → уходим и от TeamAI override, и от
    /// formation-grid краш-риска (BLT C.15 line 800 FormationFileIndex==-1 guard).
    ///
    /// State: ConcurrentDictionary&lt;agentIndex, DetachmentState&gt;. Cleanup на
    /// OnAgentDeleted / OnEndMission.
    /// </summary>
    public class HeroDetachmentBehavior : MissionBehavior
    {
        public override MissionBehaviorType BehaviorType => MissionBehaviorType.Other;

        public static HeroDetachmentBehavior Instance { get; private set; }

        public enum DetachOrder
        {
            None,
            Hold,       // stay at fixed scripted position
            Charge,     // engage nearest enemy formation
            Follow,     // return to formation AI (loose follow)
            Walls,      // siege: navigate to wall/ladder
            Gate,       // siege: navigate to gate
        }

        private class DetachmentState
        {
            public Agent Agent;
            public DetachOrder Order;
            public WorldPosition HoldPosition;   // Hold target
            public WorldPosition NavTarget;      // Walls/Gate target
            public bool NavValid;                // NavTarget set?
            public float NextReissueAt;
        }

        private readonly ConcurrentDictionary<int, DetachmentState> _states =
            new ConcurrentDictionary<int, DetachmentState>();

        private const float REISSUE_INTERVAL = 0.5f;

        // Sprint 5.32 (LOG-2) — periodic stats snapshot (отличить "никто не
        // запросил" от "behavior сломан").
        private const float STATS_LOG_INTERVAL = 10.0f;
        private float _nextStatsLogAt = 0f;
        private float _firstDetachAt = -1f;

        public override void OnBehaviorInitialize()
        {
            base.OnBehaviorInitialize();
            Instance = this;
            BannerlordLinkModule.Log("[DET] HeroDetachmentBehavior init (agent-scripted control)");
        }

        protected override void OnEndMission()
        {
            base.OnEndMission();
            _states.Clear();
            Instance = null;
        }

        public override void OnAgentDeleted(Agent affectedAgent)
        {
            base.OnAgentDeleted(affectedAgent);
            if (affectedAgent == null) return;
            _states.TryRemove(affectedAgent.Index, out _);
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            float now;
            try { now = Mission.CurrentTime; }
            catch { return; }

            if (now >= _nextStatsLogAt)
            {
                _nextStatsLogAt = now + STATS_LOG_INTERVAL;
                LogStatsSnapshot(now);
            }

            if (_states.Count == 0) return;

            List<DetachmentState> snapshot;
            try { snapshot = _states.Values.ToList(); }
            catch { return; }

            foreach (var st in snapshot)
            {
                try
                {
                    if (st == null || st.Agent == null) continue;
                    if (now < st.NextReissueAt) continue;
                    bool active;
                    try { active = st.Agent.IsActive(); }
                    catch { _states.TryRemove(st.Agent?.Index ?? -1, out _); continue; }
                    if (!active)
                    {
                        _states.TryRemove(st.Agent.Index, out _);
                        continue;
                    }
                    ReissueOrder(st);
                    st.NextReissueAt = now + REISSUE_INTERVAL;
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[DET] reissue crashed: {ex.Message}");
                }
            }
        }

        // ── Public API (called by action handlers) ─────────────────────────────

        /// <summary>Mark agent as detached (under our scripted control). Idempotent.
        /// НЕ переносит agent между формациями — просто регистрирует state.
        /// Initial order = Hold на текущей позиции.</summary>
        public bool Detach(Agent agent)
        {
            if (agent == null || !agent.IsActive()) return false;
            if (Mission.Current == null) return false;
            if (_states.ContainsKey(agent.Index)) return true;

            try
            {
                var st = new DetachmentState
                {
                    Agent = agent,
                    Order = DetachOrder.Hold,
                    HoldPosition = agent.GetWorldPosition(),
                    NextReissueAt = 0f,
                };
                _states[agent.Index] = st;
                if (_firstDetachAt < 0f)
                {
                    try { _firstDetachAt = Mission.Current.CurrentTime; } catch { _firstDetachAt = 0f; }
                }
                ApplyHold(st);
                BannerlordLinkModule.Log(
                    $"[DET] DETACH @{ResolveUsername(agent)} idx={agent.Index} " +
                    $"(scripted control, total active={_states.Count})");
                return true;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] Detach crashed: {ex.Message}");
                return false;
            }
        }

        /// <summary>Return agent to normal formation/team AI control.</summary>
        public bool Attach(Agent agent)
        {
            if (agent == null) return false;
            if (!_states.TryRemove(agent.Index, out _)) return false;
            try
            {
                if (agent.IsActive())
                {
                    try { agent.DisableScriptedMovement(); } catch { }
                    try { agent.DisableScriptedCombatMovement(); } catch { }
                    try { agent.SetAutomaticTargetSelection(true); } catch { }
                }
                BannerlordLinkModule.Log($"[DET] ATTACH agent={agent.Index} → AI control");
                return true;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] Attach crashed: {ex.Message}");
                return false;
            }
        }

        public bool Hold(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            st.Order = DetachOrder.Hold;
            try { st.HoldPosition = agent.GetWorldPosition(); } catch { }
            st.NextReissueAt = 0f;
            ApplyHold(st);
            BannerlordLinkModule.Log($"[DET] HOLD agent={agent.Index}");
            return true;
        }

        public bool Charge(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            st.Order = DetachOrder.Charge;
            st.NextReissueAt = 0f;
            ApplyCharge(st);
            BannerlordLinkModule.Log($"[DET] CHARGE agent={agent.Index}");
            return true;
        }

        public bool Follow(Agent agent)
        {
            // Follow = просто вернуть AI-контроль (агент следует за своей
            // формацией). Нет отдельной механики — эквивалент Attach без
            // удаления state (остаётся detached для будущих команд).
            if (!EnsureDetached(agent, out var st)) return false;
            st.Order = DetachOrder.Follow;
            st.NextReissueAt = 0f;
            try { agent.DisableScriptedMovement(); } catch { }
            return true;
        }

        public bool Walls(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            if (!IsSiegeMission())
            {
                BannerlordLinkModule.Log($"[DET] WALLS agent={agent.Index} REFUSE: не siege");
                return false;
            }
            var wp = FindNearestSiegeTarget(agent, gateOnly: false);
            if (!wp.IsValid)
            {
                BannerlordLinkModule.Log($"[DET] WALLS agent={agent.Index} REFUSE: target не найден");
                return false;
            }
            st.Order = DetachOrder.Walls;
            st.NavTarget = wp;
            st.NavValid = true;
            st.NextReissueAt = 0f;
            ApplyNavigate(st);
            BannerlordLinkModule.Log($"[DET] WALLS agent={agent.Index}");
            return true;
        }

        public bool Gate(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            if (!IsSiegeMission())
            {
                BannerlordLinkModule.Log($"[DET] GATE agent={agent.Index} REFUSE: не siege");
                return false;
            }
            var wp = FindNearestSiegeTarget(agent, gateOnly: true);
            if (!wp.IsValid)
            {
                BannerlordLinkModule.Log($"[DET] GATE agent={agent.Index} REFUSE: gate не найден");
                return false;
            }
            st.Order = DetachOrder.Gate;
            st.NavTarget = wp;
            st.NavValid = true;
            st.NextReissueAt = 0f;
            ApplyNavigate(st);
            BannerlordLinkModule.Log($"[DET] GATE agent={agent.Index}");
            return true;
        }

        public bool IsDetached(Agent agent)
        {
            return agent != null && _states.ContainsKey(agent.Index);
        }

        // ── Scripted-control appliers ──────────────────────────────────────────

        private void ApplyHold(DetachmentState st)
        {
            try
            {
                var pos = st.HoldPosition;
                st.Agent.SetScriptedPosition(ref pos, false,
                    Agent.AIScriptedFrameFlags.NeverSlowDown);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplyHold warn: {ex.Message}");
            }
        }

        private void ApplyCharge(DetachmentState st)
        {
            try
            {
                var agent = st.Agent;
                try { agent.DisableScriptedMovement(); } catch { }
                try { agent.DisableScriptedCombatMovement(); } catch { }
                try { agent.SetAutomaticTargetSelection(true); } catch { }
                try { agent.SetScriptedFlags(Agent.AIScriptedFrameFlags.None); } catch { }

                var enemyFormation = FindNearestEnemyFormation(agent);
                if (enemyFormation != null)
                {
                    try { agent.SetTargetFormationIndex(enemyFormation.Index); } catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplyCharge warn: {ex.Message}");
            }
        }

        private void ApplyNavigate(DetachmentState st)
        {
            if (!st.NavValid) return;
            try
            {
                var pos = st.NavTarget;
                st.Agent.SetScriptedPosition(ref pos, false,
                    Agent.AIScriptedFrameFlags.NeverSlowDown);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplyNavigate warn: {ex.Message}");
            }
        }

        private void ReissueOrder(DetachmentState st)
        {
            switch (st.Order)
            {
                case DetachOrder.Hold:   ApplyHold(st);     break;
                case DetachOrder.Charge: ApplyCharge(st);   break;
                case DetachOrder.Walls:
                case DetachOrder.Gate:   ApplyNavigate(st); break;
                case DetachOrder.Follow:
                    // AI-controlled — ничего не reissue'им.
                    break;
            }
        }

        // ── Private helpers ────────────────────────────────────────────────────

        private bool EnsureDetached(Agent agent, out DetachmentState st)
        {
            st = null;
            if (agent == null || !agent.IsActive()) return false;
            if (!_states.TryGetValue(agent.Index, out st))
            {
                if (!Detach(agent)) return false;
                if (!_states.TryGetValue(agent.Index, out st)) return false;
            }
            return true;
        }

        /// <summary>Find nearest enemy formation with units (для Charge target).</summary>
        private static Formation FindNearestEnemyFormation(Agent agent)
        {
            try
            {
                Team myTeam = agent.Team;
                if (myTeam == null || Mission.Current == null) return null;
                Vec2 ap = agent.Position.AsVec2;
                Formation best = null;
                float bestSq = float.MaxValue;
                foreach (Team t in Mission.Current.Teams)
                {
                    if (t == null || !t.IsEnemyOf(myTeam)) continue;
                    foreach (Formation f in t.FormationsIncludingEmpty)
                    {
                        if (f == null || f.CountOfUnits == 0) continue;
                        Vec2 fp;
                        try { fp = f.OrderPosition; }
                        catch { continue; }
                        float d = ap.DistanceSquared(fp);
                        if (d < bestSq) { bestSq = d; best = f; }
                    }
                }
                return best;
            }
            catch { return null; }
        }

        private string ResolveUsername(Agent agent)
        {
            try
            {
                var hero = (agent?.Character as TaleWorlds.CampaignSystem.CharacterObject)?.HeroObject;
                if (hero != null)
                {
                    var byDict = HeroIdentityBehavior.Instance?.GetUsername(hero);
                    if (!string.IsNullOrEmpty(byDict)) return byDict;
                    if (hero.Name != null)
                    {
                        string ext = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name.ToString());
                        if (!string.IsNullOrEmpty(ext)) return ext;
                    }
                }
            }
            catch { }
            return "?";
        }

        private void LogStatsSnapshot(float now)
        {
            try
            {
                int total = _states.Count;
                int holdN = 0, chargeN = 0, followN = 0, wallsN = 0, gateN = 0;
                foreach (var st in _states.Values)
                {
                    if (st == null) continue;
                    switch (st.Order)
                    {
                        case DetachOrder.Hold:   holdN++;   break;
                        case DetachOrder.Charge: chargeN++; break;
                        case DetachOrder.Follow: followN++; break;
                        case DetachOrder.Walls:  wallsN++;  break;
                        case DetachOrder.Gate:   gateN++;   break;
                    }
                }
                string sinceFirst = _firstDetachAt >= 0f ? $"{(now - _firstDetachAt):F1}s" : "—";
                BannerlordLinkModule.Log(
                    $"[DET-STATS] t={now:F1}s active={total} " +
                    $"(hold:{holdN} charge:{chargeN} follow:{followN} " +
                    $"walls:{wallsN} gate:{gateN}) since_first={sinceFirst}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET-STATS] log crashed: {ex.Message}");
            }
        }

        private bool IsSiegeMission()
        {
            try
            {
                return Mission.Current != null && Mission.Current.IsSiegeBattle;
            }
            catch { }
            // Fallback: scan behaviors по имени.
            try
            {
                foreach (var b in Mission.Current.MissionBehaviors)
                {
                    if (b == null) continue;
                    if (b.GetType().Name.IndexOf("Siege", StringComparison.OrdinalIgnoreCase) >= 0)
                        return true;
                }
            }
            catch { }
            return false;
        }

        /// <summary>Find nearest siege navigation target (gate or wall/ladder)
        /// as a WorldPosition. Scene scan по script components / name.</summary>
        private WorldPosition FindNearestSiegeTarget(Agent agent, bool gateOnly)
        {
            try
            {
                Vec3 agentPos = agent.Position;
                GameEntity bestEntity = null;
                float bestDistSq = float.MaxValue;

                var scene = Mission.Current.Scene;
                if (scene == null) return WorldPosition.Invalid;

                var allEntities = new List<GameEntity>();
                try { scene.GetAllEntitiesWithScriptComponent<SiegeLadder>(ref allEntities); }
                catch { }

                if (allEntities.Count == 0)
                {
                    try
                    {
                        var roots = new List<GameEntity>();
                        scene.GetEntities(ref roots);
                        foreach (var e in roots)
                        {
                            if (e == null) continue;
                            string nm = e.Name?.ToLowerInvariant() ?? "";
                            if (gateOnly)
                            {
                                if (nm.Contains("gate") || nm.Contains("door") || nm.Contains("barricade"))
                                    allEntities.Add(e);
                            }
                            else
                            {
                                if (nm.Contains("ladder") || nm.Contains("tower")
                                    || nm.Contains("wall_path") || nm.Contains("siege"))
                                    allEntities.Add(e);
                            }
                        }
                    }
                    catch (Exception scanEx)
                    {
                        BannerlordLinkModule.Log($"[DET] scene scan warn: {scanEx.Message}");
                    }
                }

                foreach (var e in allEntities)
                {
                    if (e == null) continue;
                    Vec3 ep;
                    try { ep = e.GlobalPosition; }
                    catch { continue; }
                    float d = (ep - agentPos).LengthSquared;
                    if (d < bestDistSq) { bestDistSq = d; bestEntity = e; }
                }

                if (bestEntity == null) return WorldPosition.Invalid;
                return new WorldPosition(Mission.Current.Scene, UIntPtr.Zero,
                    bestEntity.GlobalPosition, false);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] FindNearestSiegeTarget warn: {ex.Message}");
                return WorldPosition.Invalid;
            }
        }
    }
}
