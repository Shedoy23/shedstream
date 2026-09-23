using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem.Encounters;

internal static partial class Program
{
    // 23.09, владелец: автопилот должен играть без него. Любое новое, ещё не
    // встречавшееся состояние выключает его — и включить некому. Автовозврат:
    // после самовыключения, когда отряд снова на свободной карте, включиться
    // самому; не больше 3 раз за 30 минут; после F12 — никогда.
    static void ResumeTests()
    {
        var t0 = new DateTime(2026, 9, 23, 12, 0, 0, DateTimeKind.Utc);
        Try("автовозврат после сбоя, когда отряд снова на карте", () =>
        {
            var b = Fresh(); Enable(b); SetClock(t0);
            b.Disable("тест: неизвестное состояние");
            SetClock(t0.AddSeconds(10));
            Check(!b.TryAutoResume() && b.CurrentMode == AutopilotBehavior.Mode.Off, "первые 20 с не включаемся");
            SetClock(t0.AddSeconds(25));
            Check(b.TryAutoResume() && b.CurrentMode == AutopilotBehavior.Mode.Apply, "через 20 с включились сами");
            Check(LogCount("АВТОВОЗВРАТ") >= 1, "возврат записан с причиной");
        });
        Try("после F12 автовозврата нет", () =>
        {
            var b = Fresh(); Enable(b); SetClock(t0);
            b.Disable("выключено игроком (F12)");
            SetClock(t0.AddMinutes(5));
            Check(!b.TryAutoResume() && b.CurrentMode == AutopilotBehavior.Mode.Off, "стример выключил — остаётся выключенным");
        });
        Try("не больше 3 возвратов за 30 минут", () =>
        {
            var b = Fresh(); Enable(b);
            var at = t0;
            for (int i = 0; i < 3; i++)
            {
                SetClock(at); b.Disable("тест: сбой " + i);
                at = at.AddSeconds(30); SetClock(at);
                Check(b.TryAutoResume(), "возврат " + (i + 1));
            }
            SetClock(at); b.Disable("тест: сбой 4");
            at = at.AddSeconds(30); SetClock(at);
            Check(!b.TryAutoResume() && b.CurrentMode == AutopilotBehavior.Mode.Off, "четвёртый за полчаса — остаёмся выключенными");
            Check(LogCount("АВТОВОЗВРАТ: лимит") == 1, "лимит записан");
        });
        Try("во встрече не включаемся, ждём свободной карты", () =>
        {
            var b = Fresh(); Enable(b); SetClock(t0);
            b.Disable("тест: сбой во встрече");
            PlayerEncounter.Current = new PlayerEncounter();
            SetClock(t0.AddSeconds(25));
            Check(!b.TryAutoResume(), "встреча идёт — не включаемся");
            PlayerEncounter.Current = null;
            Check(b.TryAutoResume(), "встреча кончилась — включились");
        });
    }
}
