using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace BannerlordAutopilot
{
    /// <summary>Свой файл лога.
    ///
    /// Почему не игровой: лог игры перетирается и его глушат другие моды, а
    /// весь смысл прототипа — доказательство. Нужен файл, который можно
    /// прочитать после сеанса и увидеть: какие оценки пришли, что выбрано,
    /// куда партия поехала и когда автопилот выключился.
    ///
    /// Пишем в Documents\Mount and Blade II Bannerlord\Logs — рядом с тем, где
    /// игрок и так ищет свои логи.</summary>
    internal static class AutopilotLog
    {
        private static readonly object Gate = new object();
        private static string _path;

        internal static string Path => _path ?? (_path = BuildPath());

        private static string BuildPath()
        {
            try
            {
                string docs = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                string dir = System.IO.Path.Combine(docs, "Mount and Blade II Bannerlord", "Logs");
                Directory.CreateDirectory(dir);
                return System.IO.Path.Combine(dir,
                    "autopilot_" + DateTime.Now.ToString("yyyyMMdd", CultureInfo.InvariantCulture) + ".txt");
            }
            catch (Exception)
            {
                // Нет доступа к Documents — пишем рядом с модом, лишь бы не молча.
                return System.IO.Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "autopilot.txt");
            }
        }

        internal static void Write(string line)
        {
            string stamped = DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + "  " + line;
            lock (Gate)
            {
                try
                {
                    File.AppendAllText(Path, stamped + Environment.NewLine, Encoding.UTF8);
                }
                catch (Exception)
                {
                    // Лог не должен ронять игру ни при каких обстоятельствах.
                }
            }
        }

        /// <summary>Заголовок сеанса: без него в файле за день невозможно
        /// отличить один запуск игры от другого.</summary>
        internal static void Session(string note)
        {
            Write(new string('=', 72));
            Write("СЕАНС " + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)
                  + " — " + note);
        }
    }
}
