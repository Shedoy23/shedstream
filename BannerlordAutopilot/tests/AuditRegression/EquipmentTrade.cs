using System;
using System.Collections.Generic;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;

internal static partial class Program
{
    static void EquipmentTradeTests()
    {
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
    }
}

namespace TaleWorlds.Core
{
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
        public static bool CanUseItem(CharacterObject character, EquipmentElement item)=>!item.Item.TestUnusable;
    }
}
