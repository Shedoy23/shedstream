using System;
using BannerlordAutopilot;
using TaleWorlds.Core;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.MountAndBlade;

int failed = 0;
void Check(bool ok, string text) { Console.WriteLine((ok ? "ok   " : "FAIL ") + text); if (!ok) failed++; }

var mission = new Mission();
var originallyManual = new Formation { Move = new MovementOrder { Kind = 2 }, FiringOrder = new FiringOrder { Kind = 2 } };
var originallyAi = new Formation { IsAIControlled = true, Move = new MovementOrder { Kind = 3 } };
var empty = new Formation { CountOfUnits = 0 };
mission.PlayerTeam.FormationsIncludingEmpty.Add(originallyManual); mission.PlayerTeam.FormationsIncludingEmpty.Add(originallyAi);
mission.PlayerTeam.FormationsIncludingEmpty.Add(empty);
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
typeof(BattleAutopilotMission).GetMethod("PollDeployment", System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic)?.Invoke(behavior,null);
Check(mission.Deployment.FinishCalls==1,"опрос приложения не повторяет завершение расстановки");
behavior.OnAfterDeploymentFinished(); behavior.OnMissionTick(0.1f);
Check(mission.MainAgent.Controller == AgentControllerType.AI, "главный герой передан боевому AI");
Check(!originallyManual.IsAIControlled && !originallyAi.IsAIControlled
      && originallyManual.Move.Kind == 1 && originallyAi.Move.Kind == 1
      && originallyManual.FiringOrder.Kind == 1 && originallyAi.FiringOrder.Kind == 1,
      "в полевом бою непустые формации сразу получают атаку и стрельбу по готовности");
Check(empty.Move.Kind == 0 && !empty.IsAIControlled, "пустая формация не получает приказ");
empty.CountOfUnits=7;
behavior.OnMissionTick(1.1f);
Check(empty.Move.Kind==1 && empty.FiringOrder.Kind==1 && !empty.IsAIControlled,
      "подкрепление в прежде пустой формации получает атаку после появления");
originallyManual.SetMovementOrder(new MovementOrder { Kind=2 });
behavior.OnMissionTick(1.1f);
Check(originallyManual.Move.Kind==1,"сброшенный движком приказ атаки обновляется в ходе боя");
Check(mission.MainAgent.AlarmCalls == 1 && mission.MainAgent.UnpauseCalls == 1, "герой разбужен после расстановки");
Check(mission.MainAgent.StopUsingCalls == 1 && mission.MainAgent.DisableScriptedCalls == 1,
      "старое взаимодействие и scripted movement сняты");
Check(mission.MainAgent.CommonAIComponent.InitializeCalls == 1 && mission.MainAgent.HumanAIComponent.InitializeCalls == 1
      && mission.MainAgent.HumanAIComponent.SyncCalls == 1, "компоненты боевого AI заново инициализированы");
Check(mission.MainAgent.RidingOrderCalls == 1 && originallyManual.ChangedCalls == 1,
      "приказ посадки и состояние формации синхронизированы");
Check(mission.MainAgent.LastRidingOrder == RidingOrder.RidingOrderEnum.Mount,
      "полевой бой сохраняет приказ формации ехать верхом");
AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Off; behavior.OnMissionTick(0.1f);
Check(mission.MainAgent.Controller == AgentControllerType.Player, "F12 возвращает живого героя");
Check(mission.MainAgent.AIStateFlags == Agent.AIStateFlag.None && mission.MainAgent.SpeedResetCalls == 1
      && mission.MainAgent.MountAgent.SpeedResetCalls == 1 && originallyManual.ChangedCalls == 2,
      "F12 очищает состояние AI и ограничения скорости героя с лошадью");
Check(!originallyManual.IsAIControlled && originallyAi.IsAIControlled, "возвращено только управление, которым владел мод");
Check(originallyManual.Move.Kind == 2 && originallyManual.FiringOrder.Kind == 2
      && originallyAi.Move.Kind == 3 && originallyAi.FiringOrder.Kind == 0,
      "F12 восстанавливает прежние приказы формаций");
