using System;
using System.Collections.Generic;
using System.Net;
using System.Text;
using Verse;
using RimLink.Utils;

namespace RimLink.API
{
    /// <summary>
    /// Все HTTP запросы к бэкенду.
    /// Каждый вызов создаёт отдельный WebClient (WebClient не thread-safe).
    /// Все методы безопасны для вызова из фонового потока — они не трогают игровые объекты.
    /// </summary>
    public class RimLinkAPI
    {
        private string _serverUrl;
        private readonly RimLinkMod _mod;
        // 2026-07-19: heartbeat-ошибки логируем на СМЕНЕ состояния (не спамим
        // каждые 30с, но и не молчим как раньше — молчание скрыло мёртвый URL).
        private volatile bool _heartbeatFailing;

        static RimLinkAPI()
        {
            // 2026-07-19: форс TLS 1.2 — бэкенд теперь на https (shedoy23.ru),
            // а Unity/Mono WebClient без этого может резать handshake.
            try
            {
                ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            }
            catch { /* старый рантайм без Tls12 — оставляем как есть */ }
        }

        // WebClient не поддерживает Timeout напрямую — наследуем и переопределяем GetWebRequest
        private class TimedWebClient : WebClient
        {
            private const int TimeoutMs = 8000; // 8 секунд — достаточно для LAN/VPS
            protected override WebRequest GetWebRequest(Uri uri)
            {
                var r = base.GetWebRequest(uri);
                if (r != null) r.Timeout = TimeoutMs;
                if (r is HttpWebRequest http) http.ReadWriteTimeout = TimeoutMs;
                return r;
            }
        }

        public RimLinkAPI(RimLinkMod mod)
        {
            _mod = mod;
            _serverUrl = mod.ServerUrl;
        }

        public void UpdateServerUrl(string url) => _serverUrl = url;

        // ── Helpers ────────────────────────────────────────────────────────────

        private WebClient MakeClient()
        {
            var c = new TimedWebClient { Encoding = Encoding.UTF8 };
            c.Headers[HttpRequestHeader.ContentType] = "application/json";
            c.Headers[HttpRequestHeader.UserAgent] = "RimLink-Mod/1.0";
            // Security 2.1: module-токен, если задан в настройках мода.
            var token = _mod?.ModuleToken;
            if (!string.IsNullOrEmpty(token))
                c.Headers[HttpRequestHeader.Authorization] = "Bearer " + token;
            return c;
        }

        private string Post(string path, string json)
        {
            using (var c = MakeClient())
                return c.UploadString(_serverUrl + path, json);
        }

        private string Get(string path)
        {
            using (var c = MakeClient())
                return c.DownloadString(_serverUrl + path);
        }

        private static bool ResponseIsOk(string raw, out string error)
        {
            error = null;
            if (string.IsNullOrWhiteSpace(raw))
            {
                error = "empty response";
                return false;
            }

            var data = SimpleJson.Deserialize(raw);
            if (data.TryGetValue("status", out var status)
                && string.Equals(status?.ToString(), "ok", StringComparison.OrdinalIgnoreCase))
                return true;
            if (data.TryGetValue("success", out var success) && success is bool b && b)
                return true;

            if (data.TryGetValue("message", out var message) && message != null)
                error = message.ToString();
            else
                error = "server rejected request";
            return false;
        }

