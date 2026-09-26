using System;
using System.Collections.Generic;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

internal static partial class Program
{
    static void EquipmentTradeTests()
    {
        foreach (string condition in new[] { "full", "room", "food", "locked", "observe", "no_cash" })
        Try("sell trip " + condition, () => {
            var b=Fresh(); var w=MakeWorld(prisoners:false); var p=MobileParty.MainParty;
            p.Party.PartySizeLimit=p.Party.NumberOfAllMembers; // Проверяем продажу при отсутствии потребности в найме.
            w.Place.Position=new CampaignVec2 { X=10 }; Settlement.All.Add(w.Place);
            var enemy = new TestFaction(); ((TestFaction)p.MapFaction).Enemies.Add(enemy);
            Settlement.All.Add(new Settlement { IsTown=true, MapFaction=enemy, Position=new CampaignVec2 { X=1 } });
            Settlement.All.Add(new Settlement { IsTown=true, MapFaction=p.MapFaction, IsUnderSiege=true, Position=new CampaignVec2 { X=2 } });
            var tracker=new TestViewTracker(); Campaign.Current.Behaviors.Add(tracker);
            var loot=new ItemObject { Name="loot", TestPrice=20, IsFood=condition=="food" };
            p.ItemRoster.TestAdd(loot, 5); p.TotalWeightCarried=condition=="room" ? 40 : 100;
            if(condition=="locked") tracker.Locks.Add(loot.StringId);
            if(condition=="no_cash") w.Place.TestGold=0;
            Campaign.Current.Models.MobilePartyAIModel.NextBehavior=AiBehavior.EngageParty;
            Campaign.Current.Models.MobilePartyAIModel.NextTarget=new MobileParty { IsBandit=true };
            Campaign.Current.Models.MobilePartyAIModel.NextScore=100;
            Enable(b, condition=="observe" ? AutopilotBehavior.Mode.Observe : AutopilotBehavior.Mode.Apply);
            HourlyTick(b);
            bool routed=p.TargetSettlement==w.Place && p.DefaultBehavior==AiBehavior.GoToSettlement;
            Check(routed==(condition=="full"), "sell trip eligibility " + condition);
            if(condition=="full") {
                HourlyTick(b);
                Check(p.TargetSettlement==w.Place && p.DefaultBehavior==AiBehavior.GoToSettlement, "nearby bandits do not interrupt unloading trip");
                p.ItemRoster.TestAdd(loot,-5); p.TotalWeightCarried=20;
                HourlyTick(b);
                Check(p.DefaultBehavior==AiBehavior.EngageParty, "normal decisions resume after unloading");
            }
        });
        // 26.09, владелец: перегруз от еды (запас 460 дней, вес x5) — лишнюю еду продаём.
        Try("лишняя еда продаётся, запас на 20 дней и все виды остаются", () => {
            Fresh(); var w = MakeWorld(prisoners: false); var p = MobileParty.MainParty;
            var tracker = new TestViewTracker(); Campaign.Current.Behaviors.Add(tracker);
            var meat = new ItemObject { Name="мясо", StringId="meat", IsFood=true, TestPrice=3 };
            p.FoodChange = -10; p.ItemRoster.TestAdd(w.Grain, 900); p.ItemRoster.TestAdd(meat, 100);
            int gold = Hero.MainHero.Gold;
            EquipmentAndTrade.Sell(p, w.Place);
            Check(p.ItemRoster.TotalFood == 200, "осталось еды ровно на 20 дней: " + p.ItemRoster.TotalFood);
            Check(p.ItemRoster.TestCount(w.Grain) > 0 && p.ItemRoster.TestCount(meat) > 0, "оба вида еды сохранились");
            Check(Hero.MainHero.Gold > gold && LogCount("лишней еды 800") == 1, "продано 800 лишних, деньги получены");
        });
        Try("еды мало — не продаём ни крошки", () => {
            Fresh(); var w = MakeWorld(prisoners: false); var p = MobileParty.MainParty;
            var tracker = new TestViewTracker(); Campaign.Current.Behaviors.Add(tracker);
            p.FoodChange = -10; p.ItemRoster.TestAdd(w.Grain, 150);
            EquipmentAndTrade.Sell(p, w.Place);
            Check(p.ItemRoster.TestCount(w.Grain) == 150, "150 при норме 200 — всё остаётся");
        });
        Try("main hero equipment and protected inventory", () => {
            Fresh(); var w = MakeWorld(prisoners: false); var p = MobileParty.MainParty;
            var tracker = new TestViewTracker(); Campaign.Current.Behaviors.Add(tracker);
            var old = new ItemObject { Name="old", ItemType=ItemObject.ItemTypeEnum.HeadArmor, Armor=1, TestPrice=5 };
            var upgrade = new ItemObject { Name="better", ItemType=ItemObject.ItemTypeEnum.HeadArmor, Armor=10, TestPrice=30 };
            var locked = new ItemObject { Name="locked", TestPrice=100 };
            var quest = new ItemObject { Name="quest", Quest=true, TestPrice=100 };
            Hero.MainHero.BattleEquipment[EquipmentIndex.Head] = new EquipmentElement(old);
            var companion = new Hero(); companion.BattleEquipment[EquipmentIndex.Head] = new EquipmentElement(old);
            p.MemberRoster.AddToCounts(companion.CharacterObject, 1);
            p.ItemRoster.TestAdd(upgrade, 1); p.ItemRoster.TestAdd(locked, 1);
            p.ItemRoster.TestAdd(quest, 1); p.ItemRoster.TestAdd(w.Grain, 3);
            tracker.Locks.Add(locked.StringId);
            int gold = Hero.MainHero.Gold;
            EquipmentAndTrade.Equip(p); EquipmentAndTrade.Sell(p, w.Place);
            Check(Hero.MainHero.BattleEquipment[EquipmentIndex.Head].Item == upgrade && p.ItemRoster.TestCount(upgrade)==0, "main hero wears inventory upgrade");
            Check(companion.BattleEquipment[EquipmentIndex.Head].Item == old, "companion equipment unchanged");
            Check(p.ItemRoster.TestCount(old)==0 && Hero.MainHero.Gold==gold+5, "old equipment sold after upgrade");
            Check(p.ItemRoster.TestCount(locked)==1 && p.ItemRoster.TestCount(quest)==1 && p.ItemRoster.TestCount(w.Grain)==3, "food locks and quest items retained");
        });
        Try("merchant cannot underpay", () => {
            Fresh(); var w=MakeWorld(prisoners:false); Campaign.Current.Behaviors.Add(new TestViewTracker());
            var item=new ItemObject { Name="loot", TestPrice=25 }; var e=new EquipmentElement(item, new ItemModifier());
            MobileParty.MainParty.ItemRoster.AddToCounts(e, 3); w.Place.TestGold=30; int gold=Hero.MainHero.Gold;
            EquipmentAndTrade.Sell(MobileParty.MainParty, w.Place);
            Check(MobileParty.MainParty.ItemRoster.GetElementNumber(MobileParty.MainParty.ItemRoster.FindIndexOfElement(e))==2 && Hero.MainHero.Gold==gold+25 && w.Place.TestGold==5, "only affordable unit sold with modifier preserved");
        });
        Try("equipment restrictions and exact modifiers", () => {
            Fresh(); MakeWorld(prisoners:false); var p=MobileParty.MainParty;
            var tracker=new TestViewTracker(); Campaign.Current.Behaviors.Add(tracker);
            var old=new ItemObject { Name="old", ItemType=ItemObject.ItemTypeEnum.HeadArmor, Armor=1 };
            var good=new ItemObject { Name="good", ItemType=ItemObject.ItemTypeEnum.HeadArmor, Armor=3 };
            var forbidden=new ItemObject { Name="requires skill", ItemType=ItemObject.ItemTypeEnum.HeadArmor, Armor=30, TestUnusable=true };
            var locked=new ItemObject { Name="locked", ItemType=ItemObject.ItemTypeEnum.HeadArmor, Armor=50 };
            var modifier=new ItemModifier(); var improved=new EquipmentElement(good, modifier);
            var sword=new ItemObject { Name="sword", ItemType=ItemObject.ItemTypeEnum.OneHandedWeapon, TestPrice=10, PrimaryWeapon=new() { ItemUsage="onehanded" } };
            var wrongUsage=new ItemObject { Name="wrong usage", ItemType=ItemObject.ItemTypeEnum.OneHandedWeapon, TestPrice=30, PrimaryWeapon=new() { ItemUsage="unmounted" } };
            Hero.MainHero.BattleEquipment[EquipmentIndex.Head]=new EquipmentElement(old);
            Hero.MainHero.BattleEquipment[EquipmentIndex.Weapon0]=new EquipmentElement(sword);
            p.ItemRoster.AddToCounts(improved, 2); p.ItemRoster.TestAdd(forbidden, 1); p.ItemRoster.TestAdd(locked, 1); p.ItemRoster.TestAdd(wrongUsage, 1);
            tracker.Locks.Add(locked.StringId);
            EquipmentAndTrade.Equip(p); EquipmentAndTrade.Equip(p);
            Check(Hero.MainHero.BattleEquipment[EquipmentIndex.Head].IsEqualTo(improved) && p.ItemRoster.GetElementNumber(p.ItemRoster.FindIndexOfElement(improved))==1 && p.ItemRoster.TestCount(old)==1, "skill and lock gates; exact modifier conserved; second equip idempotent");
            Check(Hero.MainHero.BattleEquipment[EquipmentIndex.Weapon0].Item==sword && Hero.MainHero.BattleEquipment[EquipmentIndex.Weapon1].IsEmpty, "weapon use preserved and empty weapon slot unchanged");
        });
        Try("mount and harness compatibility", () => {
            Fresh(); MakeWorld(prisoners:false); var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var horse=new ItemObject { Name="horse", ItemType=ItemObject.ItemTypeEnum.Horse, TestPrice=40, HorseComponent=new() { Monster=new() { FamilyType=1 } } };
            var harness=new ItemObject { Name="harness", ItemType=ItemObject.ItemTypeEnum.HorseHarness, Armor=5, ArmorComponent=new() { FamilyType=1 } };
            var badHarness=new ItemObject { Name="camel harness", ItemType=ItemObject.ItemTypeEnum.HorseHarness, Armor=50, ArmorComponent=new() { FamilyType=2 } };
            p.ItemRoster.TestAdd(horse,1); p.ItemRoster.TestAdd(harness,1); p.ItemRoster.TestAdd(badHarness,1);
            EquipmentAndTrade.Equip(p);
            Check(Hero.MainHero.BattleEquipment[EquipmentIndex.Horse].Item==horse && Hero.MainHero.BattleEquipment[EquipmentIndex.HorseHarness].Item==harness && p.ItemRoster.TestCount(badHarness)==1, "only compatible mount armor equipped");
        });
        Try("village sale live pricing and all nonfood", () => {
            Fresh(); var w=MakeWorld(village:true, prisoners:false); var p=MobileParty.MainParty;
            Campaign.Current.Behaviors.Add(new TestViewTracker());
            var tools=new ItemObject { Name="tools", TestPrice=10, TestPriceIncreasePerSale=5 };
            var horse=new ItemObject { Name="spare mount", ItemType=ItemObject.ItemTypeEnum.Horse, TestPrice=20 };
            p.ItemRoster.TestAdd(tools,2); p.ItemRoster.TestAdd(horse,1); int gold=Hero.MainHero.Gold;
            EquipmentAndTrade.Sell(p,w.Place);
            Check(p.ItemRoster.Count==0 && Hero.MainHero.Gold==gold+45, "village buys goods and spare horses using updated prices");
        });
        Try("trade gates and silent no op", () => {
            Fresh(); var w=MakeWorld(prisoners:false); var p=MobileParty.MainParty;
            var loot=new ItemObject { Name="loot", TestPrice=20 }; p.ItemRoster.TestAdd(loot,1);
            EquipmentAndTrade.Sell(p,w.Place);
            Check(p.ItemRoster.TestCount(loot)==1, "missing lock information prevents sale");
            Campaign.Current.Behaviors.Add(new TestViewTracker()); Campaign.Current.Models.SettlementAccessModel.TestTrade=false;
            EquipmentAndTrade.Sell(p,w.Place);
            Check(p.ItemRoster.TestCount(loot)==1, "native trade denial respected");
            Campaign.Current.Models.SettlementAccessModel.TestTrade=true;
            TaleWorlds.CampaignSystem.Actions.SellItemsAction.TestBroken=true;
            bool rejected=false; try { EquipmentAndTrade.Sell(p,w.Place); } catch (InvalidOperationException) { rejected=true; }
            Check(rejected && p.ItemRoster.TestCount(loot)==1, "silent sale no op rejected");
        });
    }
}

