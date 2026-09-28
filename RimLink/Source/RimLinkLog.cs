using System;
using System.IO;
using Verse;

namespace RimLink
{
    /// <summary>
    /// Свой файл лога мода: ModLogs\rimlink_ГГГГММДД.txt рядом с Player.log.
    ///
    /// ЗАЧЕМ. Движок перестаёт писать Player.log после «Reached max messages
    /// limit. Stopping logging to avoid spam», и замолкает вместе с ним весь
    /// мод. 2026-09-05 лимит выбрал чужой AutoPriorities своими 4144
    /// исключениями: в логе осталось 298 команд из 630, и вторая половина
    /// эфира стала непроверяемой (`docs/POSTSTREAM_TRIAGE_2026-09-05-evening.md`).
    /// Файл пишется напрямую, счётчик движка на него не влияет.
    ///
    /// Порядок внутри важен: сначала строка уходит в файл, только потом в
    /// Verse.Log. Движок вправе отказать — файл к этому моменту уже записан.
    /// </summary>
    public static class RimLinkLog
    {
        private const string SubFolder = "ModLogs";

        private static readonly object Gate = new object();

        /// <summary>Куда писать. Задают только харнесы; в игре null.</summary>
        internal static string DirectoryOverride { get; set; }

        public static void Msg(string message)
        {
            Write("INFO", message);
            Log.Message(message);
        }

        public static void Warn(string message)
        {
            Write("WARN", message);
            Log.Warning(message);
        }

        public static void Err(string message)
        {
            Write("ERR", message);
            Log.Error(message);
        }

        /// <summary>Файл текущего дня — новый файл на каждый календарный день.</summary>
        public static string CurrentPath()
        {
            return Path.Combine(ResolveDirectory(), $"rimlink_{DateTime.Now:yyyyMMdd}.txt");
        }

        private static void Write(string level, string message)
        {
            try
            {
                string path = CurrentPath();
                lock (Gate)
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    File.AppendAllText(
                        path,
                        $"[{DateTime.Now:HH:mm:ss.fff}] [{level}] {message}{Environment.NewLine}");
                }
            }
            catch (Exception)
            {
                // Лог важнее тишины, но не важнее игры: не даём упасть на диске.
            }
        }

        private static string ResolveDirectory()
        {
            if (!string.IsNullOrEmpty(DirectoryOverride)) return DirectoryOverride;

            string saveData = null;
            // ConfigFolderPath уже используется модом (CommandQueue), его родитель —
            // папка сохранений, там же лежит Player.log.
            try { saveData = Path.GetDirectoryName(GenFilePaths.ConfigFolderPath); }
            catch (Exception) { }

            if (string.IsNullOrEmpty(saveData))
            {
                saveData = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                    "AppData", "LocalLow", "Ludeon Studios", "RimWorld by Ludeon Studios");
            }

            return Path.Combine(saveData, SubFolder);
        }
    }
}
