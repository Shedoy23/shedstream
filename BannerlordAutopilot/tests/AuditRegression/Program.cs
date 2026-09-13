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
        return new AutopilotBehavior();
    }

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
                        Show(TownMenu(s, canWait));
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

        Console.WriteLine($"\nИтог: {passed} ok, {failed} FAIL");
        return failed;
    }
}
