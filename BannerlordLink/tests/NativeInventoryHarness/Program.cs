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
  var behavior=new EquipmentShopBehavior(); behavior.RegisterEvents();
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
  hero.PartyBelongedTo=new Party();
  data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero)));
  Check((bool?)data["inventory_state"]?["party_available"]==true,"empty existing party inventory is available");
  armor.NotMerchandise=true;
  hero.PartyBelongedTo.ItemRoster.AddToCounts(new EquipmentElement(armor),2);
  var ledger=behavior.Read(hero); ledger.Add("armor");
  data=JObject.Parse(behavior.Snapshot(hero,ledger));
  Check(data["items"].Any(x=>(string)x["source"]=="party" && (int?)x["count"]==2),"owned non-merchandise gear is not filtered by shop policy");
  Check(data["items"].Any(x=>(string)x["source"]=="legacy"),"legacy stored items are explicitly separate from native baggage");
  HeroIdentityBehavior.Instance.Users[hero.StringId]="alice"; hero.Name="Renamed Lord";
  try { data=JObject.Parse(behavior.Snapshot(hero,behavior.Read(hero))); Check((string)data["username"]=="alice","persistent identity survives game rename"); }
  catch(Exception) { Check(false,"persistent identity survives game rename"); }
  Console.WriteLine($"{checks} checks, {failures} failures"); return failures==0?0:1;
 }
}
