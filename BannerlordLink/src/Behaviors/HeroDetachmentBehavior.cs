using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Linq;
using TaleWorlds.Core;
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
            Charge,     // engage nearest enemy formation
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
        private const float SKIRMISH_STANDOFF = 22f;
        // Мёртвая зона против джиттера (принцип BehaviorSkirmish: держать в полосе, а не
        // дёргаться каждый тик). Пока ближайший враг ДАЛЬШЕ триггера — стоим и стреляем;
        // как только поджал ближе — отходим на SKIRMISH_STANDOFF. Отход восстанавливает
        // 22м (>> триггера) → «стою/отхожу» не мигает (гистерезис). Репорт #32.
        private const float SKIRMISH_KITE_TRIGGER = 14f;   // ~0.64 × standoff
        private const float RAID_ORBIT_RADIUS = 20f;
        private const float RAID_ORBIT_STEP_RAD = 0.4f;

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
                // 2026-06-01 DIAG — почему агент не двигается? Ключевое: он = игрок
                // (Controller=Player / Agent.Main → scripted-движение игнорится движком)?
                try
                {
                    bool isMain = Agent.Main != null && agent == Agent.Main;
                    string form = agent.Formation != null ? agent.Formation.Index.ToString() : "none";
                    BannerlordLinkModule.Log(
                        $"[DET-DIAG] idx={agent.Index} isMain={isMain} controller={agent.Controller} " +
                        $"formation={form} team={agent.Team?.Side}");
                }
                catch (Exception dex) { BannerlordLinkModule.Log($"[DET-DIAG] warn: {dex.Message}"); }
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

        public bool Skirmish(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            st.Order = DetachOrder.Skirmish;
            st.NextReissueAt = 0f;
            st.SkirmishHolding = false;   // новый приказ → перепин hold-позиции с нуля
            ApplySkirmish(st);
            BannerlordLinkModule.Log($"[DET] SKIRMISH agent={agent.Index}");
            return true;
        }

        public bool Raid(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            st.Order = DetachOrder.Raid;
            st.NextReissueAt = 0f;
            ApplyRaid(st);
            BannerlordLinkModule.Log($"[DET] RAID agent={agent.Index}");
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
                // 2026-06-01 FIX — раньше DisableScriptedMovement + SetTargetFormationIndex
                // возвращало агента под контроль формации (которая стоит) → герой не двигался.
                // Теперь СКРИПТУЕМ позицию НА ближайшего врага (тот же механизм, что Hold,
                // но цель — враг) + авто-таргет для атаки в упор. Re-issue каждые 0.5с ведёт
                // за движущимся врагом.
                var enemy = FindNearestEnemyAgent(agent);
                if (enemy != null)
                {
                    // 2026-06-17 — «вблизи»: ВСЕГДА в КОНТАКТ к врагу, для всех классов
                    // (дистанционный бой — отдельный приказ Skirmish «издали»). Скриптуем
                    // на позицию врага + авто-таргет; re-issue 0.5с ведёт за врагом.
                    var pos = enemy.GetWorldPosition();
                    agent.SetScriptedPosition(ref pos, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    try { agent.SetAutomaticTargetSelection(true); } catch { }
                }
                else
                {
                    // Врагов не нашли — снимаем скрипт, пусть AI решает сам.
                    try { agent.DisableScriptedMovement(); } catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplyCharge warn: {ex.Message}");
            }
        }

        // 2026-06-17 / 2026-07-19 (#32) — Skirmish: «встал на дистанции и стреляет».
        // Дэд-зона против джиттера (принцип движкового BehaviorSkirmish: держать позицию
        // в полосе, не пересчитывать цель каждый тик). Пока ближайший враг ДАЛЬШЕ
        // SKIRMISH_KITE_TRIGGER — пиним позицию ОДИН раз и стоим (авто-таргет стреляет);
        // как только враг поджал ближе триггера — отходим на SKIRMISH_STANDOFF. Раньше
        // точка-цель пересчитывалась от движущегося ближайшего врага каждые 0.5с → герой
        // бесконечно бегал за прыгающей точкой (репорт #32 «бегает туда-сюда в поиске места»).
        private void ApplySkirmish(DetachmentState st)
        {
            try
            {
                var agent = st.Agent;
                var enemy = FindNearestEnemyAgent(agent);
                if (enemy == null)
                {
                    try { agent.DisableScriptedMovement(); } catch { }
                    st.SkirmishHolding = false;
                    return;
                }
                try { agent.SetAutomaticTargetSelection(true); } catch { }

                var epos = enemy.GetWorldPosition();
                Vec2 ec = epos.AsVec2;
                Vec2 away = agent.Position.AsVec2 - ec;   // enemy → agent
                float dist = away.Length;

                if (dist < SKIRMISH_KITE_TRIGGER)
                {
                    // Враг поджал ближе триггера → отходим на standoff по линии от врага
                    // (быстро). Пока ближе — восстанавливаем дистанцию, потом встанем.
                    if (dist > 0.01f)
                    {
                        away = away * (SKIRMISH_STANDOFF / dist);
                        try { epos.SetVec2(ec + away); } catch { }
                    }
                    agent.SetScriptedPosition(ref epos, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    st.SkirmishHolding = false;
                }
                else if (!st.SkirmishHolding)
                {
                    // Комфортная дистанция, ещё не «встали» → пиним ТЕКУЩУЮ позицию ОДИН
                    // раз и переходим в hold. Дальше не трогаем → стоит и стреляет,
                    // не бегает за прыгающей точкой.
                    var here = agent.GetWorldPosition();
                    agent.SetScriptedPosition(ref here, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    st.SkirmishHolding = true;
                }
                // else: держим позицию (не re-issue'им) — стоит на месте, авто-таргет стреляет.
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplySkirmish warn: {ex.Message}");
            }
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
                case DetachOrder.Hold:     ApplyHold(st);      break;
                case DetachOrder.Charge:   ApplyCharge(st);    break;
                case DetachOrder.Skirmish: ApplySkirmish(st);  break;
                case DetachOrder.Raid:     ApplyRaid(st);      break;
                case DetachOrder.Walls:
                case DetachOrder.Gate:     ApplyNavigate(st);  break;
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

        /// <summary>Nearest active enemy agent — цель scripted-позиции для Charge.</summary>
        private static Agent FindNearestEnemyAgent(Agent agent)
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
