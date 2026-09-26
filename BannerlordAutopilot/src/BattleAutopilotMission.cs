using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.MountAndBlade.Missions.Handlers;

namespace BannerlordAutopilot
{
    /// <summary>Управляет обычной сухопутной полевой миссией, открытой F11.
    /// Расстановка завершается штатным controller; затем тактический AI получает
    /// обычные формации, а боевой AI — главного героя. Результат и закрытие миссии
    /// остаются штатным BattleEndLogic.</summary>
    internal sealed class BattleAutopilotMission : MissionLogic
    {
        private bool _deploymentRequested;
        private bool _controlGiven;
        private bool _exitRequested;
        private float _completedWait;
        private float _exitRetry;
        private float _fieldOrderRefresh;
        private bool _fieldAttackActive;
        private Agent _givenAgent;
        private bool _siegeDismountGiven;
        private Formation _preSiegeHeroFormation;
        private bool _siegeFormationChanged;
        private readonly List<Formation> _formationsGiven = new List<Formation>();
        private readonly Dictionary<Formation, (bool AiControlled, MovementOrder Move, FiringOrder Fire)> _fieldOrders
            = new Dictionary<Formation, (bool, MovementOrder, FiringOrder)>();
        private readonly Dictionary<Formation, (MovementOrder Move, FiringOrder Fire)> _hideoutOrders
            = new Dictionary<Formation, (MovementOrder, FiringOrder)>();

        private bool CanControlNow => Mission.Mode == MissionMode.Battle
            || (Mission.Mode == MissionMode.Stealth && AutopilotBehavior.Instance?.IsOwnedHideoutBattle == true);

        internal static bool IsSupportedCampaignBattle()
        {
            MobileParty party = MobileParty.MainParty;
            return Campaign.Current != null
                   && (AutopilotBehavior.IsSupportedFieldBattleEncounter(party)
                       || AutopilotBehavior.Instance?.IsOwnedOperationBattle(party) == true);
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            if (_faulted) return;
            try { TickCore(dt); }
            catch (Exception ex) { Fault("тик боя", ex); }
        }

        // 23.09: тик боя шёл без перехвата — исключение движка здесь роняло
        // игру и повторялось бы каждый кадр. После сбоя бой больше не трогаем:
        // автопилот выключен, управление возвращается один раз, если выйдет.
        private bool _faulted;

        private void Fault(string what, Exception ex)
        {
            _faulted = true;
            Exception cause = ex is System.Reflection.TargetInvocationException && ex.InnerException != null ? ex.InnerException : ex;
            AutopilotBehavior.Instance?.Disable(what + " упал: " + cause.GetType().Name + ": " + cause.Message);
            try { RestorePlayerControl(); }
            catch (Exception restore) { AutopilotLog.Write("БОЙ: вернуть управление после сбоя не вышло: " + restore.GetType().Name + ": " + restore.Message); }
        }

        private void TickCore(float dt)
        {
            if (AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply)
            {
                RestorePlayerControl();
                return;
            }

            if (!_controlGiven && Mission.IsDeploymentFinished && CanControlNow)
            {
                GiveControlToAi();
            }
            if (_controlGiven && _fieldAttackActive
                && Mission.Mode == MissionMode.Battle && !Mission.MissionEnded)
            {
                _fieldOrderRefresh += dt;
                if (_fieldOrderRefresh >= 1f)
                {
                    _fieldOrderRefresh = 0f;
                    RefreshFieldAttackOrders();
                }
            }
        }

