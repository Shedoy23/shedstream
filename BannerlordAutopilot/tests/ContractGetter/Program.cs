using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;

// Контрпример независимой проверки 13.09
// (dist/audit/autopilot-review-2026-09-13/contract-getter). Stubs.cs — её файл без
// изменений (md5 CD2CBDCEDD5A2DA56BE9259B6CE99260): у Campaign.CurrentMenuContext
// нет публичного чтения. Мод это свойство ЧИТАЕТ, значит в такой сборке он упал
// бы посреди кампании, а прежний контракт сверял только тип свойства.
// Код возврата: 0 — контракт такой API отверг (верно), 1 — принял (дефект).
// У проверяющего смысл был обратным: она доказывала, что дефект есть.
internal static class Program
{
    private static int Main()
    {
        bool noGetter = typeof(Campaign).GetProperty("CurrentMenuContext")?.GetGetMethod() == null;
        bool accepted = EngineContract.Verify();
        Console.WriteLine("у Campaign.CurrentMenuContext нет публичного чтения: " + noGetter);
        Console.WriteLine("контракт: " + (accepted ? "ПРИНЯЛ — дефект" : "отверг — верно") + "; " + EngineContract.Report);
        return noGetter && !accepted ? 0 : 1;
    }
}
