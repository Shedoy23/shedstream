using System;
using System.Linq;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

internal static partial class Program
{
    static (AutopilotBehavior Pilot, Settlement Castle, MobileParty Ally, AIBehaviorData Goal) AssemblyWorld(
        int own = 100, int defense = 150, int allyStrength = 90, float distance = 40, float speed = 4)
    {
        var b = Fresh(); var castle = ConquestWorld(food:200, gold:50000, wounded:0);
        castle.StringId = "town_V6"; castle.Name = "Жакулан"; castle.Militia = defense;
        Settlement.All.Add(castle);
        var p = MobileParty.MainParty; p.MemberRoster.AddToCounts(Veteran(), own - 10);
        var kingdom = new Kingdom(); kingdom.Enemies.Add(castle.MapFaction);
        p.MapFaction = p.Party.MapFaction = kingdom; Clan.PlayerClan.Kingdom = kingdom;
        Clan.PlayerClan.Influence = 1000;
        var ally = new MobileParty { Name="Первый союзник", StringId="first_ally", IsLordParty=true,
            MapFaction=kingdom, Speed=speed, Position=new CampaignVec2 { X=distance } };
        ally.Party.MapFaction=kingdom;
        ally.MemberRoster.AddToCounts(Veteran(), allyStrength);
        ally.ItemRoster.TestAdd(new ItemObject { IsFood=true }, 200);
        MobileParty.All.Add(ally); p.ThinkParamsCache.PossibleArmyMembersUponArmyCreation.Add(ally);
        Enable(b);
        return (b,castle,ally,new AIBehaviorData(castle,AiBehavior.BesiegeSettlement,
            MobileParty.NavigationType.Default,true,false,false));
    }

    static void AttachArmyMember(MobileParty ally)
    {
        ally.AttachedTo=MobileParty.MainParty;
        if(!MobileParty.MainParty.AttachedParties.Contains(ally)) MobileParty.MainParty.AttachedParties.Add(ally);
    }

    static void ArmyContinuityTests()
    {
        foreach(var force in new[]{(Own:1499,Defense:1044),(Own:1847,Defense:1295),(Own:1960,Defense:1318)})
        Try("Jaculan logged army now qualifies "+force.Own,()=> {
            var w=AssemblyWorld(own:force.Own,defense:force.Defense); w.Ally.IsActive=false;
            var plain=new AIBehaviorData(w.Castle,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false);
            Check(ArmyCall(w.Pilot,"WhyNotApplicable",plain)==null,"actual logged army passes new x1.2 entry");
        });
        foreach(int own in new[]{119,120}) Try("new siege entry x1.2 boundary "+own,()=> {
            var w=AssemblyWorld(own:own,defense:100); w.Ally.IsActive=false;
            MobileParty.MainParty.ThinkParamsCache.PossibleArmyMembersUponArmyCreation.Clear();
            var plain=new AIBehaviorData(w.Castle,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false);
            Check((ArmyCall(w.Pilot,"WhyNotApplicable",plain)==null)==(own==120),"entry accepts exactly x1.2 and rejects below");
        });

        foreach(int defense in new[]{105,110}) Try("committed march has separate margin "+defense,()=> {
            var w=AssemblyWorld(own:120,defense:100); w.Ally.IsActive=false;
            ArmyCall(w.Pilot,"ApplyDecision",MobileParty.MainParty,
                new AIBehaviorData(w.Castle,AiBehavior.BesiegeSettlement,MobileParty.NavigationType.Default,false,false,false),9f);
            w.Castle.Militia=defense;
            HourlyTick(w.Pilot);
            Check((MobileParty.MainParty.TargetSettlement==w.Castle && MobileParty.MainParty.IsMoving)==(defense==105),
                "march continues above x1.1, cancels below x1.1");
        });

        Try("near arriving reinforcements survive old 24 hour deadline",()=> {
            var w=AssemblyWorld(); var p=MobileParty.MainParty;
            Check((bool)ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f),"army created");
            CampaignTime.TestHours=24; w.Ally.Position=new CampaignVec2 {X=8};
            ArmyCall(w.Pilot,"PollArmy",p); ArmyCall(w.Pilot,"DisbandIdleArmy",p);
            Check(p.Army!=null && !AutopilotLog.Lines.Any(l=>l.Contains("сбор завершён")),"still awaits near sufficient pending force at 24 hours");
            CampaignTime.TestHours=27; AttachArmyMember(w.Ally); ArmyCall(w.Pilot,"PollArmy",p);
            Check(p.TargetSettlement==w.Castle && p.IsMoving,"arrivals after 24 hours enable actual march");
        });

