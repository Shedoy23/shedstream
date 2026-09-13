// Минимальные заменители движка Bannerlord для регрессии по независимой проверке.
// Основа — стенд проверяющего (dist/audit/autopilot-review/harness/Stubs.cs),
// дополнен тем, чем пользуется исправленный мод: настоящий выход из поселения
// (LeaveSettlement/Finish/GatePosition), признаки встречи с партией и боя,
// меню поселения с ожиданием (PlayerTownVisitCampaignBehavior, 1.4.8) и ход
// времени кампании для сторожа простоя.
//
// Имена типов совпадают с настоящей DLL (IMapPoint, CampaignVec2, MenuContext,
// GameMenu), потому что контракт мода сверяет типы полей, а не только их наличие.
using System;
using System.Collections.Generic;
using TaleWorlds.CampaignSystem.Conversation;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Map;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
namespace TaleWorlds.Core {
 public class Stub {}
 public class GameState {}
 public class GameStateManager { public GameState ActiveState { get; set; } = new MapState(); public bool ActiveStateDisabledByUser { get; set; } }
 public class Game { public static Game Current = new(); public GameStateManager GameStateManager { get; } = new(); }
}
namespace TaleWorlds.Library { public class Stub {} }
namespace TaleWorlds.CampaignSystem.Map { public interface IMapPoint {} }
namespace TaleWorlds.CampaignSystem.Conversation { public class ConversationManager { public bool IsConversationInProgress { get; set; } } }
namespace TaleWorlds.CampaignSystem.GameMenus {
 public class GameMenuOption {
  public string IdString { get; set; } public bool IsEnabled { get; set; } = true; public bool IsLeave { get; set; }
  public object Tooltip { get; set; }
  public Func<bool> Condition = () => true; public Action Consequence;
 }
 public class GameMenu {
  public string StringId { get; set; } public bool IsWaitMenu { get; set; } public bool IsWaitActive { get; set; }
  public readonly List<GameMenuOption> Options = new();
  public IEnumerable<GameMenuOption> MenuOptions => Options;
  public List<object> MenuRepeatObjects { get; } = new();
  public bool GetMenuOptionConditionsHold(TaleWorlds.Core.Game game, MenuContext menuContext, int menuItemNumber) => Options[menuItemNumber].Condition();
  public GameMenuOption GetGameMenuOption(int menuItemNumber) => Options[menuItemNumber];
 }
}
namespace TaleWorlds.CampaignSystem.GameState {
 public class MapState : TaleWorlds.Core.GameState {}
 public class MenuContext {
  public static List<string> Invoked = new();
  public GameMenu GameMenu { get; set; }
  // Как кнопка: пункт по индексу, его последствие. Индексы без повторяемых объектов.
  public void InvokeConsequence(int index) { var o = GameMenu.GetGameMenuOption(index); Invoked.Add(o.IdString); o.Consequence?.Invoke(); }
 }
}
namespace TaleWorlds.CampaignSystem {
 public enum AiBehavior { None, Hold, GoToSettlement, PatrolAroundPoint, EscortParty, BesiegeSettlement }
 public struct CampaignVec2 { public float X; public override string ToString()=>X.ToString(); }
 public struct CampaignTime { public static double TestHours; private double _h; public static CampaignTime Now => new CampaignTime { _h = TestHours }; public double ToHours => _h; }
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
 public enum CampaignTimeControlMode { Stop, UnstoppablePlay, UnstoppableFastForward, StoppablePlay, StoppableFastForward, UnstoppableFastForwardForPartyWaitTime, FastForwardStop }
 public class Campaign {
  public static Campaign Current = new();
  private CampaignTimeControlMode _mode = CampaignTimeControlMode.Stop;
  // Как в движке: при блокировке запись молча игнорируется.
  public CampaignTimeControlMode TimeControlMode { get => _mode; set { if (!TimeControlModeLock) _mode = value; } }
  public bool TimeControlModeLock { get; set; }
  // ComputeIsWaiting в движке: Hold или партия уже у цели.
  public bool IsMainPartyWaiting => MobileParty.MainParty.DefaultBehavior == AiBehavior.Hold || !MobileParty.MainParty.IsMoving;
  public MenuContext CurrentMenuContext { get; set; }
  public ConversationManager ConversationManager { get; } = new();
  public void SetTimeSpeed(int speed) {
   bool stopped = TimeControlMode == CampaignTimeControlMode.Stop || TimeControlMode == CampaignTimeControlMode.FastForwardStop;
   bool hold = MobileParty.MainParty.DefaultBehavior == AiBehavior.Hold;
   if (speed == 0) TimeControlMode = CampaignTimeControlMode.Stop;
   else if (speed == 1) TimeControlMode = stopped && hold ? CampaignTimeControlMode.UnstoppablePlay : CampaignTimeControlMode.StoppablePlay;
   else if (speed == 2) TimeControlMode = stopped && hold ? CampaignTimeControlMode.UnstoppableFastForward : CampaignTimeControlMode.StoppableFastForward;
  }
 }
 public class Hero { public static Hero MainHero = new(); public bool IsPrisoner; public bool IsWounded; }
 public interface IDataStore { void SyncData(string key, ref bool value); }
 public abstract class CampaignBehaviorBase { public abstract void RegisterEvents(); public abstract void SyncData(IDataStore data); }
 public class Event { public void AddNonSerializedListener(object owner, Action a) {} }
 public static class CampaignEvents { public static Event HourlyTickEvent=new(), OnGameLoadFinishedEvent=new(); }
 public class CampaignEventDispatcher {
  public static CampaignEventDispatcher Instance {get;} = new();
  public static List<(AIBehaviorData,float)> NextScores = new();
  public void AiHourlyTick(MobileParty p, PartyThinkParams t) { t.AIBehaviorScores.AddRange(NextScores); }
 }
}
namespace TaleWorlds.CampaignSystem.Settlements {
 public class Settlement : IMapPoint {
  public string Name="Town"; public bool IsUnderSiege; public CampaignVec2 GatePosition = new CampaignVec2{X=42};
  public bool IsVillage { get; set; }
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
  public int HoldCalls; public bool StandsAtLastVisited;
  public void SetMoveModeHold() {HoldCalls++; DefaultBehavior=AiBehavior.Hold;TargetSettlement=null;IsMoving=false;}
 }
}
namespace TaleWorlds.CampaignSystem.Encounters {
 public class PlayerEncounter {
  public static PlayerEncounter Current; public static Settlement EncounterSettlement;
  public static MobileParty EncounteredMobileParty; public static MapEvent Battle;
  public static bool LeaveEncounter {get;set;}
  public static int LeaveSettlementCalls, FinishCalls;
  public bool IsPlayerWaiting { get; set; }
  // Эффекты — те, что наблюдаются в движке: вывод из поселения и закрытие встречи
  // (Finish делает GameMenu.ExitToLast — меню закрывается).
  public static void LeaveSettlement() { LeaveSettlementCalls++; MobileParty.MainParty.CurrentSettlement = null; }
  public static void Finish(bool forcePlayerOutFromSettlement = true) {
   FinishCalls++; Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop; Current = null; EncounterSettlement = null; EncounteredMobileParty = null; Battle = null;
   Campaign.Current.CurrentMenuContext = null;
   if (forcePlayerOutFromSettlement) MobileParty.MainParty.CurrentSettlement = null;
  }
 }
}
namespace TaleWorlds.CampaignSystem.Actions {
 public static class LeaveSettlementAction {
  public static void ApplyForParty(MobileParty p) {p.CurrentSettlement=null;}
 }
 public static class SetPartyAiAction {
  public static int VisitCalls;
  public static void GetActionForVisitingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {VisitCalls++;p.DefaultBehavior=AiBehavior.GoToSettlement;p.TargetSettlement=s;p.IsMoving=true;}
  public static void GetActionForPatrollingAroundSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.PatrolAroundPoint;p.TargetSettlement=s;p.IsMoving=true;}
  public static void GetActionForPatrollingAroundPoint(MobileParty p, CampaignVec2 s, MobileParty.NavigationType n, bool f) {p.DefaultBehavior=AiBehavior.PatrolAroundPoint;p.IsMoving=true;}
  public static void GetActionForEscortingParty(MobileParty p, MobileParty s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.EscortParty;p.IsMoving=true;}
 }
}
namespace Helpers {
 public static class MobilePartyHelper {
  public static Settlement GetCurrentSettlementOfMobilePartyForAICalculation(MobileParty p) =>
   p.CurrentSettlement ?? (p.LastVisitedSettlement != null && p.StandsAtLastVisited ? p.LastVisitedSettlement : null);
 }
}
namespace BannerlordAutopilot {
 internal static class AutopilotLog {
  internal static List<string> Lines=new(); internal static string Path=>"in-memory";
  internal static void Write(string s) {Lines.Add(s);} internal static void Session(string s) {Lines.Add(s);}
 }
}
