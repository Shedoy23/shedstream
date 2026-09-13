using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;

// Контрпример итоговой независимой проверки 13.09
// (dist/audit/autopilot-review-2026-09-13/contract-scores-getter). Stubs.cs — её файл
// без изменений (md5 F0774EA796C4C76886610C616BCE6B39): у PartyThinkParams.AIBehaviorScores
// нет публичного чтения. Мод это свойство ЧИТАЕТ; общая проверка чтения его не
// покрывала — у AIBehaviorScores своя, отдельная проверка типа.
// Код возврата: 0 — контракт такой API отверг (верно), 1 — принял (дефект).
// У проверяющей смысл был обратным: она доказывала, что дефект есть.
internal static class Program
{
    private static int Main()
    {
        bool noGetter = typeof(PartyThinkParams).GetProperty("AIBehaviorScores")?.GetGetMethod() == null;
        bool accepted = EngineContract.Verify();
        Console.WriteLine("у PartyThinkParams.AIBehaviorScores нет публичного чтения: " + noGetter);
        Console.WriteLine("контракт: " + (accepted ? "ПРИНЯЛ — дефект" : "отверг — верно") + "; " + EngineContract.Report);
        return noGetter && !accepted ? 0 : 1;
    }
}
