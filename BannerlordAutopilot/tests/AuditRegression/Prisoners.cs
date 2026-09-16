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
        vm.OtherPartyPrisoners.Add(new PartyCharacterVM {Troop=new TroopRosterElement {Character=character,Number=21,WoundedNumber=21}});
        var state=new PartyState {PartyScreenLogic=logic,PartyScreenMode=loot ? Helpers.PartyScreenHelper.PartyScreenMode.Loot : Helpers.PartyScreenHelper.PartyScreenMode.Normal};
        state.Handler=new SandBox.GauntletUI.GauntletPartyScreen(vm);
        TaleWorlds.Core.Game.Current.GameStateManager.ActiveState=state;
        return vm;
    }
    static void PrisonerTests()
    {
        foreach (int free in new[]{30,7,0}) Try("пленные, свободно "+free,()=>{
            var b=Surrender(); var vm=PrisonerScreen(50,50-free);
            for(int i=0;i<5;i++) b.PollState();
            Check(vm.Closed==1 && MobileParty.MainParty.PrisonRoster.TotalManCount==50-free+Math.Min(free,21),"пленные приняты в пределах лимита и изменения сохранены: "+free);
            Check(vm.Confirmed==(free<21 ? 1:0) && !InformationManager.IsAnyInquiryActive(),"подтверждён только оставшийся избыток: "+free);
        });
        foreach (string boundary in new[]{"normal","foreign","inquiry","off"}) Try("граница пленных "+boundary,()=>{
            var b=Surrender(); var vm=PrisonerScreen(50,0,boundary!="normal");
            if(boundary=="foreign") PlayerEncounter.Current=new PlayerEncounter();
            if(boundary=="inquiry") InformationManager.TestInquiryActive=true;
            if(boundary=="off") b.Disable("test");
            b.PollState();
            Check(vm.Closed==0 && vm.PartyScreenLogic.CurrentData.RightPrisonerRoster.TotalManCount==0,"чужой экран/модалка/F12 не трогаются: "+boundary);
        });
    }
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
  public PartyScreenData CurrentData {get;}=new(); public bool IsDoneActive()=>true;
  public class PartyScreenData {public TroopRoster RightPrisonerRoster {get;}=TroopRoster.CreateDummyTroopRoster();}
 }
}
namespace SandBox.GauntletUI {
 public class GauntletPartyScreen {private readonly PartyVM _dataSource; public GauntletPartyScreen(PartyVM vm){_dataSource=vm;} }
}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.Party {
 public class PartyCharacterVM {public TroopRosterElement Troop {get;set;} public bool IsTroopTransferrable {get;set;}=true; public readonly PartyScreenLogic.PartyRosterSide Side=PartyScreenLogic.PartyRosterSide.Left;}
 public class PartyVM {
  public PartyScreenLogic PartyScreenLogic {get;} public List<PartyCharacterVM> OtherPartyPrisoners {get;}=new();
  public bool IsAnyPopUpOpen {get;set;} public int Closed,Confirmed;
  public PartyVM(PartyScreenLogic logic){PartyScreenLogic=logic;}
  private void OnTransferTroop(PartyCharacterVM troop,int index,int count,PartyScreenLogic.PartyRosterSide side){
   var e=troop.Troop; int wounded=Math.Min(e.WoundedNumber,count); e.Number-=count;e.WoundedNumber-=wounded;troop.Troop=e;
   PartyScreenLogic.CurrentData.RightPrisonerRoster.Add(new TroopRosterElement {Character=e.Character,Number=count,WoundedNumber=wounded});
  }
  public void ExecuteRemoveZeroCounts(){OtherPartyPrisoners.RemoveAll(t=>t.Troop.Number==0);}
  public void ExecuteDone(){
   if(OtherPartyPrisoners.Any(t=>t.Troop.Number>0)) InformationManager.ShowInquiry(new InquiryData {IsAffirmativeOptionShown=true,AffirmativeAction=CloseScreenInternal});
   else CloseScreenInternal();
  }
  private void CloseScreenInternal(){
   if(OtherPartyPrisoners.Any(t=>t.Troop.Number>0)) Confirmed++;
   foreach(var e in PartyScreenLogic.CurrentData.RightPrisonerRoster.GetTroopRoster()) MobileParty.MainParty.PrisonRoster.Add(e);
   Closed++; TaleWorlds.Core.Game.Current.GameStateManager.PopState(0); PlayerEncounter.Finish();
  }
 }
}
