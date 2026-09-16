using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.Siege;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.Core;

internal static partial class Program
{
    static Settlement ConquestWorld(int food = 35, int gold = 350, int wounded = 3)
    {
        var party = MobileParty.MainParty; var ours = new TestFaction(); var enemy = new TestFaction(); ours.Enemies.Add(enemy);
        party.MapFaction = ours; party.FoodChange = -5; party.TotalWage = 50; Hero.MainHero.Gold = gold;
        party.MemberRoster.AddToCounts(new CharacterObject(), 10, woundedCount: wounded);
        party.ItemRoster.TestAdd(new ItemObject { IsFood = true }, food);
        return new Settlement { IsCastle = true, MapFaction = enemy };
    }
    static void ConquestTests()
    {
        foreach (int shortage in new[] { 0, 1, 2, 3 })
        Try("готовность к наступлению " + shortage, () => {
            var b = Fresh(); var castle = ConquestWorld(shortage == 1 ? 34 : 35, shortage == 2 ? 349 : 350, shortage == 3 ? 4 : 3);
            var town = new Settlement { IsTown = true, MapFaction = MobileParty.MainParty.MapFaction };
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(castle, AiBehavior.BesiegeSettlement, MobileParty.NavigationType.Default, false, false, false), 9f));
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData(town, AiBehavior.GoToSettlement, MobileParty.NavigationType.Default, false, false, false), 2f));
            Enable(b); HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement == (shortage == 0 ? castle : town), "порог 7/7/70, нехватка " + shortage);
        });
        Try("осада: штатная стратегия, ожидание готовности и штурм", () => {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            MobileParty.MainParty.TargetSettlement = castle; MobileParty.MainParty.DefaultBehavior = AiBehavior.BesiegeSettlement;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = castle;
            var siege = new SiegeEvent { BesiegedSettlement = castle }; siege.BesiegerCamp.LeaderParty = MobileParty.MainParty;
            int assaults = 0;
            var wait = new GameMenu { StringId = "menu_siege_strategies", IsWaitMenu = true };
            wait.Options.Add(new GameMenuOption { IdString = "menu_siege_strategies_lead_assault", Consequence = () => assaults++ });
            Show(Menu("castle_outside", "town_besiege", () => { MobileParty.MainParty.SiegeEvent = siege; Show(wait); }));
            b.PollState(); b.PollState();
            Check(siege.BesiegerCamp.SiegeStrategy == DefaultSiegeStrategies.PrepareAssault && wait.IsWaitActive && assaults == 0,
                "осада начата, машины отданы штатной стратегии, раннего штурма нет");
            siege.BesiegerCamp.IsReadyToBesiege = true; b.PollState();
            Check(assaults == 1 && b.CurrentMode == AutopilotBehavior.Mode.Apply, "готовность AI запускает полноценный штурм");
            var battle = new MapEvent { MapEventSettlement = castle, IsSiegeAssault = true, PlayerSide = BattleSideEnum.Attacker };
            MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle;
            Check(b.IsOwnedOperationBattle(MobileParty.MainParty), "наша наступательная осада поддержана боевой миссией");
        });
    }
}
namespace TaleWorlds.CampaignSystem.Siege
{
    public class SiegeStrategy { }
    public static class DefaultSiegeStrategies
    {
        public static SiegeStrategy PrepareAssault { get; } = new();
        public static SiegeStrategy Custom { get; } = new();
        public static System.Collections.Generic.IEnumerable<SiegeStrategy> AllAttackerStrategies => new[] { PrepareAssault };
    }
    public class BesiegerCamp
    {
        public MobileParty LeaderParty { get; set; }
        public bool IsReadyToBesiege { get; set; }
        public SiegeStrategy SiegeStrategy { get; private set; } = DefaultSiegeStrategies.Custom;
        public void SetSiegeStrategy(SiegeStrategy strategy) { SiegeStrategy = strategy; }
    }
    public class SiegeEvent
    {
        public Settlement BesiegedSettlement { get; set; }
        public BesiegerCamp BesiegerCamp { get; } = new();
        public BesiegerCamp GetSiegeEventSide(BattleSideEnum side) => BesiegerCamp;
    }
}
namespace TaleWorlds.CampaignSystem.ComponentInterfaces
{
    public class SiegeEventModel { public float GetSiegeStrategyScore(SiegeEvent siege, BattleSideEnum side, SiegeStrategy strategy) => 1f; }
}
