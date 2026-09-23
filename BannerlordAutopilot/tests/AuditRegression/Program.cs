using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameMenus;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Map;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using ItemObject = TaleWorlds.Core.ItemObject;

// Регрессия по независимой проверке 12.09.2026.
//
// Сценарии взяты из стенда проверяющего, но ПЕРЕВЁРНУТЫ: там каждая проверка
// доказывала, что дефект воспроизводится («REPRODUCED»), здесь — что его нет.
// Прогон не обрывается на первом провале: печатает каждую проверку и код
// возврата равен числу провалов. На коде до исправления проверки обязаны быть
// красными — иначе они ничего не доказывают.
//
// Это заменители движка, а не кампания: проверяются решения мода и то, какое
// состояние он оставляет, но не исход боя и не загрузка настоящего сейва.
internal static partial class Program
{
    static int passed, failed;

    static void Check(bool ok, string name)
    {
        if (ok) { passed++; Console.WriteLine("  ok    " + name); }
        else { failed++; Console.WriteLine("  FAIL  " + name); }
    }

    static void Try(string name, Action scenario)
    {
        try { scenario(); }
        catch (Exception ex) { failed++; Console.WriteLine("  FAIL  " + name + " — исключение: " + ex.GetType().Name + ": " + ex.Message); }
    }

    static AutopilotBehavior Fresh()
    {
        MobileParty.AllBanditParties.Clear();
        MobileParty.All.Clear();
        Settlement.All.Clear();
        Hideout.All.Clear();
        MobileParty.TestIsActiveThrows = false; MobileParty.MainParty = new MobileParty(); Hero.MainHero = new Hero(); Campaign.Current = new Campaign();
        TaleWorlds.Core.Game.Current = new TaleWorlds.Core.Game(); CampaignTime.TestHours = 0; MenuContext.Invoked.Clear();
        PlayerEncounter.Current = null; PlayerEncounter.EncounterSettlement = null;
        PlayerEncounter.EncounteredMobileParty = null; PlayerEncounter.Battle = null; PlayerEncounter.EncounteredBattle = null;
        PlayerEncounter.LeaveEncounter = false; PlayerEncounter.LeaveSettlementCalls = 0; PlayerEncounter.FinishCalls = 0;
        AutopilotBehavior.AutoLeaveSettlement = true; AutopilotLog.Lines.Clear();
        CampaignEventDispatcher.NextScores.Clear(); TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls = 0;
        TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.PatrolCalls = 0;
        TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.EngageCalls = 0;
        CampaignEventDispatcher.Recruited.Clear(); CampaignEventDispatcher.ThinkFood = -1; CampaignEventDispatcher.ThinkMembers = -1;
        CampaignEventDispatcher.TestRecruitedThrows = false;
        TaleWorlds.CampaignSystem.Actions.SellItemsAction.TestBroken = false; TaleWorlds.CampaignSystem.Actions.SellPrisonersAction.TestCalls = 0;
        TaleWorlds.Library.InformationManager.TestInquiryActive = false;
        TaleWorlds.CampaignSystem.Clan.PlayerClan = new TaleWorlds.CampaignSystem.Clan();
        TaleWorlds.ScreenSystem.ScreenManager.TopScreen = null; Helpers.MobilePartyHelper.TestLockedIds.Clear();
        Helpers.FactionHelper.TestEnemies.Clear();
        return new AutopilotBehavior { RandomDialogsEnabled = false };
    }

    // ── Обслуживание в поселении ──────────────────────────────────────────────

    static void SetLimit(string name, object value)
    {
        Type limits = typeof(AutopilotBehavior).Assembly.GetType("BannerlordAutopilot.ServiceLimits")
                      ?? throw new Exception("у автопилота нет пределов обслуживания (ServiceLimits)");
        (limits.GetField(name, BindingFlags.Static | BindingFlags.NonPublic) ?? throw new Exception("нет предела " + name))
            .SetValue(null, value);
    }

    sealed class World
    {
        public Settlement Place; public Hero Notable; public CharacterObject Recruit; public ItemObject Grain;
        public CharacterObject Looter; public CharacterObject Lord;
    }

    /// <summary>Поселение с рынком (300 зерна по 20), старостой с тремя добровольцами (по 30),
    /// отряд из 20 при пределе 100, расход еды 5 в день, жалование 50 в день;
    /// в плену 10 грабителей (выкуп 20) и один лорд (выкуп 1000).</summary>
    static World MakeWorld(bool village = false, int gold = 20000, bool prisoners = true)
    {
        SetLimit("MinGoldReserve", 2000); SetLimit("ReserveWageDays", 7); SetLimit("MaxFoodSpendPerPass", 5000);
        SetLimit("MaxRecruitSpendPerPass", 5000); SetLimit("MaxRecruitsPerPass", 30); SetLimit("PassIntervalHours", 6.0);
        var faction = new TestFaction();
        var party = MobileParty.MainParty;
        party.MapFaction = faction; party.FoodChange = -5f; party.TotalWage = 50; party.Party.PartySizeLimit = 100;
        party.MemberRoster.AddToCounts(new CharacterObject { Name = "Ветеран", StringId = "veteran" }, 20);
        Hero.MainHero.Gold = gold;
        var w = new World
        {
            Place = new Settlement { Name = village ? "Деревня" : "Ликарон", IsTown = !village, IsVillage = village, MapFaction = faction },
            Grain = new ItemObject { Name = "Зерно", IsFood = true, TestPrice = 20 },
            Notable = new Hero { Name = "Староста" },
            Recruit = new CharacterObject { Name = "Новобранец", StringId = "recruit", TestCost = 30 },
        };
        if (village)
        {
            var boundTown = new Settlement { Name = "Торговый город", IsTown = true };
            w.Place.Village.TradeBound = boundTown;
            w.Place.Village.Bound = boundTown;
        }
        w.Place.ItemRoster.TestAdd(w.Grain, 300);
        for (int i = 0; i < 3; i++) w.Notable.VolunteerTypes[i] = w.Recruit;
        w.Place.Notables.Add(w.Notable);
        if (prisoners)
        {
            w.Looter = new CharacterObject { Name = "Грабитель", StringId = "looter", TestRansom = 20 };
            w.Lord = new CharacterObject { Name = "Пленный лорд", StringId = "lord", IsHero = true, TestRansom = 1000 };
            party.PrisonRoster.AddToCounts(w.Looter, 10);
            party.PrisonRoster.AddToCounts(w.Lord, 1);
        }
        return w;
    }

    static int Grain(World w) => MobileParty.MainParty.ItemRoster.TestCount(w.Grain);

    // ── Меню поселения как в PlayerTownVisitCampaignBehavior (1.4.8) ──────────
    // «town» → «town_wait» открывает «town_wait_menus» (IsPlayerWaiting, Hold,
    // время — UnstoppableFastForward); «wait_leave» возвращает в «town» и ставит
    // паузу (EndWait). Выход из поселения закрывает меню (Finish → ExitToLast).

    static void Show(GameMenu menu)
    {
        if (Campaign.Current.CurrentMenuContext == null) Campaign.Current.CurrentMenuContext = new MenuContext();
        Campaign.Current.CurrentMenuContext.GameMenu = menu;
    }

    static GameMenu TownMenu(Settlement s, bool canWait)
    {
        var menu = new GameMenu { StringId = "town" };
        menu.Options.Add(new GameMenuOption
        {
            IdString = "town_wait", IsEnabled = canWait, Consequence = () =>
            {
                Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop;          // SwitchToMenu
                var wait = new GameMenu { StringId = "town_wait_menus", IsWaitMenu = true, IsWaitActive = true };
                wait.Options.Add(new GameMenuOption
                {
                    IdString = "wait_leave", IsLeave = true, Consequence = () =>
                    {
                        Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop;  // EndWait
                        PlayerEncounter.Current.IsPlayerWaiting = false;
                        // SwitchToMenuIfThereIsAnInterrupt → GetGenericStateMenu (59418-59430):
                        // партия внутри мирного города, не ждёт — «town_outside», не «town».
                        Show(new GameMenu { StringId = "town_outside" });
                    }
                });
                Show(wait);
                PlayerEncounter.Current.IsPlayerWaiting = true; MobileParty.MainParty.SetMoveModeHold();
                Campaign.Current.TimeControlMode = CampaignTimeControlMode.UnstoppableFastForward; // StartWait
            }
        });
        menu.Options.Add(new GameMenuOption { IdString = "town_leave", IsLeave = true });
        return menu;
    }

    /// <summary>Прибыли в город: встреча с поселением, партия внутри, меню города открыто.</summary>
    static Settlement ArriveTown(string name = "Town", bool canWait = true) => ArriveTown(new Settlement { Name = name }, canWait);

    static Settlement ArriveTown(Settlement s, bool canWait = true)
    {
        PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = s;
        MobileParty.MainParty.CurrentSettlement = s; MobileParty.MainParty.IsMoving = false;
        Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop;                  // меню ставит паузу
        Show(TownMenu(s, canWait));
        return s;
    }

    // Деревня (1.4.8): «village_wait» открывает village_wait_menus и выводит партию за
    // околицу (LeaveSettlementAction, 206140-206144); «wait_leave» — EnterSettlementAction
    // и меню «village» (205995-205999), а IsPlayerWaiting НЕ сбрасывает: во всей сборке
    // false ему пишут только 184347, 184412, 184574, 184595 и town wait_leave (205913).
    static GameMenu VillageMenu(Settlement v)
    {
        var menu = new GameMenu { StringId = "village" };
        menu.Options.Add(new GameMenuOption
        {
            IdString = "village_wait", Consequence = () =>
            {
                Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop;
                var wait = new GameMenu { StringId = "village_wait_menus", IsWaitMenu = true, IsWaitActive = true };
                wait.Options.Add(new GameMenuOption
                {
                    IdString = "wait_leave", IsLeave = true, Consequence = () =>
                    {
                        wait.IsWaitActive = false; Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop; // EndWait
                        MobileParty.MainParty.CurrentSettlement = MobileParty.MainParty.LastVisitedSettlement;      // EnterSettlementAction
                        Show(VillageMenu(v));
                    }
                });
                Show(wait);
                PlayerEncounter.Current.IsPlayerWaiting = true; MobileParty.MainParty.SetMoveModeHold();
                Campaign.Current.TimeControlMode = CampaignTimeControlMode.UnstoppableFastForward;
                MobileParty.MainParty.CurrentSettlement = null;                                           // LeaveSettlementAction
            }
        });
        return menu;
    }

    static Settlement ArriveVillage(string name) => ArriveVillage(new Settlement { Name = name, IsVillage = true });

    static Settlement ArriveVillage(Settlement v)
    {
        PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = v;
        MobileParty.MainParty.CurrentSettlement = v; MobileParty.MainParty.LastVisitedSettlement = v; MobileParty.MainParty.IsMoving = false;
        Campaign.Current.TimeControlMode = CampaignTimeControlMode.Stop;
        Show(VillageMenu(v));
        return v;
    }

    static bool Waiting => PlayerEncounter.Current != null && PlayerEncounter.Current.IsPlayerWaiting;

    static MapState Map() => (MapState)TaleWorlds.Core.Game.Current.GameStateManager.ActiveState;

    static bool TimeRuns
    {
        get
        {
            var m = Campaign.Current.TimeControlMode;
            return m == CampaignTimeControlMode.UnstoppablePlay || m == CampaignTimeControlMode.UnstoppableFastForward
                   || m == CampaignTimeControlMode.UnstoppableFastForwardForPartyWaitTime
                   || ((m == CampaignTimeControlMode.StoppablePlay || m == CampaignTimeControlMode.StoppableFastForward)
                       && !Campaign.Current.IsMainPartyWaiting);
        }
    }

