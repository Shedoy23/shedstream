using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Siege;
using TaleWorlds.Core;

internal static partial class Program
{
    static void SiegeTransitionTests()
    {
        Try("disable preserves operation diagnostics", () => {
            var b = Fresh(); Enable(b); var place = Siege();
            Show(Menu("join_siege_event", "join_siege_event_break_in", () => {}));
            b.PollState();
            b.Disable("test transition");
            Check(AutopilotLog.Lines.Any(line => line.Contains("ОПЕРАЦИЯ ПРИ ВЫКЛЮЧЕНИИ:")
                && line.Contains("join_siege_event")), "disable logs operation menu before session reset");
        });
        foreach (string completion in new[] { "siege_attacker_defeated", "siege_attacker_left", "unrelated", "different_settlement" })
        Try("owned defender completion " + completion, () => {
            var b = Fresh(); Enable(b); var place = Siege();
            Show(Menu("join_siege_event", "join_siege_event_break_in", () => {
                MobileParty.MainParty.CurrentSettlement = place;
                Show(new GameMenu { StringId = "menu_siege_strategies", IsWaitMenu = true });
            }));
            b.PollState();
            var battle = new MapEvent { MapEventSettlement = place, IsSiegeAssault = true, PlayerSide = BattleSideEnum.Defender };
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle;
            Show(Menu("encounter", "attack", () => {})); b.PollState();
            b.OnOperationMissionEnded();
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = null;
            place.IsUnderSiege = false;
            int exits = 0;
            if (completion == "different_settlement")
                MobileParty.MainParty.CurrentSettlement = new TaleWorlds.CampaignSystem.Settlements.Settlement();
            string menu = completion == "different_settlement" ? "siege_attacker_defeated" : completion;
            Show(Menu(menu, menu + "_leave", () => { exits++; PlayerEncounter.Finish(); }));
            b.PollState();
            bool owned = completion == "siege_attacker_defeated" || completion == "siege_attacker_left";
            Check(exits == (owned ? 1 : 0), "only owned native completion is clicked: " + completion);
            Check(b.CurrentMode == (owned ? AutopilotBehavior.Mode.Apply : AutopilotBehavior.Mode.Off),
                "known completion stays enabled, unknown encounter remains protected: " + completion);
        });
        Try("allied siege native camp then assault", () => {
            var b = Fresh(); var place = ConquestWorld(wounded: 0); var party = MobileParty.MainParty;
            var camp = new MobileParty { IsLordParty = true, MapFaction = party.MapFaction };
            camp.Party.MapFaction = party.MapFaction;
            var siege = new SiegeEvent { BesiegedSettlement = place };
            siege.BesiegerCamp.LeaderParty = camp; place.SiegeEvent = siege; place.IsUnderSiege = true;
            camp.BesiegerCamp = siege.BesiegerCamp; MobileParty.All.Add(camp);
            Enable(b); party.DefaultBehavior = AiBehavior.BesiegeSettlement; party.TargetSettlement = place;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = place;
            var wait = new GameMenu { StringId = "menu_siege_strategies", IsWaitMenu = true };
            Show(Menu("join_siege_event", "join_siege_event", () => {
                PlayerEncounter.Finish(); party.BesiegerCamp = siege.BesiegerCamp; party.SiegeEvent = siege;
                Show(wait);
            }));
            b.PollState(); b.PollState();
            Check(wait.IsWaitActive && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                "native allied join ends encounter and remains in active siege wait");
            PlayerEncounter.Current = new PlayerEncounter();
            PlayerEncounter.EncounterSettlement = place;
            party.MapEvent = PlayerEncounter.Battle = new MapEvent {
                MapEventSettlement = place, IsSiegeAssault = true, PlayerSide = BattleSideEnum.Attacker };
            int attacks = 0; Show(Menu("encounter", "attack", () => attacks++)); b.PollState();
            Check(attacks == 1 && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                "allied assault remains owned after native camp transition");
        });
    }
}