Check(empty.Move.Kind==0 && empty.FiringOrder.Kind==0,"F12 восстанавливает прежние приказы появившейся формации");
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
var siege = new Mission { Mode=MissionMode.Battle, IsDeploymentFinished=true };
siege.MainAgent.MountAgent = new Agent();
siege.MainAgent.Formation = new Formation { FormationIndex=FormationClass.Cavalry };
siege.MainAgent.IsRangedCached = true;
var originalSiegeFormation = siege.MainAgent.Formation;
var assaultInfantry = new Formation { FormationIndex=FormationClass.Infantry };
siege.PlayerTeam.FormationsIncludingEmpty.Add(assaultInfantry);
siege.PlayerTeam.FormationsIncludingEmpty.Add(siege.MainAgent.Formation);
MobileParty.MainParty.MapEvent.IsSiegeAssault = true;
var siegeBehavior = new BattleAutopilotMission { Mission=siege };
AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Apply;
siegeBehavior.OnMissionTick(0.1f);
Check(siege.MainAgent.LastRidingOrder == RidingOrder.RidingOrderEnum.Dismount,
      "осадный бой при верховом герое отдаёт приказ спешиться");
Check(siege.MainAgent.Formation == assaultInfantry && assaultInfantry.IsAIControlled,
      "герой с луком следует за штурмовой пехотой под штатным AI");
Check(siege.MainAgent.Formation.IsAIControlled && siege.MainAgent.Formation.Move.Kind == 0,
      "осадные формации остаются под штатным тактическим AI");
AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Off;
siegeBehavior.OnMissionTick(0.1f);
Check(siege.MainAgent.LastRidingOrder == RidingOrder.RidingOrderEnum.Mount,
      "F12 возвращает исходный приказ героя после осады");
Check(siege.MainAgent.Formation == originalSiegeFormation,
      "F12 возвращает исходную формацию героя после осады");
// Optional RBM is discovered without a compile-time dependency.
var rbmAssembly = System.Reflection.Emit.AssemblyBuilder.DefineDynamicAssembly(
    new System.Reflection.AssemblyName("RBMConfig"), System.Reflection.Emit.AssemblyBuilderAccess.Run);
