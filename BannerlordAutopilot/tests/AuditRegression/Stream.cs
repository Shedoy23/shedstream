using System.IO;
using BannerlordAutopilot;
using TaleWorlds.CampaignSystem.Party;

internal static partial class Program
{
    // 23.09, владелец: «мысли» автопилота на экран стрима с пометкой «играет ИИ».
    static void StreamStatusTests()
    {
        string file = Path.Combine(Path.GetTempPath(), "autopilot_stream_test.txt");
        Check(StreamStatus.FilePath == file, "тесты не пишут в настоящий файл OBS");
        Try("на экране «играет ИИ» и решение, пока автопилот ведёт", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            HuntTarget("лорд Дерфольд", 100, 10, enemy);
            HourlyTick(b);
            string text = File.ReadAllText(file);
            Check(text.Contains(StreamStatus.Header), "пометка «играет ИИ» на экране");
            Check(text.Contains("Нападаем на «лорд Дерфольд»"), "решение понятной фразой: " + text.Replace("\n", " | "));
        });
        Try("F12 — экран пуст: играет стример", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            HuntTarget("лорд", 100, 10, enemy);
            HourlyTick(b);
            b.Disable("выключено игроком (F12)");
            Check(File.ReadAllText(file).Trim().Length == 0, "после F12 на экране ничего");
        });
        Try("отход виден зрителям", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            Fort("Свой замок", -5, MobileParty.MainParty.MapFaction);
            Chaser(enemy, 500, 8);
            b.PollState();
            Check(File.ReadAllText(file).Contains("Отступаем"), "отход на экране");
        });
    }
}
