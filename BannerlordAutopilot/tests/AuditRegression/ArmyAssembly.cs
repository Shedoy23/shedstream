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
    static object ArmyCall(AutopilotBehavior b, string method, params object[] args) =>
        typeof(AutopilotBehavior).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic).Invoke(b, args);

    static void ArmyAssemblyTests()
    {
        foreach (string outcome in new[] { "arrived", "departed", "inactive", "timeout", "pending" })
        Try("army actual assembly " + outcome, () => {
            var b = Fresh(); var castle = ConquestWorld(wounded: 0); castle.Militia = 15;
            var party = MobileParty.MainParty; var kingdom = new Kingdom(); kingdom.Enemies.Add(castle.MapFaction);
            party.MapFaction = kingdom; Clan.PlayerClan.Kingdom = kingdom; Clan.PlayerClan.Influence = 100;
            var ally = new MobileParty { MapFaction = kingdom };
            ally.MemberRoster.AddToCounts(new CharacterObject { Tier = 4 }, 30);
            ally.ItemRoster.TestAdd(new ItemObject { IsFood = true }, 35);
            party.ThinkParamsCache.PossibleArmyMembersUponArmyCreation.Add(ally);
            Enable(b);
            var objective = new AIBehaviorData(castle, AiBehavior.BesiegeSettlement,
                MobileParty.NavigationType.Default, true, false, false);
            Check((bool)ArmyCall(b, "StartArmy", party, objective, 9f), "assembly starts: " + outcome);
            if (outcome == "arrived") { ally.AttachedTo = party; party.AttachedParties.Add(ally); }
            if (outcome == "departed") ally.Army = null;
            if (outcome == "inactive") ally.IsActive = false;
            if (outcome == "timeout") CampaignTime.TestHours += 24;
            ArmyCall(b, "PollArmy", party);
            if (outcome == "pending")
            {
                Check(party.TargetSettlement != castle && !AutopilotLog.Lines.Any(l => l.Contains("АРМИЯ: сбор завершён")),
                    "pending invitee is still awaited before deadline");
                return;
            }
            Check((party.TargetSettlement == castle) == (outcome == "arrived"),
                "only actually sufficient assembled troops march: " + outcome);
            string expected = outcome == "arrived" ? "прибыли все" : outcome == "timeout" ? "истекли 24" : "потеря приглашений";
            Check(AutopilotLog.Lines.Any(l => l.Contains("АРМИЯ: сбор завершён") && l.Contains(expected)
                && l.Contains(outcome == "arrived" ? "прибыли 1/1" : "прибыли 0/1")),
                "assembly outcome distinguishes actual arrivals: " + outcome);
            if (outcome == "arrived") return;
            Check((bool)ArmyCall(b, "SiegeRecentlyRejected", castle), "failed actual strength records siege cooldown: " + outcome);
            party.Army = null; ally.Army = null; ally.IsActive = true;
            float before = Clan.PlayerClan.Influence;
            Check(!(bool)ArmyCall(b, "StartArmy", party, objective, 9f) && Clan.PlayerClan.Influence == before,
                "same rejected target cannot spend influence on immediate reassembly: " + outcome);
        });
    }
}
