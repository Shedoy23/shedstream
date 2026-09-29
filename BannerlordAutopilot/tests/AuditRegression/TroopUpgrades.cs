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
        Try("прокачка: чужая правка ростера не выключает автопилот", () => {
            var b=Fresh(); MakeWorld(gold:500, prisoners:false); SetLimit("MinGoldReserve",0);
            var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var target=new CharacterObject { Name="trained" };
            var source=new CharacterObject { Name="recruit", UpgradeTargets=new[] { target } };
            p.MemberRoster.AddToCounts(source,3,xpChange:300);
            Campaign.Current.Models.PartyWageModel.TestTotalWage=(party,roster)=>10;
            Enable(b);
            bool fired=false;
            // Только настоящий ростер отряда: расчёт будущего жалования работает с копией.
            TroopRoster.TestOnSizeChanged = r => { if (fired || r != p.MemberRoster) return; fired=true; r.AddToCounts(source,-1); };
            Exception thrown=null;
            try { TroopUpgrades.Run(p); } catch (Exception ex) { thrown=ex; } finally { TroopRoster.TestOnSizeChanged=null; }
            Check(thrown==null, "несовпадение книг не бросает исключение (раньше оно выключало автопилот)");
            Check(p.MemberRoster.GetTroopRoster().Where(e=>e.Character==target).Sum(e=>e.Number)<=1, "после несовпадения прокачка этого захода прекращена");
            Check(AutopilotLog.Lines.Any(l=>l.Contains("ПРОКАЧКА ОСТАНОВЛЕНА") && l.Contains("бойцов было")), "журнал называет числа несовпадения");
        });
        // Native SetElementXp clamps BEFORE AddToCounts removes a troop.
        foreach (var sample in new[] { (Count: 5, Xp: 6300), (Count: 2, Xp: 2885) })
        Try("troop upgrades accept native pre-removal cap " + sample.Xp, () => {
            Fresh(); MakeWorld(gold:500, prisoners:false); SetLimit("MinGoldReserve",0);
            var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var target=new CharacterObject { Name="trained" };
            var source=new CharacterObject { Name="recruit", UpgradeTargets=new[] { target }, TestUpgradeXpCost=900 };
            p.MemberRoster.AddToCounts(source,sample.Count,xpChange:sample.Xp);
            Campaign.Current.Models.PartyWageModel.TestTotalWage=(party,roster)=>10;
            TroopRoster.TestOnSetXp = (r,i,xp) => r==p.MemberRoster
                ? Math.Min(xp,r.GetElementCopyAtIndex(i).Number*900) : xp;
            try { TroopUpgrades.Run(p); } finally { TroopRoster.TestOnSetXp=null; }
            Check(!AutopilotLog.Lines.Any(l=>l.Contains("ПРОКАЧКА ОСТАНОВЛЕНА")), "native pre-removal XP cap continues " + sample.Xp);
            Check(p.MemberRoster.GetTroopRoster().Where(e=>e.Character==target).Sum(e=>e.Number)==sample.Count,
                "all affordable upgrades finish after native cap " + sample.Xp);
            Check(Hero.MainHero.Gold==500-sample.Count*20, "every upgraded troop charged once " + sample.Xp);
        });
        Try("troop upgrades reject unrelated XP loss", () => {
            Fresh(); MakeWorld(gold:500, prisoners:false); SetLimit("MinGoldReserve",0);
            var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var target=new CharacterObject { Name="trained" };
            var source=new CharacterObject { Name="recruit", UpgradeTargets=new[] { target } };
            p.MemberRoster.AddToCounts(source,3,xpChange:300);
            Campaign.Current.Models.PartyWageModel.TestTotalWage=(party,roster)=>10;
            TroopRoster.TestOnSetXp=(r,i,xp)=>r==p.MemberRoster ? xp-1 : xp;
            try { TroopUpgrades.Run(p); } finally { TroopRoster.TestOnSetXp=null; }
            Check(AutopilotLog.Lines.Any(l=>l.Contains("ПРОКАЧКА ОСТАНОВЛЕНА")), "unexpected XP loss still stops upgrades");
            Check(p.MemberRoster.GetTroopRoster().Where(e=>e.Character==target).Sum(e=>e.Number)==1, "unexpected XP loss does not trigger further spending");
        });
        // 22.09 10:56:57: «опыт остатка был 1798, ждали 1248, стал 1100» — 1100 = 2 бойца
        // x 550. Игра держит опыт стопки не выше «бойцов x цена повышения»
        // (PartyBase.OnXpChanged) и после уменьшения стопки срезает излишек. Ручное
        // повышение делает те же шаги, это не ошибка учёта.
        Try("troop upgrades accept native xp cap on remainder", () => {
            var b=Fresh(); MakeWorld(gold:500, prisoners:false); SetLimit("MinGoldReserve",0);
            var p=MobileParty.MainParty; Campaign.Current.Behaviors.Add(new TestViewTracker());
            var target=new CharacterObject { Name="trained" };
            var source=new CharacterObject { Name="recruit", UpgradeTargets=new[] { target } };
            p.MemberRoster.AddToCounts(source,3,xpChange:380);
            Campaign.Current.Models.PartyWageModel.TestTotalWage=(party,roster)=>10;
            Enable(b);
            // Движковое правило: опыт стопки <= Number x 100 (цена в заглушке — 100).
            TroopRoster.TestOnSizeChanged = r => { if (r != p.MemberRoster) return; int i=r.FindIndexOfTroop(source); if (i<0) return;
                var e=r.GetElementCopyAtIndex(i); if (e.Xp > e.Number*100) r.SetElementXp(i, e.Number*100); };
            try { TroopUpgrades.Run(p); } finally { TroopRoster.TestOnSizeChanged=null; }
            Check(!AutopilotLog.Lines.Any(l=>l.Contains("ПРОКАЧКА ОСТАНОВЛЕНА")), "срез опыта по правилу игры не считается несовпадением");
            Check(p.MemberRoster.GetTroopRoster().Where(e=>e.Character==target).Sum(e=>e.Number)==3, "все трое повышены: опыта хватало на каждого");
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
        public int TestUpgradeXpCost=100;
        public int GetUpgradeXpCost(PartyBase party,int index)=>TestUpgradeXpCost;
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
        public static Func<TroopRoster,int,int,int> TestOnSetXp;
        public void SetElementXp(int index,int xp) { var e=_data[index]; e.Xp=TestOnSetXp==null ? xp : TestOnSetXp(this,index,xp); _data[index]=e; }
    }
}
