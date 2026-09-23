using System;
using System.Collections.Generic;

namespace TaleWorlds.Core { public enum MissionMode { Deployment, Battle, Stealth, CutScene, Conversation } public enum AgentControllerType { Player, AI } public enum FormationClass { Infantry, Ranged, Cavalry } }
namespace TaleWorlds.Library { public static class InformationManager { public static bool Inquiry; public static bool IsAnyInquiryActive() => Inquiry; } }
namespace TaleWorlds.CampaignSystem {
 public class Campaign { public static Campaign Current = new(); }
 public class MapEvent { public object MapEventSettlement; public bool IsNavalMapEvent; public bool IsSiegeAssault; }
 namespace Encounters { public class PlayerEncounter {} }
 namespace Party { public class MobileParty { public static MobileParty MainParty = new(); public MapEvent MapEvent = new(); } }
}
namespace TaleWorlds.MountAndBlade {
 using TaleWorlds.Core;
 public abstract class MissionBehavior {
  public Mission Mission { get; set; }
  public virtual void OnMissionTick(float dt) {} public virtual void OnAfterDeploymentFinished() {} protected virtual void OnEndMission() {}
  public virtual void OnMissionModeChange(MissionMode oldMissionMode, bool atStart) {}
 }
 public abstract class MissionLogic : MissionBehavior {}
 public class CommonAIComponent { public int InitializeCalls; public void Initialize() { InitializeCalls++; } }
 public class HumanAIComponent { public int InitializeCalls, SyncCalls; public void Initialize() { InitializeCalls++; } public void SyncBehaviorParamsIfNecessary() { SyncCalls++; } }
 public class RidingOrder { public enum RidingOrderEnum { Free, Mount, Dismount } public RidingOrderEnum OrderEnum = RidingOrderEnum.Mount; }
 public class Agent {
  public enum AIStateFlag { None, Alarmed }
  public AgentControllerType Controller = AgentControllerType.Player; public bool Active = true; public int AlarmCalls, UnpauseCalls, ResetCalls;
  public int StopUsingCalls, DisableScriptedCalls, RidingOrderCalls, SpeedResetCalls;
  public bool IsUsingGameObject = true; public AIStateFlag AIStateFlags = AIStateFlag.None;
  public CommonAIComponent CommonAIComponent = new(); public HumanAIComponent HumanAIComponent = new();
  public Formation Formation; public Agent MountAgent; public bool IsRangedCached; public RidingOrder.RidingOrderEnum LastRidingOrder; public bool IsActive() => Active;
  public bool ThrowOnAlarm; public void SetAlarmState(AIStateFlag value) { AlarmCalls++; if (ThrowOnAlarm) throw new NullReferenceException("тест: движок бросил в бою"); } public void SetIsAIPaused(bool value) { if (!value) UnpauseCalls++; }
  public void ResetEnemyCaches() { ResetCalls++; } public void HandleStopUsingAction() { StopUsingCalls++; IsUsingGameObject = false; }
  public void DisableScriptedMovement() { DisableScriptedCalls++; } public void SetRidingOrder(RidingOrder.RidingOrderEnum value) { RidingOrderCalls++; LastRidingOrder=value; }
  public void SetMaximumSpeedLimit(float value, bool isMultiplier) { SpeedResetCalls++; }
 }
 public struct MovementOrder { public int Kind; public int OrderEnum => Kind; public static MovementOrder MovementOrderCharge => new MovementOrder {Kind=1}; }
 public struct FiringOrder { public int Kind; public int OrderEnum => Kind; public static FiringOrder FiringOrderFireAtWill => new FiringOrder {Kind=1}; }
 public class Formation { public int CountOfUnits=5; public FormationClass FormationIndex; public MovementOrder Move; public FiringOrder FiringOrder; public ref readonly MovementOrder GetReadonlyMovementOrderReference()=>ref Move; public void SetMovementOrder(MovementOrder m){Move=m;} public void SetFiringOrder(FiringOrder f){FiringOrder=f;} public bool IsAIControlled; public int ChangedCalls; public RidingOrder RidingOrder = new(); public void SetControlledByAI(bool value, bool enforceNotSplittableByAI = false) { IsAIControlled = value; } public void OnUnitAddedOrRemoved() { ChangedCalls++; } }
 public class TeamAIComponent {}
 public class Team {
  public TeamAIComponent TeamAI = new(); public List<Formation> FormationsIncludingEmpty = new();
  public Formation GetFormation(FormationClass index) => FormationsIncludingEmpty.Find(f=>f.FormationIndex==index);
  public void DelegateCommandToAI() { foreach (var f in FormationsIncludingEmpty) f.SetControlledByAI(true); }
 }
 public class DeploymentMissionController : MissionBehavior {
  public bool TeamSetupOver; public int FinishCalls;
  public void FinishDeployment() { FinishCalls++; Mission.DeploymentSteps.Add("finish"); Mission.IsDeploymentFinished = true; Mission.Mode = MissionMode.Battle; Mission.Behaviors.RemoveAll(b=>b is DeploymentMissionController); }
 }
 public class BattleDeploymentMissionController : DeploymentMissionController {}
 public class SiegeDeploymentMissionController : DeploymentMissionController {}
 public class AssignPlayerRoleInTeamMissionController { public Mission Mission; public void OnPlayerTeamDeployed() { Mission.DeploymentSteps.Add("role"); } }
 public class Mission {
  public List<MissionBehavior> Behaviors=new();
  public bool CameraIsFirstPerson; public bool MissionEnded; public int ExitCalls; public MissionResult MissionResult; public BattleEndLogic EndLogic;
  public MissionMode Mode = MissionMode.Deployment; public bool IsDeploymentFinished; public bool IsFriendlyMission; public Team PlayerTeam = new(); public Agent MainAgent = new();
  public List<string> DeploymentSteps = new();
  public DeploymentMissionController Deployment;
  public Missions.Handlers.SiegeDeploymentHandler SiegeHandler;
  public AssignPlayerRoleInTeamMissionController RoleController;
  public T GetMissionBehavior<T>() where T:class => (Deployment as T) ?? (EndLogic as T) ?? (SiegeHandler as T) ?? (RoleController as T);
 }
 public class MissionResult { public bool BattleResolved; }
 public class BattleEndLogic { public enum ExitResult { True, False, NeedsPlayerConfirmation } public Mission Mission; public bool AllowExit = true; public int Calls; public ExitResult TryExit() { Calls++; if (!AllowExit) return ExitResult.False; Mission.ExitCalls++; return ExitResult.True; } }
}
namespace TaleWorlds.MountAndBlade.Missions.Handlers {
 public class SiegeDeploymentHandler {
  public TaleWorlds.MountAndBlade.Mission Mission; public bool ThrowOnDeploy;
  public void AutoDeployTeamUsingTeamAI(TaleWorlds.MountAndBlade.Team team, bool autoAssignDetachments = true) { Mission.DeploymentSteps.Add("deploy"); if(ThrowOnDeploy) throw new Exception("deployment failed"); if(autoAssignDetachments) AutoAssignDetachmentsForDeployment(team); }
  public void AutoAssignDetachmentsForDeployment(TaleWorlds.MountAndBlade.Team team) { Mission.DeploymentSteps.Add("detachments"); }
 }
}
namespace BannerlordAutopilot {
 using TaleWorlds.CampaignSystem.Party;
 internal sealed class AutopilotBehavior {
  internal enum Mode { Off, Apply } internal static AutopilotBehavior Instance = new(); internal Mode CurrentMode = Mode.Apply;
  internal static bool IsSupportedFieldBattleEncounter(MobileParty party) => true;
  internal bool IsOwnedOperationBattle(MobileParty party) => false;
  internal bool IsOwnedHideoutBattle {get;set;}
  internal void OnOperationMissionEnded() {}
  internal void Disable(string reason){CurrentMode=Mode.Off;}
 }
 internal static class AutopilotLog { internal static readonly List<string> Lines = new(); internal static void Write(string text) => Lines.Add(text); }
}
