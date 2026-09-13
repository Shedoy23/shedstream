using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;

// Контрпример независимой проверки 13.09
// (dist/audit/autopilot-review-2026-09-13/contract-getter). Stubs.cs — её файл без
// изменений (md5 CD2CBDCEDD5A2DA56BE9259B6CE99260): у Campaign.CurrentMenuContext
// нет публичного чтения. Мод это свойство ЧИТАЕТ, значит в такой сборке он упал
// бы посреди кампании, а прежний контракт сверял только тип свойства.
// Код возврата: 0 — контракт такой API отверг ИМЕННО за это свойство (верно),
// 1 — принял или не назвал его (дефект). Причину надо требовать поимённо: в этих
// заменителях нет типов, добавленных в контракт позже, и отказ по ним скрыл бы
// пропажу проверки чтения. У проверяющей смысл был обратным: она доказывала дефект.
internal static class Program
{
    private const string Expected = "Campaign.CurrentMenuContext : MenuContext";

    private static int Main()
    {
        bool noGetter = typeof(Campaign).GetProperty("CurrentMenuContext")?.GetGetMethod() == null;
        bool accepted = EngineContract.Verify();
        bool named = EngineContract.Report.Contains(Expected);
        Console.WriteLine("у Campaign.CurrentMenuContext нет публичного чтения: " + noGetter);
        Console.WriteLine("контракт: " + (accepted ? "ПРИНЯЛ — дефект" : named ? "отверг и назвал «" + Expected + "» — верно" : "отверг, но это свойство НЕ назвал — дефект")
                          + "; " + EngineContract.Report);
        return noGetter && !accepted && named ? 0 : 1;
    }
}
