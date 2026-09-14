using System;
using BannerlordAutopilot;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

int failed = 0;
void Check(bool ok, string text) { Console.WriteLine((ok ? "ok   " : "FAIL ") + text); if (!ok) failed++; }

var mission = new Mission();
var originallyManual = new Formation(); var originallyAi = new Formation { IsAIControlled = true };
mission.PlayerTeam.FormationsIncludingEmpty.Add(originallyManual); mission.PlayerTeam.FormationsIncludingEmpty.Add(originallyAi);
mission.MainAgent.Formation = originallyManual;
mission.MainAgent.MountAgent = new Agent { IsUsingGameObject = false };
mission.Deployment = new BattleDeploymentMissionController { Mission = mission, TeamSetupOver = true };
var behavior = new BattleAutopilotMission { Mission = mission };
behavior.OnMissionTick(0.1f);
Check(mission.Deployment.FinishCalls == 1 && mission.IsDeploymentFinished, "готовая расстановка завершается один раз");
behavior.OnAfterDeploymentFinished(); behavior.OnMissionTick(0.1f);
Check(mission.MainAgent.Controller == AgentControllerType.AI, "главный герой передан боевому AI");
Check(originallyManual.IsAIControlled && originallyAi.IsAIControlled, "формации переданы тактическому AI");
Check(mission.MainAgent.AlarmCalls == 1 && mission.MainAgent.UnpauseCalls == 1, "герой разбужен после расстановки");
Check(mission.MainAgent.StopUsingCalls == 1 && mission.MainAgent.DisableScriptedCalls == 1,
      "старое взаимодействие и scripted movement сняты");
Check(mission.MainAgent.CommonAIComponent.InitializeCalls == 1 && mission.MainAgent.HumanAIComponent.InitializeCalls == 1
      && mission.MainAgent.HumanAIComponent.SyncCalls == 1, "компоненты боевого AI заново инициализированы");
Check(mission.MainAgent.RidingOrderCalls == 1 && originallyManual.ChangedCalls == 1,
      "приказ посадки и состояние формации синхронизированы");
AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Off; behavior.OnMissionTick(0.1f);
Check(mission.MainAgent.Controller == AgentControllerType.Player, "F12 возвращает живого героя");
Check(mission.MainAgent.AIStateFlags == Agent.AIStateFlag.None && mission.MainAgent.SpeedResetCalls == 1
      && mission.MainAgent.MountAgent.SpeedResetCalls == 1 && originallyManual.ChangedCalls == 2,
      "F12 очищает состояние AI и ограничения скорости героя с лошадью");
Check(!originallyManual.IsAIControlled && originallyAi.IsAIControlled, "возвращено только управление, которым владел мод");
return failed;