        Try("gathering has hard cap even if allies never attach",()=> {
            var w=AssemblyWorld(); var p=MobileParty.MainParty;
            ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f);
            CampaignTime.TestHours=73; ArmyCall(w.Pilot,"PollArmy",p);
            Check(AutopilotLog.Lines.Any(l=>l.Contains("сбор завершён")) && p.TargetSettlement!=w.Castle,"unattached future force cannot march after bounded wait");
        });

        foreach(bool replaceArmy in new[]{false,true}) Try("F12 resumes only same owned army "+replaceArmy,()=> {
            var w=AssemblyWorld(); var p=MobileParty.MainParty;
            ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f);
            CampaignTime.TestHours=5; w.Pilot.Disable("выключено игроком (F12)");
            if(replaceArmy) p.Army=new Army {LeaderParty=new MobileParty()};
            CampaignTime.TestHours=100; Enable(w.Pilot); ArmyCall(w.Pilot,"PollArmy",p);
            if(replaceArmy) Check(p.TargetSettlement!=w.Castle,"foreign replacement army does not inherit stale goal");
            else {
                Check(!AutopilotLog.Lines.Any(l=>l.Contains("сбор завершён")),"time while off does not expire resumed gathering");
                AttachArmyMember(w.Ally); ArmyCall(w.Pilot,"PollArmy",p);
                Check(p.TargetSettlement==w.Castle,"same gathering objective survives toggle");
            }
        });

        Try("failed assembled force is not immediately recycled after cooldown",()=> {
            var w=AssemblyWorld(allyStrength:20); var p=MobileParty.MainParty;
            // Force the call directly: simulate a viable plan whose defenders grew during travel.
            ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f); AttachArmyMember(w.Ally); ArmyCall(w.Pilot,"PollArmy",p);
            CampaignTime.TestHours=13; p.Army=null; w.Ally.Army=null; w.Ally.AttachedTo=null; p.AttachedParties.Clear();
            var before=Clan.PlayerClan.Influence;
            Check(!(bool)ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f) && Clan.PlayerClan.Influence==before,"same rejected potential army cannot spend influence again when 12 hours expire");
        });

        Try("failed army can retry after actual defenders weaken",()=> {
            var w=AssemblyWorld(allyStrength:20); var p=MobileParty.MainParty;
            ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f); AttachArmyMember(w.Ally); ArmyCall(w.Pilot,"PollArmy",p);
            CampaignTime.TestHours=13; p.Army=null; w.Ally.Army=null; w.Ally.AttachedTo=null; p.AttachedParties.Clear();
            w.Castle.Militia=90;
            Check((bool)ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f),"observed defense reduction unlocks retry");
        });

        Try("existing army calls fresh reinforcement instead of disbanding",()=> {
            var w=AssemblyWorld(allyStrength:20); var p=MobileParty.MainParty;
            ArmyCall(w.Pilot,"StartArmy",p,w.Goal,9f); AttachArmyMember(w.Ally);
            var fresh=new MobileParty {Name="Подкрепление",StringId="second_ally",IsLordParty=true,MapFaction=p.MapFaction};
            fresh.Party.MapFaction=p.MapFaction; fresh.MemberRoster.AddToCounts(Veteran(),80);
            fresh.ItemRoster.TestAdd(new ItemObject {IsFood=true},200); MobileParty.All.Add(fresh);
            var army=p.Army; ArmyCall(w.Pilot,"PollArmy",p);
            Check(fresh.Army==army && p.Army==army && p.TargetSettlement!=w.Castle,"insufficient actual force invites reinforcement into same army");
            AttachArmyMember(fresh); ArmyCall(w.Pilot,"PollArmy",p);
            Check(p.TargetSettlement==w.Castle,"reinforced existing army marches after actual arrival");
        });

        Try("definitely late invitees do not inflate siege forecast",()=> {
            var w=AssemblyWorld(allyStrength:150,distance:150,speed:1); var p=MobileParty.MainParty;
            var method=typeof(AutopilotBehavior).GetMethod("TryFindSiegeTarget",BindingFlags.Instance|BindingFlags.NonPublic);
            var args=new object[]{p,default(AIBehaviorData),0f};
            Check(!(bool)method.Invoke(w.Pilot,args),"150-hour lower-bound arrival cannot justify bounded assembly");
        });
    }
}
