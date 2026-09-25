using System;
using System.Linq;
using BannerlordLink.Actions;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;
class Program {
 static int failures,checks;
 static void Check(bool value,string name) { checks++; Console.WriteLine((value?"PASS ":"FAIL ")+name); if(!value) failures++; }
 static int Main() {
  var forgeHero = HeroLookup.Hero = new Hero();
  var forgeItem = new ItemObject { StringId="forge", ItemComponent=new ItemComponent {ItemModifierGroup=new ItemModifierGroup()} };
  var fine = new ItemModifier {StringId="fine",ItemQuality=ItemQuality.Fine};
  forgeItem.ItemComponent.ItemModifierGroup.Mods.Add(fine);
  forgeHero.BattleEquipment[EquipmentIndex.Head]=new EquipmentElement(forgeItem);
  var badForge=new JObject { ["target"]="alice",["slot"]="head",["_reforge"]=new JObject { ["save_id"]="old",["hero_id"]="hero1",["session_id"]="old",["item_id"]="forge",["modifier_id"]="fine" }};
  new ReforgeQualityHandler().ExecuteAsync(badForge).GetAwaiter().GetResult();
  Check(forgeHero.BattleEquipment[EquipmentIndex.Head].ItemModifier==null,"stale paid reforge cannot affect another load");
  var behavior=new EquipmentShopBehavior(); behavior.RegisterEvents();
  var validForge = new JObject { ["target"]="alice",["slot"]="head",["_reforge"]=new JObject {
   ["save_id"]="save1",["hero_id"]="hero1",["session_id"]=behavior.SessionId,
   ["slot"]="head",["item_id"]="forge",["expected_modifier"]="",["modifier_id"]="fine",["rank"]=1 }};
  new ReforgeQualityHandler().ExecuteAsync(validForge).GetAwaiter().GetResult();
  Check(forgeHero.BattleEquipment[EquipmentIndex.Head].ItemModifier==fine && ActionFeedback.Applied,"verified paid reforge applies native modifier before success");
  new ReforgeQualityHandler().ExecuteAsync(validForge).GetAwaiter().GetResult();
  Check(ActionFeedback.Error=="equipment_changed" && forgeHero.BattleEquipment[EquipmentIndex.Head].ItemModifier==fine,"replayed stale grant cannot upgrade twice");
  behavior=new EquipmentShopBehavior(); behavior.RegisterEvents(); // independent inventory fixture
  var armor=new ItemObject {StringId="armor",Name="Armor",ItemType=ItemObject.ItemTypeEnum.BodyArmor,Value=10};
  MBObjectManager.Instance.Objects[armor.StringId]=armor;
  var hero=HeroLookup.Hero=new Hero {IsPrisoner=true,PartyBelongedToAsPrisoner=new Party()};
  hero.BattleEquipment[EquipmentIndex.Body]=new EquipmentElement(armor);
  hero.PartyBelongedToAsPrisoner.ItemRoster.AddToCounts(new EquipmentElement(armor),7);
  Check(EquipmentShopBehavior.PartyInventory(hero)==null,"prisoner never resolves captor roster");
  var data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero)));
  Check(!data["items"].Any(x=>(string)x["source"]=="party"),"snapshot does not leak captor items");
  Check(data["items"].Any(x=>(string)x["slot"]=="body"),"prisoner retains visible native equipment");
  Check((string)data["inventory_state"]?["party_reason"]=="hero_prisoner","captivity is explicit, not empty inventory");
  var request=new JObject { ["target"]="alice",["hero_id"]="hero1",["save_id"]="save1",["equipment_session_id"]=behavior.SessionId,["item_id"]="armor",["price_gold"]=100,["source"]="party",["owned_id"]="party|armor|",["slot"]="body" };
  foreach(var action in new[]{"hero.buy_equipment","hero.equip_owned","hero.unequip_owned","hero.discard_owned"}) {
   ActionFeedback.Error=null;
   new EquipmentShopHandler(action).ExecuteAsync(request).GetAwaiter().GetResult();
   Check(ActionFeedback.Error=="hero_prisoner","hostile prisoner request refused: "+action);
  }
  Check(hero.Gold==10000 && hero.PartyBelongedToAsPrisoner.ItemRoster.GetElementCopyAtIndex(0).Amount==7,"captor goods and hero gold unchanged");
  hero.IsPrisoner=false; hero.PartyBelongedToAsPrisoner=null;
  data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero)));
  Check((string)data["inventory_state"]?["party_reason"]=="no_party_inventory","no party is unavailable, not empty");
  new EquipmentShopHandler("hero.buy_equipment").ExecuteAsync(request).GetAwaiter().GetResult();
  Check(ActionFeedback.Error=="no_inventory" && hero.Gold==10000,"no-party queued purchase cannot spend gold");
  Check((bool?)data["inventory_state"]?["buy_equip_available"]==true && (bool?)data["inventory_state"]?["in_mission"]==false,"snapshot advertises direct purchase and map state");
  Check((int?)data["items"].First(x=>(string)x["slot"]=="body")["trade_in_gold"]==10,"native equipment quote contains trade-in value");
  request["equip_now"]=true; request["expected_item_id"]="armor"; request["expected_modifier_id"]=""; request["trade_in_gold"]=10;
  new EquipmentShopHandler("hero.buy_equipment").ExecuteAsync(request).GetAwaiter().GetResult();
  Check(ActionFeedback.Applied && hero.Gold==9910 && hero.PartyBelongedTo==null && hero.BattleEquipment[EquipmentIndex.Body].Item==armor,"real behavior supports direct equipment without a party");
  data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero)));
  Check(data["items"].Count()==1 && (string)data["items"][0]["source"]=="equipped","trade-in does not resurrect sold gear in legacy storage");
  data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero),true));
  Check((bool?)data["inventory_state"]?["in_mission"]==true,"mission snapshot disables direct purchase");
  request.Remove("equip_now");
  hero.PartyBelongedTo=new Party{LeaderHero=hero};
  data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero)));
  Check((bool?)data["inventory_state"]?["party_available"]==true,"empty existing party inventory is available");
  armor.NotMerchandise=true;
  hero.PartyBelongedTo.ItemRoster.AddToCounts(new EquipmentElement(armor),2);
  var ledger=behavior.Read(hero); ledger.Add("armor");
  data=JObject.Parse(behavior.Snapshot(hero,ledger));
  Check(data["items"].Any(x=>(string)x["source"]=="party" && (int?)x["count"]==2),"owned non-merchandise gear is not filtered by shop policy");
  Check(data["items"].Any(x=>(string)x["source"]=="legacy"),"legacy stored items are explicitly separate from native baggage");
  var replacement=new ItemObject {StringId="replacement",Name="Replacement",ItemType=ItemObject.ItemTypeEnum.BodyArmor};
  MBObjectManager.Instance.Objects[replacement.StringId]=replacement;
  var saved=ledger.Add("replacement"); behavior.Store(hero,ledger);
  request["source"]="legacy"; request["owned_id"]=saved.OwnedId;
  int before=hero.PartyBelongedTo.ItemRoster.GetElementCopyAtIndex(0).Amount;
  new EquipmentShopHandler("hero.equip_owned").ExecuteAsync(request).GetAwaiter().GetResult();
  Check(ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].Item==replacement
   && hero.PartyBelongedTo.ItemRoster.GetElementCopyAtIndex(0).Amount==before+1,"legacy replacement returns displaced native armor to real baggage");
  HeroIdentityBehavior.Instance.Users[hero.StringId]="alice"; hero.Name="Renamed Lord";
  try { data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero))); Check((string)data["username"]=="alice","persistent identity survives game rename"); }
  catch(Exception) { Check(false,"persistent identity survives game rename"); }
  var wire=new BannerlordLink.BackendStub(); BannerlordLink.BannerlordLinkModule.Backend=wire;
  behavior.Push(hero,behavior.Read(hero)); System.Threading.Thread.Sleep(100);
  behavior.Push(hero,behavior.Read(hero)); System.Threading.Thread.Sleep(100);
  Check(wire.Events==1,"identical inventory does not publish again just because sequence advanced");
  var right=new JObject { ["hero_id"]=hero.StringId,["username"]="alice",["slot"]="head",["item_id"]="forge",["modifier_id"]="fine",["rank"]=1 };
  hero.BattleEquipment[EquipmentIndex.Head]=new EquipmentElement(forgeItem);
  Check(ReforgeQuality.Restore(hero,right,"save1","alice"),"paid quality restored after rollback");
  Check(!ReforgeQuality.Restore(hero,right,"save1","alice"),"restoration is idempotent");
  hero.BattleEquipment[EquipmentIndex.Head]=new EquipmentElement(forgeItem);
  Check(!ReforgeQuality.Restore(hero,right,"other-save","alice"),"paid quality does not cross campaigns");
  Check(!ReforgeQuality.Restore(hero,right,"save1","other-user"),"paid quality does not cross owners");
  right["hero_id"]="other-hero";
  Check(!ReforgeQuality.Restore(hero,right,"save1","alice"),"paid quality does not cross heirs");
  right["hero_id"]=hero.StringId;
  TaleWorlds.MountAndBlade.Mission.Current=new TaleWorlds.MountAndBlade.Mission();
  Check(!ReforgeQuality.Restore(hero,right,"save1","alice"),"restoration waits outside mission");
  TaleWorlds.MountAndBlade.Mission.Current=null;
  hero.BattleEquipment[EquipmentIndex.Head]=new EquipmentElement(armor);
  Check(!ReforgeQuality.Restore(hero,right,"save1","alice"),"restoration does not replace a different item");
  var clock=DateTime.UtcNow;
  var publisher=new InventorySnapshotPublisher(()=>clock);
  int deliveries=0; bool delivered=false;
  Func<string,System.Threading.Tasks.Task<bool>> send = json => {System.Threading.Interlocked.Increment(ref deliveries); return System.Threading.Tasks.Task.FromResult(delivered);};
  string sample="{\"hero_id\":\"h\",\"username\":\"a\",\"equipment_session_id\":\"s\",\"inventory_seq\":1}";
  publisher.Queue(sample,send); System.Threading.Thread.Sleep(100);
  delivered=true; publisher.Queue(sample,send); System.Threading.Thread.Sleep(100);
  Check(deliveries==2,"failed send does not poison dedup cache");
  publisher.Queue(sample,send); System.Threading.Thread.Sleep(100);
  Check(deliveries==2,"successful unchanged snapshot suppressed");
  clock=clock.AddSeconds(121); publisher.Queue(sample,send); System.Threading.Thread.Sleep(100);
  Check(deliveries==3,"unchanged snapshot eventually heals server state");
  var blocked=new System.Threading.Tasks.TaskCompletionSource<bool>();
  var firstStarted=new System.Threading.ManualResetEventSlim();
  var deliveredRows=new System.Collections.Generic.List<string>();
  var latest=new InventorySnapshotPublisher();
  Func<string,System.Threading.Tasks.Task<bool>> slow = json => {
   lock(deliveredRows) {deliveredRows.Add(json);if(deliveredRows.Count==1) {firstStarted.Set();return blocked.Task;}}
   return System.Threading.Tasks.Task.FromResult(true);
  };
  latest.Queue(sample,slow); firstStarted.Wait(2000);
  latest.Queue(sample.Replace("1}","2,\"changed\":2}"),slow);
  latest.Queue(sample.Replace("1}","3,\"changed\":3}"),slow);
  blocked.SetResult(true); System.Threading.Thread.Sleep(100);
  lock(deliveredRows) Check(deliveredRows.Count==2 && deliveredRows.Last().Contains("\"changed\":3"),"slow transport retains only latest waiting hero snapshot");
  Console.WriteLine($"{checks} checks, {failures} failures"); return failures==0?0:1;
 }
}
