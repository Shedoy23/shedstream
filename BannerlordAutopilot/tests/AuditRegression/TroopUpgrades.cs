using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.Core;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;

internal static partial class Program
{
    static void TroopUpgradeTests()
    {
        foreach (string mode in new[] { "apply", "observe", "modal", "battle" })
        Try("hourly upgrade boundary " + mode, () => {
            var b=Fresh(); MakeWorld(gold:500, prisoners:false); SetLimit("MinGoldReserve",0);
            var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var target=new CharacterObject { Name="trained" };
            var troop=new CharacterObject { Name="recruit", UpgradeTargets=new[] { target } };
            p.MemberRoster.AddToCounts(troop,1,xpChange:100);
            Campaign.Current.Models.PartyWageModel.TestTotalWage=(party,roster)=>10;
            Enable(b,mode=="observe" ? AutopilotBehavior.Mode.Observe : AutopilotBehavior.Mode.Apply);
            if(mode=="modal") TaleWorlds.Library.InformationManager.TestInquiryActive=true;
            if(mode=="battle") p.MapEvent=new TaleWorlds.CampaignSystem.MapEvent();
            HourlyTick(b);
            Check((p.MemberRoster.FindIndexOfTroop(target)>=0)==(mode=="apply"), "hourly upgrade respects " + mode);
        });
        foreach (string condition in new[] { "ready", "no_xp", "reserve", "perk", "hero", "horse", "locked_horse" })
        Try("troop upgrades " + condition, () => {
            Fresh(); MakeWorld(gold:500, prisoners:false); SetLimit("MinGoldReserve",0);
            var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var foot=new CharacterObject { Name="foot", DefaultFormationClass=FormationClass.Infantry };
            var ranged=new CharacterObject { Name="archer", DefaultFormationClass=FormationClass.Ranged };
            var source=new CharacterObject { Name="recruit", UpgradeTargets=new[] { foot,ranged }, IsHero=condition=="hero" };
            if(condition=="horse" || condition=="locked_horse") {
                var category=new ItemCategory(); ranged.UpgradeRequiresItemFromCategory=category;
                var horse=new ItemObject { Name="horse", ItemCategory=category };
                p.ItemRoster.TestAdd(horse,1);
                if(condition=="locked_horse") ((TestViewTracker)Campaign.Current.GetCampaignBehavior<IViewDataTracker>()).Locks.Add(horse.StringId);
                source.UpgradeTargets=new[] { ranged };
            }
            if(condition=="perk") ranged.TestPerkBlocked=foot.TestPerkBlocked=true;
            p.MemberRoster.AddToCounts(source,2,woundedCount:1,xpChange:condition=="no_xp" ? 0 : 200);
            Campaign.Current.Models.PartyWageModel.TestTotalWage=(party, roster)=>condition=="reserve" ? 100 : 10;
            int before=p.MemberRoster.TotalManCount, wounded=p.MemberRoster.TotalWounded;
            TroopUpgrades.Run(p);
            int expected=condition=="ready" ? 2 : condition=="horse" ? 1 : 0;
            Check(p.MemberRoster.GetTroopRoster().Where(e=>e.Character==ranged).Sum(e=>e.Number)==expected, "upgrade eligibility and preferred branch " + condition);
            Check(p.MemberRoster.TotalManCount==before && p.MemberRoster.TotalWounded==wounded && Hero.MainHero.Gold==500-expected*20, "headcount wounded and payment preserved " + condition);
            if(condition=="horse") Check(p.ItemRoster.Count==0 && p.MemberRoster.GetTroopRoster().First(e=>e.Character==source).Xp==100, "upgrade consumes one horse and exact XP");
        });
    }
}
namespace TaleWorlds.Core
{
    public enum FormationClass { Infantry,Ranged,Cavalry,HorseArcher,HeavyCavalry,LightCavalry,HeavyInfantry,Skirmisher }
    public class ItemCategory { }
    public partial class ItemObject { public ItemCategory ItemCategory; }
}
namespace TaleWorlds.CampaignSystem
{
    public partial class CampaignEventDispatcher
    {
        public void OnPlayerUpgradedTroops(CharacterObject from,CharacterObject to,int number) { }
    }
    public partial class CharacterObject
    {
        public FormationClass DefaultFormationClass;
        public CharacterObject[] UpgradeTargets=Array.Empty<CharacterObject>();
        public ItemCategory UpgradeRequiresItemFromCategory;
        public bool TestPerkBlocked;
        public int GetUpgradeXpCost(PartyBase party,int index)=>100;
        public int GetUpgradeGoldCost(PartyBase party,int index)=>20;
    }
}
namespace TaleWorlds.CampaignSystem.ComponentInterfaces
{
    public class PartyTroopUpgradeModel
    {
        public bool CanPartyUpgradeTroopToTarget(PartyBase party,CharacterObject source,CharacterObject target)=>!source.IsHero && !target.TestPerkBlocked;
    }
}
namespace TaleWorlds.CampaignSystem.Roster
{
    public partial class TroopRoster
    {
        public int FindIndexOfTroop(CharacterObject troop)=>_data.FindIndex(e=>e.Character==troop);
        public TroopRosterElement GetElementCopyAtIndex(int index)=>_data[index];
        public int GetElementXp(int index)=>_data[index].Xp;
        public void SetElementXp(int index,int xp) { var e=_data[index]; e.Xp=xp; _data[index]=e; }
    }
}
