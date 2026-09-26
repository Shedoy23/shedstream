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
        Thoughts.Pick = n => 0;
        Try("на экране «играет ИИ» и решение, пока автопилот ведёт", () =>
        {
            var (b, enemy) = HuntWorld(men: 90);
            HuntTarget("лорд Дерфольд", 100, 10, enemy);
            HourlyTick(b);
            string text = File.ReadAllText(file);
            Check(text.Contains(StreamStatus.Header), "пометка «играет ИИ» на экране");
            Check(text.Contains("Вижу «лорд Дерфольд» — их 100, нас 90"), "решение живой фразой с цифрами: " + text.Replace("\n", " | "));
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
        // 26.09, владелец: «больше мыслей, менее официально, более человечно».
        Try("реплики: у каждой фразы корректные подстановки и она влезает в строку", () =>
        {
            var table = (System.Collections.Generic.Dictionary<string, string[]>)typeof(Thoughts)
                .GetField("Table", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic).GetValue(null);
            int bad = 0; string first = null;
            foreach (var kv in table)
                foreach (var v in kv.Value)
                {
                    string line = null;
                    try { line = string.Format(v, "Очень Длинное Название Замка", 1234, 5678); } catch { }
                    if (line == null || line.Length > 90 || kv.Value.Length < 2) { bad++; first ??= kv.Key + ": " + v; }
                }
            Check(bad == 0, "все фразы форматируются, не длиннее 90 знаков, у события от 2 вариантов; первая плохая: " + first);
        });
        Try("реплики: подряд не повторяются, одну цель не твердим", () =>
        {
            var (b, _) = HuntWorld(men: 90);
            var pick = Thoughts.Pick; Thoughts.Pick = n => 0;
            try
            {
                Thoughts.Say("battle_won", "бой 1"); Thoughts.Say("battle_won", "бой 2");
                var lines = File.ReadAllLines(file);
                Check(lines.Length >= 3 && lines[1] != lines[2], "две победы подряд — разные фразы: " + string.Join(" | ", lines));
                int before = File.ReadAllLines(file).Length;
                Thoughts.Say("hunt_lord", "лорд А", "лорд А", 10, 20);
                Thoughts.Say("hunt_lord", "лорд А", "лорд А", 10, 20);
                Check(File.ReadAllLines(file).Length == before + 1, "погоня за тем же лордом — одна строка, а не две");
            }
            finally { Thoughts.Pick = pick; }
        });
    }
}
