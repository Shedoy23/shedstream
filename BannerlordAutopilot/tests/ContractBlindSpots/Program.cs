using System;
using BannerlordAutopilot;

// Заменители в Stubs.cs несовместимы с настоящим движком нарочно:
//   AIBehaviorScores — строка; AIBehaviorData.Party — int;
//   у Rethink нет записи; метода патруля вокруг точки нет.
// Код возврата: 0 — контракт ОТВЕРГ такой API (правильно), 1 — принял (дефект).
// У проверяющего смысл был обратным: он доказывал, что дефект есть.
internal static class Program
{
    private static int Main()
    {
        bool accepted = EngineContract.Verify();
        Console.WriteLine("несовместимый API: " + (accepted ? "ПРИНЯТ — дефект контракта" : "отвергнут — верно"));
        Console.WriteLine(EngineContract.Report);
        return accepted ? 1 : 0;
    }
}
