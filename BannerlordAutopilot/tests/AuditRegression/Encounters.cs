using System;
using System.Linq;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

// Прогон 16.09.2026, сборка bdb5982. Игра (rgl_log_37644) открыла join_encounter
// в 19:44:42, пока автопилот гнался за грабителями; журнал автопилота молчал 24 с,
// меню закрыл человек. Там же простой «96 с» сразу после боевой сцены и рейд —
// лучшее решение штатного AI 91 раз, ни разу не названный в пропусках.
internal static partial class Program
{
    /// <summary>Автопилот гонится за грабителями, а те уже дерутся с третьей партией:
    /// движок открывает join_encounter, встреча — с теми же грабителями.</summary>
    static MapEvent PursuedBanditInForeignBattle(TestFaction defenders)
    {
        var ours = new TestFaction(); var bandits = new TestFaction(); ours.Enemies.Add(bandits);
        MobileParty.MainParty.MapFaction = ours;
        var looters = new MobileParty { Name = "Грабители", IsBandit = true, MapFaction = bandits };
        MobileParty.MainParty.TargetParty = looters; MobileParty.MainParty.DefaultBehavior = AiBehavior.EngageParty;
        var battle = new MapEvent();
        battle.AttackerSide.LeaderParty = new PartyBase { MapFaction = bandits, MobileParty = looters };
        battle.DefenderSide.LeaderParty = new PartyBase { MapFaction = defenders };
        looters.MapEvent = battle;
        PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredBattle = battle;
        PlayerEncounter.EncounteredMobileParty = looters;
        return battle;
    }

    static void EncounterTests()
    {
        Console.WriteLine("\n[прогон 16.09] чужой бой на пути погони и сторож простоя");
        Try("погоня за грабителями, которые уже дерутся с мирной партией", () =>
        {
            var b = Fresh(); b.RandomDialogsEnabled = new AutopilotBehavior().RandomDialogsEnabled; Enable(b);
            var battle = PursuedBanditInForeignBattle(new TestFaction());
            var join = new GameMenu { StringId = "join_encounter" };
            join.Options.Add(new GameMenuOption { IdString = "join_encounter_help_defenders", Consequence = () => {
                MobileParty.MainParty.MapEvent = battle; PlayerEncounter.Battle = battle;
                var fight = new GameMenu { StringId = "encounter" };
                fight.Options.Add(new GameMenuOption { IdString = "attack" }); Show(fight);
            }});
            Show(join); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { "join_encounter_help_defenders" }),
                  "меню чужого боя не принимается за ожидание разговора: нажата помощь защитникам (16.09 19:44:42 — тишина)");
            b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { "join_encounter_help_defenders", "attack" })
                  && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                  "после помощи защитникам открывается полноценный бой, автопилот включён");
        });
        Try("сторож простоя не глохнет, пока встречу держит разговор", () =>
        {
            var b = Fresh(); var t0 = new DateTime(2026, 9, 16, 19, 44, 42);
            SetClock(t0); Enable(b);
            var ours = new TestFaction(); var bandits = new TestFaction(); ours.Enemies.Add(bandits);
            MobileParty.MainParty.MapFaction = ours;
            var looters = new MobileParty { Name = "Грабители", IsBandit = true, MapFaction = bandits };
            MobileParty.MainParty.TargetParty = looters; MobileParty.MainParty.DefaultBehavior = AiBehavior.EngageParty;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = looters;
            var conversation = Campaign.Current.ConversationManager;
            conversation.ConversationParty = looters; conversation.IsConversationInProgress = true;
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = "common_bandit_surrender_join_offer", IsClickable = true });
            b.PollState(); SetClock(t0.AddSeconds(11)); b.PollState();
            Check(LogCount("ПРОСТОЙ") == 1, "время стоит 11 с под разговором, которого автопилот не знает, — простой записан");
            Check(conversation.Selected.Count == 0, "незнакомая реплика по-прежнему не нажимается");
            SetClock(DateTime.UtcNow);
        });
        Try("время боевой сцены не считается простоем", () =>
        {
            var b = Fresh(); var t0 = new DateTime(2026, 9, 16, 17, 48, 35);
            SetClock(t0); Enable(b); b.PollState();
            // Пока идёт миссия, модуль опрашивает её, а не карту (AutopilotSubModule.OnApplicationTick).
            MethodInfo watchMission = typeof(AutopilotBehavior).GetMethod("WatchMission", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)
                ?? throw new Exception("у автопилота нет отметки боевой сцены для сторожа простоя (WatchMission)");
            for (int s = 1; s <= 96; s++) { SetClock(t0.AddSeconds(s)); watchMission.Invoke(b, null); }
            SetClock(t0.AddSeconds(97)); b.PollState();
            Check(LogCount("ПРОСТОЙ") == 0, "96 с боя не записаны простоем сразу после выхода из сцены (16.09 17:50:11)");
            SetClock(t0.AddSeconds(108)); b.PollState();
            Check(LogCount("ПРОСТОЙ") == 1, "настоящий простой после сцены записан через 10 с");
            SetClock(DateTime.UtcNow);
        });
        Try("все пропущенные решения названы в журнале", () =>
        {
            var b = Fresh(); Enable(b);
            var castle = new Settlement { Name = "Замок Кранирог" }; var village = new Settlement { Name = "Родобас", IsVillage = true };
            var town = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.BesiegeSettlement, castle, 3.0f), (AiBehavior.RaidSettlement, village, 5.6f), (AiBehavior.GoToSettlement, town, 1.0f));
            HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l => l.Contains("пропущено") && l.Contains("Кранирог") && l.Contains("RaidSettlement → Родобас")),
                  "пропуск рейда виден рядом с пропуском осады (16.09: рейд лучшим 91 раз, в журнале ни разу)");
            Check(MobileParty.MainParty.TargetSettlement == town, "применено лучшее выполнимое решение");
        });
    }
}
