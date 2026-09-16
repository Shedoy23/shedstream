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
        });
        Try("осада: F10 и запрещённая кнопка", () => {
            var b=Fresh(); Siege(); int clicks=0;
            Show(Menu("join_siege_event","join_siege_event_break_in",()=>clicks++,false));
            Enable(b,AutopilotBehavior.Mode.Observe); b.PollState();
            Check(clicks==0,"F10 не прорывается");
            Enable(b); b.PollState(); Check(clicks==0,"условия прорыва не обходятся");
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
            var vm=new TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.GameMenuTroopSelectionVM();
            vm.Done=()=>{ launched++; Screen.IsInHideoutTroopManage=false; };
            Show(Menu("hideout_place","assault",()=>{
                Campaign.Current.CurrentMenuContext.Handler=new SandBox.View.Menu.MenuViewContext(vm);
                Screen.IsInHideoutTroopManage=true;
            }));
            Enable(b); b.PollState(); b.PollState(); b.PollState();
            Check(launched==1 && MenuContext.Invoked.Count(x=>x=="assault")==1,
                "атака открыла отряд, его штатное подтверждение выполнено один раз");
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
    }
}
namespace TaleWorlds.Core { public enum BattleSideEnum { None=-1, Defender, Attacker } }
namespace SandBox.View.Menu {
 public class MenuViewContext {
  public List<object> MenuViews { get; }=new();
  public MenuViewContext(object vm) {MenuViews.Add(new SandBox.GauntletUI.Menu.GauntletMenuTroopSelectionView(vm));}
 }
}
namespace SandBox.GauntletUI.Menu {
 public class GauntletMenuTroopSelectionView { private readonly object _dataSource; public GauntletMenuTroopSelectionView(object vm){_dataSource=vm;} }
}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu {
 public class GameMenuTroopSelectionVM {
  public bool IsEnabled {get;set;}=true; public bool IsDoneEnabled {get;set;}=true;
  public Action Done; public void ExecuteDone(){IsEnabled=false;Done?.Invoke();}
 }
}
