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
 static void LootTests() {
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
  public List<ItemRosterElement> Left=new(),Right=new(); public bool IsTrading {get;set;} public int TotalAmount {get;set;}
  public IReadOnlyList<ItemRosterElement> GetElementsInRoster(InventorySide side)=>side==InventorySide.OtherInventory?Left:Right;
 }
}
namespace TaleWorlds.CampaignSystem.GameState {public class InventoryState:TaleWorlds.Core.GameState {public object Handler{get;set;} public InventoryLogic InventoryLogic{get;set;} public string InventoryMode{get;set;}}}
namespace SandBox.GauntletUI {public class GauntletInventoryScreen {private SPInventoryVM _dataSource;public GauntletInventoryScreen(SPInventoryVM vm){_dataSource=vm;}}}
namespace TaleWorlds.CampaignSystem.ViewModelCollection.Inventory {
 public class SPInventoryVM {
  private InventoryLogic _inventoryLogic;public SPInventoryVM(InventoryLogic logic){_inventoryLogic=logic;}
  public string LeftSearchText{get;set;}="filtered";private bool filtered=true;
  public int Capacity=100,Buys,Closed,Saved,ForeignAccepted;public bool ForeignQuery,LoseItems;
  public void ExecuteFilterNone(){filtered=false;}
  public void ExecuteBuyAllItems(){Buys++;if(filtered||LeftSearchText!="")return;var item=_inventoryLogic.Left[0].EquipmentElement;int total=_inventoryLogic.Left.Sum(x=>x.Amount);int n=Math.Min(Capacity,total);_inventoryLogic.Left.Clear();_inventoryLogic.Left.Add(new ItemRosterElement(default,total-n));if(!LoseItems)_inventoryLogic.Right.Add(new ItemRosterElement(item,n));}
  public void ExecuteCompleteTranstactions(){if(ForeignQuery)InformationManager.ShowInquiry(new InquiryData{IsAffirmativeOptionShown=true,AffirmativeAction=()=>ForeignAccepted++});else if(_inventoryLogic.Left.Sum(x=>x.Amount)>0)InformationManager.ShowInquiry(new InquiryData{IsAffirmativeOptionShown=true,AffirmativeAction=HandleDone});else HandleDone();}
  private void HandleDone(){Saved=_inventoryLogic.Right.Sum(x=>x.Amount);foreach(var e in _inventoryLogic.Right) TaleWorlds.CampaignSystem.Party.MobileParty.MainParty.ItemRoster.AddToCounts(e.EquipmentElement,e.Amount);Closed++;Game.Current.GameStateManager.PopState(0);}
 }
}




