using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace BannerlordAutopilot
{
    /// <summary>«Мысли» автопилота для экрана стрима (23.09.2026, решение владельца).
    ///
    /// Файл читает OBS (источник «Текст», галка «Читать из файла») — без сервера и
    /// без ревью Twitch. Пока автопилот ведёт отряд (F11): строка «ИГРАЕТ ИИ» и
    /// последние решения короткими фразами. Выключен — файл пуст, на экране
    /// ничего: когда играет стример, пометки быть не должно.</summary>
    internal static class StreamStatus
    {
        internal const string Header = "ИГРАЕТ ИИ — стример отошёл, отрядом командую я";
        private const int Keep = 5;
        private static readonly object Gate = new object();
        private static readonly LinkedList<string> Lines = new LinkedList<string>();
        private static bool _active;
        internal static string FilePath = BuildPath();

        private static string BuildPath()
        {
            try
            {
                string docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                return Path.Combine(docs, "Mount and Blade II Bannerlord", "Logs", "autopilot_stream.txt");
            }
            catch (Exception) { return Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "autopilot_stream.txt"); }
        }

        internal static void SetActive(bool active)
        {
            lock (Gate) { _active = active; if (!active) Lines.Clear(); Flush(); }
            Thoughts.Reset();
        }

        internal static void Note(string phrase)
        {
            if (string.IsNullOrEmpty(phrase)) return;
            lock (Gate)
            {
                if (Lines.First?.Value == phrase) return;
                Lines.AddFirst(phrase);
                while (Lines.Count > Keep) Lines.RemoveLast();
                Flush();
            }
        }

        private static void Flush()
        {
            try
            {
                var sb = new StringBuilder();
                if (_active)
                {
                    sb.AppendLine(Header);
                    foreach (string line in Lines) sb.AppendLine("• " + line);
                }
                // Через временный файл: OBS не должен прочитать недописанный текст.
                string temp = FilePath + ".tmp";
                Directory.CreateDirectory(Path.GetDirectoryName(FilePath));
                File.WriteAllText(temp, sb.ToString(), new UTF8Encoding(true));
                if (File.Exists(FilePath)) File.Delete(FilePath);
                File.Move(temp, FilePath);
            }
            catch (Exception)
            {
                // Экран стрима не должен ронять игру ни при каких обстоятельствах.
            }
        }
    }
}
