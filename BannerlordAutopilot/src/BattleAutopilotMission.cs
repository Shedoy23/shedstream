using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

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
        private Agent _givenAgent;
        private bool _siegeDismountGiven;
        private readonly List<Formation> _formationsGiven = new List<Formation>();
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
            if (AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply)
            {
                RestorePlayerControl();
                return;
            }

            if (!_controlGiven && Mission.IsDeploymentFinished && CanControlNow)
            {
                GiveControlToAi();
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
                BattleDeploymentMissionController deployment =
                    Mission.GetMissionBehavior<BattleDeploymentMissionController>();
                if (deployment != null && deployment.TeamSetupOver && Mission.MainAgent != null)
                {
                    _deploymentRequested = true;
                    AutopilotLog.Write("БОЙ: штатная расстановка готова; начинаем бой");
                    try { deployment.FinishDeployment(); }
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
            if (team.TeamAI != null) team.DelegateCommandToAI();
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
            AutopilotLog.Write("БОЙ: герой и " + _formationsGiven.Count + " формаций переданы штатному AI");
        }

        private void RestorePlayerControl()
        {
            if (!_controlGiven)
            {
                return;
            }
            foreach (Formation formation in _formationsGiven)
            {
                formation?.SetControlledByAI(false);
            }
            foreach (var pair in _hideoutOrders)
            {
                pair.Key.SetMovementOrder(pair.Value.Move);
                pair.Key.SetFiringOrder(pair.Value.Fire);
            }
            _hideoutOrders.Clear();
            if (_givenAgent != null && _givenAgent.IsActive() && Mission.MainAgent == _givenAgent)
            {
                _givenAgent.Controller = AgentControllerType.Player;
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
            _controlGiven = false;
            AutopilotLog.Write("БОЙ: управление возвращено герою и формациям (F12 или переход миссии)");
        }

        protected override void OnEndMission()
        {
            AutopilotBehavior.Instance?.OnOperationMissionEnded();
            _hideoutOrders.Clear();
            _formationsGiven.Clear();
            _givenAgent = null;
            _siegeDismountGiven = false;
            _controlGiven = false;
            base.OnEndMission();
        }
    }
}
