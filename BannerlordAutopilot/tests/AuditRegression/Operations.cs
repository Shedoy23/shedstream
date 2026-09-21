using System;
using System.Linq;
using System.Collections.Generic;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    static GameMenu Menu(string id, string option, Action consequence, bool enabled = true)
    {
        var m = new GameMenu { StringId = id };
        m.Options.Add(new GameMenuOption { IdString=option, IsEnabled=enabled, Consequence=consequence });
        return m;
    }
    static Settlement Siege()
    {
        var faction = new TestFaction(); MobileParty.MainParty.MapFaction=faction;
        var s = new Settlement { IsUnderSiege=true, MapFaction=faction };
        PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s;
        PlayerEncounter.EncounteredMobileParty=new MobileParty();
        return s;
    }
    static Settlement Camp(float x=10, bool spotted=true)
    {
        var s=new Settlement { IsHideout=true, Position=new CampaignVec2 {X=x} };
        s.Hideout=new Hideout {Settlement=s,IsSpotted=spotted,IsInfested=true};
        Hideout.All.Add(s.Hideout); return s;
    }
    static void OperationTests()
    {
        Try("осада: помощь и прорыв", () => {
            var b=Fresh(); var s=Siege(); int lost=0;
            Show(Menu("join_siege_event","join_siege_event_break_in",()=>Show(Menu("break_in_menu","break_in_menu_accept",()=>{
                lost+=3; Show(Menu("break_in_debrief_menu","break_in_debrief_continue",()=>{
                    MobileParty.MainParty.CurrentSettlement=s; MobileParty.MainParty.BesiegedSettlement=s;
                    Show(new GameMenu {StringId="menu_siege_strategies",IsWaitMenu=true,IsWaitActive=true});
                }));
            }))));
            Enable(b); b.PollState(); b.PollState(); b.PollState(); b.PollState();
            Check(lost==3 && MobileParty.MainParty.CurrentSettlement==s && b.CurrentMode==AutopilotBehavior.Mode.Apply,
                "помощь защитникам: штатные потери один раз, партия внутри, режим не выключен");
            Check(MenuContext.Invoked.SequenceEqual(new[]{"join_siege_event_break_in","break_in_menu_accept","break_in_debrief_continue"}),
                "точная цепочка помощи, без штурма лагеря/автобоя/вылазки");
            Check(Campaign.Current.TimeControlMode!=CampaignTimeControlMode.Stop,"ожидание обороны продвигает время");
            var battle=new MapEvent {MapEventSettlement=s,IsSiegeAssault=true,PlayerSide=TaleWorlds.Core.BattleSideEnum.Defender};
            MobileParty.MainParty.MapEvent=PlayerEncounter.Battle=battle;
            int attacks=0; Show(Menu("encounter","attack",()=>attacks++)); b.PollState();
            Check(attacks==1 && b.IsOwnedOperationBattle(MobileParty.MainParty),"атака осаждающих запускает полноценную оборону");
            battle.PlayerSide=TaleWorlds.Core.BattleSideEnum.Attacker;
            Check(!b.IsOwnedOperationBattle(MobileParty.MainParty),"бой на стороне осаждающих не присваивается");
            battle.PlayerSide=TaleWorlds.Core.BattleSideEnum.Defender; battle.MapEventSettlement=new Settlement();
            Check(!b.IsOwnedOperationBattle(MobileParty.MainParty),"другая крепость не присваивается");
        });
        Try("осада: F10 и запрещённая кнопка", () => {
            var b=Fresh(); Siege(); int clicks=0;
            Show(Menu("join_siege_event","join_siege_event_break_in",()=>clicks++,false));
            Enable(b,AutopilotBehavior.Mode.Observe); b.PollState();
            Check(clicks==0,"F10 не прорывается");
            Enable(b); b.PollState(); Check(clicks==0,"условия прорыва не обходятся");
        });
        Try("осада прервала отдых: скрыта помощь, доступен выход", () => {
            var b=Fresh(); var s=Siege(); s.Name="Диатма";
            MobileParty.MainParty.CurrentSettlement=s;
            var menu=new GameMenu { StringId="encounter_interrupted_siege_preparations" };
            menu.Options.Add(new GameMenuOption { IdString="encounter_interrupted_siege_preparations_join_defend",
                Condition=()=>false, Consequence=()=>throw new Exception("скрытая помощь нажата") });
            menu.Options.Add(new GameMenuOption { IdString="encounter_interrupted_siege_preparations_leave_town",
                Consequence=()=>PlayerEncounter.Finish() });
            Show(menu); Enable(b); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[]{"encounter_interrupted_siege_preparations_leave_town"})
                  && b.CurrentMode==AutopilotBehavior.Mode.Apply && MobileParty.MainParty.CurrentSettlement==null,
                  "при скрытой обороне нажата только штатная кнопка выхода, автопилот остался включён");
            Check(AutopilotLog.Lines.Any(l=>l.Contains("ОСАДА: помощь защитникам скрыта") && l.Contains("Диатма")),
                  "причина ухода из города видна в журнале");
        });
        Try("осада прервала отдых: доступная оборона приоритетнее выхода", () => {
            var b=Fresh(); var s=Siege(); MobileParty.MainParty.CurrentSettlement=s;
            var menu=new GameMenu { StringId="encounter_interrupted_siege_preparations" };
            menu.Options.Add(new GameMenuOption { IdString="encounter_interrupted_siege_preparations_join_defend" });
            menu.Options.Add(new GameMenuOption { IdString="encounter_interrupted_siege_preparations_leave_town" });
            Show(menu); Enable(b); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[]{"encounter_interrupted_siege_preparations_join_defend"}),
                  "доступная помощь защитникам сохраняет прежний приоритет");
        });
        Try("убежища: известная цель", () => {
            var b=Fresh(); Hideout.All.Clear(); CampaignTime.TestHours=12;
            Camp(1,false); var near=Camp(8); Camp(30); Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement==near && MobileParty.MainParty.IsMoving,
                "при отсутствии штатных целей выбирается ближайшее известное убежище, скрытое игнорируется");
            b.Disable("test"); Hideout.All.Clear();
        });
        Try("убежище: атака и штатный отряд", () => {
            var b=Fresh(); Hideout.All.Clear(); CampaignTime.TestHours=12; var s=Camp();
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s;
            MobileParty.MainParty.CurrentSettlement=s; int launched=0;
            var vm=new TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection.GameMenuTroopSelectionVM();
            vm.Done=()=>{ launched++; Screen.IsInHideoutTroopManage=false; };
            Show(Menu("hideout_place","assault",()=>{
                Campaign.Current.CurrentMenuContext.Handler=new SandBox.View.Menu.MenuViewContext(vm);
                Screen.IsInHideoutTroopManage=true;
            }));
            Enable(b); b.PollState(); b.PollState(); b.PollState();
            Check(launched==1 && MenuContext.Invoked.Count(x=>x=="assault")==1,
                "атака открыла отряд, его штатное подтверждение выполнено один раз");
            var battle=new MapEvent {MapEventSettlement=s,IsHideoutBattle=true};
            MobileParty.MainParty.MapEvent=PlayerEncounter.Battle=battle;
            Check(b.IsOwnedOperationBattle(MobileParty.MainParty),"свой бой в убежище получает управление");
            var conversation=Campaign.Current.ConversationManager;
            conversation.IsConversationInProgress=true;
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="bandit_hideout_start_defender_1",IsClickable=true});
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="bandit_hideout_start_defender_2",IsClickable=true});
            b.RandomDialogsEnabled=true; b.PollDialogs();
            Check(conversation.Selected.SequenceEqual(new[]{"bandit_hideout_start_defender_2"}),"главарь: полный бой имеет приоритет над случайным диалогом");
            conversation.IsConversationInProgress=false; b.OnOperationMissionEnded();
            MobileParty.MainParty.MapEvent=PlayerEncounter.Battle=null;
            Show(Menu("hideout_place","leave",()=>PlayerEncounter.Finish())); b.PollState();
            Check(PlayerEncounter.Current==null && MobileParty.MainParty.CurrentSettlement==null,"после завершения миссии убежище покидается штатно");
            CampaignEventDispatcher.NextScores.Clear(); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement!=s,"попытка того же убежища не повторяется сразу после боя");
            b.Disable("test"); Check(!b.IsOwnedOperationBattle(MobileParty.MainParty),"F12 снимает владение боем убежища");
            Hideout.All.Clear();
        });
        Try("убежище: F10 и недоступная атака", () => {
            var b=Fresh(); Hideout.All.Clear(); CampaignTime.TestHours=12; var s=Camp();
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s;
            MobileParty.MainParty.CurrentSettlement=s; int clicks=0;
            Show(Menu("hideout_place","assault",()=>clicks++,false));
            Enable(b,AutopilotBehavior.Mode.Observe); b.PollState();
            Check(clicks==0,"F10 не атакует убежище");
            Enable(b); b.PollState(); Check(clicks==0,"недоступная атака не исполняется"); Hideout.All.Clear();
        });
        Try("убежище: ночь, окно поверх карты, утро", () => {
            var b=Fresh(); CampaignTime.TestHours=22; var s=Camp();
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s; MobileParty.MainParty.CurrentSettlement=s;
            var menu=Menu("hideout_place","assault",()=>{},false);
            menu.Options.Add(new GameMenuOption {IdString="wait",Consequence=()=>Show(new GameMenu {StringId="hideout_wait",IsWaitMenu=true})});
            Show(menu); Enable(b); Screen.IsEscapeMenuOpened=true; b.PollState();
            Check(MenuContext.Invoked.Count==0,"меню паузы блокирует операцию");
            Screen.IsEscapeMenuOpened=false; b.PollState(); b.PollState();
            Check(MenuDriver.CurrentMenuId=="hideout_wait" && Campaign.Current.TimeControlMode!=CampaignTimeControlMode.Stop,"ночью включается штатное ожидание утра");
            CampaignTime.TestHours=30; int attacks=0; Show(Menu("hideout_after_wait","assault",()=>attacks++)); b.PollState();
            Check(attacks==1 && !MenuContext.Invoked.Contains("attack") && !MenuContext.Invoked.Contains("send_troops"),"утром штурм, без скрытого подхода или автобоя");
        });
        Try("убежище: чужой/недоступный отряд", () => {
            var b=Fresh(); CampaignTime.TestHours=12; var s=Camp(); int done=0;
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s; MobileParty.MainParty.CurrentSettlement=s;
            var vm=new TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection.GameMenuTroopSelectionVM {Done=()=>done++,IsDoneEnabled=false};
            Show(Menu("hideout_place","assault",()=>{Campaign.Current.CurrentMenuContext.Handler=new SandBox.View.Menu.MenuViewContext(vm); Screen.IsInHideoutTroopManage=true;}));
            Enable(b); b.PollState(); b.PollState();
            Check(done==0 && b.CurrentMode==AutopilotBehavior.Mode.Off,"недопустимое количество бойцов не подтверждается");
            vm.IsDoneEnabled=true; Enable(b); b.PollState();
            Check(done==0,"ранее открытый выбор отряда не присваивается после F11");
        });
        Try("убежище: окно выбора отряда не появилось", () => {
            var t0=DateTime.UtcNow; SetClock(t0);
            var b=Fresh(); CampaignTime.TestHours=12; var s=Camp(); int leaves=0;
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s; MobileParty.MainParty.CurrentSettlement=s;
            // Штатный assault только зовёт Handler?.OnOpenTroopSelection: без обработчика
            // кнопка молча не делает ничего, меню остаётся, игра стоит (21.09 20:34).
            int assaults=0;
            var menu=Menu("hideout_place","assault",()=>assaults++);
            menu.Options.Add(new GameMenuOption {IdString="leave",Consequence=()=>{leaves++; PlayerEncounter.Finish();}});
            Show(menu); Enable(b); b.PollState();
            SetClock(t0.AddSeconds(10)); b.PollState(); b.PollState();
            Check(assaults==1 && leaves==0 && b.CurrentMode==AutopilotBehavior.Mode.Apply,"первые 15 секунд окно ждём, не уходим и не жмём повторно");
            // Решение владельца 21.09: на этом экране нужен штурм, а не уход.
            SetClock(t0.AddSeconds(16)); b.PollState(); b.PollState();
            Check(assaults==2 && leaves==0,"после ожидания штурм повторяется, а не заменяется уходом");
            SetClock(t0.AddSeconds(32)); b.PollState(); b.PollState();
            Check(assaults==3 && leaves==0,"вторая попытка повтора тоже штурмует");
            SetClock(t0.AddSeconds(48)); b.PollState(); b.PollState();
            Check(assaults==3 && leaves==1,"после трёх молчаливых штурмов уходим штатной кнопкой, а не стоим на паузе");
            Check(b.CurrentMode==AutopilotBehavior.Mode.Apply,"неоткрывшееся окно больше не выключает автопилот");
            Check(AutopilotLog.Lines.Any(l=>l.Contains("повторяем штатный штурм")),"причина и номер попытки записаны в журнал");
            SetClock(DateTime.UtcNow);
        });
        Try("осада: оборона недоступна — прорыв наружу", () => {
            var b=Fresh(); var ours=new TestFaction(); MobileParty.MainParty.MapFaction=ours;
            var s=new Settlement {IsUnderSiege=true,MapFaction=ours};
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounterSettlement=s;
            MobileParty.MainParty.CurrentSettlement=s;
            var menu=new GameMenu {StringId="encounter_interrupted_siege_preparations"};
            menu.Options.Add(new GameMenuOption {IdString="encounter_interrupted_siege_preparations_join_defend",IsEnabled=false,Consequence=()=>{}});
            menu.Options.Add(new GameMenuOption {IdString="encounter_interrupted_siege_preparations_break_out_of_town",Consequence=()=>
                Show(Menu("break_out_menu","break_out_menu_accept",()=>{
                    MobileParty.MainParty.CurrentSettlement=null; PlayerEncounter.EncounterSettlement=null;
                    Show(Menu("break_out_debrief_menu","break_out_debrief_continue",()=>PlayerEncounter.Finish()));
                }))});
            Show(menu); Enable(b); b.PollState(); b.PollState(); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[]{"encounter_interrupted_siege_preparations_break_out_of_town","break_out_menu_accept","break_out_debrief_continue"}),
                "прорыв идёт штатной цепочкой: подтверждение и дебриф");
            Check(b.CurrentMode==AutopilotBehavior.Mode.Apply && PlayerEncounter.Current==null,"прорыв доведён до конца и не выключает автопилот");
        });
        Try("цель обороны и повтор убежища", () => {
            var b=Fresh(); CampaignTime.TestHours=12; Camp(); var ours=new TestFaction(); MobileParty.MainParty.MapFaction=ours;
            var s=new Settlement {IsUnderSiege=true,MapFaction=ours};
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(s,AiBehavior.DefendSettlement,MobileParty.NavigationType.Default,false,false,false),58));
            Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior==AiBehavior.GoToSettlement && MobileParty.MainParty.TargetSettlement==s && MobileParty.MainParty.IsMoving,"штатная цель обороны исполняется поездкой и приоритетнее зачистки");
        });
    }
}
namespace TaleWorlds.Core { public enum BattleSideEnum { None=-1, Defender, Attacker } }
namespace SandBox.View.Menu {
 public class MenuViewContext : TaleWorlds.CampaignSystem.GameState.IMenuContextHandler {
  public List<object> MenuViews { get; }=new();
  public MenuViewContext(TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection.GameMenuTroopSelectionVM vm) {MenuViews.Add(new SandBox.GauntletUI.Menu.GauntletMenuTroopSelectionView(vm));}
 }
}
namespace SandBox.GauntletUI.Menu {
 public class GauntletMenuTroopSelectionView { private readonly TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection.GameMenuTroopSelectionVM _dataSource; public GauntletMenuTroopSelectionView(TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection.GameMenuTroopSelectionVM vm){_dataSource=vm;} }
}
namespace TaleWorlds.CampaignSystem.GameState { public interface IMenuContextHandler {} }
namespace TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection {
 public class GameMenuTroopSelectionVM {
  public bool IsEnabled {get;set;}=true; public bool IsDoneEnabled {get;set;}=true;
  public Action Done; public void ExecuteDone(){IsEnabled=false;Done?.Invoke();}
 }
}
