using System.Linq;
using System;
using BannerlordLink.Util;
class Program {
 static int n;
 static void Check(bool value,string name) { if(!value) throw new Exception(name); n++; }
 static void Main() {
  Check(ProgressionPolicy.Focus(2,1,5,50000).Available,"focus price exact");
  Check(ProgressionPolicy.Focus(2,1,5,50000).CostGold==50000,"tier2");
  Check(ProgressionPolicy.Focus(0,2,5,70000).CostGold==70000,"bulk sums tiers");
  Check(ProgressionPolicy.Focus(3,1,3,999999).Reason=="native_focus_limit","mod lower cap");
  Check(ProgressionPolicy.Focus(5,1,8,999999).Reason=="focus_purchase_limit","no invented tier6");
  Check(ProgressionPolicy.Focus(4,2,8,999999).Reason=="focus_purchase_limit","no silent amount clamp");
  Check(ProgressionPolicy.Focus(-1,1,5,999999).Reason=="invalid_progression_value","negative focus");
  Check(ProgressionPolicy.Focus(0,0,5,999999).Reason=="invalid_amount","zero amount");
  Check(ProgressionPolicy.Focus(2,1,5,49999).Reason=="not_enough_hero_gold","gold boundary");
  Check(ProgressionPolicy.Attribute(7,1,7,999999).Reason=="native_attribute_limit","mod attr cap");
  Check(ProgressionPolicy.Attribute(10,1,20,999999).Reason=="attribute_purchase_limit","preserve attr balance");
  Check(ProgressionPolicy.Attribute(8,2,10,100000).CostGold==100000,"bulk attr");
  Check(ProgressionPolicy.ValidateExpected(2,50000,2,50000)==null,"matching quote");
  Check(ProgressionPolicy.ValidateExpected(3,60000,2,50000)=="stale_progression_value","stale value");
  Check(ProgressionPolicy.ValidateExpected(2,50000,2,1)=="stale_progression_price","stale price");
  Check(ProgressionPolicy.XpReason(330,1,1)=="skill_purchase_limit","xp policy cap");
  Check(ProgressionPolicy.XpReason(100,0,1)=="skill_learning_unavailable","zero learning");
  Check(ProgressionPolicy.XpReason(100,1,0)=="skill_learning_unavailable","zero multiplier");
  Check(ProgressionPolicy.XpReason(100,float.NaN,1)=="skill_learning_unavailable","invalid rate");
  Check(ProgressionPolicy.XpReason(100,0.5f,2)==null,"native learning allowed");
  Integration();
  Console.WriteLine($"PASS {n} progression checks");
 }
 static void Integration() {
  var registry=TaleWorlds.ObjectSystem.MBObjectManager.Instance;
  registry.Skills.Add(null); registry.Skills.Add(new TaleWorlds.Core.SkillObject{StringId=""});
  registry.Skills.Add(new TaleWorlds.Core.SkillObject{StringId=" Mod.Skill "});
  registry.Attributes.Add(new TaleWorlds.Core.CharacterAttribute{StringId="Mod.Attr"});
  var hero=new TaleWorlds.CampaignSystem.Hero(); hero.HeroDeveloper.Owner=hero;
  BannerlordLink.Actions.HeroLookup.Hero=hero;
  var request=new Newtonsoft.Json.Linq.JObject { ["save_id"]="save",["equipment_session_id"]="session",["hero_id"]="hero",["skill_key"]=" Mod.Skill ",["amount"]=1,["expected_value"]=2,["expected_cost_gold"]=50000 };
  var snap=HeroProgressionRuntime.Snapshot(hero);
  Check(snap["skills"].Count()==1,"bad registry entries excluded");
  Check((string)snap["skills"][0]["id"]==" Mod.Skill ","opaque skill ID");
  Check((int)snap["skills"][0]["focus_options"][0]["cost_gold"]==50000,"snapshot quote");
  TaleWorlds.MountAndBlade.Mission.Current=new TaleWorlds.MountAndBlade.Mission();
  snap=HeroProgressionRuntime.Snapshot(hero);
  Check(!(bool)snap["skills"][0]["focus_options"][0]["available"],"focus unavailable mission");
  Check((bool)snap["skills"][0]["xp_available"],"XP remains available mission");
  TaleWorlds.MountAndBlade.Mission.Current=null;
  request["hero_id"]="old"; ProgressionPurchase.Apply("viewer",request,true);
  Check(ActionFeedback.Failure=="stale_hero_identity"&&hero.Gold==100000,"old hero no charge");
  request["hero_id"]="hero"; request["expected_cost_gold"]=1; ProgressionPurchase.Apply("viewer",request,true);
  Check(ActionFeedback.Failure=="stale_progression_price"&&hero.Gold==100000,"tampered price");
  request["expected_cost_gold"]=50000;
  TaleWorlds.CampaignSystem.Actions.GiveGoldAction.NoOp=true; ProgressionPurchase.Apply("viewer",request,true);
  Check(ActionFeedback.Failure=="progression_charge_failed"&&hero.Gold==100000&&hero.HeroDeveloper.Focus==2,"no-op debit cannot grant focus");
  TaleWorlds.CampaignSystem.Actions.GiveGoldAction.NoOp=false; TaleWorlds.CampaignSystem.Actions.GiveGoldAction.ThrowAfter=true; ProgressionPurchase.Apply("viewer",request,true);
  Check(hero.Gold==100000&&hero.HeroDeveloper.Focus==2,"debit-then-throw refunds observed gold");
  TaleWorlds.CampaignSystem.Actions.GiveGoldAction.ThrowAfter=false;
  hero.HeroDeveloper.NoOp=true; ProgressionPurchase.Apply("viewer",request,true);
  Check(ActionFeedback.Failure=="progression_postcondition_failed"&&hero.Gold==100000,"no-op refund");
  hero.HeroDeveloper.NoOp=false; hero.HeroDeveloper.ThrowBefore=true; ProgressionPurchase.Apply("viewer",request,true);
  Check(hero.Gold==100000&&ActionFeedback.Applied==0,"pre-effect exception refund");
  hero.HeroDeveloper.ThrowBefore=false; hero.HeroDeveloper.ThrowAfter=true; ProgressionPurchase.Apply("viewer",request,true);
  Check(hero.Gold==50000&&hero.HeroDeveloper.Focus==3&&ActionFeedback.Applied==1,"post-effect exception confirms no refund");
  Check(HeroProgressionRuntime.ValidateContext(hero,new Newtonsoft.Json.Linq.JObject(),true)==null,"daily context exception");
  Check(HeroProgressionRuntime.ValidateContext(hero,new Newtonsoft.Json.Linq.JObject())=="progression_context_required","paid context mandatory");
  hero.HeroDeveloper.Rate=0;
  Check(HeroProgressionRuntime.XpCandidates(hero).Count==0&&!(bool)HeroProgressionRuntime.Snapshot(hero)["random_xp_available"],"snapshot random execution agreement");
  hero.HeroDeveloper.Rate=1; hero.HeroDeveloper.ThrowAfter=false;
  var xpRequest=(Newtonsoft.Json.Linq.JObject)request.DeepClone(); xpRequest["target"]="viewer"; xpRequest["xp"]=50000; xpRequest["reward_boost"]=1.5;
  var handler=new BannerlordLink.Actions.AddSkillXpHandler();
  int acks=ActionFeedback.Applied;
  xpRequest["equipment_session_id"]="old"; handler.ExecuteAsync(xpRequest).GetAwaiter().GetResult();
  Check(ActionFeedback.Failure=="stale_equipment_session"&&hero.HeroDeveloper.TotalXp==0,"XP stale session rejected");
  xpRequest["equipment_session_id"]="session"; hero.HeroDeveloper.RawXpOnly=true;
  handler.ExecuteAsync(xpRequest).GetAwaiter().GetResult();
  Check(ActionFeedback.Applied==acks+1&&hero.HeroDeveloper.TotalXp==75000,"raw XP effect confirms boosted reward");
  hero.HeroDeveloper.NoOp=true; acks=ActionFeedback.Applied;
  handler.ExecuteAsync(xpRequest).GetAwaiter().GetResult();
  Check(ActionFeedback.Failure.StartsWith("skill_xp_not_applied")&&ActionFeedback.Applied==acks,"XP no-op fails");
  hero.HeroDeveloper.NoOp=false; hero.HeroDeveloper.ThrowAfter=true;
  handler.ExecuteAsync(xpRequest).GetAwaiter().GetResult();
  Check(ActionFeedback.Applied==acks+1,"XP exception after raw effect confirms");
  hero.HeroDeveloper.ThrowAfter=false;
  var daily=new Newtonsoft.Json.Linq.JObject { ["target"]="viewer",["_daily"]=true,["xp"]=50000 };
  handler.ExecuteAsync(daily).GetAwaiter().GetResult();
  Check(hero.HeroDeveloper.LastGrant==50000&&ActionFeedback.Applied==acks+2,"daily contextless random reward retained");
  hero.Gold=100000; request["expected_value"]=3; request["expected_cost_gold"]=60000;
  hero.HeroDeveloper.UnreadableAfter=true;
  // Use fresh developer so the pre-mutation observation still succeeds.
  hero.HeroDeveloper=new TaleWorlds.CampaignSystem.Developer { Owner=hero,Focus=3,UnreadableAfter=true };
  acks=ActionFeedback.Applied; ProgressionPurchase.Apply("viewer",request,true);
  Check(ActionFeedback.Failure=="progression_outcome_unknown"&&ActionFeedback.Applied==acks&&hero.Gold==40000,"unreadable outcome explicit failure without gold refund");
  hero.HeroDeveloper=new TaleWorlds.CampaignSystem.Developer {Owner=hero,UnreadableXp=true};
  acks=ActionFeedback.Applied; handler.ExecuteAsync(xpRequest).GetAwaiter().GetResult();
  Check(ActionFeedback.Failure=="skill_xp_outcome_unknown"&&ActionFeedback.Applied==acks,"unreadable XP explicit unknown failure");
  hero.HeroDeveloper=new TaleWorlds.CampaignSystem.Developer {Owner=hero,UnreadableXp=true,ReadableRaw=true};
  handler.ExecuteAsync(xpRequest).GetAwaiter().GetResult();
  Check(ActionFeedback.Applied==acks+1,"independent raw XP observation proves effect");
  hero.HeroDeveloper=new TaleWorlds.CampaignSystem.Developer {Owner=hero}; hero.Gold=100000;
  var attrRequest=(Newtonsoft.Json.Linq.JObject)request.DeepClone(); attrRequest["attribute_key"]="Mod.Attr"; attrRequest["expected_value"]=2; attrRequest["expected_cost_gold"]=50000;
  ProgressionPurchase.Apply("viewer",attrRequest,false);
  Check(hero.AttributeValue==3&&hero.Gold==50000,"attribute actual handler purchase");
  ProgressionPurchase.Apply("viewer",attrRequest,false);
  Check(ActionFeedback.Failure=="stale_progression_value"&&hero.Gold==50000,"repeated old quote cannot double charge");
  Check(HeroProgressionRuntime.ValidateContext(hero,new Newtonsoft.Json.Linq.JObject {["save_id"]="old",["equipment_session_id"]="session",["hero_id"]="hero"})=="stale_hero_session","save identity mismatch");
  hero.Gold=100000; hero.HeroDeveloper.NoOp=true; attrRequest["expected_value"]=3;
  HeroGoldCharge.NoOp=true; int refunds=HeroGoldCharge.Calls;
  ProgressionPurchase.Apply("viewer",attrRequest,false);
  Check(ActionFeedback.Failure=="progression_compensation_failed"&&hero.Gold==50000&&HeroGoldCharge.Calls==refunds+1,"no-op refund detected once");
  HeroGoldCharge.NoOp=false; HeroGoldCharge.ReportFailure=true; hero.Gold=100000; refunds=HeroGoldCharge.Calls;
  ProgressionPurchase.Apply("viewer",attrRequest,false);
  Check(ActionFeedback.Failure=="progression_compensation_failed"&&hero.Gold==100000&&HeroGoldCharge.Calls==refunds+1,"uncertain refund not retried");





 }

}
