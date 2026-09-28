// Инвариант: строка мода попадает в СВОЙ файл даже тогда, когда лог движка
// замолчал. Именно это сломалось 05.09 — RimWorld выключил Player.log по
// «Reached max messages limit», и вместе с ним пропало 332 команды из 630.
using RimLink;
using Verse;

string dir = Path.Combine(Path.GetTempPath(), "rimlink-log-harness-" + Guid.NewGuid().ToString("N"));
RimLinkLog.DirectoryOverride = dir;

RimLinkLog.Msg("[RimLink] Выполняем команду: train_skill");

string path = RimLinkLog.CurrentPath();
if (!File.Exists(path)) throw new Exception($"Файл лога не создан: {path}");
if (Path.GetFileName(path) != $"rimlink_{DateTime.Now:yyyyMMdd}.txt")
    throw new Exception($"Имя файла не по дню: {Path.GetFileName(path)}");

// Движок перестал принимать сообщения — ровно случай 05.09.
Log.Silenced = true;

bool engineRefused = false;
try { RimLinkLog.Warn("[RimLink] Команда equip_item без эффекта — шлём success=false (рефанд)"); }
catch (Exception) { engineRefused = true; }
try { RimLinkLog.Err("[RimLink] EquipItem: Object reference not set to an instance of an object"); }
catch (Exception) { engineRefused = true; }

if (!engineRefused) throw new Exception("Харнес не проверил отказ движка — стаб не сработал");

string[] lines = File.ReadAllLines(path);
if (lines.Length != 3) throw new Exception($"В файле {lines.Length} строк вместо 3: {string.Join(" | ", lines)}");
if (!lines[0].Contains("[INFO]") || !lines[0].Contains("train_skill"))
    throw new Exception($"Первая строка не та: {lines[0]}");
if (!lines[1].Contains("[WARN]") || !lines[1].Contains("рефанд"))
    throw new Exception($"Отказ не записан после того, как движок замолчал: {lines[1]}");
if (!lines[2].Contains("[ERR]") || !lines[2].Contains("EquipItem"))
    throw new Exception($"Ошибка не записана после того, как движок замолчал: {lines[2]}");

Directory.Delete(dir, true);
Console.WriteLine("PASS: свой файл лога пишется, и пишется даже когда лог движка замолчал");

namespace Verse
{
    /// <summary>Стаб движка: Silenced=true повторяет «Reached max messages limit».</summary>
    public static class Log
    {
        public static bool Silenced;
        public static void Message(string s) { Refuse(); }
        public static void Warning(string s) { Refuse(); }
        public static void Error(string s) { Refuse(); }
        private static void Refuse() { if (Silenced) throw new Exception("engine log is off"); }
    }

    public static class GenFilePaths { public static string ConfigFolderPath => Path.GetTempPath(); }
}