        private bool PostAndRequireOk(string path, string json, out string error)
        {
            try
            {
                return ResponseIsOk(Post(path, json), out error);
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        // ── Сессия и статус ────────────────────────────────────────────────────

        /// <summary>Вызывается при старте новой игры — очищает старых пешек на сервере.</summary>
        public bool SessionStart()
        {
            if (PostAndRequireOk("/api/rimworld/session-start", "{}", out string error))
            {
                Log.Message("[RimLink] Session started");
                return true;
            }
            Log.Warning($"[RimLink] SessionStart failed: {error}");
            return false;
        }

        /// <summary>Отправляет heartbeat (пинг) каждые 30 секунд, пока игра запущена.</summary>
        public void Heartbeat()
        {
            try
            {
                Post("/api/rimworld/heartbeat", "{}");
                if (_heartbeatFailing)
                {
                    _heartbeatFailing = false;
                    Log.Message("[RimLink] Heartbeat restored — сервер снова доступен");
                }
                #if DEBUG
                Log.Message("[RimLink] Heartbeat sent");
                #endif
            }
            catch (Exception e)
            {
                // Логируем ПЕРВУЮ ошибку серии (не спамим каждые 30с). Раньше
                // Release молчал совсем — мёртвый URL месяц не было видно в логах.
                if (!_heartbeatFailing)
                {
                    _heartbeatFailing = true;
                    Log.Warning($"[RimLink] Heartbeat failed (дальше молчу до восстановления): {e.Message}");
                }
            }
        }

        /// <summary>Уведомляет сервер о закрытии игры.</summary>
        public void SendOffline()
        {
            try 
            { 
                Post("/api/rimworld/offline", "{}");
                Log.Message("[RimLink] Offline notification sent");
            }
            catch (Exception e) 
            { 
                Log.Warning($"[RimLink] SendOffline failed: {e.Message}"); 
            }
        }

        // ── Команды ────────────────────────────────────────────────────────────

        /// <summary>
        /// Получает очередь команд, ожидающих выполнения в игре.
        /// Возвращает null при сетевой ошибке (сервер недоступен).
        /// Возвращает пустой список если команд нет.
        /// </summary>
        public List<Dictionary<string, object>> GetCommands()
        {
            try
            {
                string raw = Get("/api/rimworld/commands");
                if (string.IsNullOrEmpty(raw) || raw == "[]")
                    return new List<Dictionary<string, object>>();

                var list = SimpleJson.DeserializeList(raw);
                var result = new List<Dictionary<string, object>>();
                foreach (var item in list)
                {
                    if (item is Dictionary<string, object> d)
                        result.Add(d);
                    else if (item is IDictionary<string, object> dict)
                        result.Add(new Dictionary<string, object>(dict));
                }

                return result;
            }
            catch (Exception e)
            {
                Log.Warning($"[RimLink] GetCommands failed: {e.Message}");
                return null; // null = сетевая ошибка, SyncLoop включит backoff
            }
        }

        /// <summary>Подтверждает выполнение команды серверу.</summary>
        public bool AckCommand(string commandId, bool success, string message, out string error)
        {
            var d = new Dictionary<string, object>
            {
                { "command_id", commandId },
                { "success",    success    },
                { "message",    message    }
            };
            bool delivered = PostAndRequireOk(
                "/api/rimworld/ack-command", SimpleJson.Serialize(d), out error);
            if (delivered)
            {
                #if DEBUG
                Log.Message($"[RimLink] Command {commandId} acknowledged (success={success})");
                #endif
                return true;
            }
            return false;
        }

        /// <summary>Уведомляет сервер о завершении обработки пакета команд.</summary>
        public void OnCommandsProcessed(int count)
        {
            try
            {
                var d = new Dictionary<string, object>
                {
                    { "processed", count }
                };
                Post("/api/rimworld/commands-processed", SimpleJson.Serialize(d));
                
                #if DEBUG
                Log.Message($"[RimLink] Commands processed: {count}");
                #endif
            }
            catch (Exception e)
            {
                Log.Warning($"[RimLink] OnCommandsProcessed failed: {e.Message}");
            }
        }

        // ── Пешки ──────────────────────────────────────────────────────────────

        /// <summary>Отправляет полные данные одной пешки.</summary>
        public bool SyncPawn(Dictionary<string, object> pawnData)
        {
            if (PostAndRequireOk("/api/rimworld/sync-pawn",
                SimpleJson.Serialize(pawnData), out string error))
            {
                return true;
            }
            Log.Warning($"[RimLink] SyncPawn failed: {error}");
            return false;
        }

        /// <summary>Отправляет данные нескольких пешек одним запросом.</summary>
        public bool SyncPawnsBulk(List<Dictionary<string, object>> pawns)
        {
            string json = SimpleJson.SerializeList(
                new List<object>(pawns.ConvertAll(p => (object)p)));
            if (PostAndRequireOk("/api/rimworld/sync-pawns", json, out string error))
            {
                return true;
            }
            Log.Warning($"[RimLink] SyncPawnsBulk failed: {error}");
            return false;
        }

        // ── Магазин ────────────────────────────────────────────────────────────

        /// <summary>Отправляет полный каталог предметов (одежда, оружие, импланты, нейротренеры).</summary>
        public bool SyncShopCatalog(List<object> items)
        {
            if (PostAndRequireOk("/api/rimworld/shop-catalog",
                SimpleJson.SerializeList(items), out string error))
            {
                Log.Message($"[RimLink] Shop catalog synced: {items.Count} items");
                return true;
            }
            Log.Warning($"[RimLink] SyncShopCatalog failed: {error}");
            return false;
        }

        // ── Ивенты ────────────────────────────────────────────────────────────

        /// <summary>Отправляет каталог ивентов (IncidentDef + WeatherDef) на сервер.</summary>
        public bool SyncEventCatalog(List<object> events)
        {
            if (PostAndRequireOk("/api/rimworld/event-catalog",
                SimpleJson.SerializeList(events), out string error))
            {
                Log.Message($"[RimLink] Event catalog synced: {events.Count} events");
                return true;
            }
            Log.Warning($"[RimLink] SyncEventCatalog failed: {error}");
            return false;
        }

        // ── Утилиты ────────────────────────────────────────────────────────────

        public bool TestModuleConnection(out string error)
        {
            return PostAndRequireOk("/api/rimworld/heartbeat", "{}", out error);
        }

        /// <summary>Проверяет соединение с сервером (ping).</summary>
        public bool Ping()
        {
            try
            {
                Get("/api/rimworld/status");
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