        // FinishDeployment removes both the controller and its handler. Calling it
        // inside Mission.OnTick invalidates the engine's reverse index loop.
        internal void PollDeployment()
        {
            if (AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply
                || TaleWorlds.Library.InformationManager.IsAnyInquiryActive() || Mission.MissionEnded) return;
            if (!_deploymentRequested && Mission.Mode == MissionMode.Deployment)
            {
                SiegeDeploymentMissionController siege = Mission.GetMissionBehavior<SiegeDeploymentMissionController>();
                DeploymentMissionController deployment = siege
                    ?? (DeploymentMissionController)Mission.GetMissionBehavior<BattleDeploymentMissionController>();
                if (deployment != null && deployment.TeamSetupOver && Mission.MainAgent != null
                    && Mission.PlayerTeam != null)
                {
                    SiegeDeploymentHandler handler = siege != null
                        ? Mission.GetMissionBehavior<SiegeDeploymentHandler>() : null;
                    if (siege != null && handler == null) return;
                    _deploymentRequested = true;
                    try
                    {
                        if (handler != null)
                        {
                            // Same sequence as DeploymentControllerVM.DeployFormationsOfPlayer:
                            // let native siege tactics place troops, then assign roles and crews.
                            handler.AutoDeployTeamUsingTeamAI(Mission.PlayerTeam, autoAssignDetachments: false);
                            Mission.GetMissionBehavior<AssignPlayerRoleInTeamMissionController>()?.OnPlayerTeamDeployed();
                            handler.AutoAssignDetachmentsForDeployment(Mission.PlayerTeam);
                            AutopilotLog.Write("ОСАДА: штатное авторазмещение и назначение расчётов выполнены");
                        }
                        AutopilotLog.Write("БОЙ: штатная расстановка готова; начинаем бой");
                        deployment.FinishDeployment();
                    }
                    catch (Exception ex)
                    {
                        AutopilotBehavior.Instance.Disable("завершение расстановки остановлено: " + ex);
                    }
                }
            }

        }

        public override void OnAfterDeploymentFinished()
        {
            base.OnAfterDeploymentFinished();
            GiveControlToAi();
        }

        public override void OnMissionModeChange(MissionMode oldMissionMode, bool atStart)
        {
            base.OnMissionModeChange(oldMissionMode, atStart);
            // Hideout cinematics build the companion list from AI agents. Main hero
            // must be a player again BEFORE the cinematic collects those agents.
            if (!CanControlNow) RestorePlayerControl();
        }

        // Called from application polling as the scoreboard may pause mission ticks.
        internal void PollCompletedBattle(float dt)
        {
            if (_exitRequested || AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply
                || !Mission.MissionEnded || Mission.MissionResult?.BattleResolved != true
                || TaleWorlds.Library.InformationManager.IsAnyInquiryActive())
            {
                _completedWait = 0f;
                return;
            }
            _completedWait += dt;
            if (_completedWait < 3f) return;
            _exitRetry -= dt;
            if (_exitRetry > 0f) return;
            _exitRetry = 1f;
            var end = Mission.GetMissionBehavior<BattleEndLogic>();
            try
            {
                if (end != null && end.TryExit() == BattleEndLogic.ExitResult.True)
                {
                    _exitRequested = true;
                    var result = Mission.MissionResult;
                    if (result != null && result.PlayerVictory) Thoughts.Say("battle_won", null);
                    else if (result != null && result.PlayerDefeated) Thoughts.Say("battle_lost", null);
                    AutopilotLog.Write("БОЙ: результат определён игрой; штатный выход из завершённой миссии");
                }
            }
            catch (Exception ex)
            {
                _exitRequested = true; // No repeated call after an unknown partial engine effect.
                AutopilotLog.Write("БОЙ: автоматический выход остановлен, требуется TAB: " + ex);
            }
        }

