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
mission.Behaviors.Add(mission.Deployment); mission.Behaviors.Add(new BattleDeploymentMissionController {Mission=mission}); mission.Behaviors.Add(behavior);
bool tickSafe=true;
try { for (int i=mission.Behaviors.Count-1;i>=0;i--) mission.Behaviors[i].OnMissionTick(0.1f); }
catch (ArgumentOutOfRangeException) { tickSafe=false; }
Check(tickSafe && mission.Deployment.FinishCalls==0,"обход MissionBehaviors не меняет список завершением расстановки");
behavior.OnMissionTick(0.1f);
typeof(BattleAutopilotMission).GetMethod("PollDeployment", System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic)?.Invoke(behavior,null);
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
AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Apply;
mission.EndLogic = new BattleEndLogic { Mission = mission };
for (int i=0;i<10;i++) behavior.PollCompletedBattle(0.5f);
Check(mission.EndLogic.Calls == 0, "активный бой не закрывается");
mission.MissionEnded = true; mission.MissionResult = new MissionResult { BattleResolved = true };
TaleWorlds.Library.InformationManager.Inquiry = true;
for (int i=0;i<10;i++) behavior.PollCompletedBattle(0.5f);
Check(mission.EndLogic.Calls == 0, "модальное окно не подтверждается выходом");
TaleWorlds.Library.InformationManager.Inquiry = false;
mission.EndLogic.AllowExit = false;
for (int i=0;i<8;i++) behavior.PollCompletedBattle(0.5f);
Check(mission.EndLogic.Calls > 0 && mission.ExitCalls == 0, "отказ движка не обходится прямым EndMission");
mission.EndLogic.AllowExit = true;
for (int i=0;i<10;i++) behavior.PollCompletedBattle(0.5f);
Check(mission.ExitCalls == 1, "завершённый бой закрывается штатно ровно один раз");
var stopped = new BattleAutopilotMission { Mission = mission };
AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Off;
for (int i=0;i<10;i++) stopped.PollCompletedBattle(0.5f);
Check(mission.ExitCalls == 1, "F12 запрещает автоматический выход");
AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Apply;
var hideout = new Mission { Mode=MissionMode.Battle, IsDeploymentFinished=true };
AutopilotBehavior.Instance.IsOwnedHideoutBattle=true;
hideout.Mode=MissionMode.Stealth;
var hideoutFormation=new Formation(); hideout.PlayerTeam.FormationsIncludingEmpty.Add(hideoutFormation);
hideout.PlayerTeam.TeamAI=null;
var hideoutBehavior = new BattleAutopilotMission { Mission=hideout };
hideoutBehavior.OnMissionTick(0.1f);
Check(hideout.MainAgent.Controller==AgentControllerType.AI,"герой убежища управляется AI без TeamAI (как HideoutBattle игры)");
Check(hideoutFormation.Move.Kind==1 && hideoutFormation.FiringOrder.Kind==1,"отряд убежища идёт в атаку, а не остаётся на месте");
hideout.Mode=MissionMode.CutScene; hideoutBehavior.OnMissionModeChange(MissionMode.Stealth,false);
Check(hideout.MainAgent.Controller==AgentControllerType.Player && hideoutFormation.Move.Kind==0,
    "перед сценой главаря герой исключён из списка AI спутников, приказы восстановлены");
hideout.Mode=MissionMode.Stealth; hideoutBehavior.OnMissionTick(0.1f);
Check(hideout.MainAgent.Controller==AgentControllerType.AI,"после сцены управление боем возобновляется");
AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Off; hideoutBehavior.OnMissionTick(0.1f);
Check(hideout.MainAgent.Controller==AgentControllerType.Player && hideoutFormation.Move.Kind==0,"F12 возвращает и героя, и приказы отряда убежища");
return failed;
