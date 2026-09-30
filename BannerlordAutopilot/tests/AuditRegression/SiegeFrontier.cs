using System;
using System.Linq;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Siege;

internal static partial class Program
{
    static string FrontierRejection(Settlement target, MobileParty party = null)
        => (string)typeof(AutopilotBehavior).GetMethod("SiegeBorderRejection",
            BindingFlags.Static | BindingFlags.NonPublic).Invoke(null,
                new object[] { party ?? MobileParty.MainParty, target });

    static Settlement FrontierFort(IFaction faction, float x, string id = "fort")
    {
        var fort = new Settlement { IsCastle = true, MapFaction = faction,
            Position = new CampaignVec2 { X = x }, StringId = id, Militia = 1 };
        Settlement.All.Add(fort);
        return fort;
    }

    static Settlement FrontierWorld(float distance = 90)
    {
        Fresh();
        var target = ConquestWorld(wounded: 0);
        target.Position = new CampaignVec2 { X = distance };
        target.StringId = "enemy_target";
        target.Militia = 1;
        Settlement.All.Add(target);
        var home = OwnSiege(x: 0);
        home.StringId = "home_fief";
        home.IsUnderSiege = false;
        return target;
    }

    static void SiegeFrontierTests()
    {
        foreach (string kind in new[] { "own", "friendly", "neutral", "null", "village", "raid", "hostile_siege" })
        Try("frontier ignores nearer non-targets: " + kind, () => {
            var target = FrontierWorld();
            var party = MobileParty.MainParty;
            var friends = new TestFaction();
            // Different friendly/neutral affiliations are deliberately not at war.
            foreach (float x in new[] { 10f, 20f, 30f })
            {
                var faction = kind == "own" ? party.MapFaction
                    : kind == "friendly" || kind == "neutral" ? friends
                    : kind == "null" ? null : target.MapFaction;
                var fort = FrontierFort(faction, x);
                if (kind == "village") { fort.IsCastle = false; fort.IsVillage = true; }
                if (kind == "raid") fort.IsUnderRaid = true;
                if (kind == "hostile_siege") fort.IsUnderSiege = true; // no joinable camp
            }
            Check(FrontierRejection(target) == null, kind + " does not consume enemy top-three quota");
        });
        Try("frontier counts actual enemies across factions and preserves third/fourth", () => {
            var target = FrontierWorld();
            var otherEnemy = new TestFaction();
            ((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Add(otherEnemy);
            FrontierFort(target.MapFaction, 10);
            FrontierFort(otherEnemy, 20);
            Check(FrontierRejection(target) == null, "third eligible enemy is allowed");
            FrontierFort(otherEnemy, 30);
            string reason = FrontierRejection(target);
            Check(reason != null, "fourth eligible enemy is rejected");
            Check(reason != null && reason.Contains("homefief=home_fief")
                && reason.Contains("distance=90.0") && reason.Contains("eligiblecloser=3")
                && reason.Contains("reason=quota"), "quota diagnostic identifies home, distance and enemy count");
            ((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Remove(otherEnemy);
            Check(FrontierRejection(target) == null, "peace immediately removes former enemies from quota");
        });
        Try("frontier retains strict distance ties and inclusive radius", () => {
            var target = FrontierWorld(100);
            FrontierFort(target.MapFaction, 10);
            FrontierFort(target.MapFaction, 20);
            FrontierFort(target.MapFaction, -100);
            Check(FrontierRejection(target) == null, "equal-distance enemy does not count as strictly closer; radius 100 allowed");
            target.Position = new CampaignVec2 { X = 100.01f };
            string reason = FrontierRejection(target);
            Check(reason != null, "radius above 100 rejected");
            Check(reason != null && reason.Contains("homefief=home_fief") && reason.Contains("reason=radius"),
                "radius diagnostic differs from quota");
        });
        Try("joinable allied camps still consume enemy quota", () => {
            var target = FrontierWorld();
            foreach (float x in new[] { 10f, 20f, 30f })
            {
                var fort = FrontierFort(target.MapFaction, x);
                var camp = new MobileParty { MapFaction = MobileParty.MainParty.MapFaction };
                var siege = new SiegeEvent { BesiegedSettlement = fort };
                siege.BesiegerCamp.LeaderParty = camp;
                fort.SiegeEvent = siege; fort.IsUnderSiege = true;
            }
            Check(FrontierRejection(target) != null, "three joinable allied sieges remain eligible enemies");
        });
        foreach (bool mercenary in new[] { false, true })
        Try("frontier uses current map affiliation, mercenary=" + mercenary, () => {
            var target = FrontierWorld();
            var kingdom = new Kingdom();
            kingdom.Enemies.Add(target.MapFaction);
            var party = MobileParty.MainParty;
            party.MapFaction = kingdom;
            Clan.PlayerClan.Kingdom = kingdom;
            Clan.PlayerClan.IsUnderMercenaryService = mercenary;
            // Stub Clan.MapFaction is independent; native resolves Kingdom through MapFaction.
            Clan.PlayerClan.MapFaction = new TestFaction();
            Clan.PlayerClan.Fiefs.Clear();
            var home = OwnSiege(x: 0); home.IsUnderSiege = false;
            foreach (float x in new[] { 10f, 20f, 30f }) FrontierFort(kingdom, x);
            Check(FrontierRejection(target) == null, "kingdom members do not occupy hostile quota");
            kingdom.Enemies.Clear();
            Check(FrontierRejection(target) != null, "affiliation's current peace rejects former target");
        });
        Try("frontier with no valid home uses party radius without top-three quota", () => {
            var target = FrontierWorld(100);
            Clan.PlayerClan.Fiefs.Clear();
            foreach (float x in new[] { 10f, 20f, 30f }) FrontierFort(target.MapFaction, x);
            Check(FrontierRejection(target) == null, "no-home radius 100 ignores quota as before");
            target.Position = new CampaignVec2 { X = 101 };
            Check(FrontierRejection(target) != null, "no-home distance over 100 rejected");
            Clan.PlayerClan = null;
            MobileParty.MainParty.Position = target.Position;
            Check(FrontierRejection(target) == null, "null clan keeps no-home fallback");
        });
        Try("invalid offensive targets cannot pass frontier eligibility", () => {
            var target = FrontierWorld();
            Check(FrontierRejection(null) != null, "null target rejected");
            var border = typeof(AutopilotBehavior).GetMethod("SiegeBorderRejection", BindingFlags.Static | BindingFlags.NonPublic);
            Check(border.Invoke(null, new object[] { null, target }) != null, "null party rejected");
            target.IsUnderRaid = true;
            Check(FrontierRejection(target) != null, "raid target rejected by same eligibility as ranking");
            target.IsUnderRaid = false; target.IsUnderSiege = true;
            Check(FrontierRejection(target) != null, "unjoinable siege target rejected");
            target.IsUnderSiege = false;
            target.MapFaction = null;
            Check(FrontierRejection(target) != null, "null target faction rejected");
            target.MapFaction = MobileParty.MainParty.MapFaction;
            Check(FrontierRejection(target) != null, "own target rejected");
            target.MapFaction = new TestFaction();
            Check(FrontierRejection(target) != null, "neutral target rejected");
            MobileParty.MainParty.MapFaction = null;
            Check(FrontierRejection(target) != null, "null attacking faction rejected");
        });
        Try("independent and native siege selection both ignore peaceful quota occupants", () => {
            foreach (bool native in new[] { false, true })
            {
                var target = FrontierWorld();
                var party = MobileParty.MainParty;
                foreach (float x in new[] { 10f, 20f, 30f }) FrontierFort(party.MapFaction, x);
                var b = new AutopilotBehavior { RandomDialogsEnabled = false };
                if (native) Scores((AiBehavior.BesiegeSettlement, target, 999f));
                Enable(b); HourlyTick(b);
                Check(SiegeTarget(b) == target && party.TargetSettlement == target,
                    (native ? "native" : "independent") + " issued siege reaches enemy target");
            }
        });
        Try("geographic-only failure is logged once per day without strength claim", () => {
            var target = FrontierWorld(101);
            var b = new AutopilotBehavior { RandomDialogsEnabled = false };
            Enable(b);
            for (int hour = 0; hour < 12; hour++) { CampaignTime.TestHours = hour; HourlyTick(b); }
            Check(AutopilotLog.Lines.Count(l => l.Contains("ПОХОД:") && l.Contains("географ")) == 1,
                "one daily geographic summary");
            Check(!AutopilotLog.Lines.Any(l => l.Contains("крепостей по силам нет")),
                "geographic-only failure does not claim insufficient strength");
            Check(AutopilotLog.Lines.Any(l => l.Contains("target=enemy_target") && l.Contains("homefief=home_fief")),
                "daily summary carries a rejected target and anchor");
        });
    }
}
