// Минимальные заменители движка Bannerlord для регрессии по независимой проверке.
// Основа — стенд проверяющего (dist/audit/autopilot-review/harness/Stubs.cs),
// дополнен тем, чем пользуется исправленный мод: настоящий выход из поселения
// (LeaveSettlement/Finish/GatePosition), признаки встречи с партией и боя,
// меню поселения с ожиданием (PlayerTownVisitCampaignBehavior, 1.4.8) и ход
// времени кампании для сторожа простоя. Типы обслуживания в поселении (еда, найм,
// пленные) — в ServicesStubs.cs.
//
// Имена типов совпадают с настоящей DLL (IMapPoint, CampaignVec2, MenuContext,
// GameMenu), потому что контракт мода сверяет типы полей, а не только их наличие.
using System;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CampaignBehaviors;
using TaleWorlds.CampaignSystem.ComponentInterfaces;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.Library;
using TaleWorlds.CampaignSystem.Conversation;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Map;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
namespace TaleWorlds.Core {
 public class Stub {}
 public class GameState {}
 // В игре у карты всегда есть экран: MapState.Handler — это MapScreen (CampaignSystem 155552).
 public class GameStateManager { public GameState ActiveState { get; set; } = new MapState { Handler = new SandBox.View.Map.MapScreen() }; public bool ActiveStateDisabledByUser { get; set; } public int PopCalls; public void PopState(int mode) { PopCalls++; ActiveState = new MapState { Handler = new SandBox.View.Map.MapScreen() }; } }
 public class Game { public static Game Current = new(); public GameStateManager GameStateManager { get; } = new(); }
}
namespace TaleWorlds.Library {
 public struct Vec2 {}
 public class Stub {}
 public class MBReadOnlyList<T> : List<T> {}
 public class MBList<T> : MBReadOnlyList<T> {}
 // Открыто ли окно-запрос (GauntletQueryManager._activeDataSource != null).
 public class InquiryData { public string TitleText; public bool IsAffirmativeOptionShown; public Action AffirmativeAction; }
 public static class InformationManager { public static event Action<InquiryData,bool,bool> OnShowInquiry; public static void ShowInquiry(InquiryData data,bool pause=false,bool prioritize=false){TestInquiryActive=true;OnShowInquiry?.Invoke(data,pause,prioritize);} public static bool TestInquiryActive; public static bool IsAnyInquiryActive() => TestInquiryActive; public static void HideInquiry() { TestInquiryActive=false; } }
}
namespace TaleWorlds.Localization { public class TextObject { public string Value; public TextObject(string text) { Value = text; } public override string ToString() => Value; } }
namespace TaleWorlds.CampaignSystem.Incidents {
 public class Incident {
  public string StringId {get;set;} public TaleWorlds.Localization.TextObject Title {get;set;} = new("");
  public readonly List<(TaleWorlds.Localization.TextObject Text,List<TaleWorlds.Localization.TextObject> Hints,Action Consequence)> Options = new();
  public int NumOfOptions => Options.Count;
  public TaleWorlds.Localization.TextObject GetOptionText(int i)=>Options[i].Text;
  public List<TaleWorlds.Localization.TextObject> GetOptionHint(int i)=>Options[i].Hints;
  public List<TaleWorlds.Localization.TextObject> InvokeOption(int i){Options[i].Consequence?.Invoke();return Options[i].Hints;}
 }
}
namespace TaleWorlds.CampaignSystem.Map { public interface IMapPoint {} }
namespace TaleWorlds.MountAndBlade {
 public class RidingOrder { public enum RidingOrderEnum { Mount, Dismount } }
 public class Agent { public void SetRidingOrder(RidingOrder.RidingOrderEnum order) {} }
 public class MissionResult { public bool BattleResolved {get;set;} }
 public class Mission { public bool MissionEnded {get;set;} public MissionResult MissionResult {get;set;} }
 public class BattleEndLogic { public enum ExitResult { True, False } public ExitResult TryExit() => ExitResult.True; }
}
namespace TaleWorlds.CampaignSystem.Conversation {
 public struct ConversationSentenceOption { public string Id; public TaleWorlds.Localization.TextObject Text; public bool IsClickable; }
 public class ConversationManager { public bool IsConversationInProgress { get; set; } public MobileParty ConversationParty {get;set;} public List<ConversationSentenceOption> CurOptions {get;set;} = new(); public bool Ended; public int ContinueCalls; public List<string> Selected = new(); public bool IsConversationEnded() => Ended; public void DoOption(int index) { Selected.Add(CurOptions[index].Id); CurOptions.Clear(); Ended=true; } public void ContinueConversation() { ContinueCalls++; IsConversationInProgress=false; } }
}
namespace TaleWorlds.CampaignSystem.GameMenus {
 public class GameMenuOption {
  public string IdString { get; set; } public bool IsEnabled { get; set; } = true; public bool IsLeave { get; set; }
  public object Tooltip { get; set; }
  public Func<bool> Condition = () => true; public Action Consequence;
 }
 public class GameMenu {
  public void StartWait() {IsWaitActive=true;}
  public string StringId { get; set; } public bool IsWaitMenu { get; set; } public bool IsWaitActive { get; set; }
  public readonly List<GameMenuOption> Options = new();
  public IEnumerable<GameMenuOption> MenuOptions => Options;
  public List<object> MenuRepeatObjects { get; } = new();
  public bool GetMenuOptionConditionsHold(TaleWorlds.Core.Game game, MenuContext menuContext, int menuItemNumber) => Options[menuItemNumber].Condition();
  public GameMenuOption GetGameMenuOption(int menuItemNumber) => Options[menuItemNumber];
 }
}
namespace TaleWorlds.CampaignSystem.GameState {
 public class KingdomState : TaleWorlds.Core.GameState {}
 public interface IMapStateHandler {}
 // NextIncident — очередь выпавшего события: движок кладёт его сюда на входе в
 // поселение (IncidentsCampaignBehaviour.InvokeIncident, 190449-190456) и
 // проверяет условия на следующем Campaign.Tick (10136-10143).
 public class MapState : TaleWorlds.Core.GameState { public IMapStateHandler Handler { get; set; } public TaleWorlds.CampaignSystem.Incidents.Incident NextIncident { get; set; } }
 public class MenuContext {
  public IMenuContextHandler Handler { get; set; }
  public static List<string> Invoked = new();
  public GameMenu GameMenu { get; set; }
  // Как кнопка: пункт по индексу, его последствие. Индексы без повторяемых объектов.
  public void InvokeConsequence(int index) { var o = GameMenu.GetGameMenuOption(index); Invoked.Add(o.IdString); o.Consequence?.Invoke(); }
 }
}
namespace TaleWorlds.CampaignSystem {
 public enum AiBehavior { None, Hold, GoToSettlement, PatrolAroundPoint, EscortParty, GoAroundParty, EngageParty, FleeToPoint, BesiegeSettlement, DefendSettlement, RaidSettlement }
 public struct CampaignVec2 { public float X; public float DistanceSquared(CampaignVec2 p) => (X-p.X)*(X-p.X); public override string ToString()=>X.ToString(); }
 public struct CampaignTime { public static double TestHours; private double _h; public static CampaignTime Now => new CampaignTime { _h = TestHours }; public double ToHours => _h; public bool IsPast => _h < TestHours; public bool IsNightTime => TestHours % 24 < 6 || TestHours % 24 >= 21; }
 public struct AIBehaviorData {
  public AIBehaviorData(IMapPoint party, AiBehavior behavior, MobileParty.NavigationType navigation, bool gather, bool fromPort, bool targetingPort) { Party=party; AiBehavior=behavior; NavigationType=navigation; WillGatherArmy=gather; IsFromPort=fromPort; IsTargetingPort=targetingPort; Position=default; }
  public AiBehavior AiBehavior; public IMapPoint Party; public CampaignVec2 Position;
  public MobileParty.NavigationType NavigationType; public bool IsFromPort, IsTargetingPort, WillGatherArmy;
  public static AIBehaviorData Invalid => default;
 }
 public class PartyThinkParams {
  public TaleWorlds.Library.MBReadOnlyList<MobileParty> PossibleArmyMembersUponArmyCreation { get; } = new();
  public List<(AIBehaviorData,float)> AIBehaviorScores {get;} = new();
  public void Reset(MobileParty p) { AIBehaviorScores.Clear(); }
 }
 public partial class MapEventSide { public PartyBase LeaderParty { get; set; } }
 public partial class MapEvent { public MapEventSide AttackerSide { get; set; } = new(); public MapEventSide DefenderSide { get; set; } = new(); public Settlement MapEventSettlement { get; set; } public bool IsNavalMapEvent { get; set; } public bool IsHideoutBattle { get; set; } public bool IsSiegeAssault { get; set; } public TaleWorlds.Core.BattleSideEnum PlayerSide { get; set; } }
 public enum CampaignTimeControlMode { Stop, UnstoppablePlay, UnstoppableFastForward, StoppablePlay, StoppableFastForward, UnstoppableFastForwardForPartyWaitTime, FastForwardStop }
 public enum ConversationContext { Default, CapturedLord, FreeOrCapturePrisonerHero, PartyEncounter, BarterResult }
 public class Campaign {
  public static Campaign Current = new();
  public ConversationContext CurrentConversationContext;
  private CampaignTimeControlMode _mode = CampaignTimeControlMode.Stop;
  // Как в движке: при блокировке запись молча игнорируется.
  public CampaignTimeControlMode TimeControlMode { get => _mode; set { if (!TimeControlModeLock) _mode = value; } }
  public bool TimeControlModeLock { get; set; }
  // ComputeIsWaiting в движке: Hold или партия уже у цели.
  public bool IsMainPartyWaiting => MobileParty.MainParty.DefaultBehavior == AiBehavior.Hold || !MobileParty.MainParty.IsMoving;
  public MenuContext CurrentMenuContext { get; set; }
  public ConversationManager ConversationManager { get; } = new();
  public GameModels Models { get; } = new();
  public readonly List<object> Behaviors = new() { new PartiesBuyFoodCampaignBehavior() };
  public T GetCampaignBehavior<T>() => Behaviors.OfType<T>().FirstOrDefault();
  public void SetTimeSpeed(int speed) {
   bool stopped = TimeControlMode == CampaignTimeControlMode.Stop || TimeControlMode == CampaignTimeControlMode.FastForwardStop;
   bool hold = MobileParty.MainParty.DefaultBehavior == AiBehavior.Hold;
   if (speed == 0) TimeControlMode = CampaignTimeControlMode.Stop;
   else if (speed == 1) TimeControlMode = stopped && hold ? CampaignTimeControlMode.UnstoppablePlay : CampaignTimeControlMode.StoppablePlay;
   else if (speed == 2) TimeControlMode = stopped && hold ? CampaignTimeControlMode.UnstoppableFastForward : CampaignTimeControlMode.StoppableFastForward;
  }
 }
 public class KingdomDecision { public bool Cancelled; public bool ShouldBeCancelled()=>Cancelled; }
 public partial class Kingdom : TestFaction { public List<KingdomDecision> UnresolvedDecisions { get; } = new(); public TaleWorlds.Localization.TextObject Name { get; set; } = new("Королевство"); }
 // Clan 31710-31714: Fiefs — города и замки клана, Villages — его деревни.
 public class Clan {
  public float Influence { get; set; }
  public static Clan PlayerClan = new(); public Kingdom Kingdom { get; set; } = new(); public IFaction MapFaction { get; set; }
  public TaleWorlds.Library.MBReadOnlyList<TaleWorlds.CampaignSystem.Settlements.Town> Fiefs { get; } = new();
  public TaleWorlds.Library.MBReadOnlyList<TaleWorlds.CampaignSystem.Settlements.Village> Villages { get; } = new();
 }
 public partial class Hero {
  public static Hero MainHero = new(); public bool IsPrisoner; public bool IsWounded;
  public string Name = "Hero"; public int Gold { get; set; }
  public bool IsAlive { get; set; } = true;
  public bool CanHaveRecruits { get; set; } = true;
  public CharacterObject[] VolunteerTypes = new CharacterObject[6];
  // Ответ DefaultVolunteerModel.MaximumIndexHeroCanRecruitFromHero(MainHero, этот староста):
  // до какого индекса игроку отдают добровольцев (отношения, фракция, перки).
  public int TestMaxRecruitIndex = 5;
  public override string ToString() => Name;
 }
 // Как настоящий IDataStore (CampaignSystem 11299): один обобщённый SyncData для любых типов.
 public interface IDataStore { bool IsSaving { get; } bool IsLoading { get; } bool SyncData<T>(string key, ref T data); }
 public abstract class CampaignBehaviorBase { public abstract void RegisterEvents(); public abstract void SyncData(IDataStore data); }
 public class Event { public void AddNonSerializedListener(object owner, Action a) {} }
 public static class CampaignEvents { public static Event HourlyTickEvent=new(), OnGameLoadFinishedEvent=new(); public static SessionEvent OnSessionLaunchedEvent = new(); }
 public partial class CampaignEventDispatcher {
  public static CampaignEventDispatcher Instance {get;} = new();
  public static List<(AIBehaviorData,float)> NextScores = new();
  // Что видел пересчёт AI в момент вызова — чтобы проверить, что обслуживание успело до него.
  public static int ThinkFood = -1, ThinkMembers = -1;
  public void AiHourlyTick(MobileParty p, PartyThinkParams t) { ThinkFood = p.TotalFoodAtInventory; ThinkMembers = p.MemberRoster.TotalManCount; t.AIBehaviorScores.AddRange(NextScores); }
  public static List<CharacterObject> Recruited = new();
  // Подписчик события найма (квест, чужой мод) бросает исключение — событие падает целиком.
  public static bool TestRecruitedThrows;
  public void OnUnitRecruited(CharacterObject character, int amount)
  {
   if (TestRecruitedThrows) throw new InvalidOperationException("подписчик события найма упал");
   for (int i = 0; i < amount; i++) Recruited.Add(character);
  }
 }
}
namespace TaleWorlds.CampaignSystem.Settlements {
 public class Hideout { public static List<Hideout> All { get; } = new(); public Settlement Settlement { get; set; } public bool IsSpotted { get; set; } public bool IsInfested { get; set; } public CampaignTime NextPossibleAttackTime { get; set; } }
 public class Town { public Settlement Settlement { get; set; } public MobileParty GarrisonParty { get; set; } public int GetItemPrice(TaleWorlds.Core.EquipmentElement element, MobileParty party = null, bool isSelling = false) => element.Item.TestPrice; }
 public class Village { public Settlement TradeBound { get; set; } public Settlement Bound { get; set; } }
 public class Settlement : IMapPoint {
  public static TaleWorlds.Library.MBReadOnlyList<Settlement> All { get; } = new();
  public bool IsHideout { get; set; } public bool IsVisible { get; set; } = true;
  public CampaignVec2 Position { get; set; } public Hideout Hideout { get; set; }
  public string Name="Town"; public bool IsUnderSiege; public CampaignVec2 GatePosition = new CampaignVec2{X=42};
  // MBObjectBase.StringId: у каждого поселения свой, из XML мира, и он же после загрузки сейва.
  static int _nextId;
  public string StringId { get; set; } = "settlement_" + (++_nextId);
  public bool IsVillage { get; set; }
  public bool IsTown { get; set; }
  public bool IsCastle { get; set; }
  public bool IsRaided { get; set; }
  public float Militia { get; set; }
  public bool IsUnderRaid { get; set; }
  public IFaction MapFaction { get; set; }
  public PartyBase Party { get; }
  public Village Village { get; }
  private readonly Town _town = new Town();
  public Town Town => IsVillage ? null : _town;
  public ItemRoster ItemRoster => Party.ItemRoster;       // рынок поселения (161206)
  public MBReadOnlyList<Hero> Notables { get; } = new();
  public int TestGold = 100000;
  public SettlementComponent SettlementComponent => new SettlementComponent(this);
  public Settlement() { Party = new PartyBase { Settlement = this }; Village = new Village { TradeBound = this, Bound = this }; }
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
 public partial class MobileParty : IMapPoint {
  public static TaleWorlds.Library.MBReadOnlyList<MobileParty> All { get; } = new();
  public bool IsVisible { get; set; } = true;
  public bool IsMilitia { get; set; }
  public bool IsCurrentlyAtSea { get; set; }
  public enum NavigationType { None, Default }
  public static MobileParty MainParty = new();
  public bool IsActive=true, IsMoving; public bool IsDisorganized; public bool IsBandit {get;set;} public bool IsCaravan {get;set;} public MapEvent MapEvent; public Army Army;
  public TaleWorlds.CampaignSystem.Siege.SiegeEvent SiegeEvent { get; set; }
  public Settlement CurrentSettlement, BesiegedSettlement, LastVisitedSettlement, TargetSettlement;
  public MobileParty TargetParty;
  public MobilePartyAi Ai=new(); public AiBehavior DefaultBehavior=AiBehavior.GoToSettlement;
  public CampaignVec2 Position; public string Name="Player";
  public float TotalWeightCarried;
  public int InventoryCapacity = 100;
  public PartyThinkParams ThinkParamsCache {get;} = new();
  public int HoldCalls; public bool StandsAtLastVisited;
  public void SetMoveModeHold() {HoldCalls++; DefaultBehavior=AiBehavior.Hold;TargetSettlement=null;IsMoving=false;}
  public PartyBase Party { get; }
  public MobileParty() { Party = new PartyBase { MobileParty = this }; }
  public Hero LeaderHero => this == MainParty ? Hero.MainHero : null;      // партия игрока: лидер — главный герой
  public IFaction MapFaction { get; set; }
  public TroopRoster MemberRoster => Party.MemberRoster;                   // 101058-101062
  public TroopRoster PrisonRoster => Party.PrisonRoster;
  public ItemRoster ItemRoster => Party.ItemRoster;
  public int TotalFoodAtInventory => ItemRoster.TotalFood;                // 101122
  public float FoodChange { get; set; } = -5f;                            // дневной расход, отрицательный
  public int TotalWage { get; set; } = 50;                                // дневное жалование
  public int PartyTradeGold => LeaderHero?.Gold ?? 0;                     // у партии лорда — золото лидера (100411)
 }
 // PartyBase (105803): ростеры партии или поселения.
 public partial class PartyBase {
  public float EstimatedStrength => MemberRoster.TotalManCount;
  public IFaction MapFaction { get; set; }
  public static PartyBase MainParty => MobileParty.MainParty?.Party;
  public TroopRoster MemberRoster { get; } = TroopRoster.CreateDummyTroopRoster();
  public TroopRoster PrisonRoster { get; } = TroopRoster.CreateDummyTroopRoster();
  public ItemRoster ItemRoster { get; } = new();
  public MobileParty MobileParty { get; set; }
  public Settlement Settlement { get; set; }
  public bool IsSettlement => Settlement != null;
  public bool IsMobile => MobileParty != null;
  public Hero LeaderHero => MobileParty?.LeaderHero;
  public int PartySizeLimit { get; set; } = 100;
  public int NumberOfAllMembers => MemberRoster.TotalManCount;            // 106163
 }
}
namespace TaleWorlds.CampaignSystem.Encounters {
 public class PlayerEncounter {
  public static PartyBase EncounteredParty => Current == null ? null : EncounteredMobileParty?.Party ?? EncounterSettlement?.Party;
  public bool Defender; public static bool PlayerIsDefender => Current.Defender;
  public static PlayerEncounter Current; public static Settlement EncounterSettlement;
  public static MobileParty EncounteredMobileParty; public static MapEvent Battle; private static MapEvent _encounteredBattle; public static MapEvent EncounteredBattle { get { if (Current == null) throw new NullReferenceException("EncounteredBattle requires Current"); return _encounteredBattle; } set { _encounteredBattle=value; } }
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
  public static void GetActionForDefendingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.DefendSettlement;p.TargetSettlement=s;p.IsMoving=true;}
  public static void GetActionForBesiegingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f) {p.DefaultBehavior=AiBehavior.BesiegeSettlement;p.TargetSettlement=s;p.IsMoving=true;}
  public static void GetActionForRaidingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.RaidSettlement;p.TargetSettlement=s;p.IsMoving=true;}
  public static int VisitCalls;
  public static int PatrolCalls;
  public static int EngageCalls;
  public static void GetActionForVisitingSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {VisitCalls++;p.DefaultBehavior=AiBehavior.GoToSettlement;p.TargetSettlement=s;p.IsMoving=true;}
  public static void GetActionForPatrollingAroundSettlement(MobileParty p, Settlement s, MobileParty.NavigationType n, bool f, bool t) {PatrolCalls++;p.DefaultBehavior=AiBehavior.PatrolAroundPoint;p.TargetSettlement=s;p.IsMoving=true;}
  public static void GetActionForPatrollingAroundPoint(MobileParty p, CampaignVec2 s, MobileParty.NavigationType n, bool f) {PatrolCalls++;p.DefaultBehavior=AiBehavior.PatrolAroundPoint;p.IsMoving=true;}
  public static void GetActionForGoingAroundParty(MobileParty p, MobileParty t, MobileParty.NavigationType n, bool f) {p.DefaultBehavior=AiBehavior.GoAroundParty;p.TargetParty=t;p.IsMoving=true;}
  public static void GetActionForEngagingParty(MobileParty p, MobileParty t, MobileParty.NavigationType n, bool f) {EngageCalls++;p.DefaultBehavior=AiBehavior.EngageParty;p.TargetParty=t;p.IsMoving=true;}
  public static void GetActionForEscortingParty(MobileParty p, MobileParty s, MobileParty.NavigationType n, bool f, bool t) {p.DefaultBehavior=AiBehavior.EscortParty;p.IsMoving=true;}
 }
}
namespace Helpers {
 // FactionHelper.GetEnemyKingdoms (4324): королевства из FactionsAtWarWith фракции.
 public static class FactionHelper {
  public static readonly List<TaleWorlds.CampaignSystem.Kingdom> TestEnemies = new();
  public static IEnumerable<TaleWorlds.CampaignSystem.Kingdom> GetEnemyKingdoms(TaleWorlds.CampaignSystem.IFaction faction) => TestEnemies;
 }
 public static class MobilePartyHelper {
  public static Settlement GetCurrentSettlementOfMobilePartyForAICalculation(MobileParty p) =>
   p.CurrentSettlement ?? (p.LastVisitedSettlement != null && p.StandsAtLastVisited ? p.LastVisitedSettlement : null);
  // 3255: все пленные главной партии, кроме закреплённых игроком на экране отряда (IViewDataTracker).
  public static HashSet<string> TestLockedIds = new();
  public static TroopRoster GetPlayerPrisonersPlayerCanSell() {
   TroopRoster roster = TroopRoster.CreateDummyTroopRoster();
   foreach (TroopRosterElement item in MobileParty.MainParty.PrisonRoster.GetTroopRoster())
    if (!TestLockedIds.Contains(item.Character.StringId)) roster.Add(item);
   return roster;
  }
 }
 public static class HeroHelper {
  // 2280: шесть слотов добровольцев, если староста жив.
  public static List<CharacterObject> GetVolunteerTroopsOfHeroForRecruitment(Hero hero) {
   var list = new List<CharacterObject>();
   if (hero.IsAlive) for (int i = 0; i < 6; i++) list.Add(hero.VolunteerTypes[i]);
   return list;
  }
  // 2275: index <= VolunteerModel.MaximumIndexHeroCanRecruitFromHero(buyer, seller).
  public static bool HeroCanRecruitFromHero(Hero buyerHero, Hero sellerHero, int index) => index <= sellerHero.TestMaxRecruitIndex;
 }
}
namespace SandBox.View.Map {
 // Окна поверх карты — слои MapScreen (SandBox.View 11135-11198). ActiveState при них
 // остаётся MapState, поэтому признак «активен экран карты» их не видит. В игре
 // сеттеры закрыты; здесь открыты, чтобы открывать окна в сценариях.
 public class MapView {}
 public class MapIncidentView : MapView { public readonly TaleWorlds.CampaignSystem.Incidents.Incident Incident; public MapIncidentView(TaleWorlds.CampaignSystem.Incidents.Incident i){Incident=i;} }
 public class MapEncyclopediaView { public bool IsEncyclopediaOpen { get; set; } }
 public class MapScreen : TaleWorlds.CampaignSystem.GameState.IMapStateHandler {
  public bool IsEscapeMenuOpened { get; set; }
  public bool IsInBattleSimulation { get; set; }
  public bool IsInTownManagement { get; set; }
  public bool IsInHideoutTroopManage { get; set; }
  public bool IsInArmyManagement { get; set; }
  public bool IsInRecruitment { get; set; }
  public bool IsInCampaignOptions { get; set; }
  public bool IsMarriageOfferPopupActive { get; set; }
  public bool IsMapCheatsActive { get; set; }
  public bool IsMapIncidentActive { get; set; }
  public bool IsHeirSelectionPopupActive { get; set; }
  public bool IsOverlayContextMenuEnabled { get; set; }
  public MapEncyclopediaView EncyclopediaScreenManager { get; } = new();
  public MapIncidentView IncidentView { get; set; }
  public SandBox.GauntletUI.Map.GauntletMapBattleSimulationView SimulationView;
  public T GetMapView<T>() where T:MapView => (IncidentView as T) ?? (SimulationView as T);
  public void RemoveMapView(MapView view) { if(view==IncidentView){IncidentView=null;IsMapIncidentActive=false;TaleWorlds.CampaignSystem.Campaign.Current.TimeControlModeLock=false;} }
 }
}
namespace BannerlordAutopilot {
 internal static class AutopilotLog {
  internal static List<string> Lines=new(); internal static string Path=>"in-memory";
  internal static void Write(string s) {Lines.Add(s);} internal static void Session(string s) {Lines.Add(s);}
 }
}
    
