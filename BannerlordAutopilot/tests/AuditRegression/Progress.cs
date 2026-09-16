using System;
using System.Linq;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

// Мера прогресса для долгого прогона: без неё «стало лучше» нечем доказать.
internal static partial class Program
{
    static void ProgressTests()
    {
        Console.WriteLine("\n[мера прогресса] недельная сводка");
        Try("сводка прогресса раз в игровую неделю", () =>
        {
            var b = Fresh(); Enable(b);
            var clan = Clan.PlayerClan; clan.MapFaction = new TestFaction();
            clan.Fiefs.Add(new Town { Settlement = new Settlement { Name = "Ревиль", IsTown = true } });
            clan.Fiefs.Add(new Town { Settlement = new Settlement { Name = "Замок Устокол", IsCastle = true } });
            clan.Villages.Add(new Village());
            Helpers.FactionHelper.TestEnemies.Add(new Kingdom { Name = new TaleWorlds.Localization.TextObject("Асераи") });
            MobileParty.MainParty.MemberRoster.AddToCounts(new CharacterObject(), 145, false, 12);
            Hero.MainHero.Gold = 2386303;
            CampaignTime.TestHours = 24 * 7 * 150 + 5; HourlyTick(b);
            Check(AutopilotLog.Lines.Any(l => l.Contains("НЕДЕЛЯ") && l.Contains("феодов 2") && l.Contains("замков 1")
                                              && l.Contains("деревень 1") && l.Contains("бойцов 145") && l.Contains("раненых 12")
                                              && l.Contains("золото 2386303") && l.Contains("Асераи")),
                  "первый час сеанса пишет сводку: феоды, деревни, бойцы, золото, войны");
            CampaignTime.TestHours += 24; HourlyTick(b);
            Check(LogCount("НЕДЕЛЯ") == 1, "внутри той же игровой недели сводка не повторяется");
            CampaignTime.TestHours = 24 * 7 * 151; HourlyTick(b);
            Check(LogCount("НЕДЕЛЯ") == 2, "новая игровая неделя — новая сводка");
        });
    }
}
