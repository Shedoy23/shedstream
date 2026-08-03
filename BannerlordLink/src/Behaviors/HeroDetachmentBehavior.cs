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
            public bool ChargeEngaged;           // Charge: враг в упор, управление отдано боевому AI
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
            BannerlordLinkModule.Log(
                $"[DET] SKIRMISH agent={agent.Index} standoff={SkirmishStandoff(agent):F0}m");
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
            // 2026-07-19 (#walls) — целимся в боевую позицию на забрале: позицию ближайшего
            // СВОЕГО бойца, стоящего ВЫШЕ нас (движок расставил защитников по стене; их точки
            // навмеш-валидны и достижимы по внутренним лестницам). Раньше целились в тело
            // стены/лестницы → герой утыкался в основание. Фолбэк на старую логику, если
            // своих на стене нет (атакующий / стена пуста).
            var wp = FindWallFiringPosition(agent);
            if (!wp.IsValid)
                wp = FindNearestSiegeTarget(agent, gateOnly: false);
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
                    // (дистанционный бой — отдельный приказ Skirmish «издали»).
                    //
                    // 2026-08-03 (просьба владельца «чтоб персонаж просто шёл в бой»):
                    // раньше мы КАЖДЫЕ 0.5с переставляли скриптованную позицию на
                    // ближайшего врага с флагом NeverSlowDown — и не снимали её никогда.
                    // Герой из-за этого вечно БЕЖАЛ к точке вместо того, чтобы драться:
                    // подбежав вплотную, он тут же получал новую точку (враг сместился
                    // или ближайшим стал другой) и снова разгонялся, вместо замаха.
                    //
                    // Теперь скрипт — только чтобы ДОЙТИ. Как только враг в пределах
                    // удара, управление отдаётся боевому AI движка: он сам выбирает
                    // цель, бьёт, блокирует и уклоняется. Отпускаем через
                    // DisableScriptedMovement + SetAutomaticTargetSelection(true).
                    //
                    // Гистерезис (ENGAGE < DISENGAGE) — чтобы у самой границы приказ не
                    // дёргался «отпустил/схватил» каждый тик. Это тот же класс ошибки и
                    // то же лекарство, что в Skirmish (#32): там пересчёт точки каждые
                    // 0.5с давал «бегает туда-сюда», и лечилось это зоной покоя.
                    const float ENGAGE_DIST    = 3.5f;   // ближе — дерись сам
                    const float DISENGAGE_DIST = 6.0f;   // дальше — снова веду к врагу

                    float dist = agent.Position.Distance(enemy.Position);
                    if (st.ChargeEngaged && dist > DISENGAGE_DIST) st.ChargeEngaged = false;
                    else if (!st.ChargeEngaged && dist <= ENGAGE_DIST) st.ChargeEngaged = true;

                    try { agent.SetAutomaticTargetSelection(true); } catch { }

                    if (st.ChargeEngaged)
                    {
                        // В упор — не мешаем движку драться.
                        try { agent.DisableScriptedMovement(); } catch { }
                    }
                    else
                    {
                        var pos = enemy.GetWorldPosition();
                        agent.SetScriptedPosition(ref pos, false,
                            Agent.AIScriptedFrameFlags.NeverSlowDown);
                    }
                }
                else
                {
                    // Врагов не нашли — снимаем скрипт, пусть AI решает сам.
                    st.ChargeEngaged = false;
                    try { agent.DisableScriptedMovement(); } catch { }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[DET] ApplyCharge warn: {ex.Message}");
            }
        }

        // 2026-06-17 / 2026-07-19 (#32) — Skirmish: «встал на дистанции и стреляет».
        // Дистанция = 0.8 × реальной дальности оружия (движковый Agent.MaximumMissileRange),
        // мёртвая зона ±band против джиттера (принцип BehaviorSkirmish: держать позицию в
        // полосе, а не пересчитывать цель каждый тик). Вне полосы (враг слишком близко ИЛИ
        // слишком далеко) — выходим на standoff; в полосе — пиним позицию ОДИН раз и стоим
        // (авто-таргет стреляет). Раньше точка-цель пересчитывалась от движущегося ближайшего
        // врага каждые 0.5с → герой бесконечно бегал за прыгающей точкой («бегает туда-сюда
        // в поиске места»).
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

                float standoff = SkirmishStandoff(agent);   // 0.8 × дальности оружия
                float band = standoff * 0.18f;              // полуширина зоны покоя
                if (band < 6f) band = 6f;

                var epos = enemy.GetWorldPosition();
                Vec2 ec = epos.AsVec2;
                Vec2 away = agent.Position.AsVec2 - ec;   // enemy → agent
                float dist = away.Length;

                bool hasLos = HasLineOfSight(agent, enemy);

                // 2026-08-03 (жалоба владельца: «держит дистанцию от врага, который бежит
                // на него, из-за этого просто бегает туда-сюда, а не атакует»).
                //
                // Причина была в том, что «слишком близко» считалось поводом ОТСТУПАТЬ.
                // Для лука standoff ≈ 0.8 × 80 м ≈ 64 м, зона покоя 52–75 м. Враг бежит
                // на героя → дистанция падает ниже 52 → его скриптуют назад на 64 м →
                // враг снова добегает. Цикл не сходится никогда, а стрелять герой не
                // успевает, потому что постоянно бежит (NeverSlowDown).
                //
                // Логическая ошибка: для стрелка «ближе, чем standoff» — НЕ проблема.
                // С 30 м стрела летит прекрасно. Дистанция нужна, чтобы не оказаться в
                // ближнем бою, а не чтобы держать рекорд дальности. Поэтому:
                //   • враг в упор            → не пятимся, дерёмся (AI возьмёт сайдарм);
                //   • ближе standoff'а, но не в упор → СТОИМ И СТРЕЛЯЕМ;
                //   • дальше полосы          → поджимаемся, чтобы достать.
                // Отступление убрано как поведение — оно и порождало «туда-сюда».
                const float SKIRMISH_MELEE_DIST = 5.0f;   // враг фактически на нас

                if (dist <= SKIRMISH_MELEE_DIST)
                {
                    // Пятиться поздно и бессмысленно — отдаём управление боевому AI.
                    st.SkirmishHolding = false;
                    try { agent.DisableScriptedMovement(); } catch { }
                    return;
                }

                bool tooFar = dist > standoff + band;

                if (tooFar)
                {
                    // Слишком далеко, чтобы достать → поджимаемся на standoff.
                    if (dist > 0.01f)
                    {
                        away = away * (standoff / dist);
                        try { epos.SetVec2(ec + away); } catch { }
                    }
                    agent.SetScriptedPosition(ref epos, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    st.SkirmishHolding = false;
                }
                else if (!hasLos)
                {
                    // 2026-07-20 (#36) — в полосе, но цель НЕ видно (укрытие/стена между
                    // нами). Раньше герой пинил позицию и мёрз, не стреляя. Теперь
                    // поджимаемся к врагу (до 0.5×standoff) искать линию огня, а не стоим
                    // столбом. Увидим цель — на след. тике вернёмся в hold.
                    if (dist > 0.01f)
                    {
                        away = away * (standoff * 0.5f / dist);
                        try { epos.SetVec2(ec + away); } catch { }
                    }
                    agent.SetScriptedPosition(ref epos, false,
                        Agent.AIScriptedFrameFlags.NeverSlowDown);
                    st.SkirmishHolding = false;
                }
                else if (!st.SkirmishHolding)
                {
                    // В полосе И есть линия огня → пиним ТЕКУЩУЮ позицию один раз и держим.
                    // Дальше не трогаем → стоит и стреляет, не бегает за прыгающей точкой.
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

        /// <summary>Боевая позиция на забрале для команды «на стену»: позиция ближайшего
        /// СВОЕГО активного бойца, стоящего ВЫШЕ нас (движок сам расставил защитников по
        /// стене — их точки навмеш-валидны и достижимы по внутренним лестницам, в отличие от
        /// тела стены/лестницы). Лучников слегка приоритезируем (они на стрелковых позициях).
        /// Invalid, если своих на забрале нет (атакующий / стена пуста) → caller делает
        /// фолбэк на FindNearestSiegeTarget.</summary>
        private WorldPosition FindWallFiringPosition(Agent agent)
        {
            try
            {
                if (Mission.Current == null) return WorldPosition.Invalid;
                Vec3 me = agent.Position;
                Team team = agent.Team;
                Agent best = null;
                float bestScore = float.MaxValue;
                foreach (var a in Mission.Current.Agents)
                {
                    if (a == null || a == agent || !a.IsActive()) continue;
                    if (a.Team != team) continue;                       // только свои
                    if (a.Position.z <= me.z + WALL_MIN_ELEVATION) continue;   // выше нас = на забрале
                    float score = (a.Position - me).LengthSquared;
                    try { if (a.IsRangedCached) score *= 0.5f; } catch { }   // лёгкий приоритет стрелков
                    if (score < bestScore) { bestScore = score; best = a; }
                }
                if (best == null) return WorldPosition.Invalid;
                return ProjectToNavMesh(Mission.Current.Scene, best.Position);
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
