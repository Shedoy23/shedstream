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
    /// Sprint 5.32 (BLT-parity Detachment) — viewer-controlled formation commands.
    ///
    /// Раньше zрители-герои спавнились через player.spawn и подчинялись AI commander
    /// формации стримера. Теперь viewer может **отделить** своего hero-agent'а
    /// от формации и приказать independent движение:
    ///   - Hold:    стоять на месте (sniper / chokepoint hold)
    ///   - Charge:  бежать на ближайшее enemy formation
    ///   - Follow:  loose-follow за parent formation сзади
    ///   - Walls:   siege only — лезть на стены/лестницы/башни
    ///   - Gate:    siege only — бежать к ближайшим воротам
    ///   - Attach:  возврат в parent formation
    ///
    /// Реализация: per-agent solo Formation. Engine native SetMovementOrder API.
    /// Re-issue команды каждые ~0.5s через OnMissionTick (engine иногда сбрасывает
    /// agent's AI после damage / stagger — periodic re-apply keeps order sticky).
    ///
    /// State storage: ConcurrentDictionary&lt;agentIndex, DetachmentState&gt;.
    /// Weak-cleanup: на OnAgentDeleted (engine event) state удаляется. Без CWT
    /// потому что Agent сам очищается engine'ом + Index reuse не страшен (next
    /// agent с тем же Index — другой viewer, отдельный detach).
    ///
    /// Pattern из Randomchair22-fork BLT (`BLTHeroDetachmentBehavior`, апрель 2026):
    /// public API (Detach/Attach/Hold/Follow/Charge/TargetDoor/Walls). Numeric
    /// values + structure отличаются — это **clean-room re-impl** (closed-source
    /// SaaS legal posture). Идею и API форму используем; код пишем сами.
    /// </summary>
    public class HeroDetachmentBehavior : MissionBehavior
    {
        public override MissionBehaviorType BehaviorType => MissionBehaviorType.Other;

        public static HeroDetachmentBehavior Instance { get; private set; }

        public enum DetachOrder
        {
            None,       // not detached
            Hold,       // stay at fixed position
            Charge,     // engage nearest enemy formation
            Follow,     // loose-follow parent formation
            Walls,      // siege: lecturer to walls/ladders
            Gate,       // siege: navigate to nearest gate
        }

        private class DetachmentState
        {
            public Agent Agent;
            public Formation ParentFormation; // куда return на attach()
            public Formation SoloFormation;   // single-unit formation для own orders
            public DetachOrder Order;
            public Vec3 HoldPosition;         // для Hold mode
            public WorldPosition NavTarget;   // для Walls/Gate mode
            public float NextReissueAt;       // throttle re-apply (engine resets иногда)
        }

        // Key = Agent.Index (engine-int). При AgentDeleted state cleared.
        private readonly ConcurrentDictionary<int, DetachmentState> _states =
            new ConcurrentDictionary<int, DetachmentState>();

        // Re-issue interval — secs. Не слишком часто (CPU), не слишком редко
        // (agent отвалится от order на damage stagger через ~1-2s).
        private const float REISSUE_INTERVAL = 0.5f;

        // Sprint 5.32 (LOG-2) — periodic snapshot stats. Каждые 10 секунд
        // dump в log breakdown активных detachment'ов чтобы streamer
        // (или мы при дебаге) мог одним grep'ом понять состояние:
        //   "[DET-STATS] t=120s active=3 (hold:1 charge:1 walls:1) since_first=45.2s"
        // Без этого нельзя сказать "сейчас 0 detach'нутых" vs "behavior сломан".
        private const float STATS_LOG_INTERVAL = 10.0f;
        private float _nextStatsLogAt = 0f;
        private float _firstDetachAt = -1f;

        public override void OnBehaviorInitialize()
        {
            base.OnBehaviorInitialize();
            Instance = this;
            BannerlordLinkModule.Log("[DET] HeroDetachmentBehavior init");
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
            // Удаляем state для умершего/деспавненного agent'а.
            // Cleanup solo formation чтобы engine не держал orphan reference.
            if (_states.TryRemove(affectedAgent.Index, out var st))
            {
                try
                {
                    if (st.SoloFormation != null && st.SoloFormation.CountOfUnits == 0)
                    {
                        // Engine cleanup пустых formations через native lifecycle;
                        // forced delete не нужен — оставляем engine handle.
                    }
                }
                catch { }
            }
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            float now;
            try { now = Mission.CurrentTime; }
            catch { return; }

            // Periodic stats log (всегда, даже если 0 active'ов — чтобы streamer
            // мог отличить "поведение mute" от "поведение работает, никто не
            // запросил command").
            if (now >= _nextStatsLogAt)
            {
                _nextStatsLogAt = now + STATS_LOG_INTERVAL;
                LogStatsSnapshot(now);
            }

            if (_states.Count == 0) return;

            // Snapshot — collection может меняться mid-frame (action handlers
            // могут add'ить state'ы вне main-tick).
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
                    BannerlordLinkModule.Log(
                        $"[DET] reissue crashed: {ex.Message}");
                }
            }
        }

        // ── Public API (called by action handlers) ─────────────────────────────

        /// <summary>Создать solo formation для agent и переместить туда.
        /// Если уже detached — no-op (idempotent).</summary>
        public bool Detach(Agent agent)
        {
            if (agent == null || !agent.IsActive()) return false;
            if (Mission.Current == null) return false;
            if (_states.ContainsKey(agent.Index)) return true; // already detached

            try
            {
                var parent = agent.Formation;
                var team = agent.Team ?? Mission.Current.PlayerTeam;
                if (team == null) return false;

                // Найти свободный formation slot. Engine использует FormationClass
                // enum (Infantry/Cavalry/Ranged/HorseArcher/...). Solo formation
                // — берём FormationClass.NumberOfRegularFormations как "custom"
                // index, или подбираем next свободный slot.
                Formation solo = null;
                try
                {
                    // Use "NumberOfRegularFormations" как marker — это последний
                    // slot, обычно пустой для viewer'ов. Если ChunkMissionAlready
                    // занял — берём первый пустой.
                    solo = FindFreeSoloFormation(team);
                }
                catch (Exception ffEx)
                {
                    BannerlordLinkModule.Log(
                        $"[DET] FindFreeSoloFormation warn: {ffEx.Message}");
                }
                if (solo == null) return false;

                // Move agent в solo formation. Engine handles removal из старой.
                agent.Formation = solo;

                _states[agent.Index] = new DetachmentState
                {
                    Agent = agent,
                    ParentFormation = parent,
                    SoloFormation = solo,
                    Order = DetachOrder.Hold,
                    HoldPosition = agent.Position,
                    NextReissueAt = 0f,
                };
                if (_firstDetachAt < 0f)
                {
                    try { _firstDetachAt = Mission.Current.CurrentTime; }
                    catch { _firstDetachAt = 0f; }
                }
                // Resolve viewer username для readable log (вместо agent.Index).
                string usernameForLog = ResolveUsername(agent);
                BannerlordLinkModule.Log(
                    $"[DET] DETACH @{usernameForLog} idx={agent.Index} " +
                    $"parent={parent?.FormationIndex.ToString() ?? "—"} → solo " +
                    $"(total active={_states.Count})");
                return true;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] Detach crashed: {ex.Message}");
                return false;
            }
        }

        public bool Attach(Agent agent)
        {
            if (agent == null) return false;
            if (!_states.TryRemove(agent.Index, out var st)) return false;
            try
            {
                if (st.ParentFormation != null && agent.IsActive())
                {
                    agent.Formation = st.ParentFormation;
                }
                BannerlordLinkModule.Log(
                    $"[DET] ATTACH agent={agent.Index} → parent={st.ParentFormation?.FormationIndex.ToString() ?? "—"}");
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
            st.HoldPosition = agent.Position;
            st.NextReissueAt = 0f;
            BannerlordLinkModule.Log($"[DET] HOLD agent={agent.Index} pos={st.HoldPosition}");
            return true;
        }

        public bool Charge(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            st.Order = DetachOrder.Charge;
            st.NextReissueAt = 0f;
            BannerlordLinkModule.Log($"[DET] CHARGE agent={agent.Index}");
            return true;
        }

        public bool Follow(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            if (st.ParentFormation == null)
            {
                BannerlordLinkModule.Log(
                    $"[DET] FOLLOW agent={agent.Index}: no parent formation → fallback CHARGE");
                st.Order = DetachOrder.Charge;
            }
            else
            {
                st.Order = DetachOrder.Follow;
            }
            st.NextReissueAt = 0f;
            return true;
        }

        public bool Walls(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            if (!IsSiegeMission())
            {
                BannerlordLinkModule.Log(
                    $"[DET] WALLS agent={agent.Index} REFUSE: не siege mission");
                return false;
            }
            var wp = FindNearestSiegeTarget(agent, gateOnly: false);
            if (!wp.IsValid)
            {
                BannerlordLinkModule.Log(
                    $"[DET] WALLS agent={agent.Index} REFUSE: ladder/wall target не найден");
                return false;
            }
            st.Order = DetachOrder.Walls;
            st.NavTarget = wp;
            st.NextReissueAt = 0f;
            BannerlordLinkModule.Log($"[DET] WALLS agent={agent.Index} → {wp.GetGroundVec3()}");
            return true;
        }

        public bool Gate(Agent agent)
        {
            if (!EnsureDetached(agent, out var st)) return false;
            if (!IsSiegeMission())
            {
                BannerlordLinkModule.Log(
                    $"[DET] GATE agent={agent.Index} REFUSE: не siege mission");
                return false;
            }
            var wp = FindNearestSiegeTarget(agent, gateOnly: true);
            if (!wp.IsValid)
            {
                BannerlordLinkModule.Log(
                    $"[DET] GATE agent={agent.Index} REFUSE: gate target не найден");
                return false;
            }
            st.Order = DetachOrder.Gate;
            st.NavTarget = wp;
            st.NextReissueAt = 0f;
            BannerlordLinkModule.Log($"[DET] GATE agent={agent.Index} → {wp.GetGroundVec3()}");
            return true;
        }

        public bool IsDetached(Agent agent)
        {
            return agent != null && _states.ContainsKey(agent.Index);
        }

        // ── Private helpers ────────────────────────────────────────────────────

        private bool EnsureDetached(Agent agent, out DetachmentState st)
        {
            st = null;
            if (agent == null || !agent.IsActive()) return false;
            if (!_states.TryGetValue(agent.Index, out st))
            {
                // Auto-detach if не detached ещё. UX-friendly: viewer может
                // нажать !hold без предварительного !detach — мы сделаем оба.
                if (!Detach(agent)) return false;
                if (!_states.TryGetValue(agent.Index, out st)) return false;
            }
            return true;
        }

        private void ReissueOrder(DetachmentState st)
        {
            if (st.SoloFormation == null) return;
            try
            {
                string usernameVerbose = ResolveUsername(st.Agent);
                BannerlordLinkModule.LogVerbose(() =>
                    $"[DET V] reissue @{usernameVerbose} idx={st.Agent.Index} " +
                    $"order={st.Order} soloFormation={st.SoloFormation.FormationIndex} " +
                    $"agent.IsActive={st.Agent.IsActive()} hp={(int)st.Agent.Health}/{(int)st.Agent.HealthLimit} " +
                    $"pos={st.Agent.Position}");
                switch (st.Order)
                {
                    case DetachOrder.Hold:
                        {
                            var wp = new WorldPosition(Mission.Current.Scene, UIntPtr.Zero,
                                st.HoldPosition, false);
                            st.SoloFormation.SetMovementOrder(MovementOrder.MovementOrderMove(wp));
                            // На месте — формация stops auto когда reach destination.
                        }
                        break;
                    case DetachOrder.Charge:
                        st.SoloFormation.SetMovementOrder(MovementOrder.MovementOrderCharge);
                        break;
                    case DetachOrder.Follow:
                        // MovementOrderFollow(Agent) — engine expects target Agent,
                        // не Formation. Используем parent formation's Captain как
                        // anchor. Если Captain null (формация без leader) — fallback
                        // на формационную OrderPosition (Move к точке формации).
                        {
                            Agent captain = null;
                            try { captain = st.ParentFormation?.Captain; }
                            catch { }
                            if (captain != null && captain.IsActive())
                            {
                                st.SoloFormation.SetMovementOrder(
                                    MovementOrder.MovementOrderFollow(captain));
                            }
                            else if (st.ParentFormation != null)
                            {
                                // Move к OrderPosition parent formation (где
                                // стримерский commander её ведёт).
                                try
                                {
                                    Vec2 opv2 = st.ParentFormation.OrderPosition;
                                    Vec3 anchor = new Vec3(opv2.x, opv2.y, 0f);
                                    var wpf = new WorldPosition(Mission.Current.Scene,
                                        UIntPtr.Zero, anchor, false);
                                    st.SoloFormation.SetMovementOrder(MovementOrder.MovementOrderMove(wpf));
                                }
                                catch
                                {
                                    st.SoloFormation.SetMovementOrder(MovementOrder.MovementOrderCharge);
                                }
                            }
                            else
                            {
                                st.SoloFormation.SetMovementOrder(MovementOrder.MovementOrderCharge);
                            }
                        }
                        break;
                    case DetachOrder.Walls:
                    case DetachOrder.Gate:
                        if (st.NavTarget.IsValid)
                        {
                            st.SoloFormation.SetMovementOrder(
                                MovementOrder.MovementOrderMove(st.NavTarget));
                        }
                        break;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DET] ReissueOrder({st.Order}) crashed: {ex.Message}");
            }
        }

        /// <summary>Find first empty formation slot в team. У team всегда есть
        /// 8 slots (FormationClass.NumberOfAllFormations). Берём first без units.</summary>
        private Formation FindFreeSoloFormation(Team team)
        {
            // 8 stock slots — большинство пустые в обычных боях. Если все 8 заняты
            // (огромная сражение с custom AI commands) — fallback к unmapped slot.
            try
            {
                foreach (var f in team.FormationsIncludingSpecialAndEmpty)
                {
                    if (f == null) continue;
                    if (f.CountOfUnits == 0) return f;
                }
            }
            catch { }
            return null;
        }

        // Sprint 5.32 (LOG-1) — resolve viewer username для readable log lines.
        // Через M9 dict (HeroIdentityBehavior) если doable, fallback к agent.Name.
        private string ResolveUsername(Agent agent)
        {
            try
            {
                var hero = (agent?.Character as TaleWorlds.CampaignSystem.CharacterObject)?.HeroObject;
                if (hero != null)
                {
                    var byDict = HeroIdentityBehavior.Instance?.GetUsername(hero);
                    if (!string.IsNullOrEmpty(byDict)) return byDict;
                    // Fallback к name parsing для legacy hero'ев без dict entry.
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

        // Sprint 5.32 (LOG-2) — periodic snapshot. Лог появляется каждые 10s
        // даже если states пусты — позволяет отличить "поведение работает,
        // никто не покупал" от "поведение сломано / mute". Breakdown по Order'ам.
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
                string sinceFirst = _firstDetachAt >= 0f
                    ? $"{(now - _firstDetachAt):F1}s"
                    : "—";
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
                // Mission.Current.Scene имеет SiegeBattleScene marker, или
                // MissionBehaviors содержат SiegeMissionController. Скан по имени.
                foreach (var b in Mission.Current.MissionBehaviors)
                {
                    if (b == null) continue;
                    string n = b.GetType().Name;
                    if (n.IndexOf("Siege", StringComparison.OrdinalIgnoreCase) >= 0)
                        return true;
                }
            }
            catch { }
            return false;
        }

        /// <summary>Find nearest siege navigation target (gate or wall/ladder).
        /// gateOnly=true → только ladders/gates с "gate" в name. Иначе любой
        /// siege navigation point (ladder/tower/wall_path).</summary>
        private WorldPosition FindNearestSiegeTarget(Agent agent, bool gateOnly)
        {
            try
            {
                Vec3 agentPos = agent.Position;
                GameEntity bestEntity = null;
                float bestDistSq = float.MaxValue;

                // Scene query — engine хранит named markers / siege weapons / gates
                // как GameEntity instances. Iterate root entities + recursive поиск.
                var scene = Mission.Current.Scene;
                if (scene == null) return WorldPosition.Invalid;

                var allEntities = new List<GameEntity>();
                try
                {
                    scene.GetAllEntitiesWithScriptComponent<SiegeLadder>(ref allEntities);
                }
                catch { /* type may not exist на старых saves — try by name below */ }

                if (allEntities.Count == 0)
                {
                    // Fallback: scan все child entities scene'а по name pattern.
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
                        BannerlordLinkModule.Log(
                            $"[DET] scene scan warn: {scanEx.Message}");
                    }
                }

                foreach (var e in allEntities)
                {
                    if (e == null) continue;
                    Vec3 ep;
                    try { ep = e.GlobalPosition; }
                    catch { continue; }
                    float d = (ep - agentPos).LengthSquared;
                    if (d < bestDistSq)
                    {
                        bestDistSq = d;
                        bestEntity = e;
                    }
                }

                if (bestEntity == null) return WorldPosition.Invalid;
                return new WorldPosition(Mission.Current.Scene, UIntPtr.Zero,
                    bestEntity.GlobalPosition, false);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DET] FindNearestSiegeTarget warn: {ex.Message}");
                return WorldPosition.Invalid;
            }
        }
    }
}
