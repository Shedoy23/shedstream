using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    static void RecoveryTests()
    {
        foreach(string route in new[] { "hunt", "initiative", "scores" })
        foreach(string health in new[] { "69", "70", "hero" })
        Try("recovery gates voluntary attack " + route + " " + health, () => {
            var (b, enemy)=HuntWorld(men:100); var p=MobileParty.MainParty;
            p.MemberRoster.AddToCounts(p.MemberRoster.GetTroopRoster().First().Character,0,
                woundedCount:health=="69" ? 31 : 30);
            Hero.MainHero.IsWounded=health=="hero";
            var target=HuntTarget("recovergate",10,3,enemy,speed:3f);
            if(route!="hunt") MobileParty.All.Remove(target);
            if(route=="initiative") {
                Campaign.Current.Models.MobilePartyAIModel.NextBehavior=AiBehavior.EngageParty;
                Campaign.Current.Models.MobilePartyAIModel.NextTarget=target;
                Campaign.Current.Models.MobilePartyAIModel.NextScore=3.5f;
            } else if(route=="scores") Scores((AiBehavior.EngageParty,target,3.5f));
            HourlyTick(b);
            Check((p.DefaultBehavior==AiBehavior.EngageParty)==(health=="70"),
                "voluntary route respects exact 70% and hero health " + route + " " + health);
        });
        Try("recovery selects nearest peaceful fort instead of another fight", () => {
            var (b, enemy)=HuntWorld(men:100); var p=MobileParty.MainParty;
            Hero.MainHero.IsWounded=true;
            var unsafeTown=new Settlement { Name="besieged", IsTown=true, IsUnderSiege=true, MapFaction=p.MapFaction, Position=new CampaignVec2 { X=1 } };
            var near=new Settlement { Name="safe near", IsCastle=true, MapFaction=p.MapFaction, Position=new CampaignVec2 { X=5 } };
            var far=new Settlement { Name="safe far", IsTown=true, MapFaction=p.MapFaction, Position=new CampaignVec2 { X=15 } };
            Settlement.All.Add(unsafeTown); Settlement.All.Add(far); Settlement.All.Add(near);
            HourlyTick(b);
            Check(p.DefaultBehavior==AiBehavior.GoToSettlement && p.TargetSettlement==near,"wounded hero goes to nearest safe fort");
        });
        Try("recovery wait releases at 70%, not full healing", () => {
            var (b, enemy)=HuntWorld(men:100); var p=MobileParty.MainParty;
            var troop=p.MemberRoster.GetTroopRoster().First().Character;
            p.MemberRoster.AddToCounts(troop,0,woundedCount:31);
            var town=ArriveTown(new Settlement { Name="heal", IsTown=true, MapFaction=p.MapFaction });
            b.PollState(); b.PollState();
            var next=new Settlement { Name="next", MapFaction=p.MapFaction };
            Scores((AiBehavior.GoToSettlement,next,10f));
            HourlyTick(b); b.PollState();
            Check(p.CurrentSettlement==town && Waiting,"69% healthy stays in native wait");
            p.MemberRoster.AddToCounts(troop,0,woundedCount:-1);
            HourlyTick(b); b.PollState();
            Check(p.CurrentSettlement==null && p.TargetSettlement==next,"70% healthy resumes without waiting for 100%");
        });
        Try("recovery hungry castle routes to food town", () => {
            var (b, enemy)=HuntWorld(men:100); var p=MobileParty.MainParty;
            Hero.MainHero.IsWounded=true; p.FoodChange=-5;
            var castle=new Settlement { Name="no food", IsCastle=true, MapFaction=p.MapFaction, Position=new CampaignVec2 { X=1 } };
            var town=new Settlement { Name="food", IsTown=true, MapFaction=p.MapFaction, Position=new CampaignVec2 { X=10 } };
            town.ItemRoster.TestAdd(new TaleWorlds.Core.ItemObject { IsFood=true },100);
            Settlement.All.Add(castle); Settlement.All.Add(town);
            HourlyTick(b);
            Check(p.TargetSettlement==town,"low food skips castle where food cannot be bought");
        });
    }
}