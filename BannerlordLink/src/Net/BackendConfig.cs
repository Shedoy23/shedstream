using System;
using System.IO;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Конфиг для общения с RimLink backend. Читается из
    /// <game>/Modules/Shedoy23.BannerlordLink/config.json.
    ///
    /// Если файла нет — создаётся template с дефолтами + warning в log.
    /// Streamer руками вставляет свой ModuleToken (Sprint 2.3 handshake)
    /// и сохраняет.
    ///
    /// Формат:
    /// {
    ///     "backend_url": "https://shedoy23.ru",
    ///     "module_token": "PASTE_HERE",
    ///     "channel_id": 98319857,
    ///     "poll_interval_ms": 3000
    /// }
    /// </summary>
    public class BackendConfig
    {
        public string BackendUrl { get; set; } = "https://shedoy23.ru";
        public string ModuleToken { get; set; } = "";
        public long ChannelId { get; set; } = 0;
        public int PollIntervalMs { get; set; } = 3000;

        private const string FILE_NAME = "config.json";

        /// <summary>Путь к config.json в папке мода.</summary>
        public static string ConfigPath
        {
            get
            {
                // Modules/Shedoy23.BannerlordLink/config.json — относительно
                // game install dir. Bannerlord устанавливает CurrentDir в
                // bin/Win64_Shipping_Client/ при запуске, поэтому идём наверх.
                string gameDir = Path.GetFullPath(Path.Combine(
                    AppDomain.CurrentDomain.BaseDirectory, "..", ".."));
                return Path.Combine(gameDir,
                    "Modules", "Shedoy23.BannerlordLink", FILE_NAME);
            }
        }

        /// <summary>Загружает config из файла. Если файла нет — создаёт
        /// template и возвращает дефолты. Если parse failed — log + дефолты.</summary>
        public static BackendConfig LoadOrCreate(Action<string> log)
        {
            string path = ConfigPath;
            try
            {
                if (!File.Exists(path))
                {
                    var template = new BackendConfig();
                    template.Save(path);
                    log($"config.json не найден — создан template {path}");
                    log($"Streamer должен вставить module_token + channel_id и сохранить.");
                    return template;
                }

                string json = File.ReadAllText(path);
                var cfg = ParseJson(json);
                log($"config.json loaded: backend={cfg.BackendUrl}, channel_id={cfg.ChannelId}, " +
                    $"token={(string.IsNullOrEmpty(cfg.ModuleToken) ? "EMPTY" : "set")}");
                return cfg;
            }
            catch (Exception ex)
            {
                log($"config.json read FAILED: {ex.Message} — using defaults");
                return new BackendConfig();
            }
        }

        public void Save(string path)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string json = string.Format(
                "{{\n" +
                "  \"backend_url\":      \"{0}\",\n" +
                "  \"module_token\":     \"{1}\",\n" +
                "  \"channel_id\":       {2},\n" +
                "  \"poll_interval_ms\": {3}\n" +
                "}}\n",
                BackendUrl,
                ModuleToken.Replace("\"", "\\\""),
                ChannelId,
                PollIntervalMs);
            File.WriteAllText(path, json);
        }

        // Минимальный JSON parser — наш формат plain, нет вложенности.
        // Не используем Newtonsoft чтобы не тащить лишнюю DLL зависимость.
        private static BackendConfig ParseJson(string json)
        {
            var cfg = new BackendConfig();
            foreach (var line in json.Split('\n'))
            {
                int colon = line.IndexOf(':');
                if (colon < 0) continue;
                string key = line.Substring(0, colon).Trim().Trim('"', ',', ' ');
                string val = line.Substring(colon + 1).Trim().TrimEnd(',').Trim();

                if (val.StartsWith("\"") && val.EndsWith("\""))
                    val = val.Substring(1, val.Length - 2);

                switch (key)
                {
                    case "backend_url":      cfg.BackendUrl = val; break;
                    case "module_token":     cfg.ModuleToken = val; break;
                    case "channel_id":
                        if (long.TryParse(val, out long cid)) cfg.ChannelId = cid;
                        break;
                    case "poll_interval_ms":
                        if (int.TryParse(val, out int ms)) cfg.PollIntervalMs = ms;
                        break;
                }
            }
            return cfg;
        }
    }
}
