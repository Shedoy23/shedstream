using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Siege;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.CampaignSystem.GameState;

internal static partial class Program
{
    // 24.09: 18.09 и 21.09 армия ~270 → 1 в бою у своей же осады — автопилот
    // принимал бой при любом перевесе врага. Порог тот же, что у отхода на карте:
    // враг от 5x везде (владелец 25.09; было 2x, при обороне своего замка — 5x).
    static void HopelessBattleTests()
    {
        foreach (var (enemy, lift) in new[] { (55, true), (45, false) })
        Try("к осадному лагерю идёт армия x" + (enemy / 10.0), () =>
        {
            var b = Fresh(); var castle = ConquestWorld(); Enable(b);
            var siege = new SiegeEvent { BesiegedSettlement = castle }; siege.BesiegerCamp.LeaderParty = MobileParty.MainParty;
            siege.BesiegerCamp.IsReadyToBesiege = true; MobileParty.MainParty.SiegeEvent = siege;
            HuntTarget("армия помощи", enemy, 8, castle.MapFaction);
            var wait = new GameMenu { StringId = "menu_siege_strategies", IsWaitMenu = true };
            wait.Options.Add(new GameMenuOption { IdString = "menu_siege_strategies_lead_assault" });
            wait.Options.Add(new GameMenuOption { IdString = "menu_siege_strategies_leave" }); Show(wait); b.PollState();
            Check(MenuContext.Invoked.Contains("menu_siege_strategies_leave") == lift
                && MenuContext.Invoked.Contains("menu_siege_strategies_lead_assault") != lift,
                (lift ? "снимаем осаду до удара" : "по силам — штурмуем") + ": " + string.Join(",", MenuContext.Invoked));
        });
        foreach (var (ours, theirs, retreat) in new[] { (100f, 550f, true), (100f, 450f, false), (100f, 150f, false) })
        Try("бой в поле, силы " + ours + " против " + theirs, () =>
        {
            var b = Fresh(); ConquestWorld(); Enable(b);
            PlayerEncounter.Current = new PlayerEncounter();
            var battle = new MapEvent(); MobileParty.MainParty.MapEvent = PlayerEncounter.Battle = battle;
            battle.StrengthOfSide[(int)TaleWorlds.Core.BattleSideEnum.Attacker] = ours;
            battle.StrengthOfSide[(int)TaleWorlds.Core.BattleSideEnum.Defender] = theirs;
            string pressed = null;
            var menu = Menu("encounter", "attack", () => pressed = pressed ?? "attack");
            menu.Options.Add(new GameMenuOption { IdString = "leave_soldiers_behind", IsEnabled = true, Consequence = () => pressed = pressed ?? "leave_soldiers_behind" });
            Show(menu); b.PollState();
            Check(pressed == (retreat ? "leave_soldiers_behind" : "attack"), "нажато «" + pressed + "»");
        });
            // Бой за свой замок: порог 5x (владелец 23.09, лог 22.09: отбивали ~5,2x).
        foreach (var (theirs, retreat) in new[] { (300f, false), (600f, true) })
        Try("бой за свой замок против " + theirs + " при наших 100", () =>
        {
            var b = Fresh(); ConquestWorld(wounded: 0); var own = OwnSiege(); Enable(b); HourlyTick(b);
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = own; PlayerEncounter.EncounteredMobileParty = new MobileParty();
            var battle = new MapEvent { MapEventSettlement = own, IsSiegeOutside = true, PlayerSide = TaleWorlds.Core.BattleSideEnum.Defender };
            MobileParty.MainParty.Party.Side = TaleWorlds.Core.BattleSideEnum.Defender;
            battle.StrengthOfSide[(int)TaleWorlds.Core.BattleSideEnum.Defender] = 100f;
            battle.StrengthOfSide[(int)TaleWorlds.Core.BattleSideEnum.Attacker] = theirs;
            PlayerEncounter.EncounteredBattle = battle;
            string pressed = null;
            var fight = Menu("encounter", "attack", () => pressed = pressed ?? "attack");
            fight.Options.Add(new GameMenuOption { IdString = "leave_soldiers_behind", IsEnabled = true, Consequence = () => pressed = pressed ?? "leave_soldiers_behind" });
            Show(Menu("join_encounter", "join_encounter_help_defenders", () => { MobileParty.MainParty.MapEvent = battle; PlayerEncounter.Battle = battle; Show(fight); }));
            b.PollState(); b.PollState();
            Check(pressed == (retreat ? "leave_soldiers_behind" : "attack"), "нажато «" + pressed + "»");
        });
        // 18.09 19:54:09 «прекращаем цель «Замок Астер»: защитники 449 > предел 408» →
        // через 3 с «найдена крепость … Замок Астер» — отряд вышел из круга подсчёта.
        Try("отказ от крепости по силам не отменяется через минуту", () =>
        {
            var b = Fresh(); var castle = ConquestWorld(); castle.Name = "Замок Астер"; castle.Militia = 5;
            Settlement.All.Add(castle); Enable(b); HourlyTick(b);
            Check(SiegeTarget(b) == castle, "сначала крепость по силам — идём");
            var relief = new MobileParty { Name = "подмога", MapFaction = castle.MapFaction, Position = castle.Position };
            relief.Party.MapFaction = castle.MapFaction;
            relief.MemberRoster.AddToCounts(new CharacterObject { Name = "страж", StringId = "guard" }, 30);
            MobileParty.All.Add(relief);
            for (int h = 0; h < 7; h++) HourlyTick(b);
            Check(LogCount("прекращаем цель «Замок Астер»") + LogCount("«Замок Астер» больше не предложена") >= 1, "защитников стало больше предела — отказались");
            Check(MobileParty.MainParty.TargetSettlement != castle, "отказались — к этой крепости больше не идём");
            MobileParty.All.Remove(relief);
            for (int h = 0; h < 7; h++) HourlyTick(b);
            Check(SiegeTarget(b) != castle && MobileParty.MainParty.TargetSettlement != castle,
                "подмога отошла, но 12 часов крепость не берём снова: " + MobileParty.MainParty.TargetSettlement?.Name);
        });
}
}