        private void GiveControlToAi()
        {
            if (_controlGiven || !CanControlNow || AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply)
            {
                return;
            }
            Team team = Mission.PlayerTeam;
            Agent agent = Mission.MainAgent;
            if (team == null || agent == null || !agent.IsActive())
            {
                return;
            }

            _formationsGiven.Clear();
            if (team.TeamAI != null) foreach (Formation formation in team.FormationsIncludingEmpty)
            {
                if (!formation.IsAIControlled)
                {
                    _formationsGiven.Add(formation);
                }
            }
            bool rbmTactics = IsRbmAiEnabled();
            if (team.TeamAI != null && MobileParty.MainParty?.MapEvent?.IsSiegeAssault != true && !rbmTactics)
            {
                _fieldAttackActive = true;
                RefreshFieldAttackOrders();
                AutopilotLog.Write("БОЙ: " + _fieldOrders.Count + " формаций получили приказ атаковать");
            }
            else if (team.TeamAI != null)
            {
                team.DelegateCommandToAI();
                if (rbmTactics) AutopilotLog.Write("БОЙ: RBM AI включён; формации переданы тактическому AI, принудительная атака отключена");
            }
            else if (AutopilotBehavior.Instance?.IsOwnedHideoutBattle == true)
            {
                foreach (Formation formation in team.FormationsIncludingEmpty)
                {
                    if (formation.CountOfUnits == 0) continue;
                    _hideoutOrders[formation] = (formation.GetReadonlyMovementOrderReference(), formation.FiringOrder);
                    formation.SetMovementOrder(MovementOrder.MovementOrderCharge);
                    formation.SetFiringOrder(FiringOrder.FiringOrderFireAtWill);
                }
            }
            _givenAgent = agent;

            // RTS Camera 5.4.16 делает больше, чем простая смена Controller:
            // старое взаимодействие и scripted movement иначе могут продолжать
            // держать героя, а компоненты AI — остаться в состоянии игрока.
            if (agent.IsUsingGameObject && !Mission.IsFriendlyMission)
            {
                agent.HandleStopUsingAction();
            }
            if (MobileParty.MainParty?.MapEvent?.IsSiegeAssault == true && team.TeamAI != null)
            {
                // A dismounted hero can still belong to a mounted/ranged formation
                // holding outside the walls. Follow the actual assault infantry.
                Formation infantry = team.GetFormation(FormationClass.Infantry);
                AutopilotLog.Write("БОЙ: герой перед штурмом: формация "
                    + (agent.Formation?.FormationIndex.ToString() ?? "нет")
                    + ", дальнее оружие с боеприпасами " + agent.IsRangedCached
                    + ", пехоты " + (infantry?.CountOfUnits ?? 0));
                if (infantry != null && infantry.CountOfUnits > 0 && agent.Formation != infantry)
                {
                    _preSiegeHeroFormation = agent.Formation;
                    _siegeFormationChanged = true;
                    agent.Formation = infantry;
                    AutopilotLog.Write("БОЙ: герой присоединился к штурмовой пехоте");
                }
            }
            agent.Controller = AgentControllerType.AI;
            agent.CommonAIComponent?.Initialize();
            agent.HumanAIComponent?.Initialize();
            agent.SetAlarmState(Agent.AIStateFlag.Alarmed);
            agent.SetIsAIPaused(false);
            agent.DisableScriptedMovement();
            if (agent.Formation != null)
            {
                agent.SetRidingOrder(agent.Formation.RidingOrder.OrderEnum);
                agent.Formation.OnUnitAddedOrRemoved();
            }
            // A siege assault has no useful mounted route through walls and ladders.
            // Override the hero's riding order only; cavalry formations keep the
            // game's own orders, and field battles retain their mounted behavior.
            if (MobileParty.MainParty?.MapEvent?.IsSiegeAssault == true)
            {
                agent.SetRidingOrder(RidingOrder.RidingOrderEnum.Dismount);
                _siegeDismountGiven = true;
                AutopilotLog.Write("БОЙ: осадный штурм, герою дан приказ спешиться"
                    + (agent.MountAgent != null ? " (герой верхом)" : ""));
            }
            agent.ResetEnemyCaches();
            agent.HumanAIComponent?.SyncBehaviorParamsIfNecessary();
            _controlGiven = true;
            // BattleOverviewCamera owns rendering independently of the main agent.
            AutopilotLog.Write(_fieldOrders.Count > 0
                ? "БОЙ: герой передан штатному AI; формации наступают по приказу автопилота"
                : "БОЙ: герой и " + _formationsGiven.Count + " формаций переданы штатному AI");
        }

