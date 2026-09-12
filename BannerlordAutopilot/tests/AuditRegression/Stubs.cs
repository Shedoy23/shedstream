// Минимальные заменители движка Bannerlord для регрессии по независимой проверке.
// Основа — стенд проверяющего (dist/audit/autopilot-review/harness/Stubs.cs),
// дополнен тем, чем пользуется исправленный мод: настоящий выход из поселения
// (LeaveSettlement/Finish/GatePosition), признаки встречи с партией и боя.
//
// Имена типов совпадают с настоящей DLL (IMapPoint, CampaignVec2), потому что
// контракт мода теперь сверяет типы полей, а не только их наличие.
using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem.Map;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
namespace TaleWorlds.Core { public class Stub {} }
namespace TaleWorlds.Library { public class Stub {} }
namespace TaleWorlds.CampaignSystem.Map { public interface IMapPoint {} }
namespace TaleWorlds.CampaignSystem {
 public enum AiBehavior { None, Hold, GoToSettlement, PatrolAroundPoint, EscortParty, BesiegeSettlement }
 public struct CampaignVec2 { public float X; public override string ToString()=>X.ToString(); }
 public struct AIBehaviorData {
  public AiBehavior AiBehavior; public IMapPoint Party; public CampaignVec2 Position;
  public MobileParty.NavigationType NavigationType; public bool IsFromPort, IsTargetingPort, WillGatherArmy;
  public static AIBehaviorData Invalid => default;
 }
 public class PartyThinkParams {
  public List<(AIBehaviorData,float)> AIBehaviorScores {get;} = new();
  public void Reset(MobileParty p) { AIBehaviorScores.Clear(); }
 }
 public class MapEvent {}
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
 public class Settlement : IMapPoint {
  public string Name="Town"; public bool IsUnderSiege; public CampaignVec2 GatePosition = new CampaignVec2{X=42};
  public override string ToString()=>Name;
 }
}
namespace TaleWorlds.CampaignSystem.Party {
 public class MobilePartyAi {
  public bool IsDisabled {get;set;} public bool DoNotMakeNewDecisions {get;set;}
  public bool RethinkAtNextHourlyTick {get;set;}
  public void SetDoNotMakeNewDecisions(bool v) {DoNotMakeNewDecisions=v;}
  public void EnableAi() {}
 }
 public class MobileParty : IMapPoint {
  public enum NavigationType { None, Default }
  public static MobileParty MainParty = new();
  public bool IsActive=true, IsMoving; public MapEvent MapEvent; public object Army,SiegeEvent;
  public Settlement CurrentSettlement, BesiegedSettlement, LastVisitedSettlement, TargetSettlement;
  public MobilePartyAi Ai=new(); public AiBehavior DefaultBehavior=AiBehavior.GoToSettlement;
  public CampaignVec2 Position; public string Name="Player";
  public PartyThinkParams ThinkParamsCache {get;} = new();
  public int HoldCalls;
  public void SetMoveModeHold() {HoldCalls++; DefaultBehavior=AiBehavior.Hold;TargetSettlement=null;}
 }
}
namespace TaleWorlds.CampaignSystem.Encounters {
 public class PlayerEncounter {
  public static PlayerEncounter Current; public static Settlement EncounterSettlement;
  public static MobileParty EncounteredMobileParty; public static MapEvent Battle;
  public static bool LeaveEncounter {get;set;}
  public static int LeaveSettlementCalls, FinishCalls;
  // Эффекты — те, что наблюдаются в движке: вывод из поселения и закрытие встречи.
  public static void LeaveSettlement() { LeaveSettlementCalls++; MobileParty.MainParty.CurrentSettlement = null; }
  public static void Finish(bool forcePlayerOutFromSettlement = true) {
   FinishCalls++; Current = null; EncounterSettlement = null; EncounteredMobileParty = null; Battle = null;
   if (forcePlayerOutFromSettlement) MobileParty.MainParty.CurrentSettlement = null;
  }
 }
}
namespace TaleWorlds.CampaignSystem.Actions {
 public static class LeaveSettlementAction {
  public static void ApplyForParty(MobileParty p) {p.CurrentSettlement=null;}
 }
 public static class SetPartyAiAction {
  public static void GetActionForVisitingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.GoToSettlement;p.TargetSettlement=s;}
  public static void GetActionForPatrollingAroundSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.PatrolAroundPoint;p.TargetSettlement=s;}
  public static void GetActionForPatrollingAroundPoint(MobileParty p, CampaignVec2 s, MobileParty.NavigationType n, bool f) {p.DefaultBehavior=AiBehavior.PatrolAroundPoint;}
  public static void GetActionForEscortingParty(MobileParty p, MobileParty s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.EscortParty;}
 }
}
namespace BannerlordAutopilot {
 internal static class AutopilotLog {
  internal static List<string> Lines=new(); internal static string Path=>"in-memory";
  internal static void Write(string s) {Lines.Add(s);} internal static void Session(string s) {Lines.Add(s);}
 }
}
