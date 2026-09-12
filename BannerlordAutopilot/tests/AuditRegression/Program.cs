using System;
using System.Collections.Generic;
using System.Reflection;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
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
        PlayerEncounter.Current = null; PlayerEncounter.EncounterSettlement = null;
        PlayerEncounter.EncounteredMobileParty = null; PlayerEncounter.Battle = null;
        PlayerEncounter.LeaveEncounter = false; PlayerEncounter.LeaveSettlementCalls = 0; PlayerEncounter.FinishCalls = 0;
        AutopilotBehavior.AutoLeaveSettlement = true; AutopilotLog.Lines.Clear();
        CampaignEventDispatcher.NextScores.Clear(); TaleWorlds.CampaignSystem.Actions.SetPartyAiAction.VisitCalls = 0;
        return new AutopilotBehavior();
    }

    /// <summary>Мирно стоим ВНУТРИ поселения (меню города открыто).</summary>
    static Settlement EnterInside(string name = "Town")
    {
        var s = new Settlement { Name = name };
        PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = s;
        MobileParty.MainParty.CurrentSettlement = s;
        return s;
    }

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
            var b = Fresh(); EnterInside(); Enable(b, AutopilotBehavior.Mode.Observe); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement != null && PlayerEncounter.Current != null
                  && !PlayerEncounter.LeaveEncounter && PlayerEncounter.FinishCalls == 0,
                  "F10 внутри поселения не выводит партию и не заказывает выход");
            b.Disable("test");
            Check(!PlayerEncounter.LeaveEncounter, "после F12 у движка не остаётся заказанного выхода");
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

        Console.WriteLine("\n[находка 1, 5] мирный выход — как у кнопки «Уйти»");
        Try("выход изнутри", () =>
        {
            var b = Fresh(); EnterInside(); Enable(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null && PlayerEncounter.Current == null,
                  "партия действительно вышла: поселение и встреча закрыты");
            Check(Math.Abs(MobileParty.MainParty.Position.X - 42f) < 0.01f, "партия выведена к воротам");
            Check(Field(b, "_settlementExitsThisSession") == 1, "выход засчитан один раз и только после перехода");
            b.PollState();
            Check(Field(b, "_settlementExitsThisSession") == 1, "повторный опрос не засчитывает выход снова");
            Check(Field(b, "_settlementVisitsThisSession") == 0, "старт внутри поселения не считается прибытием");
        });
        Try("выход от ворот замка снаружи", () =>
        {
            var b = Fresh(); Enable(b);
            PlayerEncounter.Current = new PlayerEncounter(); PlayerEncounter.EncounterSettlement = new Settlement { Name = "Замок" };
            b.PollState();
            Check(PlayerEncounter.Current == null && MobileParty.MainParty.HoldCalls >= 1, "мирная встреча у ворот закрыта и движение остановлено");
        });
        Try("прибытие во время сеанса", () =>
        {
            var b = Fresh(); Enable(b); EnterInside(); b.PollState(); b.PollState();
            Check(Field(b, "_settlementVisitsThisSession") == 1, "прибытие во время сеанса — одно посещение");
        });

        Console.WriteLine("\n[находка 4] ожидание выхода не переживает сеанс");
        Try("новый сеанс в другом городе", () =>
        {
            var b = Fresh(); EnterInside(); Enable(b); b.PollState(); b.Disable("test");
            EnterInside("Другой город");
            Enable(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null, "в новом сеансе выход из нового города выполняется");
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
            Enable(b); b.PollState();                                                 // свободная карта
            EnterInside(); b.PollState();                                             // прибыли и вышли; Finish ставит паузу
            Check(PlayerEncounter.FinishCalls == 1, "выход действительно закрыл встречу");
            Check(Campaign.Current.TimeControlMode != CampaignTimeControlMode.Stop, "после выхода время снова идёт");
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
            var reville = EnterInside("Ревиль"); b.PollState();                       // прибыли и вышли
            int exitsAfterFirst = Field(b, "_settlementExitsThisSession");
            EnterInside("Ревиль"); PlayerEncounter.EncounterSettlement = MobileParty.MainParty.CurrentSettlement;
            b.PollState();                                                            // штатный AI снова завёл в Ревиль
            Check(b.CurrentMode == AutopilotBehavior.Mode.Off, "повторный вход в только что покинутое поселение останавливает автопилот");
            Check(Field(b, "_settlementExitsThisSession") == exitsAfterFirst && MobileParty.MainParty.CurrentSettlement != null,
                  "партию не выводят снова — второго круга нет");
        });
        Try("возврат после поездки в другое место", () =>
        {
            var b = Fresh(); Enable(b);
            EnterInside("Ревиль"); b.PollState();                                     // вышли из Ревиля
            var korsia = new Settlement { Name = "Корсия" };
            CampaignEventDispatcher.NextScores.Add((new AIBehaviorData { AiBehavior = AiBehavior.GoToSettlement, Party = korsia }, 2.0f));
            HourlyTick(b);                                                            // уехали в другое место
            EnterInside("Ревиль"); b.PollState();                                     // и вернулись в Ревиль
            Check(b.CurrentMode == AutopilotBehavior.Mode.Apply && MobileParty.MainParty.CurrentSettlement == null,
                  "возврат в город после поездки в другое место — не пинг-понг: автопилот работает и выводит партию");
        });

        Console.WriteLine($"\nИтог: {passed} ok, {failed} FAIL");
        return failed;
    }
}
