using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
namespace TaleWorlds.Core { public class Stub {} }
namespace TaleWorlds.Library { public class Stub {} }
namespace TaleWorlds.CampaignSystem {
 public enum AiBehavior { None, Hold, GoToSettlement, PatrolAroundPoint, EscortParty, BesiegeSettlement }
 public struct Position { public float X; public override string ToString()=>X.ToString(); }
 public struct AIBehaviorData {
  public AiBehavior AiBehavior; public int Party; public Position Position;
  public MobileParty.NavigationType NavigationType; public bool IsFromPort, IsTargetingPort, WillGatherArmy;
  public static AIBehaviorData Invalid => default;
 }
 public class PartyThinkParams {
  public string AIBehaviorScores {get;} = "wrong type";
  public void Reset(MobileParty p) {  }
 }
 public class Campaign { public static Campaign Current = new(); }
 public class Hero { public static Hero MainHero = new(); public bool IsPrisoner; }
 public interface IDataStore { void SyncData(string key, ref bool value); }
 public abstract class CampaignBehaviorBase { public abstract void RegisterEvents(); public abstract void SyncData(IDataStore data); }
 public class Event { public void AddNonSerializedListener(object owner, Action a) {} }
 public static class CampaignEvents { public static Event HourlyTickEvent=new(), OnGameLoadFinishedEvent=new(); }
 public class CampaignEventDispatcher {
  public static CampaignEventDispatcher Instance {get;} = new();
  public void AiHourlyTick(MobileParty p, PartyThinkParams t) {}
 }
}
namespace TaleWorlds.CampaignSystem.Settlements {
 public class Settlement { public string Name="Town"; public override string ToString()=>Name; }
}
namespace TaleWorlds.CampaignSystem.Party {
 public class MobilePartyAi {
  public bool IsDisabled {get;set;} public bool DoNotMakeNewDecisions {get;set;}
  public bool RethinkAtNextHourlyTick {get;}
  public void SetDoNotMakeNewDecisions(bool v) {DoNotMakeNewDecisions=v;}
  public void EnableAi() {}
 }
 public class MobileParty {
  public enum NavigationType { None, Default }
  public static MobileParty MainParty = new();
  public bool IsActive=true, IsMoving; public object MapEvent,Army,SiegeEvent;
  public Settlement CurrentSettlement, BesiegedSettlement, LastVisitedSettlement, TargetSettlement;
  public MobilePartyAi Ai=new(); public AiBehavior DefaultBehavior=AiBehavior.GoToSettlement;
  public Position Position; public string Name="Player";
  public PartyThinkParams ThinkParamsCache {get;} = new();
  public int HoldCalls;
  public void SetMoveModeHold() {HoldCalls++; DefaultBehavior=AiBehavior.Hold;TargetSettlement=null;}
 }
}
namespace TaleWorlds.CampaignSystem.Encounters {
 public class PlayerEncounter {
  public static PlayerEncounter Current; public static Settlement EncounterSettlement;
  public static bool LeaveEncounter {get;set;}
 }
}
namespace TaleWorlds.CampaignSystem.Actions {
 public static class LeaveSettlementAction {
  public static void ApplyForParty(MobileParty p) {p.CurrentSettlement=null;}
 }
 public static class SetPartyAiAction {
  public static void GetActionForVisitingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.GoToSettlement;p.TargetSettlement=s;}
  public static void GetActionForPatrollingAroundSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.PatrolAroundPoint;p.TargetSettlement=s;}
  public static void RemovedPatrollingAroundPoint(MobileParty p, Position s, MobileParty.NavigationType n, bool f) {p.DefaultBehavior=AiBehavior.PatrolAroundPoint;}
  public static void GetActionForEscortingParty(MobileParty p, MobileParty s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.EscortParty;}
 }
}
namespace BannerlordAutopilot {
 internal static class AutopilotLog {
  internal static List<string> Lines=new(); internal static string Path=>"in-memory";
  internal static void Write(string s) {Lines.Add(s);} internal static void Session(string s) {Lines.Add(s);}
 }
}

