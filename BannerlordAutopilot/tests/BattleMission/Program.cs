using System;
using BannerlordAutopilot;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

int failed = 0;
void Check(bool ok, string text) { Console.WriteLine((ok ? "ok   " : "FAIL ") + text); if (!ok) failed++; }

var mission = new Mission();
var originallyManual = new Formation(); var originallyAi = new Formation { IsAIControlled = true };
mission.PlayerTeam.FormationsIncludingEmpty.Add(originallyManual); mission.PlayerTeam.FormationsIncludingEmpty.Add(originallyAi);
mission.Deployment = new BattleDeploymentMissionController { Mission = mission, TeamSetupOver = true };
var behavior = new BattleAutopilotMission { Mission = mission };
behavior.OnMissionTick(0.1f);
Check(mission.Deployment.FinishCalls == 1 && mission.IsDeploymentFinished, "готовая расстановка завершается один раз");
behavior.OnAfterDeploymentFinished(); behavior.OnMissionTick(0.1f);
Check(mission.MainAgent.Controller == AgentControllerType.AI, "главный герой передан боевому AI");
Check(originallyManual.IsAIControlled && originallyAi.IsAIControlled, "формации переданы тактическому AI");
Check(mission.MainAgent.AlarmCalls == 1 && mission.MainAgent.UnpauseCalls == 1, "герой разбужен после расстановки");
AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Off; behavior.OnMissionTick(0.1f);
Check(mission.MainAgent.Controller == AgentControllerType.Player, "F12 возвращает живого героя");
Check(!originallyManual.IsAIControlled && originallyAi.IsAIControlled, "возвращено только управление, которым владел мод");
return failed;
