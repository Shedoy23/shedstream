using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.Core;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Inventory;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.ViewModelCollection.Inventory;
using TaleWorlds.Library;
internal static partial class Program {
 static SPInventoryVM LootScreen(string mode="Loot", int amount=3) {
  var logic=new InventoryLogic(); logic.Left.Add(new ItemRosterElement(new EquipmentElement(new ItemObject()),amount));
  var vm=new SPInventoryVM(logic); var state=new InventoryState {InventoryLogic=logic,InventoryMode=mode};
  state.Handler=new SandBox.GauntletUI.GauntletInventoryScreen(vm); Game.Current.GameStateManager.ActiveState=state; return vm;
 }
 static SPInventoryVM DonationScreen(int gold,float xp,int room,int mounts,int misc,int total) {
  var vm=LootScreen(amount:total); var logic=((InventoryState)Game.Current.GameStateManager.ActiveState).InventoryLogic;
  logic.XpGainFromDonations=xp; vm.SetPartyXpRoom(room); vm.Mounts=mounts; vm.Misc=misc;
  TaleWorlds.CampaignSystem.Hero.MainHero.Gold=gold; return vm;
 }
 static void DonationTests() {
  // Денег много, перки есть, отряду есть куда расти → снаряжение оставляем
  // движку в опыт, забираем только коней и припасы.
  Try("добыча в опыт: богаты — берём только коней и припасы",()=>{
   var b=Surrender(); var vm=DonationScreen(gold:1_500_000,xp:900,room:1000,mounts:2,misc:3,total:10);
   b.PollState(); b.PollState();
   Check(vm.Taken("mounts")==2 && vm.Taken("misc")==3 && vm.Taken("none")==0 && vm.Closed==1,
         "взято коней "+vm.Taken("mounts")+", припасов "+vm.Taken("misc")+", всего подряд "+vm.Taken("none"));
  });
  // Денег мало — старое поведение, забираем всё.
  Try("добыча в опыт: денег мало — забираем всё",()=>{
   var b=Surrender(); var vm=DonationScreen(gold:50_000,xp:900,room:1000,mounts:2,misc:3,total:10);
   b.PollState(); b.PollState();
   Check(vm.Taken("none")==10 && vm.Taken("mounts")==0,"взято подряд "+vm.Taken("none"));
  });
  // Перков нет: движок оценивает недобранное в 0 опыта — бросать добычу
  // значит выкинуть её в никуда.
  Try("добыча в опыт: без перков забираем всё",()=>{
   var b=Surrender(); var vm=DonationScreen(gold:1_500_000,xp:0,room:1000,mounts:2,misc:3,total:10);
   b.PollState(); b.PollState();
   Check(vm.Taken("none")==10,"взято подряд "+vm.Taken("none"));
  });
  // Отряд упёрся в потолок: опыт сверх него сгорает, добычу надо забрать и продать.
  Try("добыча в опыт: отряду некуда расти — забираем всё",()=>{
   var b=Surrender(); var vm=DonationScreen(gold:1_500_000,xp:900,room:0,mounts:2,misc:3,total:10);
   b.PollState(); b.PollState();
   Check(vm.Taken("none")==10,"взято подряд "+vm.Taken("none"));
  });
 }
 static void LootTests() {
  Try("loot native close event",()=>{
   var b=Surrender();var vm=LootScreen();
   vm.OnDone=()=>{var roster=TaleWorlds.CampaignSystem.Party.MobileParty.MainParty.ItemRoster;roster.AddToCounts(roster[0].EquipmentElement,-1);};
   b.PollState();b.PollState();
   Check(vm.Saved==3 && vm.Closed==1 && vm.Buys==1 && TaleWorlds.CampaignSystem.Party.MobileParty.MainParty.ItemRoster[0].Amount==2 && b.CurrentMode==AutopilotBehavior.Mode.Apply,"native close callback changes inventory without disabling or duplicating loot");
  });
  Try("loot detached roster",()=>{
   var b=Surrender();var vm=LootScreen();
   ((InventoryState)Game.Current.GameStateManager.ActiveState).InventoryLogic.Right=new TaleWorlds.CampaignSystem.Roster.ItemRoster();
   b.PollState();Check(vm.Buys==0 && vm.Closed==0 && b.CurrentMode==AutopilotBehavior.Mode.Off,"detached player inventory rejected before native actions");
  });
  foreach(int amount in new[]{0,1,7}) Try("loot actual transfer "+amount,()=>{
   var b=Surrender(); var vm=LootScreen(amount:amount); b.PollState(); b.PollState();
   Check(vm.Saved==amount && vm.Closed==1 && vm.Buys==1 && b.CurrentMode==AutopilotBehavior.Mode.Apply,"loot saved and closed once: "+amount);
  });
  Try("prisoners then loot",()=>{
   var b=Surrender(); var encounter=PlayerEncounter.Current; var prisoners=PrisonerScreen(50,0); b.PollState(); b.PollState();
   PlayerEncounter.Current=encounter; // Native party callback preserves encounter until item loot ends.
   var vm=LootScreen(); b.PollState(); Check(vm.Saved==3 && vm.Closed==1,"loot authorization survives prisoner completion");
  });
  foreach(string boundary in new[]{"Trade","Default","foreign","off","inquiry"}) Try("loot boundary "+boundary,()=>{
   var b=Surrender(); var vm=LootScreen(boundary=="Trade"||boundary=="Default"?boundary:"Loot");
   if(boundary=="foreign")PlayerEncounter.Current=new PlayerEncounter(); if(boundary=="off")b.Disable("test");
   if(boundary=="inquiry")InformationManager.TestInquiryActive=true;
   b.PollState(); Check(vm.Buys==0 && vm.Closed==0,"loot untouched: "+boundary);
  });
  Try("loot capacity",()=>{var b=Surrender();var vm=LootScreen();vm.Capacity=1;b.PollState();Check(vm.Saved==1&&vm.Closed==1&&!InformationManager.IsAnyInquiryActive(),"native capacity and leftover confirmation");});
  Try("loot foreign query",()=>{var b=Surrender();var vm=LootScreen();vm.ForeignQuery=true;b.PollState();Check(vm.Closed==0&&vm.ForeignAccepted==0&&InformationManager.IsAnyInquiryActive(),"unknown loot query untouched");});
  Try("loot inconsistent transfer",()=>{var b=Surrender();var vm=LootScreen();vm.LoseItems=true;b.PollState();b.PollState();Check(vm.Closed==0&&vm.Buys==1&&b.CurrentMode==AutopilotBehavior.Mode.Off,"lost transfer stops without retry");});
 }
}
namespace TaleWorlds.CampaignSystem.Inventory {
 public class InventoryLogic {
  public enum InventorySide {OtherInventory,PlayerInventory}
  public List<ItemRosterElement> Left=new(); public TaleWorlds.CampaignSystem.Roster.ItemRoster Right=TaleWorlds.CampaignSystem.Party.MobileParty.MainParty.ItemRoster; public bool IsTrading {get;set;} public int TotalAmount {get;set;}
  // Движок считает это сам в экране добычи: опыт за то, что НЕ забрали.
  public float XpGainFromDonations {get;set;}
  public IReadOnlyList<ItemRosterElement> GetElementsInRoster(InventorySide side)=>side==InventorySide.OtherInventory?Left:Right;
 }
}
namespace TaleWorlds.CampaignSystem.GameState {public class InventoryState:TaleWorlds.Core.GameState {public object Handler{get;set;} public InventoryLogic InventoryLogic{get;set;} public string InventoryMode{get;set;}}}
namespace SandBox.GauntletUI {public class GauntletInventoryScreen {private SPInventoryVM _dataSource;public GauntletInventoryScreen(SPInventoryVM vm){_dataSource=vm;}}}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.Inventory {
 public class SPInventoryVM {
  private InventoryLogic _inventoryLogic;public SPInventoryVM(InventoryLogic logic){_inventoryLogic=logic;}
  public string LeftSearchText{get;set;}="filtered";private bool filtered=true;
  public int Capacity=100,Buys,Closed,Saved,ForeignAccepted;public bool ForeignQuery,LoseItems; public Action OnDone;
  // Ваниль: TransferAll пропускает отфильтрованное, поэтому «взять всё» под
  // фильтром забирает только его категорию. Заглушка это и моделирует.
  private string _filter="none"; public int Mounts,Misc;
  public int Taken(string kind)=>_taken.TryGetValue(kind,out int v)?v:0;
  private readonly Dictionary<string,int> _taken=new();
  private int _donationMaxShareableXp=1000;
  public void SetPartyXpRoom(int room){_donationMaxShareableXp=room;}
  public void ExecuteFilterNone(){filtered=false;_filter="none";}
  public void ExecuteFilterMounts(){filtered=false;_filter="mounts";}
  public void ExecuteFilterMisc(){filtered=false;_filter="misc";}
  public void ExecuteBuyAllItems(){Buys++;if(filtered||LeftSearchText!="")return;var item=_inventoryLogic.Left[0].EquipmentElement;int total=_inventoryLogic.Left.Sum(x=>x.Amount);
   int want=_filter=="mounts"?Math.Min(Mounts,total):_filter=="misc"?Math.Min(Misc,total):total;
   int n=Math.Min(Capacity,want); if(_filter=="mounts")Mounts-=n; if(_filter=="misc")Misc-=n;
   _taken[_filter]=Taken(_filter)+n;
   _inventoryLogic.Left.Clear();_inventoryLogic.Left.Add(new ItemRosterElement(default,total-n));if(!LoseItems)_inventoryLogic.Right.AddToCounts(item,n);}
  public void ExecuteCompleteTranstactions(){if(ForeignQuery)InformationManager.ShowInquiry(new InquiryData{IsAffirmativeOptionShown=true,AffirmativeAction=()=>ForeignAccepted++});else if(_inventoryLogic.Left.Sum(x=>x.Amount)>0)InformationManager.ShowInquiry(new InquiryData{IsAffirmativeOptionShown=true,AffirmativeAction=HandleDone});else HandleDone();}
  private void HandleDone(){Saved=_inventoryLogic.Right.Sum(x=>x.Amount);OnDone?.Invoke();Closed++;Game.Current.GameStateManager.PopState(0);}
 }
}





