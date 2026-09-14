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
        private Agent _givenAgent;
        private readonly List<Formation> _formationsGiven = new List<Formation>();

        internal static bool IsSupportedCampaignBattle()
        {
            MobileParty party = MobileParty.MainParty;
            return Campaign.Current != null
                   && AutopilotBehavior.IsSupportedFieldBattleEncounter(party);
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            if (AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply)
            {
                RestorePlayerControl();
                return;
            }

            if (!_deploymentRequested && Mission.Mode == MissionMode.Deployment)
            {
                BattleDeploymentMissionController deployment =
                    Mission.GetMissionBehavior<BattleDeploymentMissionController>();
                if (deployment != null && deployment.TeamSetupOver && Mission.MainAgent != null)
                {
                    _deploymentRequested = true;
                    AutopilotLog.Write("БОЙ: штатная расстановка готова; начинаем бой");
                    deployment.FinishDeployment();
                }
            }

            if (!_controlGiven && Mission.IsDeploymentFinished && Mission.Mode == MissionMode.Battle)
            {
                GiveControlToAi();
            }
        }

        public override void OnAfterDeploymentFinished()
        {
            base.OnAfterDeploymentFinished();
            GiveControlToAi();
        }

        private void GiveControlToAi()
        {
            if (_controlGiven || AutopilotBehavior.Instance?.CurrentMode != AutopilotBehavior.Mode.Apply)
            {
                return;
            }
            Team team = Mission.PlayerTeam;
            Agent agent = Mission.MainAgent;
            if (team == null || team.TeamAI == null || agent == null || !agent.IsActive())
            {
                return;
            }

            _formationsGiven.Clear();
            foreach (Formation formation in team.FormationsIncludingEmpty)
            {
                if (!formation.IsAIControlled)
                {
                    _formationsGiven.Add(formation);
                }
            }
            team.DelegateCommandToAI();
            _givenAgent = agent;
            agent.Controller = AgentControllerType.AI;
            agent.SetAlarmState(Agent.AIStateFlag.Alarmed);
            agent.SetIsAIPaused(false);
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
            if (_givenAgent != null && _givenAgent.IsActive() && Mission.MainAgent == _givenAgent)
            {
                _givenAgent.Controller = AgentControllerType.Player;
            }
            _formationsGiven.Clear();
            _givenAgent = null;
            _controlGiven = false;
            AutopilotLog.Write("БОЙ: F12 вернул управление живому герою и формациям");
        }

        protected override void OnEndMission()
        {
            _formationsGiven.Clear();
            _givenAgent = null;
            _controlGiven = false;
            base.OnEndMission();
        }
    }
}
