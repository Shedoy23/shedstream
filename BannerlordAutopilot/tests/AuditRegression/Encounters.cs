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

    /// <summary>Меню чужого боя как в EncounterGameMenuBehavior 1.4.8: помощь сторонам
    /// (доступность решает MapEvent.CanPartyJoinBattle, 112256) и уход — в join_encounter
    /// «join_encounter_leave» с Finish и Hold (183464), в encounter_interrupted — «leave»
    /// только с Finish (184697).</summary>
    static GameMenu ForeignBattleMenu(string id, MapEvent battle, bool helpDefenders)
    {
        var menu = new GameMenu { StringId = id };
        menu.Options.Add(new GameMenuOption { IdString = id + "_help_attackers", IsEnabled = false });
        menu.Options.Add(new GameMenuOption { IdString = id + "_help_defenders", IsEnabled = helpDefenders, Consequence = () => {
            MobileParty.MainParty.MapEvent = battle; PlayerEncounter.Battle = battle;
            var fight = new GameMenu { StringId = "encounter" };
            fight.Options.Add(new GameMenuOption { IdString = "attack" }); Show(fight);
        }});
        menu.Options.Add(new GameMenuOption { IdString = id == "join_encounter" ? "join_encounter_leave" : "leave", Consequence = () => {
            PlayerEncounter.Finish();
            if (id == "join_encounter") MobileParty.MainParty.SetMoveModeHold();
        }});
        return menu;
    }

    static void EncounterTests()
    {
        Try("плен не выключает автопилот до освобождения", () =>
        {
            var b = Fresh(); Enable(b); Hero.MainHero.IsPrisoner = true; MobileParty.MainParty.IsActive = false;
            var wait = new GameMenu { StringId = "prisoner_wait", IsWaitMenu = true }; Show(wait);
            b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply && wait.IsWaitActive,
                "неактивная пленная партия ждёт штатного освобождения");
            var release = new GameMenu { StringId = "menu_captivity_end_wilderness_escape" };
            release.Options.Add(new GameMenuOption { IdString = "mno_continue", Consequence = () => {
                Hero.MainHero.IsPrisoner = false; MobileParty.MainParty.IsActive = true;
                Campaign.Current.CurrentMenuContext = null;
            }}); Show(release); b.PollState();
            Check(!Hero.MainHero.IsPrisoner && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                "штатное продолжение освобождает героя и сохраняет автопилот");
        });
        Try("наблюдение не управляет пленом", () =>
        {
            var b = Fresh(); b.TryEnable(AutopilotBehavior.Mode.Observe, out _);
            Hero.MainHero.IsPrisoner = true; MobileParty.MainParty.IsActive = false;
            var wait = new GameMenu { StringId = "prisoner_wait", IsWaitMenu = true }; Show(wait); b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Observe && !wait.IsWaitActive, "F10 только наблюдает плен");
        });
        Try("выкуп отклоняется по решению владельца", () =>
        {
            var b = Fresh(); Enable(b); Hero.MainHero.IsPrisoner = true; MobileParty.MainParty.IsActive = false;
            var offer = new GameMenu { StringId = "menu_captivity_end_propose_ransom_wilderness" };
            offer.Options.Add(new GameMenuOption { IdString = "mno_captivity_end_ransom_accept" });
            offer.Options.Add(new GameMenuOption { IdString = "captivity_end_ransom_deny" }); Show(offer); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { "captivity_end_ransom_deny" }), "выкуп не оплачен, выбрано ожидание");
        });
        foreach (string id in new[] { "player_is_leaving_neutral_or_friendly", "caravan_talk_leave", "village_farmer_leave" })
        Try("мирная встреча: " + id, () =>
        {
            var b = Fresh(); Enable(b);
            var ours = new TestFaction(); MobileParty.MainParty.MapFaction = ours;
            var other = new MobileParty { MapFaction = new TestFaction() };
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = other;
            b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply, "ожидание мирного разговора не выключает автопилот");
            var c = Campaign.Current.ConversationManager; c.ConversationParty = other; c.IsConversationInProgress = true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = "main_option_hostile_1", IsClickable = true });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = id, IsClickable = true });
            b.RandomDialogsEnabled = true; b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { id }), "мирный уход имеет приоритет над случайным объявлением вражды");
        });
        foreach (string reply in new[] { "{=5KGuQb5C}We'll see who slays whom here.", "Ну, посмотрим, кто кого убьёт." })
        Try("атакующий патруль: ответ боем без приказа EngageParty: " + reply, () =>
        {
            var b = Fresh(); Enable(b);
            MobileParty.MainParty.MapFaction = new TestFaction();
            var patrol = new MobileParty { MapFaction = new TestFaction() };
            PlayerEncounter.Current = new PlayerEncounter { Defender = true };
            PlayerEncounter.EncounteredMobileParty = patrol;
            Campaign.Current.CurrentConversationContext = ConversationContext.PartyEncounter;
            var c = Campaign.Current.ConversationManager;
            c.ConversationParty = patrol; c.IsConversationInProgress = true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "mod_patrol_fight", Text = new TaleWorlds.Localization.TextObject(reply), IsClickable = true });
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { "mod_patrol_fight" })
                && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                "защитник принимает боевую реплику атакующего патруля");
        });
        Try("преследуемый вражеский лорд: знакомство, вызов и подтверждение", () =>
        {
            var b = Fresh(); Enable(b);
            var ours = new TestFaction(); var enemy = new TestFaction(); ours.Enemies.Add(enemy);
            MobileParty.MainParty.MapFaction = ours;
            var lord = new MobileParty { MapFaction = enemy };
            MobileParty.MainParty.TargetParty = lord; MobileParty.MainParty.DefaultBehavior = AiBehavior.EngageParty;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = lord;
            b.PollState(); Check(b.CurrentMode == AutopilotBehavior.Mode.Apply, "дождались разговора с целью AI");
            var c = Campaign.Current.ConversationManager; c.ConversationParty = lord; c.IsConversationInProgress = true;
            foreach (string id in new[] { "lord_meet_player_response1", "main_option_hostile_1_2", "player_verify_attack_on_enemy_lord" })
            {
                c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = id, IsClickable = true });
                b.PollDialogs();
                Check(c.Selected.LastOrDefault() == id, "штатная реплика лорду: " + id);
            }
        });
        foreach (bool escortDialog in new[] { false, true })
        Try("вражеский караван: требование и атака: " + (escortDialog ? "escort" : "обычный"), () =>
        {
            var b = Fresh(); Enable(b);
            var ours = new TestFaction(); var enemy = new TestFaction(); ours.Enemies.Add(enemy);
            MobileParty.MainParty.MapFaction = ours;
            var caravan = new MobileParty { MapFaction = enemy, IsCaravan = !escortDialog };
            MobileParty.MainParty.TargetParty = caravan;
            MobileParty.MainParty.DefaultBehavior = AiBehavior.EngageParty;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = caravan;
            Campaign.Current.CurrentConversationContext = ConversationContext.PartyEncounter;
            var c = Campaign.Current.ConversationManager;
            c.ConversationParty = caravan; c.IsConversationInProgress = true;
            string demand = escortDialog ? "adg:loot" : "caravan_loot";
            string attack = escortDialog ? "adg:attack" : "player_decided_to_fight";
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "caravan_talk_leave", IsClickable = true });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = demand, Text = new TaleWorlds.Localization.TextObject("{=WOBy5UfY}Hand over your goods, or die!"), IsClickable = true });
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { demand }), "выбрано требование товара, не уход");
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "player_decided_to_not_fight_1", IsClickable = true });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = attack, Text = new TaleWorlds.Localization.TextObject("{=EhxS7NQ4}So be it. Attack!"), IsClickable = true });
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { demand, attack }), "выбрана атака, не отказ от боя");
        });
        Try("вражеский караван предлагает выкуп, затем сдаётся: доводим до боя", () =>
        {
            var b = Fresh(); Enable(b);
            var ours = new TestFaction(); var enemy = new TestFaction(); ours.Enemies.Add(enemy);
            MobileParty.MainParty.MapFaction = ours;
            var caravan = new MobileParty { MapFaction = enemy, IsCaravan = true };
            MobileParty.MainParty.TargetParty = caravan;
            MobileParty.MainParty.DefaultBehavior = AiBehavior.EngageParty;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = caravan;
            Campaign.Current.CurrentConversationContext = ConversationContext.PartyEncounter;
            var c = Campaign.Current.ConversationManager;
            c.ConversationParty = caravan; c.IsConversationInProgress = true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "player_decided_to_take_some_goods", IsClickable = true });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "player_decided_to_take_everything", IsClickable = true });
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { "player_decided_to_take_everything" }),
                "выкуп отклонён, требуем всё");
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "player_do_not_take_prisoners", IsClickable = true });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "player_decided_to_take_prisoner", IsClickable = true });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption
                { Id = "player_decided_to_force_fight", IsClickable = true });
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[] { "player_decided_to_take_everything", "player_decided_to_force_fight" }),
                "после сдачи выбираем бой, а не товар или плен");
        });
        Try("мирная встреча: недоступная реплика и чужой собеседник", () =>
        {
            var b = Fresh(); Enable(b); b.RandomDialogsEnabled = true;
            MobileParty.MainParty.MapFaction = new TestFaction();
            var other = new MobileParty { MapFaction = new TestFaction() };
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty = other;
            var c = Campaign.Current.ConversationManager; c.ConversationParty = other; c.IsConversationInProgress = true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = "player_is_leaving_neutral_or_friendly", IsClickable = false });
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id = "main_option_hostile_1", IsClickable = true });
            b.PollDialogs(); Check(c.Selected.Count == 0, "недоступный уход не заменяется случайной угрозой");
            c.ConversationParty = new MobileParty(); b.PollDialogs();
            Check(c.Selected.Count == 0, "не выбираем за другого собеседника");
        });
        foreach (string menuId in new[] { "join_encounter", "encounter_interrupted" })
        Try("чужой бой, в который вступиться нельзя, — уходим штатно: " + menuId, () =>
        {
            var b = Fresh(); Enable(b);
            // Грабители напали на деревенских королевства, с которым мы воюем: обе стороны враги,
            // игра не пускает ни на одну (CanPartyJoinBattle), остаётся «Не вмешиваться».
            var enemyKingdom = new TestFaction();
            var battle = PursuedBanditInForeignBattle(enemyKingdom);
            ((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Add(enemyKingdom);
            Show(ForeignBattleMenu(menuId, battle, helpDefenders: false)); b.PollState();
            string leave = menuId == "join_encounter" ? "join_encounter_leave" : "leave";
            Check(MenuContext.Invoked.SequenceEqual(new[] { leave }) && PlayerEncounter.Current == null,
                  "нажата только штатная кнопка ухода «" + leave + "»");
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply && LogCount("ВСТРЕЧА") == 1,
                  "уход из чужого боя не выключает автопилот и записан с причиной");
        });
        Try("после ухода тот же отряд не преследуется, пока идёт его бой", () =>
        {
            var b = Fresh(); Enable(b);
            var enemyKingdom = new TestFaction();
            var battle = PursuedBanditInForeignBattle(enemyKingdom);
            ((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Add(enemyKingdom);
            var looters = PlayerEncounter.EncounteredMobileParty;
            Show(ForeignBattleMenu("join_encounter", battle, helpDefenders: false)); b.PollState();
            var ai = Campaign.Current.Models.MobilePartyAIModel;
            ai.NextBehavior = AiBehavior.EngageParty; ai.NextTarget = looters; ai.NextScore = 3f;
            int before = TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.EngageCalls;
            HourlyTick(b);
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply
                  && TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.EngageCalls == before,
                  "пока грабители в том бою, погоня не возобновляется — иначе круг «догнал — ушёл»");
            looters.MapEvent = null; HourlyTick(b);
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.EngageCalls == before + 1,
                  "бой закончился — отряд снова обычная цель");
        });
        Try("помощь защитникам запрещена игрой — уходим, а не выключаемся", () =>
        {
            var b = Fresh(); Enable(b);
            // Вожаки сторон подходят под правило «помогать мирным», но CanPartyJoinBattle
            // сверяет КАЖДУЮ партию стороны и кнопку выключил.
            var battle = PursuedBanditInForeignBattle(new TestFaction());
            Show(ForeignBattleMenu("join_encounter", battle, helpDefenders: false)); b.PollState();
            Check(MenuContext.Invoked.SequenceEqual(new[] { "join_encounter_leave" }) && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                  "недоступная кнопка помощи ведёт к штатному уходу, автопилот включён");
        });
        Try("F11 можно нажать прямо в меню чужого боя", () =>
        {
            var b = Fresh();
            var enemyKingdom = new TestFaction();
            var battle = PursuedBanditInForeignBattle(enemyKingdom);
            ((TestFaction)MobileParty.MainParty.MapFaction).Enemies.Add(enemyKingdom);
            Show(ForeignBattleMenu("join_encounter", battle, helpDefenders: false));
            Check(b.TryEnable(AutopilotBehavior.Mode.Apply, out string why), "включение в меню чужого боя разрешено: " + why);
        });

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
