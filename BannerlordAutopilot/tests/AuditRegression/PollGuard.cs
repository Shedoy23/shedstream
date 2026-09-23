using System;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem.Party;

internal static partial class Program
{
    // 23.09: опрос раз в 0,5 с шёл без общего перехвата — любое исключение
    // движка внутри него роняло игру вместо «автопилот выключен с причиной».
    static void PollGuardTests()
    {
        Try("исключение внутри опроса выключает автопилот, а не роняет игру", () =>
        {
            var b = Fresh(); Enable(b);
            MobileParty.TestIsActiveThrows = true;
            bool thrown = false;
            try { b.PollState(); } catch (Exception) { thrown = true; }
            MobileParty.TestIsActiveThrows = false;
            Check(!thrown, "исключение не выходит из опроса наружу");
            Check(b.CurrentMode == AutopilotBehavior.Mode.Off, "автопилот выключен: " + b.CurrentMode);
            Check(LogCount("ВЫКЛЮЧЕНИЕ: опрос упал: NullReferenceException") == 1, "причина записана в лог один раз");
            b.PollState();
            Check(LogCount("ВЫКЛЮЧЕНИЕ") == 1, "выключенный автопилот больше не опрашивает");
        });
    }
}
