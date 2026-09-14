using System;
using System.Collections.Generic;

namespace TaleWorlds.Core { public enum MissionMode { Deployment, Battle } public enum AgentControllerType { Player, AI } }
namespace TaleWorlds.CampaignSystem {
 public class Campaign { public static Campaign Current = new(); }
 public class MapEvent { public object MapEventSettlement; public bool IsNavalMapEvent; }
 namespace Encounters { public class PlayerEncounter {} }
 namespace Party { public class MobileParty { public static MobileParty MainParty = new(); public MapEvent MapEvent = new(); } }
}
namespace TaleWorlds.MountAndBlade {
 using TaleWorlds.Core;
 public abstract class MissionBehavior {
  public Mission Mission { get; set; }
  public virtual void OnMissionTick(float dt) {} public virtual void OnAfterDeploymentFinished() {} protected virtual void OnEndMission() {}
 }
 public abstract class MissionLogic : MissionBehavior {}
 public class HumanAIComponent { public int SyncCalls; public void SyncBehaviorParamsIfNecessary() { SyncCalls++; } }
 public class Agent {
  public enum AIStateFlag { Alarmed }
  public AgentControllerType Controller = AgentControllerType.Player; public bool Active = true; public int AlarmCalls, UnpauseCalls, ResetCalls;
  public HumanAIComponent HumanAIComponent = new(); public bool IsActive() => Active;
  public void SetAlarmState(AIStateFlag value) { AlarmCalls++; } public void SetIsAIPaused(bool value) { if (!value) UnpauseCalls++; }
  public void ResetEnemyCaches() { ResetCalls++; }
 }
 public class Formation { public bool IsAIControlled; public void SetControlledByAI(bool value, bool enforceNotSplittableByAI = false) { IsAIControlled = value; } }
 public class TeamAIComponent {}
 public class Team {
  public TeamAIComponent TeamAI = new(); public List<Formation> FormationsIncludingEmpty = new();
  public void DelegateCommandToAI() { foreach (var f in FormationsIncludingEmpty) f.SetControlledByAI(true); }
 }
 public class BattleDeploymentMissionController : MissionBehavior {
  public bool TeamSetupOver; public int FinishCalls;
  public void FinishDeployment() { FinishCalls++; Mission.IsDeploymentFinished = true; Mission.Mode = MissionMode.Battle; }
 }
 public class Mission {
  public MissionMode Mode = MissionMode.Deployment; public bool IsDeploymentFinished; public Team PlayerTeam = new(); public Agent MainAgent = new();
  public BattleDeploymentMissionController Deployment;
  public T GetMissionBehavior<T>() where T:class => Deployment as T;
 }
}
namespace BannerlordAutopilot {
 using TaleWorlds.CampaignSystem.Party;
 internal sealed class AutopilotBehavior {
  internal enum Mode { Off, Apply } internal static AutopilotBehavior Instance = new(); internal Mode CurrentMode = Mode.Apply;
  internal static bool IsSupportedFieldBattleEncounter(MobileParty party) => true;
 }
 internal static class AutopilotLog { internal static readonly List<string> Lines = new(); internal static void Write(string text) => Lines.Add(text); }
}
