using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.CampaignSystem.ViewModelCollection.Party;
using TaleWorlds.Library;

internal static partial class Program
{
    static AutopilotBehavior Surrender()
    {
        var b=Fresh(); Enable(b);
        var ours=new TestFaction(); var enemy=new TestFaction(); ours.Enemies.Add(enemy);
        var target=new MobileParty {IsBandit=true,MapFaction=enemy};
        MobileParty.MainParty.MapFaction=ours; MobileParty.MainParty.TargetParty=target;
        MobileParty.MainParty.DefaultBehavior=AiBehavior.EngageParty;
        PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty=target;
        var c=Campaign.Current.ConversationManager; c.IsConversationInProgress=true; c.ConversationParty=target;
        c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="common_bandit_surrender_accepted",IsClickable=true});
        b.PollDialogs(); c.IsConversationInProgress=false;
        return b;
    }
    static PartyVM PrisonerScreen(int capacity, int existing, bool loot=true)
    {
        var character=new CharacterObject {StringId="bandit"};
        var logic=new PartyScreenLogic {RightPartyPrisonersSizeLimit=capacity};
        logic.CurrentData.RightPrisonerRoster.AddToCounts(character,existing);
        var vm=new PartyVM(logic);
        if (existing > 0) vm.MainPartyPrisoners.Add(new PartyCharacterVM { Side=PartyScreenLogic.PartyRosterSide.Right, Troop=new TroopRosterElement { Character=character, Number=existing } });
        vm.OtherPartyPrisoners.Add(new PartyCharacterVM {Troop=new TroopRosterElement {Character=character,Number=21,WoundedNumber=21}});
        var state=new PartyState {PartyScreenLogic=logic,PartyScreenMode=loot ? Helpers.PartyScreenHelper.PartyScreenMode.Loot : Helpers.PartyScreenHelper.PartyScreenMode.Normal};
        state.Handler=new SandBox.GauntletUI.GauntletPartyScreen(vm);
        TaleWorlds.Core.Game.Current.GameStateManager.ActiveState=state;
        return vm;
    }
    static void PrisonerTests()
    {
        Try("lords take priority over a full prisoner roster", () => {
            var b=Surrender(); var vm=PrisonerScreen(6,5);
            var oldLord=new CharacterObject { StringId="old_lord", IsHero=true };
            var lord1=new CharacterObject { StringId="new_lord_1", IsHero=true };
            var lord2=new CharacterObject { StringId="new_lord_2", IsHero=true };
            AddOwnPrisoner(vm,oldLord,1);
            AddLeftPrisoner(vm,lord1,1); AddLeftPrisoner(vm,lord2,1);
            for(int i=0;i<20;i++) b.PollState();
            var r=MobileParty.MainParty.PrisonRoster;
            Check(vm.Closed==1 && r.TotalManCount==6 && r.TotalRegulars==3,"full roster trimmed to capacity after taking lords");
            Check(PrisonerCount(r,oldLord)==1 && PrisonerCount(r,lord1)==1 && PrisonerCount(r,lord2)==1,"every old and new lord retained");
        });
        Try("over capacity: release weakest regular prisoners first", () => {
            var b=Surrender(); var vm=PrisonerScreen(5,0); vm.OtherPartyPrisoners.Clear();
            var weak=new CharacterObject { StringId="weak", Tier=1 };
            var veteran=new CharacterObject { StringId="veteran", Tier=5 };
            var lord=new CharacterObject { StringId="lord", IsHero=true };
            AddOwnPrisoner(vm,veteran,4,1); AddOwnPrisoner(vm,lord,1); AddOwnPrisoner(vm,weak,3,2);
            for(int i=0;i<20;i++) b.PollState();
            var r=MobileParty.MainParty.PrisonRoster;
            Check(vm.Closed==1 && r.TotalManCount==5 && PrisonerCount(r,weak)==0 && PrisonerCount(r,veteran)==4,"only three weakest prisoners released");
            Check(PrisonerCount(r,lord)==1 && r.TotalWounded==1,"lord retained and veteran wounds preserved");
        });
        Try("collect lords then strongest regulars within capacity", () => {
            var b=Surrender(); var vm=PrisonerScreen(3,0);
            var elite=new CharacterObject { StringId="elite", Tier=6 };
            var lord=new CharacterObject { StringId="lord", IsHero=true };
            AddLeftPrisoner(vm,elite,4,4); AddLeftPrisoner(vm,lord,1);
            for(int i=0;i<20;i++) b.PollState();
            var r=MobileParty.MainParty.PrisonRoster;
            Check(vm.Closed==1 && r.TotalManCount==3 && PrisonerCount(r,lord)==1 && PrisonerCount(r,elite)==2,"lord first, remaining two places filled by elites");
            Check(r.TotalWounded==2,"collected elites remain wounded");
        });
        Try("lords alone above capacity are never released", () => {
            var b=Surrender(); var vm=PrisonerScreen(0,0); vm.OtherPartyPrisoners.Clear();
            var lord1=new CharacterObject { StringId="lord1", IsHero=true };
            var lord2=new CharacterObject { StringId="lord2", IsHero=true };
            var lord3=new CharacterObject { StringId="lord3", IsHero=true };
            AddOwnPrisoner(vm,lord1,1); AddOwnPrisoner(vm,lord2,1); AddLeftPrisoner(vm,lord3,1);
            for(int i=0;i<20;i++) b.PollState();
            var r=MobileParty.MainParty.PrisonRoster;
            Check(vm.Closed==1 && r.TotalHeroes==3 && PrisonerCount(r,lord3)==1,"all lords kept even when native capacity is zero");
            Check(b.CurrentMode==AutopilotBehavior.Mode.Apply && LogCount("лимит недостижим") == 1,"unavoidable excess reported once without disabling");
        });
        Try("locked weak prisoners retained when trimming", () => {
            var b=Surrender(); var vm=PrisonerScreen(3,0); vm.OtherPartyPrisoners.Clear();
            var weak=new CharacterObject { StringId="locked", Tier=1 };
            var veteran=new CharacterObject { StringId="veteran", Tier=5 };
            var lord=new CharacterObject { StringId="lord", IsHero=true };
            AddOwnPrisoner(vm,weak,2,locked:true); AddOwnPrisoner(vm,veteran,2); AddOwnPrisoner(vm,lord,1);
            for(int i=0;i<20;i++) b.PollState();
            var r=MobileParty.MainParty.PrisonRoster;
            Check(vm.Closed==1 && r.TotalManCount==3 && PrisonerCount(r,weak)==2 && PrisonerCount(r,veteran)==0 && PrisonerCount(r,lord)==1,"player lock preserved; other regulars released");
        });
        foreach(bool transferable in new[]{true,false}) Try("native release permission/no-op respected " + transferable, () => {
            var b=Surrender(); var vm=PrisonerScreen(2,4); vm.OtherPartyPrisoners.Clear();
            vm.MainPartyPrisoners[0].IsTroopTransferrable=transferable;
            vm.NoRelease=transferable;
            for(int i=0;i<6;i++) b.PollState();
            Check(transferable ? vm.TransferCalls==1 && vm.Closed==0 && b.CurrentMode==AutopilotBehavior.Mode.Off
                               : vm.TransferCalls==0 && vm.Closed==1 && MobileParty.MainParty.PrisonRoster.TotalManCount==4,
                  "failed release stops once; native forbidden release is never forced " + transferable);
        });
        foreach (int free in new[] { 0, 2, 10 }) Try("rescued soldiers " + free, () => {
            var b=Surrender(); var vm=PrisonerScreen(50,0);
            vm.PartyScreenLogic.RightPartyMembersSizeLimit=8+free;
            vm.PartyScreenLogic.CurrentData.RightMemberRoster.AddToCounts(new CharacterObject(),8);
            vm.OtherPartyTroops.Add(new PartyCharacterVM { Troop=new TroopRosterElement { Character=new CharacterObject(), Number=5, WoundedNumber=5 } });
            for(int i=0;i<8;i++) b.PollState();
            Check(vm.Closed==1 && MobileParty.MainParty.MemberRoster.TotalManCount==8+Math.Min(5,free),"rescued soldiers join only within member capacity " + free);
            Check(MobileParty.MainParty.MemberRoster.TotalWounded==Math.Min(5,free),"rescued wounded stay wounded " + free);
            Check(MobileParty.MainParty.PrisonRoster.TotalManCount==21,"prisoners still collected independently " + free);
        });
        // 26.09, владелец: полный отряд — меняем слабых наших на сильных освобождённых.
        Try("обмен: полный отряд, слева тир 5 — отпускаем тир 1 и берём сильных", () => {
            var b=Surrender(); var vm=PrisonerScreen(50,0);
            var recruit=new CharacterObject {Name="Новобранец",StringId="recruit",Tier=1};
            var vet=new CharacterObject {Name="Ветеран",StringId="vet",Tier=3};
            var elite=new CharacterObject {Name="Страж",StringId="guard",Tier=5};
            vm.PartyScreenLogic.RightPartyMembersSizeLimit=10;
            vm.PartyScreenLogic.CurrentData.RightMemberRoster.AddToCounts(recruit,4);
            vm.PartyScreenLogic.CurrentData.RightMemberRoster.AddToCounts(vet,6);
            vm.MainPartyTroops.Add(new PartyCharacterVM {Side=PartyScreenLogic.PartyRosterSide.Right,Troop=new TroopRosterElement {Character=recruit,Number=4}});
            vm.MainPartyTroops.Add(new PartyCharacterVM {Side=PartyScreenLogic.PartyRosterSide.Right,Troop=new TroopRosterElement {Character=vet,Number=6}});
            vm.OtherPartyTroops.Add(new PartyCharacterVM {Troop=new TroopRosterElement {Character=elite,Number=3}});
            for(int i=0;i<20;i++) b.PollState();
            var r=MobileParty.MainParty.MemberRoster;
            Check(vm.Closed==1 && r.TotalManCount==10, "отряд остался полным: "+r.TotalManCount);
            Check(r.GetTroopRoster().Where(t=>t.Character==elite).Sum(t=>t.Number)==3, "все 3 стража взяты");
            Check(r.GetTroopRoster().Where(t=>t.Character==recruit).Sum(t=>t.Number)==1 && r.GetTroopRoster().Where(t=>t.Character==vet).Sum(t=>t.Number)==6,
                  "отпущены ровно 3 самых слабых (новобранцы), ветераны не тронуты");
            Check(LogCount("ОБМЕН: отпущено 3 «Новобранец» (тир 1) ради «Страж» (тир 5)")==1, "обмен записан");
        });
        Try("обмен: слева не сильнее — никого не отпускаем", () => {
            var b=Surrender(); var vm=PrisonerScreen(50,0);
            var vet=new CharacterObject {Name="Ветеран",StringId="vet",Tier=3};
            var peasant=new CharacterObject {Name="Крестьянин",StringId="peasant",Tier=3};
            vm.PartyScreenLogic.RightPartyMembersSizeLimit=5;
            vm.PartyScreenLogic.CurrentData.RightMemberRoster.AddToCounts(vet,5);
            vm.MainPartyTroops.Add(new PartyCharacterVM {Side=PartyScreenLogic.PartyRosterSide.Right,Troop=new TroopRosterElement {Character=vet,Number=5}});
            vm.OtherPartyTroops.Add(new PartyCharacterVM {Troop=new TroopRosterElement {Character=peasant,Number=4}});
            for(int i=0;i<10;i++) b.PollState();
            Check(vm.Closed==1 && MobileParty.MainParty.MemberRoster.GetTroopRoster().All(t=>t.Character==vet) && LogCount("ОБМЕН")==0,
                  "равный тир — обмена нет");
        });
        Try("обмен: игра не дала отпустить — обмен прекращён, автопилот работает", () => {
            var b=Surrender(); var vm=PrisonerScreen(50,0); vm.NoRelease=true;
            var recruit=new CharacterObject {Name="Новобранец",StringId="recruit",Tier=1};
            var elite=new CharacterObject {Name="Страж",StringId="guard",Tier=5};
            vm.PartyScreenLogic.RightPartyMembersSizeLimit=4;
            vm.PartyScreenLogic.CurrentData.RightMemberRoster.AddToCounts(recruit,4);
            vm.MainPartyTroops.Add(new PartyCharacterVM {Side=PartyScreenLogic.PartyRosterSide.Right,Troop=new TroopRosterElement {Character=recruit,Number=4}});
            vm.OtherPartyTroops.Add(new PartyCharacterVM {Troop=new TroopRosterElement {Character=elite,Number=2}});
            for(int i=0;i<10;i++) b.PollState();
            Check(vm.Closed==1 && b.CurrentMode==AutopilotBehavior.Mode.Apply && LogCount("обмен на этом экране прекращён")==1,
                  "неудачный обмен не выключает автопилот и не повторяется");
        });
        foreach (bool denied in new[] { true, false }) Try("rescued transfer rejection", () => {
            var b=Surrender(); var vm=PrisonerScreen(50,0);
            vm.OtherPartyTroops.Add(new PartyCharacterVM { IsTroopTransferrable=!denied, Troop=new TroopRosterElement { Character=new CharacterObject(), Number=2 } });
            vm.NoTransfer=!denied;
            for(int i=0;i<5;i++) b.PollState();
            Check(MobileParty.MainParty.MemberRoster.TotalManCount==0 && (denied ? vm.Closed==1 : vm.Closed==0 && b.CurrentMode==AutopilotBehavior.Mode.Off && vm.TransferCalls==1), "unavailable rescued troops skipped; silent no-op stops without retry: " + denied);
        });
        foreach (int free in new[]{30,7,0}) Try("пленные, свободно "+free,()=>{
            var b=Surrender(); var vm=PrisonerScreen(50,50-free);
            for(int i=0;i<5;i++) b.PollState();
            Check(vm.Closed==1 && MobileParty.MainParty.PrisonRoster.TotalManCount==50-free+Math.Min(free,21),"пленные приняты в пределах лимита и изменения сохранены: "+free);
            Check(MobileParty.MainParty.PrisonRoster.GetTroopRoster().Sum(t=>t.WoundedNumber)==Math.Min(free,21),"раненые пленные сохранили состояние: "+free);
            Check(vm.Confirmed==(free<21 ? 1:0) && !InformationManager.IsAnyInquiryActive(),"подтверждён только оставшийся избыток: "+free);
        });
        Try("неизвестный запрос из Готово",()=>{
            var b=Surrender(); var vm=PrisonerScreen(10,10); vm.ForeignQuery=true;
            b.PollState(); b.PollState();
            Check(vm.Closed==0 && vm.ForeignAccepted==0 && InformationManager.IsAnyInquiryActive(),"посторонний callback не подтверждён и модалка не скрыта");
        });
        Try("тихий отказ переноса",()=>{
            var b=Surrender(); var vm=PrisonerScreen(10,0); vm.NoTransfer=true;
            b.PollState(); b.PollState();
            Check(vm.Closed==0 && vm.TransferCalls==1 && b.CurrentMode==AutopilotBehavior.Mode.Off,"неподтверждённый перенос не повторяется и экран не закрывается");
        });
        Try("серый пленный",()=>{
            var b=Surrender(); var vm=PrisonerScreen(10,0); vm.OtherPartyPrisoners[0].IsTroopTransferrable=false;
            b.PollState();
            Check(vm.TransferCalls==0 && vm.Closed==1,"недоступный пленный не переносится принудительно");
        });
        foreach (string boundary in new[]{"normal","foreign","inquiry","off","observe"}) Try("граница пленных "+boundary,()=>{
            var b=Surrender(); var vm=PrisonerScreen(50,0,boundary!="normal");
            if(boundary=="foreign") PlayerEncounter.Current=new PlayerEncounter();
            if(boundary=="inquiry") InformationManager.TestInquiryActive=true;
            if(boundary=="off") b.Disable("test");
            if(boundary=="observe") { b.Disable("test"); Enable(b,AutopilotBehavior.Mode.Observe); }
            b.PollState();
            Check(vm.Closed==0 && vm.PartyScreenLogic.CurrentData.RightPrisonerRoster.TotalManCount==0,"чужой экран/модалка/F12 не трогаются: "+boundary);
        });
    }
    static int PrisonerCount(TroopRoster roster, CharacterObject troop) => roster.GetTroopRoster().Where(t=>t.Character==troop).Sum(t=>t.Number);
    static void AddOwnPrisoner(PartyVM vm, CharacterObject character, int count, int wounded=0, bool locked=false)
    {
        vm.PartyScreenLogic.CurrentData.RightPrisonerRoster.AddToCounts(character,count,false,wounded);
        vm.MainPartyPrisoners.Add(new PartyCharacterVM { Side=PartyScreenLogic.PartyRosterSide.Right, IsLocked=locked,
            Troop=new TroopRosterElement { Character=character, Number=count, WoundedNumber=wounded } });
    }
    static void AddLeftPrisoner(PartyVM vm, CharacterObject character, int count, int wounded=0) =>
        vm.OtherPartyPrisoners.Add(new PartyCharacterVM { Troop=new TroopRosterElement { Character=character, Number=count, WoundedNumber=wounded } });
}
namespace Helpers { public static class PartyScreenHelper { public enum PartyScreenMode {Normal,Loot} } }
namespace TaleWorlds.CampaignSystem.GameState {
 public class PartyState:TaleWorlds.Core.GameState {public object Handler {get;set;} public PartyScreenLogic PartyScreenLogic {get;set;} public Helpers.PartyScreenHelper.PartyScreenMode PartyScreenMode {get;set;} }
}
namespace TaleWorlds.CampaignSystem.Party {
 public class PartyScreenLogic {
  public enum PartyRosterSide {Left,Right,None}
  public PartyBase RightOwnerParty {get;}=PartyBase.MainParty;
  public int RightPartyPrisonersSizeLimit {get;set;}
  public int RightPartyMembersSizeLimit {get;set;}=100;
  public PartyScreenData CurrentData {get;}=new(); public bool IsDoneActive()=>true;
  public class PartyScreenData {public TroopRoster RightPrisonerRoster {get;}=TroopRoster.CreateDummyTroopRoster(); public TroopRoster RightMemberRoster {get;}=TroopRoster.CreateDummyTroopRoster();}
 }
}
namespace SandBox.GauntletUI {
 public class GauntletPartyScreen {private readonly PartyVM _dataSource; public GauntletPartyScreen(PartyVM vm){_dataSource=vm;} }
}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.Party {
 public class PartyCharacterVM {public TroopRosterElement Troop {get;set;} public bool IsTroopTransferrable {get;set;}=true; public bool IsLocked {get;set;} public PartyScreenLogic.PartyRosterSide Side=PartyScreenLogic.PartyRosterSide.Left;}
 public class PartyVM {
  public PartyScreenLogic PartyScreenLogic {get;} public List<PartyCharacterVM> OtherPartyPrisoners {get;}=new();
  public List<PartyCharacterVM> OtherPartyTroops {get;}=new();
  public List<PartyCharacterVM> MainPartyTroops {get;}=new();
  public List<PartyCharacterVM> MainPartyPrisoners {get;}=new();
  public bool NoRelease;
  public bool IsAnyPopUpOpen {get;set;} public int Closed,Confirmed;
  public bool ForeignQuery,NoTransfer; public int ForeignAccepted,TransferCalls;
  public PartyVM(PartyScreenLogic logic){PartyScreenLogic=logic;}
  private void OnTransferTroop(PartyCharacterVM troop,int index,int count,PartyScreenLogic.PartyRosterSide side){
   TransferCalls++; if(NoTransfer)return;
   bool prisoner=OtherPartyPrisoners.Contains(troop)||MainPartyPrisoners.Contains(troop);
   if(side==PartyScreenLogic.PartyRosterSide.Right){ // наш боец/пленный — влево (отпустить)
    if(NoRelease)return;
    var m=troop.Troop; int wounds=Math.Min(m.WoundedNumber,count); m.Number-=count; m.WoundedNumber-=wounds; troop.Troop=m;
    (prisoner ? PartyScreenLogic.CurrentData.RightPrisonerRoster : PartyScreenLogic.CurrentData.RightMemberRoster).AddToCounts(m.Character,-count,false,-wounds);
    (prisoner ? OtherPartyPrisoners : OtherPartyTroops).Add(new PartyCharacterVM {Troop=new TroopRosterElement {Character=m.Character,Number=count,WoundedNumber=wounds}});
    return;
   }
   var e=troop.Troop; int wounded=Math.Min(e.WoundedNumber,count); e.Number-=count;e.WoundedNumber-=wounded;troop.Troop=e;
   (OtherPartyTroops.Contains(troop) ? PartyScreenLogic.CurrentData.RightMemberRoster : PartyScreenLogic.CurrentData.RightPrisonerRoster).Add(new TroopRosterElement {Character=e.Character,Number=count,WoundedNumber=wounded});
   var own=prisoner ? MainPartyPrisoners : MainPartyTroops;
   var present=own.FirstOrDefault(t=>t.Troop.Character==e.Character);
   if(present==null) own.Add(new PartyCharacterVM {Side=PartyScreenLogic.PartyRosterSide.Right,Troop=new TroopRosterElement {Character=e.Character,Number=count,WoundedNumber=wounded}});
   else { var updated=present.Troop; updated.Number+=count; updated.WoundedNumber+=wounded; present.Troop=updated; }
  }
  public void ExecuteRemoveZeroCounts(){OtherPartyPrisoners.RemoveAll(t=>t.Troop.Number==0);OtherPartyTroops.RemoveAll(t=>t.Troop.Number==0);MainPartyTroops.RemoveAll(t=>t.Troop.Number==0);MainPartyPrisoners.RemoveAll(t=>t.Troop.Number==0);}
  public void ExecuteDone(){
   if(ForeignQuery){InformationManager.ShowInquiry(new InquiryData {IsAffirmativeOptionShown=true,AffirmativeAction=()=>ForeignAccepted++});return;}
   if(OtherPartyPrisoners.Any(t=>t.Troop.Number>0)) InformationManager.ShowInquiry(new InquiryData {IsAffirmativeOptionShown=true,AffirmativeAction=CloseScreenInternal});
   else CloseScreenInternal();
  }
  private void CloseScreenInternal(){
   if(OtherPartyPrisoners.Any(t=>t.Troop.Number>0)) Confirmed++;
   foreach(var e in PartyScreenLogic.CurrentData.RightPrisonerRoster.GetTroopRoster()) MobileParty.MainParty.PrisonRoster.Add(e);
   foreach(var e in PartyScreenLogic.CurrentData.RightMemberRoster.GetTroopRoster()) MobileParty.MainParty.MemberRoster.Add(e);
   Closed++; TaleWorlds.Core.Game.Current.GameStateManager.PopState(0); PlayerEncounter.Finish();
  }
 }
}