    static void Scores(params (AiBehavior behavior, IMapPoint target, float score)[] scores)
    {
        CampaignEventDispatcher.NextScores.Clear();
        foreach (var s in scores)
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData { AiBehavior = s.behavior, Party = s.target }, s.score));
    }

    static void SetClock(DateTime at) =>
        (typeof(AutopilotBehavior).GetField("Clock", BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new Exception("у автопилота нет часов сторожа простоя (поле Clock)"))
        .SetValue(null, (Func<DateTime>)(() => at));

    static int LogCount(string fragment) => AutopilotLog.Lines.Count(l => l.Contains(fragment));

    /// <summary>Экран карты текущей игры — на нём открываются окна поверх карты.</summary>
    static SandBox.View.Map.MapScreen Screen =>
        (SandBox.View.Map.MapScreen)((MapState)TaleWorlds.Core.Game.Current.GameStateManager.ActiveState).Handler;

    static void Enable(AutopilotBehavior b, AutopilotBehavior.Mode mode = AutopilotBehavior.Mode.Apply)
    {
        if (!b.TryEnable(mode, out var why)) throw new Exception("не включился: " + why);
    }

    static int Field(AutopilotBehavior b, string name) =>
        (int)typeof(AutopilotBehavior).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(b);

    static void Load(AutopilotBehavior b) =>
        typeof(AutopilotBehavior).GetMethod("OnGameLoadFinished", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(b, null);

    static void HourlyTick(AutopilotBehavior b) =>
        typeof(AutopilotBehavior).GetMethod("OnHourlyTick", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(b, null);

    static string DisableSummary(AutopilotBehavior b) =>
        typeof(AutopilotBehavior).GetProperty("LastDisableSummary", BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public)?.GetValue(b) as string;

    /// <summary>Хранилище сейва в памяти — как CampaignBehaviorDataStore.BehaviorSaveData
    /// (CampaignSystem 11325): при сохранении ключ добавляется (повтор ключа — исключение),
    /// при загрузке без ключа значение не трогается и возвращается false.</summary>
    sealed class MemStore : IDataStore
    {
        public readonly Dictionary<string, object> Data = new Dictionary<string, object>();
        public bool Loading;
        public bool IsSaving => !Loading;
        public bool IsLoading => Loading;
        public bool SyncData<T>(string key, ref T data)
        {
            if (!Loading) { Data.Add(key, data); return true; }
            if (Data.TryGetValue(key, out var v)) { data = (T)v; return true; }
            return false;
        }
    }

    static int Main()
    {
        Console.WriteLine("Регрессия автопилота по независимой проверке 12.09 (заменители движка, не кампания)");
        EngineContract.Verify();
        Check(ServiceLimits.MinGoldReserve == 0, "default reserve has no fixed gold floor");
        OperationTests();
        EncounterTests();
        ConquestTests();
        DefenseTests();
        EquipmentTradeTests();
        TroopUpgradeTests();
        BanditGatheringTests();
        ProgressTests();
        Try("random default and lord introduction", () => {
            var b=Fresh(); b.RandomDialogsEnabled=new AutopilotBehavior().RandomDialogsEnabled; Enable(b);
            PlayerEncounter.Current=new PlayerEncounter();PlayerEncounter.EncounteredMobileParty=new MobileParty();
            var c=Campaign.Current.ConversationManager;c.IsConversationInProgress=true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="lord_introduction",IsClickable=true});
            b.PollState();
            Check(c.Selected.Contains("lord_introduction") && b.CurrentMode==AutopilotBehavior.Mode.Apply,"lord introduction proceeds with default random mode");
        });
        PrisonerTests();
        Try("побеждённый лорд: пленение и продолжение без вариантов", () => {
            var b=Fresh(); Enable(b); b.RandomDialogsEnabled=false;
            var c=Campaign.Current.ConversationManager; c.IsConversationInProgress=true;
            Campaign.Current.CurrentConversationContext=ConversationContext.CapturedLord;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="talk_lord_defeat_to_lord_capture_and_kill",IsClickable=true});
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="talk_lord_defeat_to_lord_capture",IsClickable=true});
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="talk_lord_defeat_to_lord_release",IsClickable=true});
            b.PollDialogs();
            Check(c.Selected.SequenceEqual(new[]{"talk_lord_defeat_to_lord_capture"}),"берёт лорда в плен, не казнит и не отпускает");
            SetClock(DateTime.UtcNow.AddSeconds(3)); b.PollDialogs();
            Check(c.ContinueCalls==1,"последнюю реплику после пленения закрывает");
            SetClock(DateTime.UtcNow);
        });
        Try("встреча: штатная реплика без вариантов", () => {
            var b=Fresh(); Enable(b); b.RandomDialogsEnabled=false;
            var c=Campaign.Current.ConversationManager; c.IsConversationInProgress=true;
            Campaign.Current.CurrentConversationContext=ConversationContext.PartyEncounter;
            b.PollDialogs();
            Check(c.ContinueCalls==1,"экран «нажмите, чтобы продолжить» закрыт без случайного режима");
        });
        Try("освобождение героя после боя", () => {
            var b=Fresh(); Enable(b);
            var ours=new TestFaction(); var enemy=new TestFaction(); ours.Enemies.Add(enemy);
            var target=new MobileParty { MapFaction=enemy };
            MobileParty.MainParty.MapFaction=ours; MobileParty.MainParty.TargetParty=target;
            MobileParty.MainParty.DefaultBehavior=AiBehavior.EngageParty;
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty=target;
            var conversation=Campaign.Current.ConversationManager;
            conversation.ConversationParty=new MobileParty(); conversation.IsConversationInProgress=true;
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="liberate_hero_4",IsClickable=true});
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="liberate_hero_3",IsClickable=true});
            b.PollDialogs();
            Check(conversation.Selected.SequenceEqual(new[]{"liberate_hero_3"}),"освобождает, не пленит спасённого героя");
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="liberate_hero_8",IsClickable=true});
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {Id="liberate_hero_7",IsClickable=true});
            SetClock(DateTime.UtcNow.AddSeconds(3)); b.PollDialogs();
            Check(conversation.Selected.SequenceEqual(new[]{"liberate_hero_3","liberate_hero_7"}),"завершает благодарность без требования долга");
            SetClock(DateTime.UtcNow);
        });
        LootTests();
        PostBattleRestTests();
        PollGuardTests();
        HuntTests();
        SiegePriorityTests();
        FleeTests();
        FleeDefenseTests();
        SiegeReliabilityTests();
        DonationTests();

        Console.WriteLine("\n[находка 2] наблюдение ничего не меняет");
        Try("F10 в поселении", () =>
        {
            var b = Fresh(); ArriveTown(); Enable(b, AutopilotBehavior.Mode.Observe); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement != null && PlayerEncounter.Current != null
                  && !PlayerEncounter.LeaveEncounter && PlayerEncounter.FinishCalls == 0,
                  "F10 внутри поселения не выводит партию и не заказывает выход");
            Check(MenuContext.Invoked.Count == 0 && !Waiting, "F10 не нажимает пунктов меню (и не начинает ожидание)");
            b.Disable("test");
            Check(!PlayerEncounter.LeaveEncounter, "после F12 у движка не остаётся заказанного выхода");
        });
        Try("F10 на паузе", () =>
        {
            var b = Fresh(); Enable(b, AutopilotBehavior.Mode.Observe); b.PollState();
            Check(Campaign.Current.TimeControlMode == CampaignTimeControlMode.Stop, "F10 не снимает игру с паузы");
        });
        Try("F10 → F12 на карте", () =>
        {
            var b = Fresh(); Enable(b, AutopilotBehavior.Mode.Observe); b.Disable("test");
            Check(MobileParty.MainParty.HoldCalls == 0, "F10 → F12 не сбрасывает ручной маршрут игрока");
            Check(!MobileParty.MainParty.Ai.RethinkAtNextHourlyTick, "автопилот не взводит сохраняемый Rethink");
        });

        Console.WriteLine("\n[находка 1] встреча с боем или чужой партией — не прибытие");
        Try("бой и осада у поселения", () =>
        {
            var b = Fresh(); Enable(b);
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = new Settlement();
            MobileParty.MainParty.MapEvent = new MapEvent(); MobileParty.MainParty.SiegeEvent = new TaleWorlds.CampaignSystem.Siege.SiegeEvent();
            b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Off, "бой/осада выключают автопилот");
            Check(PlayerEncounter.Current != null && !PlayerEncounter.LeaveEncounter && PlayerEncounter.FinishCalls == 0,
                  "встреча с боем не закрывается модом");
        });
        Try("встреча с осаждающей партией", () =>
        {
            var b = Fresh(); Enable(b);
            // EncounterSettlement тут — поселение, которое осаждает СОБЕСЕДНИК, а не наше.
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = new Settlement { Name = "Осаждённый" };
            PlayerEncounter.EncounteredMobileParty = new MobileParty { Name = "Осаждающий лорд" };
            b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Off && PlayerEncounter.Current != null && PlayerEncounter.FinishCalls == 0,
                  "встреча с партией у чужого поселения не считается прибытием и не закрывается");
        });
        foreach (string boundary in new[] { "neutral", "other_party", "not_bandit", "inquiry", "unknown_option", "observe" })
        Try("граница боевого разговора " + boundary, () => {
            var b=Fresh(); Enable(b, boundary=="observe" ? AutopilotBehavior.Mode.Observe : AutopilotBehavior.Mode.Apply);
            var ours=new TestFaction(); var enemy=new TestFaction();
            if (boundary!="neutral") ours.Enemies.Add(enemy);
            var target=new MobileParty { IsBandit=boundary!="not_bandit", MapFaction=enemy };
            MobileParty.MainParty.MapFaction=ours; MobileParty.MainParty.TargetParty=target;
            MobileParty.MainParty.DefaultBehavior=AiBehavior.EngageParty;
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty=target;
            var conversation=Campaign.Current.ConversationManager;
            conversation.ConversationParty=boundary=="other_party" ? new MobileParty() : target;
            conversation.IsConversationInProgress=true;
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id=boundary=="unknown_option" ? "common_bandit_surrender_join_offer" : "common_encounter_ultimatum", IsClickable=true });
            if (boundary=="inquiry") TaleWorlds.Library.InformationManager.TestInquiryActive=true;
            b.PollState();
            Check(conversation.Selected.Count==0 && conversation.ContinueCalls==0, "чужой выбор не исполняется: " + boundary);
        });
        foreach (string reply in new[] { "common_encounter_ultimatum", "common_bandit_surrender_accepted" })
        foreach (bool enabled in new[] { true, false })
        Try("разговор с выбранными бандитами " + reply + " " + enabled, () => {
            var b=Fresh(); Enable(b);
            b.RandomDialogsEnabled=true;
            var ours=new TestFaction(); var enemy=new TestFaction(); ours.Enemies.Add(enemy);
            var target=new MobileParty { IsBandit=true, MapFaction=enemy };
            MobileParty.MainParty.MapFaction=ours; MobileParty.MainParty.TargetParty=target;
            MobileParty.MainParty.DefaultBehavior=AiBehavior.EngageParty;
            PlayerEncounter.Current=new PlayerEncounter(); PlayerEncounter.EncounteredMobileParty=target;
            var conversation=Campaign.Current.ConversationManager;
            conversation.ConversationParty=target; conversation.IsConversationInProgress=true;
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id=reply, IsClickable=enabled });
            b.PollState();
            Check(b.CurrentMode==AutopilotBehavior.Mode.Apply, "встреча с выбранными бандитами не выключает автопилот");
            Check(conversation.Selected.Count==(enabled ? 1:0), "выбрана только доступная реплика ультиматума");
            b.PollState();
            Check(conversation.ContinueCalls==(enabled ? 1:0), "закрывается только последняя реплика выбранного разговора");
        });
        Try("случайный диалог: пауза, серые варианты и предел цикла", () => {
            var b=Fresh(); Enable(b); b.RandomDialogsEnabled=true;
            var conversation=Campaign.Current.ConversationManager;
            conversation.IsConversationInProgress=true;
            var t0=DateTime.UtcNow; SetClock(t0);
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="grey", IsClickable=false });
            b.PollDialogs();
            Check(conversation.Selected.Count==0 && conversation.ContinueCalls==0, "все реплики серые — ждём, не продолжаем вслепую");
            conversation.CurOptions.Clear();
            for (int i=0;i<17;i++) {
                conversation.CurOptions.Clear();
                conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="loop", IsClickable=true });
                SetClock(t0.AddSeconds(i*3)); b.PollDialogs();
                if (i==0) { conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="too_fast", IsClickable=true }); b.PollDialogs(); }
            }
            Check(conversation.Selected.Count==16 && !conversation.Selected.Contains("too_fast"), "между случайными выборами есть пауза; максимум 16 шагов");
            Check(!b.RandomDialogsEnabled, "зациклившийся случайный режим выключается");
            SetClock(DateTime.UtcNow);
        });
        Try("случайно принятая сдача разрешает экран пленных", () => {
            var b=Fresh(); Enable(b); b.RandomDialogsEnabled=true;
            PlayerEncounter.Current=new PlayerEncounter();
            var c=Campaign.Current.ConversationManager; c.IsConversationInProgress=true;
            c.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption {
                Id="common_bandit_surrender_accepted", IsClickable=true });
            b.PollDialogs();
            var authorized=typeof(AutopilotBehavior).GetField("_prisonerEncounter",
                BindingFlags.Instance | BindingFlags.NonPublic).GetValue(b);
            Check(c.Selected.SequenceEqual(new[]{"common_bandit_surrender_accepted"})
                && ReferenceEquals(authorized,PlayerEncounter.Current),
                "экран пленных привязан к текущей встрече до штатной реплики");
        });
        foreach (bool randomEnabled in new[] { false, true })
        Try("отдельный случайный режим " + randomEnabled, () => {
            var b=Fresh(); Enable(b); b.RandomDialogsEnabled=randomEnabled;
            var conversation=Campaign.Current.ConversationManager;
            conversation.IsConversationInProgress=true;
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="disabled", IsClickable=false });
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="available_a", IsClickable=true });
            conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="available_b", IsClickable=true });
            b.PollDialogs();
            Check(conversation.Selected.Count==(randomEnabled ? 1:0), "случайный выбор только при включённом режиме");
            Check(!conversation.Selected.Contains("disabled"), "серую реплику не выбирает");
            b.Disable("test"); conversation.CurOptions.Add(new TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption { Id="after_F12", IsClickable=true });
            b.PollDialogs();
            Check(!conversation.Selected.Contains("after_F12"), "F12 останавливает случайные диалоги");
        });
        foreach (bool enabled in new[] { true, false })
        Try("помощь защитникам, доступность " + enabled, () =>
        {
            var b = Fresh(); Enable(b);
            var ours = new TestFaction(); var enemy = new TestFaction(); ours.Enemies.Add(enemy);
            MobileParty.MainParty.MapFaction = ours;
            var battle = new MapEvent();
            battle.AttackerSide.LeaderParty = new PartyBase { MapFaction = enemy };
            battle.DefenderSide.LeaderParty = new PartyBase { MapFaction = ours };
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounteredBattle = battle;
            PlayerEncounter.EncounteredMobileParty = new MobileParty();
            var join = new GameMenu { StringId = "join_encounter" };
            join.Options.Add(new GameMenuOption { IdString = "join_encounter_help_defenders", IsEnabled = enabled, Consequence = () => {
                MobileParty.MainParty.MapEvent = battle; PlayerEncounter.Battle = battle;
                var fight = new GameMenu { StringId = "encounter" };
                fight.Options.Add(new GameMenuOption { IdString = "attack" }); Show(fight);
            }});
            Show(join); b.PollState();
            Check(MenuContext.Invoked.Count == (enabled ? 1 : 0), "помощь только доступной кнопкой, один шаг за опрос");
            b.PollState();
            Check(!enabled || MenuContext.Invoked.SequenceEqual(new[] { "join_encounter_help_defenders", "attack" }),
                  "помощь защитникам затем полноценная атака");
        });
        Try("обычный полевой бой открывается", () =>
        {
            var b = Fresh(); Enable(b);
            bool opened = false;
            var battle = new MapEvent();
            MobileParty.MainParty.MapEvent = battle;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.Battle = battle;
            var menu = new GameMenu { StringId = "encounter" };
            menu.Options.Add(new GameMenuOption { IdString = "attack", Consequence = () => opened = true });
            menu.Options.Add(new GameMenuOption { IdString = "str_order_attack", Consequence = () => throw new Exception("автосимуляция нажата") });
            Show(menu); b.PollState();
            Check(opened && MenuContext.Invoked.SequenceEqual(new[] { "attack" }),
                  "F11 нажимает штатное «В атаку» и открывает сцену, а не «Отправить войска»");
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply, "при переходе в сцену боевой автопилот остаётся включён");
        });
        Try("F11 можно включить прямо в меню полевого боя", () =>
        {
            var b = Fresh(); bool opened = false; var battle = new MapEvent();
            MobileParty.MainParty.MapEvent = battle; PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.Battle = battle;
            var menu = new GameMenu { StringId = "encounter" };
            menu.Options.Add(new GameMenuOption { IdString = "attack", Consequence = () => opened = true }); Show(menu);
            Enable(b); b.PollState();
            Check(opened && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                  "F11 из encounter разрешён и запускает полноценный бой");
        });
        Try("недоступный и особый бой не запускаются", () =>
        {
            var b = Fresh(); Enable(b);
            var battle = new MapEvent(); MobileParty.MainParty.MapEvent = battle;
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.Battle = battle;
            var menu = new GameMenu { StringId = "encounter" };
            menu.Options.Add(new GameMenuOption { IdString = "attack", IsEnabled = false, Tooltip = "герой ранен" });
            Show(menu); b.PollState();
            Check(MenuContext.Invoked.Count == 0 && b.CurrentMode == AutopilotBehavior.Mode.Off,
                  "недоступное «В атаку» не обходится, причина выключает автопилот");

            b = Fresh(); Enable(b); battle = new MapEvent { IsNavalMapEvent = true };
            MobileParty.MainParty.MapEvent = battle; PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.Battle = battle;
            Show(new GameMenu { StringId = "encounter" }); b.PollState();
            Check(MenuContext.Invoked.Count == 0 && b.CurrentMode == AutopilotBehavior.Mode.Off,
                  "морской бой не попадает под логику сухопутной миссии");
        });

        Console.WriteLine("\n[игра без человека] поселение: ждать, как NPC, и уходить по решению штатного AI");
        Try("прибытие в город", () =>
        {
            var b = Fresh(); Enable(b); b.PollState();                                // свободная карта
            var town = ArriveTown(); b.PollState();
            Check(MenuContext.Invoked.Contains("town_wait"), "в городе автопилот выбирает «Подождать» тем же пунктом меню, что игрок");
            Check(Waiting && MobileParty.MainParty.CurrentSettlement == town && PlayerEncounter.FinishCalls == 0,
                  "партия осталась в городе и ждёт — не выходит сразу, как делал прототип (пинг-понг 13.09)");
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply, "автопилот не выключился");
            Check(TimeRuns, "во время ожидания время идёт");
            b.PollState(); b.PollState();
            Check(PlayerEncounter.FinishCalls == 0 && Waiting, "следующие опросы не выводят партию");
            Check(Field(b, "_settlementVisitsThisSession") == 1, "прибытие засчитано один раз");
        });
        Try("старт внутри города", () =>
        {
            var b = Fresh(); ArriveTown(); Enable(b); b.PollState();
            Check(Waiting && Field(b, "_settlementVisitsThisSession") == 0,
                  "F11 в городе: партия ждёт, старт внутри не считается прибытием");
        });
        Try("решение остаться", () =>
        {
            var b = Fresh(); Enable(b); var town = ArriveTown(); b.PollState();
            Scores((AiBehavior.GoToSettlement, town, 2.0f), (AiBehavior.PatrolAroundPoint, town, 0.5f));
            HourlyTick(b); b.PollState();
            Check(Waiting && PlayerEncounter.FinishCalls == 0, "лучшее решение — это же поселение: партия остаётся и ждёт");
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls == 0, "приказов в своё же поселение не выдаётся");
        });
        Try("решение уйти", () =>
        {
            var b = Fresh();
            Campaign.Current.TimeControlMode = CampaignTimeControlMode.StoppablePlay;  // ехали на обычной скорости
            MobileParty.MainParty.IsMoving = true;
            Enable(b); b.PollState();
            var town = ArriveTown(); b.PollState();
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, korsia, 2.0f), (AiBehavior.GoToSettlement, town, 1.0f));
            HourlyTick(b); b.PollState();
            Check(MenuContext.Invoked.Contains("wait_leave"), "ожидание прервано пунктом «Перестать ждать»");
            Check(MobileParty.MainParty.CurrentSettlement == null && PlayerEncounter.Current == null,
                  "партия действительно вышла: поселение и встреча закрыты");
            Check(Math.Abs(MobileParty.MainParty.Position.X - 42f) < 0.01f, "партия выведена к воротам");
            Check(MobileParty.MainParty.TargetSettlement == korsia, "сразу после выхода выдан приказ, ради которого вышли");
            Check(Field(b, "_settlementExitsThisSession") == 1, "выход засчитан один раз и только после перехода");
            b.PollState();
            Check(Field(b, "_settlementExitsThisSession") == 1, "повторный опрос не засчитывает выход снова");
            Check(TimeRuns && Campaign.Current.TimeControlMode != CampaignTimeControlMode.UnstoppableFastForward
                  && Campaign.Current.TimeControlMode != CampaignTimeControlMode.StoppableFastForward,
                  "после выхода время идёт с той скоростью, что была до города (обычной, не ускоренной ожиданием)");
        });
        // Краш 18.09 14:34:34 (0xC0000005). Движок кладёт выпавшее на входе
        // событие в MapState.NextIncident, а условия проверяет на СЛЕДУЮЩЕМ
        // Campaign.Tick (10136-10143). Пять ванильных событий с триггером «вход»
        // читают в условии MainParty.CurrentSettlement без проверки на null
        // (incident_hammer_of_the_sun, ...through_proper_channels, ...the_quiet_life,
        // ...occupational_safety, ...jobs_for_the_lads), поэтому выход раньше показа
        // даёт NullReferenceException в чужом коде и закрывает игру.
        // Разбор: review/INCIDENT_EXIT_CRASH_2026-09-18.md.
        Try("выпавшее событие держит выход", () =>
        {
            var b = Fresh(); Enable(b); b.PollState();
            var town = ArriveTown(); b.PollState();
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, korsia, 2.0f), (AiBehavior.GoToSettlement, town, 1.0f));
            Map().NextIncident = new TaleWorlds.CampaignSystem.Incidents.Incident { StringId = "incident_hammer_of_the_sun" };
            HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == town && PlayerEncounter.FinishCalls == 0,
                  "пока событие в очереди, партия остаётся в поселении");
            Check(!MenuContext.Invoked.Contains("wait_leave"),
                  "«Перестать ждать» не нажато: выход держится ДО показа события, а не после");
            b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == town, "следующий опрос тоже не выводит партию");
            Map().NextIncident = null;                      // движок показал событие и очистил очередь
            b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null && PlayerEncounter.Current == null,
                  "очередь пуста — выход происходит");
            Check(MobileParty.MainParty.TargetSettlement == korsia,
                  "решение, ради которого выходили, применено после задержки");
        });
        Try("событие возникло при переключении меню после первой проверки очереди", () =>
        {
            var b = Fresh(); Enable(b); b.PollState();
            var town = ArriveTown(); b.PollState();
            var destination = new Settlement { Name = "Следующий город" };
            Scores((AiBehavior.GoToSettlement, destination, 2f), (AiBehavior.GoToSettlement, town, 1f));
            var wait = Campaign.Current.CurrentMenuContext.GameMenu.Options.First(o => o.IdString == "wait_leave");
            var original = wait.Consequence;
            wait.Consequence = () => {
                original();
                Map().NextIncident = new TaleWorlds.CampaignSystem.Incidents.Incident { StringId = "incident_hammer_of_the_sun" };
            };
            HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == town && PlayerEncounter.FinishCalls == 0,
                  "новое событие сохраняет город до движковой проверки его условия");
            Check(Map().NextIncident != null, "событие не потеряно из-за нового приказа");
            Map().NextIncident = null; b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null && MobileParty.MainParty.TargetSettlement == destination,
                  "после обработки события отложенный выход и цель сохраняются");
        });
        Try("событие не показалось — выход не зависает", () =>
        {
            var b = Fresh(); Enable(b); b.PollState();
            var town = ArriveTown(); b.PollState();
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, korsia, 2.0f), (AiBehavior.GoToSettlement, town, 1.0f));
            Map().NextIncident = new TaleWorlds.CampaignSystem.Incidents.Incident { StringId = "incident_stuck" };
            HourlyTick(b);
            for (int i = 0; i < 24; i++) b.PollState();     // предел ожидания — 20 опросов по 0.5 с
            Check(Map().NextIncident == null,
                  "после предела очередь снята самим автопилотом — движку нечего проверять после выхода");
            Check(MobileParty.MainParty.CurrentSettlement == null && MobileParty.MainParty.TargetSettlement == korsia,
                  "автопилот вышел и применил решение, а не завис в поселении");
            Check(AutopilotLog.Lines.Any(l => l.Contains("СОБЫТИЕ") && l.Contains("снято")),
                  "снятие события записано в журнал");
        });
        Try("выход от ворот замка снаружи", () =>
        {
            var b = Fresh(); Enable(b);
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = new Settlement { Name = "Замок" };
            Show(new GameMenu { StringId = "castle_outside" });
            b.PollState();
            Check(PlayerEncounter.Current == null && MobileParty.MainParty.HoldCalls >= 1,
                  "у ворот, где подождать нельзя, мирная встреча закрыта и движение остановлено");
        });
        Try("в поселении нельзя подождать", () =>
        {
            var b = Fresh(); Enable(b);
            var town = ArriveTown("Закрытый город", canWait: false); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null && PlayerEncounter.Current == null && b.CurrentMode == AutopilotBehavior.Mode.Apply,
                  "«Подождать» недоступно: партия уходит, автопилот работает дальше");
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, town, 3.0f), (AiBehavior.GoToSettlement, korsia, 1.0f));
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement == korsia,
                  "в поселение, где ждать нельзя, автопилот не возвращается по кругу — берёт следующее решение штатного AI");
        });

        Console.WriteLine("\n[находка 4] состояние не переживает сеанс");
        Try("новый сеанс в другом городе", () =>
        {
            var b = Fresh(); ArriveTown(); Enable(b); b.PollState(); b.Disable("test");
            var other = ArriveTown("Другой город");
            Enable(b); b.PollState();
            Check(Waiting && MobileParty.MainParty.CurrentSettlement == other, "в новом сеансе новый город обрабатывается: партия ждёт в нём");
        });

        Console.WriteLine("\n[находки 3, 7] чужие флаги не трогаются");
        Try("повторный F11", () =>
        {
            var b = Fresh(); MobileParty.MainParty.Ai.DoNotMakeNewDecisions = true; Enable(b); Enable(b); b.Disable("test");
            Check(MobileParty.MainParty.Ai.DoNotMakeNewDecisions, "исходное True сохранено после повторного F11");
        });
        Try("внешнее изменение во время сеанса", () =>
        {
            var b = Fresh(); Enable(b); MobileParty.MainParty.Ai.DoNotMakeNewDecisions = true; b.Disable("test");
            Check(MobileParty.MainParty.Ai.DoNotMakeNewDecisions, "выключение не затирает флаг, выставленный кем-то другим");
        });

        Console.WriteLine("\n[находка 3] загрузка сейва, сделанного при включённом автопилоте");
        Try("сохранение и загрузка", () =>
        {
            var b = Fresh(); Enable(b); MobileParty.MainParty.DefaultBehavior = AiBehavior.EscortParty;
            var store = new MemStore(); b.SyncData(store);
            var loaded = new AutopilotBehavior(); store.Loading = true; loaded.SyncData(store); Load(loaded);
            Check(loaded.CurrentMode == AutopilotBehavior.Mode.Off, "после загрузки автопилот выключен");
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.Hold, "маршрут, выданный автопилотом до сохранения, отменён");
        });

        Console.WriteLine("\n[находка 6] контракт");
        Try("повторная проверка контракта", () =>
        {
            EngineContract.Verify(); var first = EngineContract.Report;
            EngineContract.Verify(); var second = EngineContract.Report;
            Check(first == second, "повторный Verify не накручивает счётчик проверок (" + first + ")");
        });

        Console.WriteLine("\n[прогон в игре 13.09] закрытие встречи ставит паузу — цикл не должен застывать");
        Try("время после выхода", () =>
        {
            var b = Fresh();
            Campaign.Current.TimeControlMode = CampaignTimeControlMode.StoppablePlay; // автопилот ехал на обычной скорости
            MobileParty.MainParty.IsMoving = true;
            Enable(b); b.PollState();                                                 // свободная карта
            var town = ArriveTown(); b.PollState();                                   // прибыли и ждём
            Scores((AiBehavior.PatrolAroundPoint, new Settlement { Name = "Округа" }, 1.0f));
            HourlyTick(b); b.PollState();                                             // решили уйти; Finish ставит паузу
            Check(PlayerEncounter.FinishCalls == 1, "выход действительно закрыл встречу");
            Check(TimeRuns, "после выхода время снова идёт");
        });

        Console.WriteLine("\n[прогон в игре 13.09] штатный AI снова выбирает поселение, у которого партия стоит");
        Try("нет пинг-понга у ворот", () =>
        {
            var b = Fresh(); Enable(b);
            var s = new Settlement { Name = "Ревиль" };
            MobileParty.MainParty.LastVisitedSettlement = s; MobileParty.MainParty.StandsAtLastVisited = true;
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData { AiBehavior = AiBehavior.GoToSettlement, Party = s }, 2.0f));
            HourlyTick(b);
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls == 0,
                  "приказ посетить поселение, у которого партия уже стоит, не выдаётся — как у NPC");
        });
        Try("поездка в другое поселение", () =>
        {
            var b = Fresh(); Enable(b);
            var s = new Settlement { Name = "Корсия" };
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData { AiBehavior = AiBehavior.GoToSettlement, Party = s }, 2.0f));
            HourlyTick(b);
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls == 1,
                  "приказ посетить ДРУГОЕ поселение по-прежнему выдаётся (фикс не заблокировал поездки)");
        });

        Console.WriteLine("\n[прогон в игре 14.09] партия игрока замечает ближайшего врага");
        Try("ближняя атака штатной модели", () =>
        {
            var b = Fresh(); Enable(b);
            var bandits = new MobileParty { Name = "Лесные разбойники" };
            Campaign.Current.Models.MobilePartyAIModel.NextBehavior = AiBehavior.EngageParty;
            Campaign.Current.Models.MobilePartyAIModel.NextTarget = bandits;
            Campaign.Current.Models.MobilePartyAIModel.NextScore = 3.5f;
            Scores((AiBehavior.PatrolAroundPoint, new Settlement { Name = "Устокол" }, 2.25f));
            HourlyTick(b);
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.EngageCalls == 1
                  && MobileParty.MainParty.TargetParty == bandits,
                  "штатная ближняя оценка > 1 перебивает патруль и выдаёт погоню за бандитами");
            Check(AutopilotLog.Lines.Any(l => l.Contains("Лесные разбойники") && l.Contains("3.500")),
                  "цель и штатная оценка атаки записаны в журнале");
        });
        Try("слабая ближняя атака отвергнута", () =>
        {
            var b = Fresh(); Enable(b);
            Campaign.Current.Models.MobilePartyAIModel.NextBehavior = AiBehavior.EngageParty;
            Campaign.Current.Models.MobilePartyAIModel.NextTarget = new MobileParty { Name = "Сильный враг" };
            Campaign.Current.Models.MobilePartyAIModel.NextScore = 0.9f;
            Scores((AiBehavior.PatrolAroundPoint, new Settlement { Name = "Устокол" }, 2.25f));
            HourlyTick(b);
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.EngageCalls == 0
                  && MobileParty.MainParty.DefaultBehavior == AiBehavior.PatrolAroundPoint,
                  "оценка <= 1 не обходит штатный порог безопасности NPC");
        });
        Try("дальняя погоня из почасовых оценок", () =>
        {
            var b = Fresh(); Enable(b);
            var enemy = new MobileParty { Name = "Вражеский отряд" };
            Scores((AiBehavior.GoAroundParty, enemy, 2.5f),
                   (AiBehavior.PatrolAroundPoint, new Settlement { Name = "Устокол" }, 2.25f));
            HourlyTick(b);
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.GoAroundParty
                  && MobileParty.MainParty.TargetParty == enemy,
                  "штатное дальнее решение GoAroundParty больше не отбрасывается как неподдержанное");
        });

        Console.WriteLine("\n[прогон в игре 14.09] патруль не залипает на одной деревне");
        Try("одинаковый патруль не перевыдаётся", () =>
        {
            var b = Fresh(); Enable(b);
            var ustokol = new Settlement { Name = "Устокол" };
            Scores((AiBehavior.PatrolAroundPoint, ustokol, 2.25f));
            CampaignTime.TestHours = 0; HourlyTick(b);
            for (int h = 1; h <= 6; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.PatrolCalls == 1,
                  "тот же действующий приказ патруля за шесть часов выдан один раз");
            Check(LogCount("приказ не перевыдаю") == 1,
                  "продолжение того же патруля явно записано без ложной повторной выдачи");
        });
        Try("долгий патруль уступает следующей цели", () =>
        {
            var b = Fresh(); Enable(b);
            var ustokol = new Settlement { Name = "Устокол" };
            var reville = new Settlement { Name = "Ревиль" };
            Scores((AiBehavior.PatrolAroundPoint, ustokol, 2.25f), (AiBehavior.GoToSettlement, reville, 1.60f));
            CampaignTime.TestHours = 0; HourlyTick(b);
            for (int h = 1; h <= 24; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.GoToSettlement
                  && MobileParty.MainParty.TargetSettlement == reville,
                  "после 24 часов патруля предельный штраф 0.80 выводит партию к следующей штатной цели");
            Check(AutopilotLog.Lines.Any(l => l.Contains("штраф за") && l.Contains("Устокол")),
                  "причина смены патруля видна в журнале");
            Check(AutopilotLog.Lines.Any(l => l.Contains("выбрано автопилотом после ограничений") && l.Contains("Ревиль")),
                  "журнал отличает штатного победителя от фактически выбранной цели");
            Scores((AiBehavior.PatrolAroundPoint, ustokol, 2.25f), (AiBehavior.GoToSettlement, reville, 1.90f));
            for (int h = 25; h <= 30; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.TargetSettlement == reville,
                  "в течение суток охлаждения партия сразу не возвращается к тому же патрулю");
            for (int h = 31; h <= 48; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.PatrolAroundPoint
                  && MobileParty.MainParty.TargetSettlement == ustokol,
                  "через сутки охлаждение снимается и штатный сильный патруль снова допустим");
        });
        Try("сильный патруль Диатмы уступает поездке в другой город", () =>
        {
            var b = Fresh(); Enable(b);
            var faction = new TestFaction(); MobileParty.MainParty.MapFaction = faction;
            var origin = new Settlement { Name = "Диатма", IsTown = true, MapFaction = faction };
            var destination = new Settlement { Name = "Алосея", IsTown = true, MapFaction = faction };
            var unsafeTown = new Settlement { Name = "Осаждённый город", IsTown = true,
                IsUnderSiege = true, MapFaction = faction };
            Scores((AiBehavior.PatrolAroundPoint, origin, 4.309f),
                   (AiBehavior.GoToSettlement, destination, 0.64f),
                   (AiBehavior.GoToSettlement, unsafeTown, 2f));
            CampaignTime.TestHours = 0; HourlyTick(b);
            for (int h = 1; h <= 24; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.GoToSettlement
                  && MobileParty.MainParty.TargetSettlement == destination,
                  "после суток патруля маршрут идёт в безопасный другой город вопреки оценке 4.309");
            for (int h = 25; h <= 30; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.TargetSettlement == destination,
                  "до прибытия не разворачивается обратно к Диатме");
            Check(AutopilotLog.Lines.Any(l => l.Contains("ПОЕЗДКА:") && l.Contains("Алосея")),
                  "принудительная смена города объяснена в журнале");
            ArriveTown(destination); b.PollState();
            var nextTown = new Settlement { Name = "Джерак", IsTown = true, MapFaction = faction };
            Scores((AiBehavior.PatrolAroundPoint, origin, 4.309f),
                   (AiBehavior.GoToSettlement, destination, 0.4f),
                   (AiBehavior.GoToSettlement, nextTown, 0.5f));
            for (int h = 31; h <= 36; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(AutopilotLog.Lines.Any(l => l.Contains("ПОЕЗДКА: прибыли") && l.Contains("Алосея"))
                  && AutopilotLog.Lines.Any(l => l.Contains("решено уйти из «Алосея»") && l.Contains("Джерак")),
                  "после прибытия Диатма временно исключена, следующий маршрут ведёт в иной город");
        });
        Try("недавно посещённый город уступает новой мирной цели", () => {
            var b=Fresh(); Enable(b);
            var faction=new TestFaction(); MobileParty.MainParty.MapFaction=faction;
            var diatma=new Settlement { Name="Диатма", IsTown=true, MapFaction=faction };
            var fresh=new Settlement { Name="Алосея", IsTown=true, MapFaction=faction };
            ArriveTown(diatma); b.PollState();
            Scores((AiBehavior.GoToSettlement, diatma, 5f),
                   (AiBehavior.GoToSettlement, fresh, .6f));
            HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l=>l.Contains("решено уйти из «Диатма»") && l.Contains("Алосея")),
                  "обычный высокий балл недавнего города не удерживает партию на месте");
            Check(AutopilotLog.Lines.Any(l=>l.Contains("недавние города отложены")),
                  "причина смены города видна в журнале");
        });
        Try("когда все города знакомы, поездка идёт в самый давний", () => {
            var b=Fresh(); Enable(b);
            var faction=new TestFaction(); MobileParty.MainParty.MapFaction=faction;
            var origin=new Settlement { Name="Диатма", IsTown=true, MapFaction=faction };
            var older=new Settlement { Name="Роти", IsTown=true, MapFaction=faction };
            var newer=new Settlement { Name="Эпикротея", IsTown=true, MapFaction=faction };
            var visits=(Dictionary<Settlement,double>)typeof(AutopilotBehavior)
                .GetField("_recentTownVisits",BindingFlags.Instance|BindingFlags.NonPublic).GetValue(b);
            visits[older]=-100; visits[newer]=-20;
            Scores((AiBehavior.PatrolAroundPoint, origin, 4.3f),
                   (AiBehavior.GoToSettlement, older, .3f),
                   (AiBehavior.GoToSettlement, newer, .8f));
            CampaignTime.TestHours=0; HourlyTick(b);
            for (int h=1;h<=24;h++) { CampaignTime.TestHours=h; HourlyTick(b); }
            Check(MobileParty.MainParty.DefaultBehavior==AiBehavior.GoToSettlement
                  && MobileParty.MainParty.TargetSettlement==older,
                  "давно не посещённый город выигрывает у более высокой оценки недавнего");
        });
        Try("нет безопасного города — продолжаем патруль", () =>
        {
            var b = Fresh(); Enable(b);
            var faction = new TestFaction(); MobileParty.MainParty.MapFaction = faction;
            var origin = new Settlement { Name = "Диатма", IsTown = true, MapFaction = faction };
            var blocked = new Settlement { Name = "Осада", IsTown = true, IsUnderSiege = true, MapFaction = faction };
            Scores((AiBehavior.PatrolAroundPoint, origin, 4.309f),
                   (AiBehavior.GoToSettlement, blocked, 0.64f));
            CampaignTime.TestHours = 0; HourlyTick(b);
            for (int h = 1; h <= 30; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.DefaultBehavior == AiBehavior.PatrolAroundPoint
                  && MobileParty.MainParty.TargetSettlement == origin,
                  "не отправляем партию в осаждённый город ради смены места");
        });
        Try("малый перевес не дёргает текущий маршрут", () =>
        {
            var b = Fresh(); Enable(b);
            var ustokol = new Settlement { Name = "Устокол" };
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, ustokol, 2.00f));
            CampaignTime.TestHours = 0; HourlyTick(b);
            Scores((AiBehavior.GoToSettlement, ustokol, 2.00f), (AiBehavior.GoToSettlement, korsia, 2.10f));
            for (int h = 1; h <= 6; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.TargetSettlement == ustokol,
                  "перевес 0.10 меньше порога 0.15 — текущий маршрут сохранён");
            Scores((AiBehavior.GoToSettlement, ustokol, 2.00f), (AiBehavior.GoToSettlement, korsia, 2.20f));
            for (int h = 7; h <= 12; h++) { CampaignTime.TestHours = h; HourlyTick(b); }
            Check(MobileParty.MainParty.TargetSettlement == korsia,
                  "перевес 0.20 достаточен для смены маршрута");
        });

        Console.WriteLine("\n[прогон в игре 13.09] сообщение на F12 не утверждает того, чего не было");
        Try("итог выключения в наблюдении", () =>
        {
            var b = Fresh(); Enable(b, AutopilotBehavior.Mode.Observe); b.Disable("test");
            string summary = DisableSummary(b);
            Check(summary != null && !summary.Contains("остановлено") && !summary.Contains("восстановлено"),
                  "итог F12 в наблюдении не говорит об остановке и восстановлении (" + (summary ?? "итога нет") + ")");
        });

        Console.WriteLine("\n[прогон в игре 13.09, второй] пинг-понг: 89 входов и выходов в одном городе");
        Try("возврат в только что покинутое поселение", () =>
        {
            var b = Fresh(); Enable(b);
            var reville = ArriveTown("Ревиль"); b.PollState();                        // прибыли и ждём
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, korsia, 2.0f));
            HourlyTick(b); b.PollState();                                             // штатный AI увёл из Ревиля
            int finishAfterExit = PlayerEncounter.FinishCalls;
            ArriveTown(reville); b.PollState(); b.PollState(); b.PollState();         // и снова завёл в тот же Ревиль
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply && Waiting && MobileParty.MainParty.CurrentSettlement == reville,
                  "повторный вход — не повод выключаться: партия ждёт в городе, как NPC");
            Check(PlayerEncounter.FinishCalls == finishAfterExit, "партию не выводят снова — второго круга нет");
        });

        Console.WriteLine("\n[игра без человека] время не стоит, пока автопилот ведёт партию");
        Try("пауза на свободной карте", () =>
        {
            var b = Fresh(); MobileParty.MainParty.IsMoving = true;                   // Campaign.Current по умолчанию на паузе
            Enable(b); b.PollState();
            Check(TimeRuns, "автопилот снимает игру с паузы — человека за компьютером нет");
        });
        Try("время «идёт», но стоит", () =>
        {
            var b = Fresh(); Campaign.Current.TimeControlMode = CampaignTimeControlMode.StoppablePlay;
            MobileParty.MainParty.SetMoveModeHold();                                  // Stoppable + партия стоит = время не идёт
            Enable(b); b.PollState();
            Check(TimeRuns, "режим «идёт, пока партия едет» при стоящей партии заменён на неостанавливаемый");
        });

        Console.WriteLine("\n[игра без человека] решение вне области не выключает автопилот");
        Try("осада как лучшее решение", () =>
        {
            var b = Fresh(); Enable(b);
            var besieged = new Settlement { Name = "Осаждаемый" }; var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.BesiegeSettlement, besieged, 5.0f), (AiBehavior.GoToSettlement, korsia, 1.0f));
            HourlyTick(b);
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply, "автопилот работает дальше");
            Check(MobileParty.MainParty.TargetSettlement == korsia, "применено лучшее из поддерживаемых решений штатного AI");
        });

        Console.WriteLine("\n[игра без человека] сторож простоя");
        Try("простой записывается один раз", () =>
        {
            var b = Fresh(); Campaign.Current.TimeControlModeLock = true;             // паузу держит кто-то другой
            var t0 = new DateTime(2026, 9, 13, 12, 0, 0);
            SetClock(t0); Enable(b); b.PollState();
            SetClock(t0.AddSeconds(5)); b.PollState();
            Check(LogCount("ПРОСТОЙ") == 0, "пауза в 5 секунд простоем не считается");
            SetClock(t0.AddSeconds(11)); b.PollState(); SetClock(t0.AddSeconds(12)); b.PollState(); SetClock(t0.AddSeconds(30)); b.PollState();
            Check(LogCount("ПРОСТОЙ") == 1, "простой дольше 10 секунд записан ровно один раз, без повтора на каждом опросе");
            Check(AutopilotLog.Lines.Any(l => l.Contains("ПРОСТОЙ") && l.Contains("Stop") && l.Contains("заблок")),
                  "запись простоя называет состояние: режим времени и блокировку");
            CampaignTime.TestHours = 1; SetClock(t0.AddSeconds(31)); b.PollState();
            Check(LogCount("время снова идёт") == 1, "возобновление после простоя записано");
        });

        Console.WriteLine("\n[проверка 13.09] находки независимой проверки куска «игра играет сама»");
        Try("остановка ожидания в деревне", () =>
        {
            var b = Fresh(); Enable(b); b.PollState();
            ArriveVillage("Деревня"); b.PollState();
            Check(Campaign.Current.CurrentMenuContext?.GameMenu?.StringId == "village_wait_menus", "в деревне автопилот ждёт");
            var korsia = new Settlement { Name = "Корсия" };
            Scores((AiBehavior.GoToSettlement, korsia, 2.0f));
            HourlyTick(b); b.PollState();
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply,
                  "«Перестать ждать» в деревне не выключает автопилот, хотя движок оставляет IsPlayerWaiting");
            Check(MobileParty.MainParty.CurrentSettlement == null && PlayerEncounter.Current == null
                  && MobileParty.MainParty.TargetSettlement == korsia,
                  "партия вышла из деревни и поехала к цели, ради которой перестала ждать");
        });
        Try("меню под другим экраном", () =>
        {
            var b = Fresh(); ArriveTown(); TaleWorlds.Core.Game.Current.GameStateManager.ActiveState = new TaleWorlds.Core.GameState();
            Enable(b); b.PollState();
            Check(MenuContext.Invoked.Count == 0 && PlayerEncounter.FinishCalls == 0,
                  "поверх карты открыт другой экран: пункты меню под ним не нажимаются, встреча не закрывается");
            b = Fresh(); ArriveTown(); TaleWorlds.Core.Game.Current.GameStateManager.ActiveStateDisabledByUser = true;
            Enable(b); b.PollState();
            Check(MenuContext.Invoked.Count == 0 && PlayerEncounter.FinishCalls == 0,
                  "карта приостановлена окном: пункты меню не нажимаются");
        });
        Try("пауза под окном", () =>
        {
            var b = Fresh(); MobileParty.MainParty.IsMoving = true;
            TaleWorlds.Core.Game.Current.GameStateManager.ActiveStateDisabledByUser = true;
            Enable(b); b.PollState();
            Check(Campaign.Current.TimeControlMode == CampaignTimeControlMode.Stop,
                  "окно держит карту — автопилот не переписывает режим времени под ним");
        });
        Try("временная недоступность ожидания", () =>
        {
            var b = Fresh(); Enable(b);
            var blocked = ArriveTown("Закрытый на время", canWait: false); b.PollState();
            var other = new Settlement { Name = "Другой" };
            CampaignTime.TestHours = 10;
            Scores((AiBehavior.GoToSettlement, blocked, 3.0f), (AiBehavior.GoToSettlement, other, 1.0f));
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement == other, "вскоре после неудачи в то же поселение не едем");
            MobileParty.MainParty.SetMoveModeHold();
            CampaignTime.TestHours = 30;
            HourlyTick(b);
            Check(MobileParty.MainParty.TargetSettlement == blocked,
                  "через сутки запрет снят: временная причина не вычёркивает поселение до конца сеанса");
        });
        Try("идущий простой в итоге сеанса", () =>
        {
            var b = Fresh(); Campaign.Current.TimeControlModeLock = true;
            var t0 = new DateTime(2026, 9, 13, 12, 0, 0);
            SetClock(t0); Enable(b); b.PollState();
            SetClock(t0.AddSeconds(11)); b.PollState(); SetClock(t0.AddSeconds(60)); b.PollState();
            b.Disable("test");
            Check(AutopilotLog.Lines.Any(l => l.Contains("итог сеанса") && l.Contains("самый долгий 60 с")),
                  "простой, который ещё идёт при выключении, попадает в итог (было «самый долгий 0 с»)");
        });
        Try("долгое пребывание видно в журнале", () =>
        {
            var b = Fresh(); Enable(b); var town = ArriveTown("Ревиль"); b.PollState();
            for (int h = 0; h <= 130; h++)
            {
                CampaignTime.TestHours = h; Scores((AiBehavior.GoToSettlement, town, 2.0f)); HourlyTick(b); b.PollState();
            }
            Check(LogCount("ДОЛГОЕ ПРЕБЫВАНИЕ") == 1,
                  "пять суток в одном поселении без решения уйти — одна запись в журнале, а не тишина");
            Check(Waiting && b.CurrentMode == AutopilotBehavior.Mode.Apply, "запись не выгоняет партию и не выключает автопилот");
        });

        Console.WriteLine("\n[проверка 13.09, итог] пропуски после исправлений");
        Try("F11 во время уже начатого ожидания", () =>
        {
            var b = Fresh(); var town = ArriveTown("Уже ждём");
            MenuDriver.TryInvoke("town_wait", out _); MenuContext.Invoked.Clear();       // ожидание начал человек
            Enable(b);
            for (int h = 1; h <= 240; h++)
            {
                CampaignTime.TestHours = h; Scores((AiBehavior.GoToSettlement, town, 10f)); HourlyTick(b); b.PollState();
            }
            Check(LogCount("ДОЛГОЕ ПРЕБЫВАНИЕ") == 1,
                  "ожидание, начатое до F11: предупреждение о долгом пребывании всё равно появляется (было — ни одного за 240 часов)");
        });

        Console.WriteLine("\n[обслуживание] еда, найм и пленные в поселении — как NPC, путями движка");
        Try("город, денег хватает", () =>
        {
            var b = Fresh(); var w = MakeWorld(); Enable(b); b.PollState();
            ArriveTown(w.Place); b.PollState();
            var party = MobileParty.MainParty;
            Check(Grain(w) == 150, "еды куплено столько, сколько штатный расчёт запаса: 5 в день × 30 дней = 150 (куплено " + Grain(w) + ")");
            Check(w.Place.ItemRoster.TestCount(w.Grain) == 150, "у продавца убыло столько же — товар не взялся из ничего");
            Check(CampaignEventDispatcher.Recruited.Count == 3 && w.Notable.VolunteerTypes.Take(3).All(t => t == null),
                  "нанято трое доступных добровольцев, их слоты у старосты освобождены, событие найма на каждого");
            Check(party.MemberRoster.TotalManCount == 23, "в отряде стало 23");
            Check(party.PrisonRoster.TotalRegulars == 0 && party.PrisonRoster.TotalHeroes == 1,
                  "обычные пленные проданы, пленный лорд остался в плену");
            int expected = 20000 + 10 * 20 - 150 * 20 - 3 * 30;
            Check(Hero.MainHero.Gold == expected, "деньги: +200 выкуп, −3000 еда, −90 найм (стало " + Hero.MainHero.Gold + ", ждали " + expected + ")");
            Check(LogCount("КУПЛЕНО") == 1 && LogCount("НАНЯТ") == 3 && LogCount("ПРОДАНО") == 1,
                  "журнал называет фактические покупку, найм и продажу");
            Check(Waiting && PlayerEncounter.FinishCalls == 0, "обслуживание не выгоняет из города — партия ждёт, как раньше");
        });
        Try("пересчёт видит обновлённую партию", () =>
        {
            var b = Fresh(); var w = MakeWorld(); Enable(b); b.PollState();
            ArriveTown(w.Place); b.PollState();
            Scores((AiBehavior.GoToSettlement, w.Place, 2.0f)); HourlyTick(b);
            Check(CampaignEventDispatcher.ThinkFood == 150 && CampaignEventDispatcher.ThinkMembers == 23,
                  "штатный пересчёт AI после обслуживания видит купленную еду и нанятых (" + CampaignEventDispatcher.ThinkFood
                  + " еды, " + CampaignEventDispatcher.ThinkMembers + " в отряде)");
        });
        Try("денег мало", () =>
        {
            var b = Fresh(); var w = MakeWorld(gold: 2100, prisoners: false); Enable(b); b.PollState();
            ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 5 && Hero.MainHero.Gold == 2000,
                  "на еду ушло ровно то, что сверх резерва 2000: 5 зерна за 100 (зерна " + Grain(w) + ", денег " + Hero.MainHero.Gold + ")");
            Check(CampaignEventDispatcher.Recruited.Count == 0 && AutopilotLog.Lines.Any(l => l.Contains("денег сверх резерва нет")),
                  "на найм денег не хватило — никого, причина в журнале");
        });
        Try("денег нет", () =>
        {
            var b = Fresh(); var w = MakeWorld(gold: 500, prisoners: false); Enable(b); b.PollState();
            ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0 && Hero.MainHero.Gold == 500,
                  "деньги ниже резерва: ничего не куплено и не нанято, золото не тронуто");
            Check(LogCount("денег сверх резерва нет") == 2, "журнал называет причину и для еды, и для найма");
        });
        Try("еда уже есть", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); MobileParty.MainParty.ItemRoster.TestAdd(w.Grain, 200);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 200 && LogCount("еда: хватает") == 1, "запаса на 40 дней хватает до цели в 30 — еда не докупается");
        });
        Try("у продавца нет еды", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); w.Place.ItemRoster.TestAdd(w.Grain, -300);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 0 && LogCount("у продавца еды нет") == 1, "рынок пуст — ничего не куплено, причина в журнале");
        });
        Try("у продавца мало еды — частичное выполнение", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); w.Place.ItemRoster.TestAdd(w.Grain, -270);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 30 && w.Place.ItemRoster.TestCount(w.Grain) == 0 && Hero.MainHero.Gold == 20000 - 30 * 20 - 3 * 30,
                  "куплено ровно 30 из нужных 150 — сверх остатка не покупается и не оплачивается");
            Check(AutopilotLog.Lines.Any(l => l.Contains("нужно было 150, запас пополнен на 30")), "частичное выполнение названо в журнале");
        });
        Try("партия заполнена и одно место", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); MobileParty.MainParty.Party.PartySizeLimit = 20;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 0 && LogCount("партия полна") == 1, "партия полна — никого не нанимаем");
            b = Fresh(); w = MakeWorld(prisoners: false); MobileParty.MainParty.Party.PartySizeLimit = 21;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 1 && w.Notable.VolunteerTypes[1] == w.Recruit && Hero.MainHero.Gold == 20000 - 150 * 20 - 30,
                  "одно место — ровно один нанятый, остальные добровольцы остались у старосты, списана цена одного");
        });
        Try("добровольцы недоступны", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); w.Notable.TestMaxRecruitIndex = -1;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 0 && w.Notable.VolunteerTypes[0] == w.Recruit
                  && AutopilotLog.Lines.Any(l => l.Contains("не хватает отношений 3")),
                  "отношений со старостой не хватает — никого, слоты не тронуты, причина в журнале");
        });
        Try("найм закрывает дефицит состава", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false);
            // В отряде одна пехота, а цель стрелков — 70%. Стрелок дороже и ниже
            // уровнем, но дефицит рода войск должен быть важнее цены и tier.
            var infantry = new CharacterObject { Name = "Дорогой пехотинец", Tier = 6, TestCost = 20 };
            var archer = new CharacterObject { Name = "Стрелок", IsRanged = true, Tier = 1, TestCost = 30 };
            w.Notable.VolunteerTypes = new CharacterObject[6];
            w.Notable.VolunteerTypes[0] = infantry;
            w.Notable.VolunteerTypes[1] = archer;
            MobileParty.MainParty.Party.PartySizeLimit = 21;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 1 && CampaignEventDispatcher.Recruited[0] == archer
                  && w.Notable.VolunteerTypes[0] == infantry && w.Notable.VolunteerTypes[1] == null,
                  "при одном месте выбран недостающий стрелок, доступный пехотинец оставлен");
        });
        Try("пленные герои и закреплённые не продаются", () =>
        {
            var b = Fresh(); var w = MakeWorld(); Helpers.MobilePartyHelper.TestLockedIds.Add("looter");
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            var prison = MobileParty.MainParty.PrisonRoster;
            Check(TaleWorlds.CampaignSystem.Actions.SellPrisonersAction.TestCalls == 0 && prison.TotalRegulars == 10 && prison.TotalHeroes == 1,
                  "закреплённых игроком грабителей и лорда не продаём и не отпускаем — продажа даже не вызывается");
        });
        Try("повторные опросы", () =>
        {
            var b = Fresh(); var w = MakeWorld(); Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            int gold = Hero.MainHero.Gold;
            for (int i = 0; i < 5; i++) b.PollState();
            Check(LogCount("ОБСЛУЖИВАНИЕ") == 1 && Hero.MainHero.Gold == gold, "опросы в тот же час не повторяют обслуживание");
            CampaignTime.TestHours = 7; b.PollState();
            Check(LogCount("ОБСЛУЖИВАНИЕ") == 2 && Hero.MainHero.Gold == gold && Grain(w) == 150 && CampaignEventDispatcher.Recruited.Count == 3,
                  "проход через 7 часов идёт, но ничего не дублирует: еды хватает, слоты пусты, пленных нет");
        });
        Try("повторное включение и загрузка", () =>
        {
            var b = Fresh(); var w = MakeWorld(); Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            int gold = Hero.MainHero.Gold;
            b.Disable("test"); Enable(b); b.PollState();
            Check(LogCount("ОБСЛУЖИВАНИЕ") == 1 && Hero.MainHero.Gold == gold, "F12 → F11 в том же часу: второго прохода нет");
            var loaded = new AutopilotBehavior(); Enable(loaded); loaded.PollState();
            Check(Hero.MainHero.Gold == gold && Grain(w) == 150 && CampaignEventDispatcher.Recruited.Count == 3
                  && MobileParty.MainParty.PrisonRoster.TotalHeroes == 1,
                  "новый объект без данных сейва (сейв до этой версии): проход идёт заново, но по состоянию партии ничего не дублирует");
        });

        Try("деревня", () =>
        {
            var b = Fresh(); var w = MakeWorld(village: true); Enable(b); b.PollState();
            MobileParty.MainParty.LastVisitedSettlement = w.Place; ArriveVillage(w.Place); b.PollState();
            Check(Grain(w) == 60, "в деревне цель запаса — 12 дней: куплено 60 (куплено " + Grain(w) + ")");
            Check(CampaignEventDispatcher.Recruited.Count == 3, "в деревне нанято трое");
            Check(MobileParty.MainParty.PrisonRoster.TotalRegulars == 10 && AutopilotLog.Lines.Any(l => l.Contains("только в городе")),
                  "пленных в деревне не продаём — у игрока выкуп только в городе");
        });
        Try("уже начатое ожидание в городе", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); ArriveTown(w.Place);
            MenuDriver.TryInvoke("town_wait", out _); Enable(b); b.PollState();
            Check(Grain(w) == 150 && CampaignEventDispatcher.Recruited.Count == 3, "F11 во время ожидания в городе — партия внутри, обслуживание идёт");
        });
        Try("уже начатое ожидание в деревне", () =>
        {
            var b = Fresh(); var w = MakeWorld(village: true, prisoners: false);
            MobileParty.MainParty.LastVisitedSettlement = w.Place; ArriveVillage(w.Place);
            MenuDriver.TryInvoke("village_wait", out _); Enable(b); b.PollState(); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0, "в деревенском ожидании партия за околицей — не покупаем и не нанимаем");
            Check(LogCount("за околицей") == 1, "причина записана один раз, без повтора на каждом опросе");
        });
        Try("экран или окно поверх карты", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); ArriveTown(w.Place);
            TaleWorlds.Core.Game.Current.GameStateManager.ActiveState = new TaleWorlds.Core.GameState(); Enable(b); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0, "под другим экраном — ничего");
            b = Fresh(); w = MakeWorld(prisoners: false); ArriveTown(w.Place);
            TaleWorlds.Core.Game.Current.GameStateManager.ActiveStateDisabledByUser = true; Enable(b); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0, "карта приостановлена окном — ничего");
            b = Fresh(); w = MakeWorld(prisoners: false); ArriveTown(w.Place);
            TaleWorlds.Library.InformationManager.TestInquiryActive = true; Enable(b); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0 && LogCount("открыто окно") >= 1,
                  "открыт запрос (окно с кнопками) — ничего, причина в журнале");
        });
        Try("F10 и выключенный автопилот", () =>
        {
            var b = Fresh(); var w = MakeWorld(); ArriveTown(w.Place); Enable(b, AutopilotBehavior.Mode.Observe); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0 && MobileParty.MainParty.PrisonRoster.TotalRegulars == 10,
                  "F10 ничего не покупает, не нанимает и не продаёт");
            b = Fresh(); w = MakeWorld(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0 && MobileParty.MainParty.PrisonRoster.TotalRegulars == 10,
                  "выключенный автопилот ничего не делает");
        });
        Try("отказ движка и молчаливая неудача", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false);
            Campaign.Current.Models.SettlementAccessModel.TestTrade = false; Campaign.Current.Models.SettlementAccessModel.TestRecruit = false;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0
                  && LogCount("торговать игроку нельзя: закрыто проверкой") == 1 && LogCount("нанимать игроку нельзя: закрыто проверкой") == 1,
                  "пункты «Торговать» и «Нанять» закрыты для игрока — ничего, причина движка в журнале");
            b = Fresh(); w = MakeWorld(prisoners: false); TaleWorlds.CampaignSystem.Actions.SellItemsAction.TestBroken = true;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 0 && LogCount("КУПЛЕНО") == 0 && LogCount("НЕ подтвердилась") == 1,
                  "покупка молча не сработала — это не успех: в журнале «не подтвердилась», «куплено» не пишется");
        });
        Try("бой, осада и разграбленная деревня", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); Enable(b); b.PollState();
            ArriveTown(w.Place); MobileParty.MainParty.MapEvent = new MapEvent(); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0, "идёт бой — ничего");
            b = Fresh(); w = MakeWorld(prisoners: false); w.Place.IsUnderSiege = true; Enable(b); b.PollState();
            ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0, "поселение в осаде — ничего");
            b = Fresh(); w = MakeWorld(village: true, prisoners: false); w.Place.IsRaided = true; Enable(b); b.PollState();
            MobileParty.MainParty.LastVisitedSettlement = w.Place; ArriveVillage(w.Place); b.PollState();
            Check(Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0, "деревня разграблена — ничего");
        });

        Console.WriteLine("\n[проверка 14.09] пропуски обслуживания: оплата найма, предел между загрузками, пределы, которые срабатывают");
        Try("событие найма падает", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); CampaignEventDispatcher.TestRecruitedThrows = true;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            int joined = MobileParty.MainParty.MemberRoster.TotalManCount - 20;
            Check(joined == 1 && w.Notable.VolunteerTypes[0] == null && w.Notable.VolunteerTypes[1] == w.Recruit,
                  "событие упало на первом бойце: в отряде +1, его слот освобождён, остальные добровольцы у старосты (в отряде +" + joined + ")");
            int expected = 20000 - 150 * 20 - 30;
            Check(Hero.MainHero.Gold == expected,
                  "боец, уже попавший в отряд, оплачен, хотя событие после него упало (денег " + Hero.MainHero.Gold + ", ждали " + expected + ")");
            Check(b.CurrentMode == AutopilotBehavior.Mode.Off && LogCount("НАНЯТ") == 1,
                  "падение выключает автопилот, а журнал называет нанятого и оплаченного бойца (записей «НАНЯТ»: " + LogCount("НАНЯТ") + ")");
        });
        Try("загрузка сразу после прохода, упёршегося в предел", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); SetLimit("MaxFoodSpendPerPass", 1000);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            int grain = Grain(w), gold = Hero.MainHero.Gold;
            Check(grain == 50, "проход упёрся в точный предел трат на еду: 50 зерна за 1000 (куплено " + grain + ")");
            var store = new MemStore(); b.SyncData(store);                                  // сохранение в час 0
            CampaignTime.TestHours = 1;
            var loaded = new AutopilotBehavior(); store.Loading = true; loaded.SyncData(store); Load(loaded);
            Enable(loaded); loaded.PollState();
            Check(LogCount("ОБСЛУЖИВАНИЕ") == 1 && Grain(w) == grain && Hero.MainHero.Gold == gold,
                  "загрузка через час после прохода не даёт второго: предел трат за 6 часов не умножается загрузками (зерна " + Grain(w) + ")");
            int passes = LogCount("ОБСЛУЖИВАНИЕ"), grainBefore = Grain(w);
            CampaignTime.TestHours = 6; loaded.PollState();
            Check(LogCount("ОБСЛУЖИВАНИЕ") == passes + 1 && Grain(w) == grainBefore + 50,
                  "через 6 часов после прохода, сделанного до сохранения, идёт следующий (проходов " + passes + " → " + LogCount("ОБСЛУЖИВАНИЕ")
                  + ", зерна " + grainBefore + " → " + Grain(w) + ")");
        });
        Try("цена еды растёт во время покупки", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); SetLimit("MaxFoodSpendPerPass", 100);
            w.Grain.TestPrice = 10; w.Grain.TestPriceIncreasePerSale = 10;
            w.Notable.TestMaxRecruitIndex = -1;
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(Grain(w) == 4 && Hero.MainHero.Gold == 19900,
                  "каждая следующая цена пересчитана: куплено за 10+20+30+40, резерв и лимит сохранены");
        });
        Try("выбранный товар закончился, но другая еда есть", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); MobileParty.MainParty.FoodChange = -1f;
            w.Place.ItemRoster.TestAdd(w.Grain, -299);
            var other = new ItemObject { Name = "Другая еда", IsFood = true, TestPrice = 21 };
            w.Place.ItemRoster.TestAdd(other, 100);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(MobileParty.MainParty.TotalFoodAtInventory == 30 && w.Place.ItemRoster.TestCount(other) == 71,
                  "после последней дешёвой единицы выбор продолжается из оставшегося товара");
        });
        Try("деревня без торгового города", () =>
        {
            var b = Fresh(); var w = MakeWorld(village: true, prisoners: false); w.Place.Village.TradeBound = null;
            w.Notable.TestMaxRecruitIndex = -1;
            Enable(b); b.PollState(); MobileParty.MainParty.LastVisitedSettlement = w.Place; ArriveVillage(w.Place); b.PollState();
            Check(Grain(w) == 60 && Hero.MainHero.Gold == 20000 - 60 * 20,
                  "при TradeBound == null цену берём из Bound.Town, как SellItemsAction, а не условную цену деревни 1");
        });
        Try("пределы найма за проход срабатывают", () =>
        {
            // Мир MakeWorld в пределы не упирается (3 бойца по 30), и до 14.09 ни одна
            // проверка их не доводила до срабатывания — снятый предел никто бы не заметил.
            var b = Fresh(); var w = MakeWorld(prisoners: false); SetLimit("MaxRecruitsPerPass", 2);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 2 && w.Notable.VolunteerTypes[2] == w.Recruit
                  && AutopilotLog.Lines.Any(l => l.Contains("остановка: предел 2 за проход")),
                  "предел числа за проход 2: нанято двое, третий доброволец остался, причина в журнале (нанято " + CampaignEventDispatcher.Recruited.Count + ")");
            b = Fresh(); w = MakeWorld(prisoners: false); SetLimit("MaxRecruitSpendPerPass", 60);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            Check(CampaignEventDispatcher.Recruited.Count == 2 && Hero.MainHero.Gold == 20000 - 150 * 20 - 60
                  && AutopilotLog.Lines.Any(l => l.Contains("не по деньгам 1")),
                  "предел трат на найм 60: нанято двое по 30, третий не по деньгам (нанято " + CampaignEventDispatcher.Recruited.Count
                  + ", денег " + Hero.MainHero.Gold + ")");
        });
        Try("данные обслуживания в сейве пустые или испорчены", () =>
        {
            foreach (string saved in new[] { "", "мусор;=5;x=abc;;" })
            {
                var b = Fresh(); var w = MakeWorld(prisoners: false);
                var store = new MemStore { Loading = true };
                store.Data["shedautopilot_servicePasses"] = saved;
                b.SyncData(store); Load(b);
                Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
                Check(Grain(w) == 150, "сейв с данными «" + saved + "»: загрузка не падает, проход в поселении идёт (зерна " + Grain(w) + ")");
            }
        });

        Console.WriteLine("\n[прогон в игре 14.09] цепочка решений королевства");
        Try("два голосования подряд", () =>
        {
            var b = Fresh(); Enable(b);
            TaleWorlds.Core.Game.Current.GameStateManager.ActiveState = new TaleWorlds.CampaignSystem.GameState.KingdomState();
            var screen = new SandBox.GauntletUI.GauntletKingdomScreen();
            TaleWorlds.ScreenSystem.ScreenManager.TopScreen = screen;
            var firstLow = new TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.DecisionOptionVM { Name="Нет", WinPercentage=20 };
            var firstPopular = new TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.DecisionOptionVM { Name="Да", WinPercentage=80 };
            var first = new TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.ItemTypes.DecisionItemBaseVM { CanEndDecision=true };
            first.DecisionOptionsList.Add(firstLow); first.DecisionOptionsList.Add(firstPopular);
            var secondPopular = new TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.DecisionOptionVM { Name="Мир", WinPercentage=60 };
            var secondLow = new TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.DecisionOptionVM { Name="Война", WinPercentage=40 };
            var second = new TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.ItemTypes.DecisionItemBaseVM { CanEndDecision=true, IsPlayerSupporter=true };
            second.DecisionOptionsList.Add(secondPopular); second.DecisionOptionsList.Add(secondLow);
            screen.DataSource.Decision.NextItem = second;
            screen.DataSource.Decision.SetQuery(new TaleWorlds.Library.InquiryData {
                TitleText="Решение", IsAffirmativeOptionShown=true,
                AffirmativeAction=()=>screen.DataSource.Decision.CurrentDecision=first });
            TaleWorlds.Library.InformationManager.TestInquiryActive=true;
            Clan.PlayerClan.Kingdom.UnresolvedDecisions.Add(new KingdomDecision());
            for (int i=0; i<9; i++) b.PollState();
            Check(firstPopular.Selected && !firstLow.Selected,
                  "в первом окне выбран вариант 80%, а не вариант 20%");
            Check(secondPopular.Selected && secondPopular.Supported && !secondLow.Selected,
                  "следующее голосование тоже обработано: выбран вариант 60% с минимальной поддержкой");
            Check(TaleWorlds.Core.Game.Current.GameStateManager.PopCalls == 1,
                  "после запроса, двух голосований и двух итогов экран закрыт, автопилот вернулся на карту");
            Check(AutopilotLog.Lines.Count(l => l.Contains("выбран самый популярный вариант")) == 2,
                  "оба автоматически принятых решения записаны в журнале");
        });

        Console.WriteLine("\n[прогон в игре 14.09] окно поверх карты: время заперто, а автопилот окна не видел");
        Try("известное событие «Яблоки с небес»", () =>
        {
            var b = Fresh(); Enable(b);
            var incident = new TaleWorlds.CampaignSystem.Incidents.Incident {
                StringId = "incident_apples_from_heaven", Title = new TaleWorlds.Localization.TextObject("Яблоки с небес")
            };
            int selected = -1;
            incident.Options.Add((new TaleWorlds.Localization.TextObject("Помочь себе"), new List<TaleWorlds.Localization.TextObject>{new("Мораль +5")}, () => selected = 0));
            incident.Options.Add((new TaleWorlds.Localization.TextObject("Сообщить жителям"), new List<TaleWorlds.Localization.TextObject>{new("Мораль -5")}, () => selected = 1));
            Screen.IncidentView = new SandBox.View.Map.MapIncidentView(incident); Screen.IsMapIncidentActive = true;
            b.PollState();
            Check(selected >= 0 && selected <= 1 && !Screen.IsMapIncidentActive,
                  "проверенный безопасный вариант вызван, штатный слой события закрыт");
            Check(AutopilotLog.Lines.Any(l => l.Contains("СОБЫТИЕ РЕШЕНО") && l.Contains("вариант " + selected)),
                  "автоматический выбор и его результат записаны");
        });
        Try("однокнопочное событие", () =>
        {
            var b = Fresh(); Enable(b);
            var incident = new TaleWorlds.CampaignSystem.Incidents.Incident {
                StringId = "incident_ack", Title = new TaleWorlds.Localization.TextObject("Продолжение")
            };
            int calls = 0;
            incident.Options.Add((new TaleWorlds.Localization.TextObject("OK"), new List<TaleWorlds.Localization.TextObject>{new("Ничего не происходит")}, () => calls++));
            Screen.IncidentView = new SandBox.View.Map.MapIncidentView(incident); Screen.IsMapIncidentActive = true;
            b.PollState();
            Check(calls == 1 && !Screen.IsMapIncidentActive, "единственная кнопка нажата ровно один раз и окно закрыто");
        });
        Try("неизвестное многовариантное событие", () =>
        {
            var b = Fresh(); Enable(b);
            var incident = new TaleWorlds.CampaignSystem.Incidents.Incident {
                StringId = "incident_unknown", Title = new TaleWorlds.Localization.TextObject("Неизвестное")
            };
            int calls = 0;
            incident.Options.Add((new TaleWorlds.Localization.TextObject("Потратить золото"), new List<TaleWorlds.Localization.TextObject>{new("Золото -100")}, () => calls++));
            incident.Options.Add((new TaleWorlds.Localization.TextObject("Потерять бойца"), new List<TaleWorlds.Localization.TextObject>{new("Боец погибает")}, () => calls++));
            Screen.IncidentView = new SandBox.View.Map.MapIncidentView(incident); Screen.IsMapIncidentActive = true;
            b.PollState(); b.PollState();
            Check(calls == 1 && !Screen.IsMapIncidentActive, "случайный вариант неизвестного события выполнен один раз");
            Check(LogCount("СОБЫТИЕ РЕШЕНО") == 1 && AutopilotLog.Lines.Any(l => l.Contains("Золото -100")),
                  "название, варианты и последствия записаны один раз");
        });
        Try("окно случайного события у деревни", () =>
        {
            // Жемянь, 02:50: после прибытия открылось окно события (CreateLayout ставит Stop и
            // запирает время), автопилот обслуживал и нажимал «Подождать» под ним, а запись о
            // простое 161 с называла только «заблокирован».
            var b = Fresh(); var w = MakeWorld(village: true, prisoners: false); Enable(b); b.PollState();
            MobileParty.MainParty.LastVisitedSettlement = w.Place; ArriveVillage(w.Place);
            Screen.IsMapIncidentActive = true; Campaign.Current.TimeControlModeLock = true;
            var t0 = new DateTime(2026, 9, 14, 2, 50, 29);
            SetClock(t0); b.PollState();
            Check(MenuContext.Invoked.Count == 0 && Grain(w) == 0 && CampaignEventDispatcher.Recruited.Count == 0,
                  "под окном события ни обслуживания, ни «Подождать» (в игре было и то и другое)");
            SetClock(t0.AddSeconds(11)); b.PollState();
            Check(AutopilotLog.Lines.Any(l => l.Contains("ПРОСТОЙ") && l.Contains("окно случайного события")),
                  "запись о простое называет окно, которое держит игру (было только «заблокирован»)");
            Screen.IsMapIncidentActive = false; Campaign.Current.TimeControlModeLock = false;         // человек выбрал вариант
            b.PollState();
            Check(Grain(w) == 60 && CampaignEventDispatcher.Recruited.Count == 3 && MenuContext.Invoked.Contains("village_wait"),
                  "окно закрыто — автопилот продолжает сам: обслуживание и «Подождать» (зерна " + Grain(w)
                  + ", режим " + b.CurrentMode + ", окно " + Screen.IsMapIncidentActive
                  + ", вызовы " + string.Join(",", MenuContext.Invoked) + ")");
        });
        Try("каждое окно поверх карты останавливает действия", () =>
        {
            var overlays = new (string Name, Action<SandBox.View.Map.MapScreen> Open)[]
            {
                ("событие", s => s.IsMapIncidentActive = true), ("брак", s => s.IsMarriageOfferPopupActive = true),
                ("наследник", s => s.IsHeirSelectionPopupActive = true), ("армия", s => s.IsInArmyManagement = true),
                ("найм", s => s.IsInRecruitment = true), ("управление поселением", s => s.IsInTownManagement = true),
                ("логово", s => s.IsInHideoutTroopManage = true), ("автобой", s => s.IsInBattleSimulation = true),
                ("настройки", s => s.IsInCampaignOptions = true), ("меню паузы", s => s.IsEscapeMenuOpened = true),
                ("читы", s => s.IsMapCheatsActive = true), ("контекстное меню", s => s.IsOverlayContextMenuEnabled = true),
                ("энциклопедия", s => s.EncyclopediaScreenManager.IsEncyclopediaOpen = true),
            };
            var acted = new List<string>();
            foreach (var overlay in overlays)
            {
                var b = Fresh(); ArriveTown(); overlay.Open(Screen); Enable(b); b.PollState();
                if (MenuContext.Invoked.Count > 0 || PlayerEncounter.FinishCalls > 0) acted.Add(overlay.Name);
            }
            Check(acted.Count == 0, "ни под одним из " + overlays.Length + " окон карты пункты меню не нажимаются"
                                    + (acted.Count > 0 ? " (нажимались под: " + string.Join(", ", acted) + ")" : ""));
        });
        Try("энциклопедия на свободной карте", () =>
        {
            var b = Fresh(); MobileParty.MainParty.IsMoving = true; Screen.EncyclopediaScreenManager.IsEncyclopediaOpen = true;
            Enable(b); b.PollState();
            Check(Campaign.Current.TimeControlMode == CampaignTimeControlMode.Stop,
                  "человек открыл энциклопедию — автопилот не снимает паузу под ней");
        });
        Try("обслуживание во время ожидания под окном", () =>
        {
            var b = Fresh(); var w = MakeWorld(prisoners: false); SetLimit("MaxFoodSpendPerPass", 1000);
            Enable(b); b.PollState(); ArriveTown(w.Place); b.PollState();
            int grain = Grain(w);
            CampaignTime.TestHours = 7; Screen.IsMapIncidentActive = true; b.PollState();
            Check(Grain(w) == grain && LogCount("ОБСЛУЖИВАНИЕ") == 1,
                  "через 7 часов ожидания проход не идёт, пока открыто окно (зерна " + grain + " → " + Grain(w) + ")");
        });

        Console.WriteLine($"\nИтог: {passed} ok, {failed} FAIL");
        return failed;
    }
}