namespace TaleWorlds.Core
{
    public class BasicCharacterObject { }
    public enum EquipmentIndex { Weapon0, Weapon1, Weapon2, Weapon3, ExtraWeaponSlot, Head, Body, Leg, Gloves, Cape, Horse, HorseHarness }
    public class Equipment
    {
        readonly EquipmentElement[] items=new EquipmentElement[12];
        public EquipmentElement this[EquipmentIndex index] { get=>items[(int)index]; set=>items[(int)index]=value; }
    }
    public class ArmorComponent { public int FamilyType; }
    public class Monster { public int FamilyType; }
    public partial class HorseComponent { public Monster Monster = new(); }
    public class WeaponComponentData { public string ItemUsage; }
    public partial class ItemObject
    {
        public enum ItemTypeEnum { Invalid,Horse,OneHandedWeapon,TwoHandedWeapon,Polearm,Arrows,Bolts,SlingStones,Shield,Bow,Crossbow,Sling,Thrown,Goods,HeadArmor,BodyArmor,LegArmor,HandArmor,Pistol,Musket,Bullets,Animal,Book,ChestArmor,Cape,HorseHarness,Banner }
        public string StringId=Guid.NewGuid().ToString();
        public ItemTypeEnum ItemType; public int Armor; public bool Quest, NotMerchandise, TestUnusable;
        public ArmorComponent ArmorComponent;
        public WeaponComponentData PrimaryWeapon;
    }
    public partial struct EquipmentElement
    {
        public bool IsEmpty => Item==null;
        public bool IsQuestItem => Item?.Quest==true;
        public int ItemValue => Item?.TestPrice ?? 0;
        public int GetModifiedHeadArmor()=>Item?.Armor ?? 0;
        public int GetModifiedBodyArmor()=>0;
        public int GetModifiedArmArmor()=>0;
        public int GetModifiedLegArmor()=>0;
        public int GetModifiedMountBodyArmor()=>Item?.Armor ?? 0;
    }
}
namespace TaleWorlds.CampaignSystem
{
    public interface IViewDataTracker { IEnumerable<string> GetInventoryLocks(); }
    public class TestViewTracker : IViewDataTracker
    {
        public List<string> Locks = new();
        public IEnumerable<string> GetInventoryLocks()=>Locks;
    }
    public partial class Hero
    {
        public Equipment BattleEquipment = new();
        public CharacterObject CharacterObject => new() { IsHero=true, HeroObject=this };
        public bool CanHeroEquipmentBeChanged()=>true;
    }
}
namespace Helpers
{
    public static class CharacterHelper
    {
        public static bool CanUseItem(BasicCharacterObject character, EquipmentElement item)=>!item.Item.TestUnusable;
    }
}
namespace TaleWorlds.CampaignSystem.Settlements
{
    public class SettlementComponent
    {
        readonly Settlement settlement;
        public SettlementComponent(Settlement settlement) { this.settlement=settlement; }
        public int Gold=>settlement.TestGold;
    }
}
