using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

internal static partial class Program
{
    static void PostBattleRestTests()
    {
        foreach (bool castle in new[] { false, true }) Try("post battle rest " + castle, () =>
        {
            var b = Surrender(); LootScreen(); b.PollState();
            TaleWorlds.CampaignSystem.Encounters.PlayerEncounter.Finish();
            TaleWorlds.CampaignSystem.Encounters.PlayerEncounter.EncounteredMobileParty = null;
            CampaignTime.TestHours = 40; // Travel must not consume the rest period.
            var town = ArriveTown(new Settlement { Name = "Rest", IsTown = !castle, IsCastle = castle });
            b.PollState(); b.PollState();
            var next = new Settlement { Name = "Next" };
            Scores((AiBehavior.GoToSettlement, next, 10f));
            CampaignTime.TestHours = 51.9; HourlyTick(b); b.PollState();
            Check(Waiting && MobileParty.MainParty.CurrentSettlement == town && TimeRuns,
                "после добычи остаётся внутри 12 игровых часов вопреки новой цели: " + b.CurrentMode + " " + b.LastDisableSummary);
            CampaignTime.TestHours = 52; HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.CurrentSettlement == null && MobileParty.MainParty.TargetSettlement == next,
                "через 12 часов снова выполняет обычную цель");
        });
        Try("no battle no rest", () =>
        {
            var b = Fresh(); Enable(b);
            ArriveTown(new Settlement { Name = "Rest", IsTown = true }); b.PollState();
            var next = new Settlement { Name = "Next" };
            Scores((AiBehavior.GoToSettlement, next, 10f)); HourlyTick(b); b.PollState();
            Check(MobileParty.MainParty.TargetSettlement == next, "без боя обязательного отдыха нет");
        });
    }
}