var rbmTypeBuilder = rbmAssembly.DefineDynamicModule("RBMConfig").DefineType("RBMConfig.RBMConfig", System.Reflection.TypeAttributes.Public);
rbmTypeBuilder.DefineField("rbmAiEnabled", typeof(bool), System.Reflection.FieldAttributes.Public | System.Reflection.FieldAttributes.Static);
var rbmType = rbmTypeBuilder.CreateType();
foreach (bool enabled in new[] { true, false })
{
    rbmType.GetField("rbmAiEnabled").SetValue(null, enabled);
    AutopilotBehavior.Instance.CurrentMode = AutopilotBehavior.Mode.Apply;
    MobileParty.MainParty.MapEvent = new TaleWorlds.CampaignSystem.MapEvent();
    var rbmMission = new Mission { Mode=MissionMode.Battle, IsDeploymentFinished=true };
    var rbmManual = new Formation { Move = new MovementOrder { Kind=2 } };
    var rbmAlreadyAi = new Formation { IsAIControlled=true };
    rbmMission.PlayerTeam.FormationsIncludingEmpty.Add(rbmManual);
    rbmMission.PlayerTeam.FormationsIncludingEmpty.Add(rbmAlreadyAi);
    rbmMission.MainAgent.Formation=rbmManual;
    var rbmBehavior = new BattleAutopilotMission { Mission=rbmMission };
    rbmBehavior.OnAfterDeploymentFinished(); rbmBehavior.OnMissionTick(0.1f);
    Check(rbmManual.IsAIControlled == enabled, "RBM AI=" + enabled + ": выбран правильный режим командования");
    rbmManual.SetMovementOrder(new MovementOrder {Kind=3});
    rbmBehavior.OnMissionTick(1.1f);
    Check(rbmManual.Move.Kind == (enabled ? 3 : 1), "RBM AI=" + enabled + ": манёвр не перебивается при активном RBM");
    AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Off;
    rbmBehavior.OnMissionTick(0.1f);
    Check(!rbmManual.IsAIControlled && rbmAlreadyAi.IsAIControlled,
        "RBM AI=" + enabled + ": F12 возвращает только наше управление");
}
foreach (bool previousFirstPerson in new[]{false,true})
foreach (string stop in new[]{"off","dead","replacement","conversation","end"})
{
    AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Apply;
    var cameraMission=new Mission {Mode=MissionMode.Battle,IsDeploymentFinished=true,CameraIsFirstPerson=previousFirstPerson};
    var cameraBehavior=new BattleAutopilotMission {Mission=cameraMission};
    cameraBehavior.OnAfterDeploymentFinished();
    Check(cameraMission.CameraIsFirstPerson && cameraMission.MainAgent.Controller==AgentControllerType.AI,
        "camera follows first person without returning player control");
    if(stop=="off") AutopilotBehavior.Instance.CurrentMode=AutopilotBehavior.Mode.Off;
    if(stop=="dead") cameraMission.MainAgent.Active=false;
    if(stop=="replacement") cameraMission.MainAgent=new Agent();
    if(stop=="conversation") {cameraMission.Mode=MissionMode.Conversation;cameraBehavior.OnMissionModeChange(MissionMode.Battle,false);}
    if(stop=="end") typeof(BattleAutopilotMission).GetMethod("OnEndMission",System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.NonPublic).Invoke(cameraBehavior,null);
    else cameraBehavior.OnMissionTick(.1f);
    Check(cameraMission.CameraIsFirstPerson==previousFirstPerson,"camera restores previous mode: "+stop);
}
// Siege has a sibling deployment controller, not a BattleDeployment subclass.
foreach (string gate in new[] { "ready", "setup", "hero", "team", "handler", "off", "inquiry", "ended", "exception" })
{
    AutopilotBehavior.Instance.CurrentMode = gate == "off" ? AutopilotBehavior.Mode.Off : AutopilotBehavior.Mode.Apply;
    TaleWorlds.Library.InformationManager.Inquiry = gate == "inquiry";
    var deploying = new Mission { MissionEnded = gate == "ended" };
    var controller = new SiegeDeploymentMissionController { Mission = deploying, TeamSetupOver = gate != "setup" };
    deploying.Deployment = controller;
    deploying.SiegeHandler = new TaleWorlds.MountAndBlade.Missions.Handlers.SiegeDeploymentHandler { Mission = deploying, ThrowOnDeploy = gate == "exception" };
    deploying.RoleController = new AssignPlayerRoleInTeamMissionController { Mission = deploying };
    if (gate == "hero") deploying.MainAgent = null;
    if (gate == "team") deploying.PlayerTeam = null;
    if (gate == "handler") deploying.SiegeHandler = null;
    var deployingBehavior = new BattleAutopilotMission { Mission = deploying };
    deploying.Behaviors.Add(controller); deploying.Behaviors.Add(deployingBehavior);
    for (int i = deploying.Behaviors.Count - 1; i >= 0; i--) deploying.Behaviors[i].OnMissionTick(.1f);
    Check(deploying.DeploymentSteps.Count == 0, "siege deployment stays outside mission tick: " + gate);
    deployingBehavior.PollDeployment(); deployingBehavior.PollDeployment();
    if (gate == "ready")
        Check(string.Join(",", deploying.DeploymentSteps) == "deploy,role,detachments,finish" && deploying.IsDeploymentFinished,
            "siege auto-placement, player role, crews and finish execute once in native order");
    else if (gate == "exception")
        Check(string.Join(",", deploying.DeploymentSteps) == "deploy" && AutopilotBehavior.Instance.CurrentMode == AutopilotBehavior.Mode.Off,
            "partial siege deployment failure disables autopilot without finish or retry");
    else
        Check(deploying.DeploymentSteps.Count == 0, "siege deployment waits for readiness: " + gate);
}
TaleWorlds.Library.InformationManager.Inquiry = false;
return failed;