        private static bool IsRbmAiEnabled()
        {
            // Optional integration: never load RBM ourselves or require its DLL.
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (assembly.GetName().Name != "RBMConfig") continue;
                try
                {
                    return assembly.GetType("RBMConfig.RBMConfig")
                        ?.GetField("rbmAiEnabled")?.GetValue(null) is true;
                }
                catch (Exception ex)
                {
                    AutopilotLog.Write("БОЙ: не удалось определить режим RBM; сохраняем прежнее управление: " + ex.Message);
                    return false;
                }
            }
            return false;
        }

        private void RefreshFieldAttackOrders()
        {
            Team team = Mission.PlayerTeam;
            if (team?.TeamAI == null) return;
            foreach (Formation formation in team.FormationsIncludingEmpty)
            {
                if (formation.CountOfUnits == 0) continue;
                bool newlyActive = !_fieldOrders.ContainsKey(formation);
                if (newlyActive)
                    _fieldOrders[formation] = (formation.IsAIControlled,
                        formation.GetReadonlyMovementOrderReference(), formation.FiringOrder);
                if (newlyActive || formation.IsAIControlled
                    || formation.GetReadonlyMovementOrderReference().OrderEnum != MovementOrder.MovementOrderCharge.OrderEnum
                    || formation.FiringOrder.OrderEnum != FiringOrder.FiringOrderFireAtWill.OrderEnum)
                {
                    formation.SetControlledByAI(false);
                    formation.SetMovementOrder(MovementOrder.MovementOrderCharge);
                    formation.SetFiringOrder(FiringOrder.FiringOrderFireAtWill);
                    if (newlyActive) AutopilotLog.Write("БОЙ: появившаяся формация " + formation.FormationIndex + " получила приказ атаковать");
                }
            }
        }

        private void RestorePlayerControl()
        {
            if (!_controlGiven)
            {
                return;
            }
            foreach (Formation formation in _formationsGiven)
            {
                if (formation != null && !_fieldOrders.ContainsKey(formation)) formation.SetControlledByAI(false);
            }
            foreach (var pair in _fieldOrders)
            {
                pair.Key.SetControlledByAI(pair.Value.AiControlled);
                pair.Key.SetMovementOrder(pair.Value.Move);
                pair.Key.SetFiringOrder(pair.Value.Fire);
            }
            _fieldOrders.Clear();
            _fieldAttackActive = false;
            _fieldOrderRefresh = 0f;
            foreach (var pair in _hideoutOrders)
            {
                pair.Key.SetMovementOrder(pair.Value.Move);
                pair.Key.SetFiringOrder(pair.Value.Fire);
            }
            _hideoutOrders.Clear();
            if (_givenAgent != null && _givenAgent.IsActive() && Mission.MainAgent == _givenAgent)
            {
                _givenAgent.Controller = AgentControllerType.Player;
                if (_siegeFormationChanged)
                    _givenAgent.Formation = _preSiegeHeroFormation;
                _givenAgent.AIStateFlags = Agent.AIStateFlag.None;
                _givenAgent.SetMaximumSpeedLimit(-1f, false);
                _givenAgent.MountAgent?.SetMaximumSpeedLimit(-1f, false);
                if (_siegeDismountGiven && _givenAgent.Formation != null)
                    _givenAgent.SetRidingOrder(_givenAgent.Formation.RidingOrder.OrderEnum);
                _givenAgent.Formation?.OnUnitAddedOrRemoved();
            }
            _formationsGiven.Clear();
            _givenAgent = null;
            _siegeDismountGiven = false;
            _preSiegeHeroFormation = null;
            _siegeFormationChanged = false;
            _controlGiven = false;
            AutopilotLog.Write("БОЙ: управление возвращено герою и формациям (F12 или переход миссии)");
        }

        protected override void OnEndMission()
        {
            AutopilotBehavior.Instance?.OnOperationMissionEnded();
            _hideoutOrders.Clear();
            _fieldOrders.Clear();
            _fieldAttackActive = false;
            _formationsGiven.Clear();
            _givenAgent = null;
            _siegeDismountGiven = false;
            _preSiegeHeroFormation = null;
            _siegeFormationChanged = false;
            _controlGiven = false;
            base.OnEndMission();
        }
    }
}
