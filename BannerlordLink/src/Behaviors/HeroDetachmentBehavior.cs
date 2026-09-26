using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Linq;
using TaleWorlds.Core;
using TaleWorlds.Engine;
using TaleWorlds.Library;
using TaleWorlds.MountAndBlade;
using BannerlordLink.Util;

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
    ///   - Charge: scripted approach to a target, native combat on contact;
    ///             infantry selects reachable humans and limits cavalry pursuit.
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

        // 2026-06-01 FIX — раньше был автосвойством {get;private set;}. ПРОБЛЕМА:
        // static Instance обнулялся OnEndMission'ом overlapping/nested миссии
        // (hideout!) ПОКА этот behavior ещё жив и тикает → detach-команды видели
        // Instance==null ("behavior null" / "charge_failed"), хотя агент в бою.
        // Теперь резолвим из текущей миссии (авторитетно), static — fallback.
        private static HeroDetachmentBehavior _instance;
        public static HeroDetachmentBehavior Instance
        {
            get
            {
                try
                {
                    var b = Mission.Current?.GetMissionBehavior<HeroDetachmentBehavior>();
                    if (b != null) return b;
                }
                catch { }
                return _instance;
            }
            private set { _instance = value; }
        }

        public enum DetachOrder
        {
            None,
            Hold,       // stay at fixed scripted position
            Charge,     // approach selected enemy, release to native combat nearby
            Follow,     // return to formation AI (loose follow)
            Walls,      // siege: navigate to wall/ladder
            Gate,       // siege: navigate to gate
            Skirmish,   // harass at standoff range + auto-target (ranged)
            Raid,       // mounted elliptical orbit around nearest enemy + auto-target
        }

        private class DetachmentState
        {
            public Agent Agent;
            public DetachOrder Order;
            public WorldPosition HoldPosition;   // Hold target
            public WorldPosition NavTarget;      // Walls/Gate target
            public bool NavValid;                // NavTarget set?
            public float NextReissueAt;
            public bool SkirmishHolding;         // Skirmish: запинен на standoff (зона покоя) → не re-issue'им
            public string Status;
            public Agent ChargeTarget;
            public readonly Dictionary<Agent, float> IgnoredTargets = new Dictionary<Agent, float>();
            public float ProgressAt;
            public float LastProgressDistance;
            public Vec3 LastProgressPosition;
            public float NextTargetSearchAt;
            public int TargetSearchCursor;
            public float NextPathCheck;
            public bool ChargeEngaged;           // Charge: враг в упор, управление отдано боевому AI
            public int  KiteCount;               // Skirmish: attempts in this order; never auto-reset
            public bool KiteMoving;
            public WorldPosition KiteTarget;
            public float KiteDeadline;
            public float KiteProgressAt;
            public float KiteDistance;
            public float KiteReadyAt;            // Skirmish: раньше этого времени отходить нельзя
            public bool Breach;                  // Gate (атака): все ворота разбиты — пройти внутрь и драться
            public float NextRetargetAt;         // Gate: ворота ломают по ходу боя — цель пересчитываем
        }

        private readonly ConcurrentDictionary<int, DetachmentState> _states =
            new ConcurrentDictionary<int, DetachmentState>();

        private const float REISSUE_INTERVAL = 0.5f;

        // 2026-06-17 (рич-приказы) — Skirmish/Raid математика портирована из движковых
        // behaviors (agent-level, без запуска самих behaviors — без крашей):
        //   SKIRMISH_STANDOFF — pull-back дистанция, по BehaviorSkirmish (стоять на
        //     enemy + dirToMe*standoff: ближе standoff'а — отступает, дальше — поджимает).
        //   RAID_ORBIT_RADIUS — радиус орбиты, по BehaviorMountedSkirmish (база 20м).
        //   RAID_ORBIT_STEP_RAD — насколько проворачиваем точку-цель вокруг врага за
        //     один re-issue (0.5с) → конный кружит CCW вокруг ближайшего врага.
        private const float SKIRMISH_STANDOFF = 22f;   // фолбэк, если дальность оружия недоступна
        // Дистанция «встал и стреляет» = SKIRMISH_RANGE_FRACTION × реальной макс. дальности
        // выстрела оружия героя (движковый Agent.MaximumMissileRange — считает сам движок по
        // оружию в руках). ±band вокруг неё = мёртвая зона против джиттера (принцип
        // BehaviorSkirmish: держать в полосе, двигаться только вне её). Репорт #32.
        private const float SKIRMISH_RANGE_FRACTION = 0.8f;
        private const float SKIRMISH_MIN_STANDOFF = 18f;
        private const float SKIRMISH_MAX_STANDOFF = 90f;
        private const float RAID_ORBIT_RADIUS = 20f;
        private const float RAID_ORBIT_STEP_RAD = 0.4f;
        // #walls: свой боец «выше нас» на столько метров = стоит на забрале, а не на нашем
        // уровне → его позиция и есть боевая точка на стене, куда вести героя.
        private const float WALL_MIN_ELEVATION = 2.5f;

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
            // 2026-06-01 FIX — обнуляем static ТОЛЬКО если это мы. Иначе
            // OnEndMission старой/overlapping миссии затирал Instance живого
            // behavior'а (hideout) → команды видели "behavior null".
            if (ReferenceEquals(_instance, this)) _instance = null;
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
                    if (now < st.NextReissueAt || st.Status == "blocked") continue;
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
                    st.Status = "blocked";
                    try { st.Agent.DisableScriptedMovement(); } catch { }
                    BannerlordLinkModule.Log($"[DET] reissue blocked: {ex.Message}");
                }
            }
        }

        // ── Public API (called by action handlers) ─────────────────────────────

        /// <summary>Start individual Hold; refuse a redundant paid Detach.
        /// НЕ переносит agent между формациями — просто регистрирует state.
        /// Initial order = Hold на текущей позиции.</summary>
        public bool Detach(Agent agent)
        {
            if (agent == null || IsDetached(agent)) return false;
            return IssueOrder(agent, DetachOrder.Hold);
        }

        public bool Attach(Agent agent)
        {
            if (agent == null || !_states.TryGetValue(agent.Index, out var st)) return false;
            try
            {
                agent.DisableScriptedMovement();
                agent.DisableScriptedCombatMovement();
                agent.SetAutomaticTargetSelection(true);
                _states.TryRemove(agent.Index, out _);
                BannerlordLinkModule.Log($"[DET] ATTACH agent={agent.Index} -> AI control");
                return true;
            }
            catch (Exception ex)
            {
                // Keep the state so a failed cancellation is visible and retryable.
                RestoreOrder(st);
                BannerlordLinkModule.Log($"[DET] Attach failed: {ex.Message}");
                return false;
            }
        }

        public bool Hold(Agent agent) => IssueOrder(agent, DetachOrder.Hold);
        public bool Charge(Agent agent) => IssueOrder(agent, DetachOrder.Charge);
        public bool Skirmish(Agent agent) => IssueOrder(agent, DetachOrder.Skirmish);
        public bool Raid(Agent agent) => IssueOrder(agent, DetachOrder.Raid);
        public bool Follow(Agent agent) => IssueOrder(agent, DetachOrder.Follow);

        public bool Walls(Agent agent)
        {
            if (!CanControl(agent) || !IsSiegeMission()) return false;
            bool defender = IsDefender(agent);
            var target = FindWallFiringPosition(agent, defender);
            if (!target.IsValid && !defender) target = FindAttackerClimbPoint(agent);
            if (!target.IsValid) target = FindNearestSiegeTarget(agent, false);
            if (!CanPathTo(agent, target)) return false;
            return IssueOrder(agent, DetachOrder.Walls, target);
        }

        public bool Gate(Agent agent)
        {
            if (!CanControl(agent) || !IsSiegeMission()) return false;
            var target = FindGateTarget(agent, out bool breach);
            if (!target.IsValid) { breach = false; target = FindNearestSiegeTarget(agent, true); }
            if (!CanPathTo(agent, target)) return false;
            if (!IssueOrder(agent, DetachOrder.Gate, target)) return false;
            if (_states.TryGetValue(agent.Index, out var st))
            {
                st.Breach = breach;
                st.NextRetargetAt = Mission.CurrentTime + GATE_RETARGET_INTERVAL;
            }
            return true;
        }

        /// <summary>Ворота ломают по ходу боя: раз в столько секунд цель «к воротам» пересчитывается.</summary>
        private const float GATE_RETARGET_INTERVAL = 3f;

        private static bool IsDefender(Agent agent)
        {
            try { return agent.Team != null && agent.Team.Side == BattleSideEnum.Defender; }
            catch { return false; }
        }

        private static SiegePoint P(Vec3 v) => new SiegePoint(v.x, v.y, v.z);
        private static Vec3 V(SiegePoint p) => new Vec3(p.X, p.Y, p.Z);

        /// <summary>Цель «к воротам» по стороне осады (SiegeOrderPolicy.PickGate). Invalid —
        /// ворот не нашли, вызывающий берёт старый поиск по сцене.</summary>
        private WorldPosition FindGateTarget(Agent agent, out bool breach)
        {
            breach = false;
            try
            {
                var scene = Mission.Current?.Scene;
                if (scene == null) return WorldPosition.Invalid;
                bool defender = IsDefender(agent);
                var gates = new List<SiegeGate>();
                foreach (var mo in Mission.Current.ActiveMissionObjects)
                {
                    if (!(mo is CastleGate g)) continue;
                    gates.Add(new SiegeGate {
                        Outer = g.GameEntity.HasTag(CastleGate.OuterGateTag),
                        Inner = g.GameEntity.HasTag(CastleGate.InnerGateTag),
                        Open = g.IsGateOpen,
                        Middle = P(g.MiddleFrame.Origin.GetGroundVec3()),
                        Wait = P(g.DefenseWaitFrame.Origin.GetGroundVec3()),
                    });
                }
                var pick = SiegeOrderPolicy.PickGate(defender, gates, P(agent.Position));
                if (pick.Goal == GateGoal.None) return WorldPosition.Invalid;
                breach = pick.Goal == GateGoal.Breach;
                BannerlordLinkModule.Log($"[DET] GATE target agent={agent.Index} side={(defender ? "defender" : "attacker")} "
                    + $"gate={(pick.Gate.Outer ? "outer" : pick.Gate.Inner ? "inner" : "single")} open={pick.Gate.Open} goal={pick.Goal} gates={gates.Count}");
                return ProjectToNavMesh(scene, V(pick.Point));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] FindGateTarget warn: {ex.Message}");
                return WorldPosition.Invalid;
            }
        }

        /// <summary>Атакующий, которому на стену пока нет пути: к подведённой осадной
        /// башне или поднятой лестнице — туда, где идёт штурм. Лезть по лестнице скриптом
        /// агента нельзя (потолок agent-level), поэтому это основание, и дальше герой
        /// держит место и дерётся с теми, кто спускается к лестнице.</summary>
        private WorldPosition FindAttackerClimbPoint(Agent agent)
        {
            try
            {
                var scene = Mission.Current?.Scene;
                if (scene == null) return WorldPosition.Invalid;
                WorldPosition best = WorldPosition.Invalid;
                float bestSq = float.MaxValue;
                foreach (var mo in Mission.Current.ActiveMissionObjects)
                {
                    bool active = mo is SiegeTower t && t.HasArrivedAtTarget
                        || mo is SiegeLadder l && l.State == SiegeLadder.LadderState.OnWall;
                    if (!active) continue;
                    Vec3 at = mo.GameEntity.GlobalPosition;
                    float d = (at - agent.Position).LengthSquared;
                    if (d >= bestSq) continue;
                    var wp = ProjectToNavMesh(scene, at);
                    if (!CanPathTo(agent, wp)) continue;
                    best = wp; bestSq = d;
                }
                return best;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] FindAttackerClimbPoint warn: {ex.Message}");
                return WorldPosition.Invalid;
            }
        }

        private static bool CanControl(Agent agent)
        {
            return agent != null && agent.IsActive() && Mission.Current != null
                && agent != Agent.Main && agent.IsAIControlled;
        }

        // Validate first, apply a fresh state, then publish it. A refused command
        // never silently replaces a previous order with the old implicit Hold.
        private bool IssueOrder(Agent agent, DetachOrder order, WorldPosition? destination = null)
        {
            if (!CanControl(agent)) return false;
            _states.TryGetValue(agent.Index, out var previous);
            try
            {
                var st = new DetachmentState {
                    Agent = agent, Order = order, HoldPosition = agent.GetWorldPosition(),
                    NavTarget = destination ?? WorldPosition.Invalid, NavValid = destination.HasValue,
                    ProgressAt = Mission.CurrentTime, LastProgressDistance = float.MaxValue,
                    LastProgressPosition = agent.Position,
                    Status = order.ToString().ToLowerInvariant(),
                    NextReissueAt = Mission.CurrentTime + REISSUE_INTERVAL
                };
                ReissueOrder(st);
                _states[agent.Index] = st;
                if (_firstDetachAt < 0) _firstDetachAt = Mission.CurrentTime;
                BannerlordLinkModule.Log($"[DET] {order.ToString().ToUpperInvariant()} agent={agent.Index} status={st.Status}");
                return true;
            }
            catch (Exception ex)
            {
                if (previous != null) RestoreOrder(previous);
                else
                {
                    try { agent.DisableScriptedMovement(); agent.DisableScriptedCombatMovement(); } catch { }
                }
                BannerlordLinkModule.Log($"[DET] {order} REFUSE agent={agent.Index}: {ex.Message}");
                return false;
            }
        }

        private void RestoreOrder(DetachmentState st)
        {
            try {
                if (st.Status == "blocked")
                {
                    st.Agent.DisableScriptedMovement();
                    st.Agent.DisableScriptedCombatMovement();
                    st.Agent.SetAutomaticTargetSelection(true);
                }
                else if (st.Order == DetachOrder.Skirmish && st.KiteMoving)
                {
                    var destination = st.KiteTarget;
                    st.Agent.SetScriptedPosition(ref destination, false, Agent.AIScriptedFrameFlags.NeverSlowDown);
                }
                else if (st.Order == DetachOrder.Skirmish && st.SkirmishHolding)
                {
                    // Skirmish intentionally avoids reissuing a pinned position.
                    // A partially failed Attach may already have removed that pin.
                    var position = st.Agent.GetWorldPosition();
                    st.Agent.SetScriptedPosition(ref position, false, Agent.AIScriptedFrameFlags.NeverSlowDown);
                }
                else ReissueOrder(st);
            }
            catch (Exception ex) {
                st.Status = "blocked";
                try { st.Agent.DisableScriptedMovement(); } catch { }
                BannerlordLinkModule.Log($"[DET] restore failed agent={st.Agent.Index}: {ex.Message}");
            }
        }

        public bool IsDetached(Agent agent) => agent != null && _states.ContainsKey(agent.Index);

        public string GetOrderStatus(Agent agent)
        {
            return agent != null && _states.TryGetValue(agent.Index, out var st) ? st.Status : "formation";
        }

        private static bool CanPathTo(Agent agent, WorldPosition position)
        {
            try {
                return position.IsValid && Mission.Current?.Scene != null
                    && Mission.Current.Scene.DoesPathExistBetweenPositions(agent.GetWorldPosition(), position);
            }
            catch { return false; }
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
                throw;
            }
        }

        private void ApplyCharge(DetachmentState st)
        {
            var agent = st.Agent;
            bool onFoot = agent.MountAgent == null;
            float now = Mission.CurrentTime;
            Agent enemy = onFoot ? st.ChargeTarget : FindNearestEnemyAgent(agent);
            if (onFoot)
            {
                if (!EligibleFootTarget(st, enemy)) enemy = null;
                if (enemy != null && now >= st.NextPathCheck)
                {
                    if (!CanPathTo(agent, enemy.GetWorldPosition()))
                    {
                        st.IgnoredTargets[enemy] = now + 3f;
                        enemy = null;
                    }
                    st.NextPathCheck = now + 2f;
                }
                if (enemy == null) enemy = SelectFootTarget(st);
                if (enemy != st.ChargeTarget)
                {
                    st.ChargeEngaged = false;
                    st.ProgressAt = now;
                    st.LastProgressDistance = float.MaxValue;
                    st.LastProgressPosition = agent.Position;
                    st.ChargeTarget = enemy;
                    st.NextPathCheck = now + 2f;
                }
                if (enemy != null && !st.ChargeEngaged)
                {
                    float distance = agent.Position.Distance(enemy.Position);
                    // Infantry may need a detour. Only a rider chase specifically
                    // requires closing distance; foot targets also count real movement.
                    if (distance < st.LastProgressDistance - 1f
                        || (enemy.MountAgent == null && agent.Position.Distance(st.LastProgressPosition) >= 1f))
                    {
                        st.LastProgressDistance = distance;
                        st.LastProgressPosition = agent.Position;
                        st.ProgressAt = now;
                    }
                    else if (now - st.ProgressAt >= 4f)
                    {
                        // A static obstruction or an escaping horse must not own
                        // the viewer's infantry forever. Retry it only after a pause.
                        st.IgnoredTargets[enemy] = now + 8f;
                        st.ChargeTarget = enemy = SelectFootTarget(st);
                        st.ChargeEngaged = false;
                        st.ProgressAt = now;
                        st.LastProgressDistance = float.MaxValue;
                        st.LastProgressPosition = agent.Position;
                        st.NextPathCheck = now + 2f;
                    }
                }
            }

            if (enemy == null)
            {
                st.ChargeEngaged = false;
                if (onFoot)
                {
                    // Releasing to a charging formation would resume the very
                    // cavalry chase we rejected. Hold here, but keep combat AI on.
                    if (st.Status != "waiting_target") st.HoldPosition = agent.GetWorldPosition();
                    ApplyHold(st);
                    agent.SetAutomaticTargetSelection(true);
                    st.Status = "waiting_target";
                }
                else { agent.DisableScriptedMovement(); st.Status = "waiting_target"; }
                return;
            }

            float dist = agent.Position.Distance(enemy.Position);
            bool clearContact = !onFoot || HasLineOfSight(agent, enemy);
            if (st.ChargeEngaged && (dist > 6f || !clearContact))
            {
                st.ChargeEngaged = false;
                // Time spent actually fighting is not time spent failing to pursue.
                st.ProgressAt = now;
                st.LastProgressDistance = dist;
                st.LastProgressPosition = agent.Position;
            }
            else if (!st.ChargeEngaged && dist <= 3.5f && clearContact) st.ChargeEngaged = true;
            agent.SetAutomaticTargetSelection(true);
            string status = st.ChargeEngaged ? "engaged" : "approaching";
            if (st.Status != status)
                BannerlordLinkModule.Log($"[DET] CHARGE phase={status} agent={agent.Index} target={enemy.Index} mounted_target={enemy.MountAgent != null} distance={dist:F1}");
            st.Status = status;
            if (st.ChargeEngaged) agent.DisableScriptedMovement();
            else
            {
                var pos = enemy.GetWorldPosition();
                agent.SetScriptedPosition(ref pos, false, Agent.AIScriptedFrameFlags.NeverSlowDown);
            }
        }

        private bool EligibleFootTarget(DetachmentState st, Agent target, bool includeIgnored = false)
        {
            if (target == null || target == st.Agent || !target.IsActive()
                || !target.IsHuman || !target.IsEnemyOf(st.Agent)) return false;
            if (!includeIgnored && st.IgnoredTargets.TryGetValue(target, out float until) && Mission.CurrentTime < until) return false;
            // A nearby rider remains a valid threat; distant cavalry is not a
            // reasonable pursuit target for infantry. This does not affect Raid.
            return target.MountAgent == null || st.Agent.Position.Distance(target.Position) <= 12f;
        }

        private Agent SelectFootTarget(DetachmentState st)
        {
            // Keep a living, reachable target in ApplyCharge instead of swapping
            // between two enemies whenever their distances change slightly.
            float now = Mission.CurrentTime;
            if (now < st.NextTargetSearchAt) return null;
            st.NextTargetSearchAt = now + 1f;
            foreach (var expired in st.IgnoredTargets.Where(p => p.Value <= now).Select(p => p.Key).ToList())
                st.IgnoredTargets.Remove(expired);
            var candidates = Mission.Current.Agents.Where(a => EligibleFootTarget(st, a, includeIgnored: true))
                .OrderBy(a => st.Agent.Position.Distance(a.Position) <= 3.5f ? 0 : a.MountAgent == null ? 1 : 2)
                .ThenBy(a => (a.Position - st.Agent.Position).LengthSquared)
                .ToList();
            if (candidates.Count == 0) return null;
            int probes = 0, start = st.TargetSearchCursor % candidates.Count;
            // Continue the bounded search next time; restarting at the nearest
            // twelve would starve reachable enemies behind many blocked targets.
            for (int visited = 0; visited < candidates.Count && probes < 12; visited++)
            {
                int index = (start + visited) % candidates.Count;
                st.TargetSearchCursor = (index + 1) % candidates.Count;
                var candidate = candidates[index];
                if (!EligibleFootTarget(st, candidate)) continue;
                probes++;
                if (CanPathTo(st.Agent, candidate.GetWorldPosition()))
                {
                    st.TargetSearchCursor = 0;
                    return candidate;
                }
                st.IgnoredTargets[candidate] = now + 3f;
            }
            return null;
        }

        // One order permits at most three short retreats. Neither changing targets nor
        // separation resets the budget. Timers bound even a valid but unusable path.
        private void ApplySkirmish(DetachmentState st)
        {
            var agent = st.Agent;
            float now = Mission.CurrentTime;
            agent.SetAutomaticTargetSelection(true);
            var enemy = FindNearestEnemyAgent(agent, true);
            float dist = enemy == null ? float.MaxValue
                : (agent.Position.AsVec2 - enemy.Position.AsVec2).Length;

            if (enemy != null && dist <= 5f && HasLineOfSight(agent, enemy))
            {
                st.KiteMoving = false;
                st.KiteReadyAt = now + 3f;
                st.SkirmishHolding = false;
                agent.DisableScriptedMovement();
                return;
            }

            if (st.KiteMoving)
            {
                float remaining = (agent.Position.AsVec2 - st.KiteTarget.AsVec2).Length;
                if (remaining < st.KiteDistance - 0.5f)
                {
                    st.KiteDistance = remaining;
                    st.KiteProgressAt = now;
                }
                if (enemy == null || remaining <= 1.5f || now >= st.KiteDeadline
                    || now - st.KiteProgressAt >= 2f || !CanPathTo(agent, st.KiteTarget))
                {
                    st.KiteMoving = false;
                    st.KiteReadyAt = now + 3f;
                    HoldSkirmish(st);
                }
                // Keep the original destination until arrival/timeout, never chase
                // a point recomputed from a moving enemy.
                return;
            }

            if (enemy == null || now < st.KiteReadyAt)
            {
                HoldSkirmish(st);
                return;
            }

            var epos = enemy.GetWorldPosition();
            Vec2 ec = epos.AsVec2;
            Vec2 away = agent.Position.AsVec2 - ec;
            float standoff = SkirmishStandoff(agent);
            if (dist < 12f)
            {
                if (st.KiteCount < 3 && dist > 0.01f)
                {
                    // Destination shifts at most eight metres; actual navigation may detour.
                    var target = agent.GetWorldPosition();
                    target.SetVec2(agent.Position.AsVec2 + away * (8f / dist));
                    st.KiteCount++; // Failed attempts also consume the finite budget.
                    if (CanPathTo(agent, target))
                    {
                        agent.SetScriptedPosition(ref target, false,
                            Agent.AIScriptedFrameFlags.NeverSlowDown);
                        st.KiteTarget = target;
                        st.KiteMoving = true;
                        st.KiteDeadline = now + 4f;
                        st.KiteProgressAt = now;
                        st.KiteDistance = 8f;
                        st.SkirmishHolding = false;
                        BannerlordLinkModule.Log($"[DET] SKIRMISH retreat agent={agent.Index} count={st.KiteCount}/3");
                        return;
                    }
                    st.KiteReadyAt = now + 3f;
                }
                HoldSkirmish(st);
                return;
            }

            bool hasLos = HasLineOfSight(agent, enemy);
            if (dist > standoff + Math.Max(6f, standoff * 0.18f) || !hasLos)
            {
                // Losing sight is not permission to move backwards or through walls.
                float desired = hasLos ? standoff : Math.Min(dist, standoff * 0.5f);
                if (dist > 0.01f) epos.SetVec2(ec + away * (desired / dist));
                if (CanPathTo(agent, epos))
                {
                    agent.SetScriptedPosition(ref epos, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    st.SkirmishHolding = false;
                    return;
                }
            }
            HoldSkirmish(st);
        }

        private static void HoldSkirmish(DetachmentState st)
        {
            if (st.SkirmishHolding) return;
            var here = st.Agent.GetWorldPosition();
            st.Agent.SetScriptedPosition(ref here, false,
                Agent.AIScriptedFrameFlags.NeverSlowDown);
            st.SkirmishHolding = true;
        }

        // Standoff = SKIRMISH_RANGE_FRACTION × реальной макс. дальности выстрела оружия героя.
        // Agent.MaximumMissileRange = GetMissileRange() — нативный расчёт движка по оружию в
        // руках (тот же источник, что у FormationQuerySystem.MaximumMissileRange), без завязки
        // на формацию (в отличие от MissileRangeAdjusted, которая лезет в Formation и упала бы
        // у detached-агента). Фолбэк 22м если дальность недоступна (сменил на мили / нет данных).
        private static float SkirmishStandoff(Agent agent)
        {
            float range = 0f;
            try { range = agent.MaximumMissileRange; } catch { }
            float s = range > 1f ? range * SKIRMISH_RANGE_FRACTION : SKIRMISH_STANDOFF;
            if (s < SKIRMISH_MIN_STANDOFF) s = SKIRMISH_MIN_STANDOFF;
            if (s > SKIRMISH_MAX_STANDOFF) s = SKIRMISH_MAX_STANDOFF;
            return s;
        }

        // 2026-06-17 — Raid: «набег» для конных. Эллиптическая орбита по
        // BehaviorMountedSkirmish, упрощённая до круга радиуса RAID_ORBIT_RADIUS
        // вокруг ближайшего врага (для одного агента эллипс схлопывается в круг).
        // Точку-цель ставим на угол (текущий пеленг агента от врага) + STEP → конный
        // постоянно догоняет точку чуть впереди по окружности = кружит CCW. Авто-таргет
        // = рубит/стреляет на проходе. Self-correcting: пеленг берём от ТЕКУЩЕЙ позиции.
        private void ApplyRaid(DetachmentState st)
        {
            try
            {
                var agent = st.Agent;
                var enemy = FindNearestEnemyAgent(agent);
                if (enemy != null)
                {
                    var pos = enemy.GetWorldPosition();
                    Vec2 ec = pos.AsVec2;
                    Vec2 toMe = agent.Position.AsVec2 - ec;
                    float bearing = (toMe.LengthSquared > 0.0001f)
                        ? (float)Math.Atan2(toMe.y, toMe.x)
                        : 0f;
                    float ang = bearing + RAID_ORBIT_STEP_RAD;   // лидируем вперёд → CCW
                    Vec2 off = new Vec2((float)Math.Cos(ang), (float)Math.Sin(ang))
                               * RAID_ORBIT_RADIUS;
                    try { pos.SetVec2(ec + off); } catch { }
                    agent.SetScriptedPosition(ref pos, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    try { agent.SetAutomaticTargetSelection(true); } catch { }
                }
                else
                {
                    try { agent.DisableScriptedMovement(); } catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplyRaid warn: {ex.Message}");
                throw;
            }
        }

        private void ApplyNavigate(DetachmentState st)
        {
            if (!st.NavValid) throw new InvalidOperationException("navigation_target_invalid");
            if (st.Status == "blocked") return;
            if (!IsSiegeMission()) throw new InvalidOperationException("navigation_path_unavailable");
            float now = Mission.CurrentTime;
            // Ворота ломают по ходу боя: защитник отходит к следующим целым, атакующий
            // идёт к следующим, а когда разбиты все — проходит внутрь.
            if (st.Order == DetachOrder.Gate && now >= st.NextRetargetAt)
            {
                st.NextRetargetAt = now + GATE_RETARGET_INTERVAL;
                var fresh = FindGateTarget(st.Agent, out bool breach);
                if (fresh.IsValid && CanPathTo(st.Agent, fresh)
                    && (fresh.GetGroundVec3().Distance(st.NavTarget.GetGroundVec3()) > 3f || breach != st.Breach))
                {
                    st.NavTarget = fresh; st.Breach = breach; st.Status = "gate";
                    st.ProgressAt = now; st.LastProgressDistance = float.MaxValue; st.LastProgressPosition = st.Agent.Position;
                    BannerlordLinkModule.Log($"[DET] GATE retarget agent={st.Agent.Index} breach={breach}");
                }
            }
            if (st.Status == "arrived")
            {
                // 26.09: дошёл — держит место и дерётся. Раньше «arrived» отдавал героя
                // строю (DisableScriptedMovement), и строй уводил его обратно на своё место.
                var hold = st.NavTarget;
                st.Agent.SetScriptedPosition(ref hold, false, Agent.AIScriptedFrameFlags.NeverSlowDown);
                return;
            }
            if (!CanPathTo(st.Agent, st.NavTarget))
                throw new InvalidOperationException("navigation_path_unavailable");
            float distance = st.Agent.Position.Distance(st.NavTarget.GetGroundVec3());
            if (distance <= 2f)
            {
                st.Agent.SetAutomaticTargetSelection(true);
                if (st.Order == DetachOrder.Gate && st.Breach)
                {
                    // Все ворота разбиты и мы внутри — дальше как «в атаку».
                    st.Order = DetachOrder.Charge; st.Status = "approaching";
                    st.ChargeTarget = null; st.ChargeEngaged = false; st.NextTargetSearchAt = 0f;
                    st.ProgressAt = now; st.LastProgressDistance = float.MaxValue; st.LastProgressPosition = st.Agent.Position;
                    BannerlordLinkModule.Log($"[DET] GATE breached agent={st.Agent.Index} -> charge");
                    return;
                }
                st.Status = "arrived";
                var hold = st.NavTarget;
                st.Agent.SetScriptedPosition(ref hold, false, Agent.AIScriptedFrameFlags.NeverSlowDown);
                BannerlordLinkModule.Log($"[DET] {st.Order.ToString().ToUpperInvariant()} arrived agent={st.Agent.Index} -> holding and fighting");
                return;
            }
            if (distance < st.LastProgressDistance - 1f
                || st.Agent.Position.Distance(st.LastProgressPosition) >= 1f)
            {
                st.LastProgressDistance = distance;
                st.LastProgressPosition = st.Agent.Position;
                st.ProgressAt = now;
            }
            else if (now - st.ProgressAt >= 6f)
            {
                st.Agent.DisableScriptedMovement();
                st.Status = "blocked";
                BannerlordLinkModule.Log($"[DET] navigation blocked agent={st.Agent.Index} order={st.Order}");
                return;
            }
            var pos = st.NavTarget;
            st.Agent.SetScriptedPosition(ref pos, false, Agent.AIScriptedFrameFlags.NeverSlowDown);
        }

        private void ReissueOrder(DetachmentState st)
        {
            switch (st.Order)
            {
                case DetachOrder.Hold:     ApplyHold(st);      break;
                case DetachOrder.Charge:   ApplyCharge(st);    break;
                case DetachOrder.Skirmish: ApplySkirmish(st);  break;
                case DetachOrder.Raid:     ApplyRaid(st);      break;
                case DetachOrder.Walls:
                case DetachOrder.Gate:     ApplyNavigate(st);  break;
                case DetachOrder.Follow:
                    st.Agent.DisableScriptedMovement();
                    st.Agent.SetAutomaticTargetSelection(true);
                    st.Status = "formation";
                    break;
            }
        }

        // ── Private helpers ────────────────────────────────────────────────────

        /// <summary>2026-07-20 (#36) — есть ли у стрелка чистая линия огня до цели.
        /// Луч от «глаз» героя к телу врага через Scene: если упёрся в террейн/статичный
        /// объект (стена, камень, осадная конструкция) РАНЬШЕ цели — выстрел перекрыт.
        /// Агенты рейкастом не ловятся (свои/чужие тела луч не блокируют), так что
        /// проходящий мимо боец ложного «нет ЛОС» не даёт. При любой ошибке → true
        /// (лучше стрелять, чем мёрзнуть).</summary>
        private static bool HasLineOfSight(Agent from, Agent to)
        {
            try
            {
                var scene = Mission.Current?.Scene;
                if (scene == null || from == null || to == null) return true;
                Vec3 src = from.Position; src.z += 1.5f;   // ~уровень глаз
                Vec3 tgt = to.Position;   tgt.z += 1.0f;   // ~корпус цели
                float hitDist;
                bool hit = scene.RayCastForClosestEntityOrTerrain(src, tgt, out hitDist);
                if (!hit) return true;                     // ничего между нами
                float full = (tgt - src).Length;
                return hitDist >= full - 1.0f;             // препятствие на цели/за ней = видим
            }
            catch { return true; }
        }

        /// <summary>Nearest active enemy agent — цель scripted-позиции для Charge.</summary>
        private static Agent FindNearestEnemyAgent(Agent agent, bool humansOnly = false)
        {
            try
            {
                if (agent == null || Mission.Current == null) return null;
                Vec3 ap = agent.Position;
                Agent best = null;
                float bestSq = float.MaxValue;
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || a == agent || !a.IsActive()) continue;
                    if (humansOnly && !a.IsHuman) continue;
                    if (!a.IsEnemyOf(agent)) continue;
                    float d = (a.Position - ap).LengthSquared;
                    if (d < bestSq) { bestSq = d; best = a; }
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
                int skirmishN = 0, raidN = 0;
                foreach (var st in _states.Values)
                {
                    if (st == null) continue;
                    switch (st.Order)
                    {
                        case DetachOrder.Hold:     holdN++;     break;
                        case DetachOrder.Charge:   chargeN++;   break;
                        case DetachOrder.Skirmish: skirmishN++; break;
                        case DetachOrder.Raid:     raidN++;     break;
                        case DetachOrder.Follow:   followN++;   break;
                        case DetachOrder.Walls:    wallsN++;    break;
                        case DetachOrder.Gate:     gateN++;     break;
                    }
                }
                string sinceFirst = _firstDetachAt >= 0f ? $"{(now - _firstDetachAt):F1}s" : "—";
                BannerlordLinkModule.Log(
                    $"[DET-STATS] t={now:F1}s active={total} " +
                    $"(hold:{holdN} charge:{chargeN} skirmish:{skirmishN} raid:{raidN} " +
                    $"follow:{followN} walls:{wallsN} gate:{gateN}) since_first={sinceFirst}");
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

        /// <summary>Боевая позиция на забрале для команды «на стену»: позиция ближайшего
        /// СВОЕГО активного бойца, стоящего ВЫШЕ нас (движок сам расставил защитников по
        /// стене — их точки навмеш-валидны и достижимы по внутренним лестницам, в отличие от
        /// тела стены/лестницы). Лучников слегка приоритезируем (они на стрелковых позициях).
        /// Invalid, если своих на забрале нет (атакующий / стена пуста) → caller делает
        /// фолбэк на FindNearestSiegeTarget.</summary>
        private WorldPosition FindWallFiringPosition(Agent agent, bool defender)
        {
            try
            {
                if (Mission.Current == null) return WorldPosition.Invalid;
                Vec3 me = agent.Position;
                Team team = agent.Team;
                var spots = new List<Agent>();
                var enemies = new List<SiegePoint>();
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || a == agent || !a.IsActive()) continue;
                    if (a.Team != team)
                    {
                        if (a.IsEnemyOf(agent)) enemies.Add(P(a.Position));
                        continue;
                    }
                    if (a.Position.z > me.z + WALL_MIN_ELEVATION) spots.Add(a);   // выше нас = на забрале
                }
                // 26.09: защитник — на участок, где враг ближе всего (лестницы, башни),
                // а не к ближайшему своему; атакующий — к ближайшему, куда уже есть путь.
                var order = SiegeOrderPolicy.RankWallSpots(spots.Select(a => P(a.Position)).ToList(), P(me), enemies, defender);
                int checks = 0;
                foreach (int i in order)
                {
                    if (++checks > 12) break;
                    if (CanPathTo(agent, spots[i].GetWorldPosition()))
                        return ProjectToNavMesh(Mission.Current.Scene, spots[i].Position);
                }
                return WorldPosition.Invalid;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] FindWallFiringPosition warn: {ex.Message}");
                return WorldPosition.Invalid;
            }
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
                try {
                    if (gateOnly) scene.GetAllEntitiesWithScriptComponent<CastleGate>(ref allEntities);
                    else scene.GetAllEntitiesWithScriptComponent<SiegeLadder>(ref allEntities);
                }
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
                    if (d < bestDistSq && CanPathTo(agent, ProjectToNavMesh(scene, ep))) { bestDistSq = d; bestEntity = e; }
                }

                if (bestEntity == null) return WorldPosition.Invalid;
                // 2026-06-17 (Bug B partial) — entity.GlobalPosition сидит на сетке
                // стены/ворот (часто вне navmesh / в текстуре) → агент упирался и
                // застревал. Проецируем на ближайшую navmesh-грань, чтобы scripted-
                // движение дошло до ОСНОВАНИЯ стены/ворот. (Лазить по лестнице
                // agent-скриптом всё равно нельзя — это потолок agent-level.)
                return ProjectToNavMesh(scene, bestEntity.GlobalPosition);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] FindNearestSiegeTarget warn: {ex.Message}");
                return WorldPosition.Invalid;
            }
        }

        /// <summary>Snap raw world position onto nearest navmesh face so a scripted
        /// agent can actually path to it (вместо «торчать в текстуре»). Fallback —
        /// сырая позиция (старое поведение), чтобы не падать.</summary>
        private static WorldPosition ProjectToNavMesh(Scene scene, Vec3 rawPos)
        {
            try
            {
                UIntPtr navFace = scene.GetNavigationMeshForPosition(rawPos);
                if (navFace == UIntPtr.Zero)
                {
                    // rawPos может быть выше/ниже сетки (на стене) — расширяем поиск.
                    try { navFace = scene.GetNearestNavigationMeshForPosition(rawPos, 5f, false); }
                    catch { }
                }
                var wp = new WorldPosition(scene, navFace, rawPos, false);
                try { wp.GetNavMesh(); } catch { }   // форсим re-проекцию Z на navmesh-грань
                return wp;
            }
            catch
            {
                return new WorldPosition(scene, UIntPtr.Zero, rawPos, false);
            }
        }
    }
}
