using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;

internal static partial class Program
{
    // Native 1.4.8 evidence (D:/shedlink-build/bl-decomp/TaleWorlds.CampaignSystem.decompiled.cs):
    // DesertersCampaignBehavior.SpawnDesertersParty:180288 -> CreateLooterParty:109998
    // creates BanditPartyComponent; UpdatePartyComponentFlags:104167 sets IsBandit.
    // Thus the ordinary bandit fixture models native deserters without special name matching.
    // These tests call real production gathering through PollState; engine creation is not simulated.
    static TestFaction DeserterFaction()
    {
        var faction = new TestFaction();
        ((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Add(faction);
        faction.Enemies.Add(MobileParty.MainParty.MapFaction);
        return faction;
    }

    static void DeserterGatheringTests()
    {
        Try("обычные дезертиры и грабители собираются совместно", () => {
            var w = GatheringWorld();
            var deserters = GatherCandidate("Дезертиры", 30, 1, DeserterFaction());
            var looters = GatherCandidate("Грабители", 30, 2, w.Bandits);
            w.Pilot.PollState();
            Check(deserters.MapEvent == w.Battle && looters.MapEvent == w.Battle,
                "обе совместимые бандитские фракции добраны с 40 до 100 силы");
            Check(deserters.Position.X == 0 && looters.Position.X == 0 && MenuContext.Invoked.Contains("attack"),
                "дезертиры присоединены штатным setter до обычной атаки");
        });
        Try("дезертиры могут быть исходной целью общего боя", () => {
            var w = GatheringWorld();
            var target = PlayerEncounter.EncounteredMobileParty;
            target.Name = "Дезертиры";
            target.MapFaction = DeserterFaction(); target.Party.MapFaction = target.MapFaction;
            var looters = GatherCandidate("Грабители", 60, 1, w.Bandits);
            w.Pilot.PollState();
            Check(looters.MapEvent == w.Battle && looters.Party.TestJoinCalls == 1,
                "начало боя с дезертирами не запрещает добор грабителей");
        });
        Try("вражда дезертиров с исходными бандитами запрещает смешивание", () => {
            var w = GatheringWorld(); var deserterFaction = DeserterFaction();
            w.Bandits.Enemies.Add(deserterFaction); deserterFaction.Enemies.Add(w.Bandits);
            var deserters = GatherCandidate("Дезертиры", 60, 1, deserterFaction);
            var looters = GatherCandidate("Грабители", 60, 2, w.Bandits);
            w.Pilot.PollState();
            Check(deserters.MapEvent == null && deserters.Position.X == 1 && looters.MapEvent == w.Battle,
                "совместимость сторон решает CanPartyJoinBattle, название не обходит дипломатию");
        });
        foreach (string reason in new[] { "army", "battle", "far", "too-strong" })
        Try("дезертиры исключаются по общим ограничениям: " + reason, () => {
            var w = GatheringWorld();
            var deserters = GatherCandidate("Дезертиры", reason == "too-strong" ? 81 : 60, 1, DeserterFaction());
            if (reason == "army") deserters.Army = new Army();
            if (reason == "battle") deserters.MapEvent = new MapEvent();
            if (reason == "far") deserters.Position = new CampaignVec2 { X = 121 };
            float before = deserters.Position.X;
            w.Pilot.PollState();
            Check(deserters.MapEvent != w.Battle && deserters.Party.TestJoinCalls == 0 && deserters.Position.X == before,
                "добор не перемещает дезертиров при " + reason);
        });
        Try("квестовых дезертиров нельзя похищать из задания", () => {
            var w = GatheringWorld();
            var deserters = GatherCandidate("Квестовые дезертиры", 60, 1, DeserterFaction());
            deserters.IsCurrentlyUsedByAQuest = true;
            var ordinary = GatherCandidate("Обычные дезертиры", 60, 2, deserters.MapFaction as TestFaction);
            w.Pilot.PollState();
            Check(deserters.MapEvent == null && deserters.Position.X == 1 && deserters.Party.TestJoinCalls == 0,
                "квестовый отряд не телепортирован и не включён в чужой бой");
            Check(ordinary.MapEvent == w.Battle, "ограничение задания не запрещает обычных дезертиров той же фракции");
        });
        Try("бой с квестовыми дезертирами не усиливается внешними отрядами", () => {
            var w = GatheringWorld();
            PlayerEncounter.EncounteredMobileParty.IsCurrentlyUsedByAQuest = true;
            var ordinary = GatherCandidate("Обычные дезертиры", 60, 1, DeserterFaction());
            w.Pilot.PollState();
            Check(ordinary.MapEvent == null && ordinary.Position.X == 1,
                "исходный квестовый бой сохраняет свой состав противников");
        });
    }
}
