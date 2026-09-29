using System;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

internal static partial class Program
{
    static void CampaignCommitmentTests()
    {
        foreach(bool inquiry in new[] {false,true})
        Try("deferred campaign execution guard "+inquiry, () => {
            var b=Fresh(); var castle=ConquestWorld(food:200,gold:5000,wounded:0); castle.Militia=1;
            Settlement.All.Add(castle); var p=MobileParty.MainParty; p.Party.PartySizeLimit=10;
            Enable(b);
            var apply=typeof(AutopilotBehavior).GetMethod("ApplyDecision",BindingFlags.Instance|BindingFlags.NonPublic);
            var goal=new AIBehaviorData(castle,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false);
            apply.Invoke(b,new object[] {p,goal,8f});
            p.SetMoveModeHold();
            if(inquiry) { TaleWorlds.Library.InformationManager.TestInquiryActive=true; HourlyTick(b); }
            else { ((TestFaction)p.MapFaction).Enemies.Clear(); apply.Invoke(b,new object[] {p,goal,8f}); }
            Check(!p.IsMoving,"pending march is not issued through modal or after peace: "+inquiry);
        });

        foreach (string scenario in new[] { "hunt", "patrol", "margin", "overload", "peace", "stronger", "food" })
        Try("committed siege campaign " + scenario, () => {
            var b = Fresh(); var castle = ConquestWorld(food:200, gold:5000, wounded:0);
            castle.Name="Campaign castle"; castle.Position=new CampaignVec2 { X=80 }; castle.Militia=1;
            Settlement.All.Add(castle);
            var p=MobileParty.MainParty; p.Party.PartySizeLimit=10; p.Party.MapFaction=p.MapFaction;
            var market=new Settlement { Name="Market", IsTown=true, MapFaction=p.MapFaction, Position=new CampaignVec2 { X=20 } };
            Settlement.All.Add(market); Campaign.Current.Behaviors.Add(new TestViewTracker());
            var loot=new ItemObject { Name="loot", TestPrice=20 }; p.ItemRoster.TestAdd(loot,5);
            Enable(b);
            typeof(AutopilotBehavior).GetMethod("ApplyDecision", BindingFlags.Instance|BindingFlags.NonPublic)
                .Invoke(b,new object[] {p,new AIBehaviorData(castle,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false),8f});
            if(scenario=="hunt") HuntTarget("minor distraction",3,8,castle.MapFaction,speed:3f);
            if(scenario=="patrol") CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(market,AiBehavior.PatrolAroundPoint,MobileParty.NavigationType.Default,false,false,false),99f));
            if(scenario=="margin") p.TotalWeightCarried=96;
            if(scenario=="overload") p.TotalWeightCarried=150;
            if(scenario=="peace") ((TestFaction)p.MapFaction).Enemies.Clear();
            if(scenario=="stronger") castle.Militia=100;
            if(scenario=="food") p.FoodChange=-100;
            HourlyTick(b);
            if(scenario=="peace" || scenario=="stronger" || scenario=="food")
                Check(!(p.TargetSettlement==castle && p.IsMoving),"invalid or unprepared campaign is cancelled: "+scenario);
            else if(scenario=="overload") {
                Check(p.TargetSettlement==market,"real overload routes to safe market");
                b.PollState(); // free-map poll used to clear offensive ownership during diversion
                p.TotalWeightCarried=20; p.ItemRoster.TestAdd(loot,-5);
                var alternative=new Settlement { Name="Another castle",IsCastle=true,MapFaction=castle.MapFaction,Militia=1 };
                Settlement.All.Add(alternative);
                CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(alternative,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false),99f));
                HourlyTick(b);
                Check(p.TargetSettlement==castle && p.DefaultBehavior==AiBehavior.GoToSettlement,"original siege resumes after unloading");
            }
            else Check(p.TargetSettlement==castle && p.DefaultBehavior==AiBehavior.GoToSettlement,"valid committed siege survives distraction: "+scenario);
        });
    }
}
