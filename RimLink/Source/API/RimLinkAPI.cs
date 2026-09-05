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
            // Module API holds an action poll for up to 25 seconds.
            private const int TimeoutMs = 30000;
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
                RimLinkLog.Msg("[RimLink] Session started");
                return true;
            }
            RimLinkLog.Warn($"[RimLink] SessionStart failed: {error}");
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
                    RimLinkLog.Msg("[RimLink] Heartbeat restored — сервер снова доступен");
                }
                #if DEBUG
                RimLinkLog.Msg("[RimLink] Heartbeat sent");
                #endif
            }
            catch (Exception e)
            {
                // Логируем ПЕРВУЮ ошибку серии (не спамим каждые 30с). Раньше
                // Release молчал совсем — мёртвый URL месяц не было видно в логах.
                if (!_heartbeatFailing)
                {
                    _heartbeatFailing = true;
                    RimLinkLog.Warn($"[RimLink] Heartbeat failed (дальше молчу до восстановления): {e.Message}");
                }
            }
        }

        /// <summary>Уведомляет сервер о закрытии игры.</summary>
        public void SendOffline()
        {
            try 
            { 
                Post("/api/rimworld/offline", "{}");
                RimLinkLog.Msg("[RimLink] Offline notification sent");
            }
            catch (Exception e) 
            { 
                RimLinkLog.Warn($"[RimLink] SendOffline failed: {e.Message}"); 
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
            // New Module API is a long-poll: normally the command reaches the
            // game within a fraction of a second.  Keep the legacy fetch as a
            // compatibility drain for commands queued by an older backend.
            if (!string.IsNullOrEmpty(_mod?.ModuleToken))
            {
                try
                {
                    string moduleRaw = Get("/v1/module/rimworld/actions?since=0");
                    var envelope = SimpleJson.Deserialize(moduleRaw);
                    var result = new List<Dictionary<string, object>>();
                    if (envelope.TryGetValue("actions", out var actionsObj)
                        && actionsObj is System.Collections.IEnumerable actions)
                    {
                        foreach (var item in actions)
                        {
                            var action = item as Dictionary<string, object>;
                            if (action == null && item is IDictionary<string, object> dict)
                                action = new Dictionary<string, object>(dict);
                            if (action == null) continue;

                            var command = new Dictionary<string, object>();
                            if (action.TryGetValue("data", out var dataObj)
                                && dataObj is IDictionary<string, object> data)
                                foreach (var pair in data) command[pair.Key] = pair.Value;
                            command["id"] = action.TryGetValue("action_id", out var actionId)
                                ? actionId?.ToString() ?? "" : "";
                            command["type"] = action.TryGetValue("type", out var actionType)
                                ? actionType?.ToString() ?? "" : "";
                            result.Add(command);
                        }
                    }
                    if (result.Count > 0) return result;
                }
                catch (Exception e)
                {
                    RimLinkLog.Warn($"[RimLink] Module API unavailable, using legacy queue: {e.Message}");
                }
            }

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
                RimLinkLog.Warn($"[RimLink] GetCommands failed: {e.Message}");
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
            // A generic ACK for a legacy id returns acked=false, so it is safe
            // to probe the new endpoint first and fall back to the old one.
            if (!string.IsNullOrEmpty(_mod?.ModuleToken))
            {
                try
                {
                    var generic = new Dictionary<string, object>
                    {
                        { "action_id", commandId }, { "success", success },
                        { "error", success ? "" : (message ?? "") }
                    };
                    var raw = Post("/v1/module/rimworld/ack", SimpleJson.Serialize(generic));
                    var response = SimpleJson.Deserialize(raw);
                    if (response.TryGetValue("acked", out var acked) && acked is bool b && b)
                    {
                        error = null;
                        return true;
                    }
                }
                catch (Exception e) { error = e.Message; }
            }

            bool delivered = PostAndRequireOk(
                "/api/rimworld/ack-command", SimpleJson.Serialize(d), out error);
            if (delivered)
            {
                #if DEBUG
                RimLinkLog.Msg($"[RimLink] Command {commandId} acknowledged (success={success})");
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
                RimLinkLog.Msg($"[RimLink] Commands processed: {count}");
                #endif
            }
            catch (Exception e)
            {
                RimLinkLog.Warn($"[RimLink] OnCommandsProcessed failed: {e.Message}");
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
            RimLinkLog.Warn($"[RimLink] SyncPawn failed: {error}");
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
            RimLinkLog.Warn($"[RimLink] SyncPawnsBulk failed: {error}");
            return false;
        }

        // ── Магазин ────────────────────────────────────────────────────────────

        /// <summary>Отправляет полный каталог предметов (одежда, оружие, импланты, нейротренеры).</summary>
        public bool SyncShopCatalog(List<object> items)
        {
            if (PostAndRequireOk("/api/rimworld/shop-catalog",
                SimpleJson.SerializeList(items), out string error))
            {
                RimLinkLog.Msg($"[RimLink] Shop catalog synced: {items.Count} items");
                return true;
            }
            RimLinkLog.Warn($"[RimLink] SyncShopCatalog failed: {error}");
            return false;
        }

        // ── Ивенты ────────────────────────────────────────────────────────────

        /// <summary>Отправляет каталог ивентов (IncidentDef + WeatherDef) на сервер.</summary>
        public bool SyncEventCatalog(List<object> events)
        {
            if (PostAndRequireOk("/api/rimworld/event-catalog",
                SimpleJson.SerializeList(events), out string error))
            {
                RimLinkLog.Msg($"[RimLink] Event catalog synced: {events.Count} events");
                return true;
            }
            RimLinkLog.Warn($"[RimLink] SyncEventCatalog failed: {error}");
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
