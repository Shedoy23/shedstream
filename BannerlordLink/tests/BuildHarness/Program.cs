using System;
using System.Linq;
using System.Collections.Generic;
using BannerlordLink.Util;
using BannerlordLink.Actions;
using BannerlordLink.Behaviors;
using BannerlordLink.Net;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.Core;
using TaleWorlds.CampaignSystem;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

class Program {
    static int checks;
    static void Check(bool condition,string name) { if(!condition)throw new Exception("FAIL: "+name); checks++; }
    static Hero Hero=>HeroLookup.Hero;
    static EquipmentShopBehavior Shop=>EquipmentShopBehavior.Instance;
    static JObject Payload()=>new() { ["target"]="alice",["save_id"]="save1",["hero_id"]="hero1",["equipment_session_id"]="session1" };
    static void Run(string action,JObject data) { ActionFeedback.Error=null;ActionFeedback.Applied=false;new HeroBuildHandler(action).ExecuteAsync(data).GetAwaiter().GetResult(); }
    static ItemObject Item(string id,string category,int tier=0,int value=10,SkillObject skill=null,int difficulty=0) {
        var i=new ItemObject {StringId=id,Name=id,Category=category,Tier=tier,Value=value,Difficulty=difficulty,PrimaryWeapon=skill==null?null:new WeaponComponentData{RelevantSkill=skill}};
        if(category=="bow")i.PrimaryWeapon.AmmoClass=WeaponClass.Arrow;
        if(category=="arrows")i.PrimaryWeapon=new WeaponComponentData{WeaponClass=WeaponClass.Arrow};
        MBObjectManager.Instance.Objects[id]=i;return i;
    }
    static void Reset() { HeroLookup.Hero=new Hero();EquipmentShopBehavior.Instance=new EquipmentShopBehavior {Saved=new EquipmentLedger{Build=new HeroBuildState()}};MBObjectManager.Instance=new MBObjectManager();Mission.Current=null; }
    static int Main() { try {
        Check(typeof(EquipmentLedger).GetField("Build")!=null,"new hero build persists in campaign inventory"); Reset();
        Check(JsonConvert.DeserializeObject<EquipmentLedger>("{\"Items\":[]}").Build==null,"old saves are not migrated");
        foreach(var pair in new[]{(0,1),(25,1),(49,1),(50,2),(149,2),(150,3),(999,3)}) Check(HeroBuildPolicy.Rank(pair.Item1)==pair.Item2,"actual skill rank boundary "+pair.Item1);
        var build=Shop.Saved.Build;build.SelectedWeaponType="one_handed";build.WeaponPowerCooldownUntil=1090;
        Check(HeroBuildPolicy.CanActivate(build,"rage",true,1089)=="weapon_power_cooldown","shared cooldown blocks before expiry");
        Check(HeroBuildPolicy.Select(build,"bow",true,false)==null && build.WeaponPowerCooldownUntil==1090,"switch weapon never resets cooldown");
        Check(HeroBuildPolicy.CanActivate(build,"explosive_arrows",true,1089)=="weapon_power_cooldown","other weapon shares cooldown");
        Check(HeroBuildPolicy.CanActivate(build,"explosive_arrows",true,1090)==null,"exact expiry unlocks");
        Check(HeroBuildPolicy.CanActivate(build,"rage",true,1200)=="weapon_power_not_selected","unselected power refused");
        Check(HeroBuildPolicy.CanActivate(build,"explosive_arrows",false,1200)=="required_weapon_not_wielded","carried weapon not sufficient");
        Check(HeroBuildPolicy.Select(build,"shield",true,true)=="in_mission" && build.SelectedWeaponType=="bow","cannot switch during mission");
        Check(HeroBuildPolicy.Select(build,"invalid",true,false)=="unknown_weapon_power","unknown power refused");
        Check(HeroBuildPolicy.Select(build,"shield",false,false)=="required_weapon_not_equipped","unequipped option refused");
        foreach(var def in HeroBuildPolicy.Powers) {
            build.SelectedWeaponType=def.Weapon;bool ranged=new[]{"bow","crossbow","thrown"}.Contains(def.Weapon);
            Check(HeroBuildPolicy.AllowsHit(build,def.Power,def.Weapon,ranged),"matching weapon hit "+def.Weapon);
            Check(!HeroBuildPolicy.AllowsHit(build,def.Power,"unrelated",ranged),"weapon swap cannot leak "+def.Weapon);
            Check(!HeroBuildPolicy.AllowsHit(build,def.Power,def.Weapon,!ranged),"melee/missile mismatch "+def.Weapon);
        }
        var restored=JsonConvert.DeserializeObject<EquipmentLedger>(JsonConvert.SerializeObject(Shop.Saved));
        Check(restored.Build.WeaponPowerCooldownUntil==1090,"cooldown survives save/load");
        PowerCache.UpdateHero("alice","berserk",3);
        var powers=(Dictionary<string,Dictionary<string,double[]>>)typeof(PowerCache).GetField("_powers",System.Reflection.BindingFlags.NonPublic|System.Reflection.BindingFlags.Static).GetValue(null);
        powers["berserk"]=new Dictionary<string,double[]> { ["hp_multiplier"]=new[]{2d,3d,4d},["lifesteal_pct"]=new[]{20d,30d,40d} };
        Check(PowerCache.GetPowerValue("alice","hp_multiplier")==1.15,"guardian replaces old class HP");
        Check(PowerCache.GetPowerValue("alice","lifesteal_pct")==null,"no old class passive stacking");
        Check(PowerCache.GetHeroClass("alice")?.classKey=="free_build","legacy XP/regen/tournament maps neutralized");
        Shop.Saved.Build.Specialization="assault";
        Check(PowerCache.GetPowerValue("alice","hp_multiplier")==null,"switch specialization removes guardian HP");
        Check(HeroBuildPolicy.DamageMultiplier(Shop.Saved.Build,false)==1.1 && HeroBuildPolicy.DamageMultiplier(Shop.Saved.Build,true)==1,"assault only melee");
        Shop.Saved.Build.Specialization="marksman";
        Check(HeroBuildPolicy.DamageMultiplier(Shop.Saved.Build,true)==1.1 && HeroBuildPolicy.DamageMultiplier(Shop.Saved.Build,false)==1,"marksman only ranged");
        Shop.Saved.Build=null;Check(PowerCache.GetPowerValue("alice","hp_multiplier")==4,"unmigrated legacy hero retains behavior");Reset();
        var sword=Item("sword","one_handed",0,10,DefaultSkills.OneHanded);var shield=Item("shield","shield");Item("body","body");Item("legs","leg");
        Item("expensive","one_handed",0,999,DefaultSkills.OneHanded);Item("too_difficult","one_handed",0,1,DefaultSkills.OneHanded,100);Item("too_high_tier","one_handed",5,1,DefaultSkills.OneHanded);
        var kit=HeroBuildRuntime.Starter(Hero,"infantry");Check(kit["weapon0"]==sword && kit["weapon1"]==shield,"starter picks deterministic usable basic items");
        var preview=HeroBuildRuntime.Snapshot(Hero,Shop.Saved.Build);
        Check(preview["starter_kits"].First()["items"].Any(x=>x["item_id"].ToString()=="sword"),"actual starter contents previewed");
        Check(HeroBuildRuntime.Starter(Hero,"archer")==null,"missing bow/ammo disables kit");
        var tier2=Item("tier2_twohand","two_handed",1,1,DefaultSkills.TwoHanded);
        Check(HeroBuildRuntime.Starter(Hero,"two_handed")==null,"public tier II never substituted into free tier I starter");
        var bow=Item("bow","bow",0,20,DefaultSkills.Bow);var arrows=Item("arrows","arrows");Hero.BattleEquipment[EquipmentIndex.Weapon0]=new EquipmentElement(bow);
        Check(!HeroBuildRuntime.Equipped(Hero,"bow"),"bow without ammo unavailable");Hero.BattleEquipment[EquipmentIndex.Weapon1]=new EquipmentElement(arrows);
        Check(HeroBuildRuntime.Equipped(Hero,"bow"),"bow plus arrows available");Check(HeroBuildRuntime.Formation(Hero)==FormationClass.Ranged,"formation from equipment");
        arrows.PrimaryWeapon.WeaponClass=WeaponClass.Bolt;
        Check(!HeroBuildRuntime.Equipped(Hero,"bow") && HeroBuildRuntime.Starter(Hero,"archer")==null,"incompatible ammo disabled for selection and starter");
        arrows.PrimaryWeapon.WeaponClass=WeaponClass.Arrow;
        Hero.BattleEquipment[EquipmentIndex.Horse]=new EquipmentElement(Item("horse","horse"));Check(HeroBuildRuntime.Formation(Hero)==FormationClass.HorseArcher,"mount+bow formation");
        var agent=new Agent{WieldedWeapon=new MissionWeapon{Item=bow,CurrentUsageItem=bow.PrimaryWeapon}};
        Check(HeroBuildRuntime.Wielded(agent,"bow") && !HeroBuildRuntime.Wielded(agent,"shield"),"wielded primary checked");
        agent.WieldedOffhandWeapon=new MissionWeapon{Item=shield,CurrentUsageItem=new WeaponComponentData{WeaponClass=WeaponClass.SmallShield}};
        Check(HeroBuildRuntime.Wielded(agent,"shield"),"offhand shield checked");
        Check(HeroBuildRuntime.WeaponType(new MissionWeapon{Item=arrows,CurrentUsageItem=new WeaponComponentData{WeaponClass=WeaponClass.Arrow}})=="bow","actual projectile resolves bow after switch");
        Check(HeroBuildRuntime.WeaponType(new MissionWeapon{Item=Item("javelin","thrown"),CurrentUsageItem=new WeaponComponentData{RelevantSkill=DefaultSkills.Polearm}})=="polearm","javelin melee not throwing hit");
        Hero.Skills["Bow"]=150;preview=HeroBuildRuntime.Snapshot(Hero,Shop.Saved.Build);var option=preview["power_options"].First(x=>x["weapon_type"].ToString()=="bow");
        Check((int)option["rank"]==3 && (int)option["skill_level"]==150 && (double)option["value"]==30,"catalog uses actual native skill");
        var request=Payload();request["specialization"]="marksman";Run("hero.set_specialization",request);
        Check(ActionFeedback.Applied && Shop.Saved.Build.Specialization=="marksman","specialization commits");
        Check(Hero.BattleEquipment[EquipmentIndex.Weapon0].Item==bow && Hero.GetSkillValue(DefaultSkills.Bow)==150,"spec does not change gear or skill");
        Run("hero.set_specialization",request);Check(ActionFeedback.Error=="already_selected","duplicate spec no false effect");
        request["specialization"]="hacker";Run("hero.set_specialization",request);Check(ActionFeedback.Error=="unknown_specialization","hostile spec refused");
        request["specialization"]="guardian";request["save_id"]="oldsave";Run("hero.set_specialization",request);Check(ActionFeedback.Error=="stale_hero_session","stale save refused");
        request["save_id"]="save1";request["hero_id"]="otherhero";Run("hero.set_specialization",request);Check(ActionFeedback.Error=="stale_hero_session","replaced hero refused");
        request["hero_id"]="hero1";request["equipment_session_id"]="oldruntime";Run("hero.set_specialization",request);Check(ActionFeedback.Error=="stale_equipment_session","old runtime refused");
        request=Payload();request["specialization"]="guardian";Mission.Current=new Mission();Run("hero.set_specialization",request);Check(ActionFeedback.Error=="in_mission","mission blocks mutation");Mission.Current=null;
        Hero.IsPrisoner=true;Run("hero.set_specialization",request);Check(ActionFeedback.Error=="prisoner","prisoner blocks mutation");Hero.IsPrisoner=false;
        request=Payload();request["weapon_type"]="bow";Shop.Saved.Build.WeaponPowerCooldownUntil=2000;Run("hero.select_weapon_power",request);
        Check(ActionFeedback.Applied && Shop.Saved.Build.SelectedWeaponType=="bow" && Shop.Saved.Build.WeaponPowerCooldownUntil==2000,"selection preserves cooldown");
        request=Payload();request["starter_kit"]="infantry";Run("hero.claim_starter",request);
        Check(ActionFeedback.Applied && Shop.Saved.Build.StarterKit=="infantry","starter commits once");
        Check(Hero.BattleEquipment[EquipmentIndex.Weapon0].Item==sword,"starter equips previewed native item");
        Check(Shop.Saved.Items.Any(x=>x.ItemId=="bow" && x.Slot==null),"starter preserves purchased gear");
        int count=Shop.Saved.Items.Count;Run("hero.claim_starter",request);Check(ActionFeedback.Error=="starter_already_claimed" && Shop.Saved.Items.Count==count,"starter cannot refill");
        Shop.Saved=JsonConvert.DeserializeObject<EquipmentLedger>(JsonConvert.SerializeObject(Shop.Saved));Run("hero.claim_starter",request);Check(ActionFeedback.Error=="starter_already_claimed","claim survives save/load");
        Shop.Saved.Build.StarterKit=null;Hero.BattleEquipment[EquipmentIndex.Weapon0]=new EquipmentElement(bow);Shop.StoreFails=true;Run("hero.claim_starter",request);
        Check(ActionFeedback.Error.StartsWith("build_failed:") && Shop.Saved.Build.StarterKit==null,"failed commit does not consume starter");
        Check(Hero.BattleEquipment[EquipmentIndex.Weapon0].Item==bow,"failed starter restores displaced gear rather than keeping granted weapon");Shop.StoreFails=false;Shop.PushFails=true;Run("hero.claim_starter",request);
        Check(ActionFeedback.Applied && Shop.Saved.Build.StarterKit=="infantry","mirror failure after commit remains success");
        Console.WriteLine("PASS "+checks+" free build checks (real policies, runtime and action handler; native stubs)");return 0;
    } catch(Exception ex) {Console.Error.WriteLine(ex);return 1;} }
}