namespace TaleWorlds.ScreenSystem {
 public class ScreenBase {}
 public static class ScreenManager { public static ScreenBase TopScreen { get; set; } }
}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions {
 public class KingdomDecisionsVM {
  private TaleWorlds.Library.InquiryData _queryData;
  public ItemTypes.DecisionItemBaseVM CurrentDecision { get; set; }
  public ItemTypes.DecisionItemBaseVM NextItem { get; set; }
  public void SetQuery(TaleWorlds.Library.InquiryData q) { _queryData=q; }
  private void OnDecisionOver() { CurrentDecision=NextItem; NextItem=null; if(CurrentDecision==null) TaleWorlds.CampaignSystem.Clan.PlayerClan.Kingdom.UnresolvedDecisions.Clear(); }
  private void OnSingleDecisionOver() { TaleWorlds.CampaignSystem.Clan.PlayerClan.Kingdom.UnresolvedDecisions.Clear(); }
 }
 public class DecisionOptionVM {
  public bool CanBeChosen { get; set; } = true;
  public bool IsOptionForAbstain { get; set; }
  public int WinPercentage { get; set; }
  public string Name { get; set; }
  public bool Selected { get; set; }
  public bool Supported { get; set; }
  private void ExecuteSelection() { Selected=true; }
  private void OnSupportStrengthChange(int index) { Supported=index==0; }
 }
}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.ItemTypes {
 public class DecisionItemBaseVM {
  public bool IsKingsDecisionOver { get; set; }
  public bool IsPlayerSupporter { get; set; }
  public bool CanEndDecision { get; set; }
  public List<TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.DecisionOptionVM> DecisionOptionsList { get; } = new();
  public void ExecuteFinalSelection() { IsKingsDecisionOver=true; }
  private void ExecuteDone() { TaleWorlds.Library.InformationManager.TestInquiryActive=true; }
 }
}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement {
 public class KingdomManagementVM { public Decisions.KingdomDecisionsVM Decision { get; set; } = new(); }
}
namespace SandBox.GauntletUI {
 public class GauntletKingdomScreen : TaleWorlds.ScreenSystem.ScreenBase {
  public TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.KingdomManagementVM DataSource { get; set; } = new();
 }
}
