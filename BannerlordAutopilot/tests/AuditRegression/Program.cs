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
internal static class Program
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
        MobileParty.MainParty = new MobileParty(); Hero.MainHero = new Hero(); Campaign.Current = new Campaign();
        TaleWorlds.Core.Game.Current = new TaleWorlds.Core.Game(); CampaignTime.TestHours = 0; MenuContext.Invoked.Clear();
        PlayerEncounter.Current = null; PlayerEncounter.EncounterSettlement = null;
        PlayerEncounter.EncounteredMobileParty = null; PlayerEncounter.Battle = null;
        PlayerEncounter.LeaveEncounter = false; PlayerEncounter.LeaveSettlementCalls = 0; PlayerEncounter.FinishCalls = 0;
        AutopilotBehavior.AutoLeaveSettlement = true; AutopilotLog.Lines.Clear();
        CampaignEventDispatcher.NextScores.Clear(); TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls = 0;
        CampaignEventDispatcher.Recruited.Clear(); CampaignEventDispatcher.ThinkFood = -1; CampaignEventDispatcher.ThinkMembers = -1;
        TaleWorlds.CampaignSystem.Actions.SellItemsAction.TestBroken = false; TaleWorlds.CampaignSystem.Actions.SellPrisonersAction.TestCalls = 0;
        TaleWorlds.Library.InformationManager.TestInquiryActive = false; Helpers.MobilePartyHelper.TestLockedIds.Clear();
        return new AutopilotBehavior();
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

    /// <summary>Хранилище сейва в памяти: сначала пишем, потом читаем тем же ключом.</summary>
    sealed class MemStore : IDataStore
    {
        public readonly Dictionary<string, bool> Data = new Dictionary<string, bool>();
        public bool Loading;
        public void SyncData(string key, ref bool value)
        {
            if (Loading) value = Data.TryGetValue(key, out var v) && v;
            else Data[key] = value;
        }
    }

    static int Main()
    {
        Console.WriteLine("Регрессия автопилота по независимой проверке 12.09 (заменители движка, не кампания)");
        EngineContract.Verify();

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
            MobileParty.MainParty.MapEvent = new MapEvent(); MobileParty.MainParty.SiegeEvent = new object();
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
            Check(Grain(w) == 4 && Hero.MainHero.Gold == 2020,
                  "на еду ушло только то, что сверх резерва 2000 с запасом на цену: 4 зерна за 80 (зерна " + Grain(w) + ", денег " + Hero.MainHero.Gold + ")");
            Check(CampaignEventDispatcher.Recruited.Count == 0 && AutopilotLog.Lines.Any(l => l.Contains("не по деньгам 3")),
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
            Check(AutopilotLog.Lines.Any(l => l.Contains("нужно было 150, куплено 30")), "частичное выполнение названо в журнале");
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
                  "после загрузки проход идёт заново, но по сохранённому состоянию ничего не дублирует");
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

        Console.WriteLine($"\nИтог: {passed} ok, {failed} FAIL");
        return failed;
    }
}
