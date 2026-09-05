using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace BannerlordLink.Net
{
    /// <summary>
    /// HTTP-клиент для общения с RimLink backend.
    ///
    /// Использование:
    ///   var cfg = BackendConfig.LoadOrCreate(log);
    ///   var client = new BackendClient(cfg, log);
    ///   bool reachable = await client.PingAsync();
    ///   // Sprint 2.3+: PostEventAsync, GetPendingActionsAsync, AckActionAsync
    ///
    /// Дизайн:
    ///   - Singleton HttpClient (НЕ создавать new HttpClient на каждый запрос —
    ///     socket exhaustion на долгом polling)
    ///   - Bearer module_token из config (Sprint 2.3 будет настоящий handshake)
    ///   - Все методы async, ошибки логируются через cb log, return false/null
    ///   - TLS 1.2 явно выставлен (.NET Framework 4.7.2 default не включает)
    /// </summary>
    public class BackendClient : IDisposable
    {
        private readonly BackendConfig _config;
        private readonly Action<string> _log;
        private readonly HttpClient _http;
        private readonly DurableEventOutbox _outbox;

        internal long ChannelId => _config.ChannelId;

        public BackendClient(BackendConfig config, Action<string> log)
        {
            _config = config;
            _log = log;

            // TLS 1.2 enable — .NET 4.7.2 default protocol не включает его
            try
            {
                ServicePointManager.SecurityProtocol |=
                    SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11;
            }
            catch (Exception ex)
            {
                _log($"TLS protocol set warning: {ex.Message}");
            }

            _http = new HttpClient
            {
                BaseAddress = new Uri(_config.BackendUrl),
                // 35s > backend long-poll timeout (25s) на /v1/module/<id>/actions.
                // Без этого client cancellation срабатывал до response →
                // backend marked dispatched но client body не получал.
                Timeout = TimeSpan.FromSeconds(35),
            };
            _http.DefaultRequestHeaders.UserAgent.ParseAdd(
                "BannerlordLink/0.1.0 (+https://shedoy23.ru)");

            if (!string.IsNullOrEmpty(_config.ModuleToken))
            {
                _http.DefaultRequestHeaders.Authorization =
                    new AuthenticationHeaderValue("Bearer", _config.ModuleToken);

                string outboxPath = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                    "Mount and Blade II Bannerlord", "Configs", "ModState",
                    $"bannerlordlink_outbox_{_config.ChannelId}.jsonl");
                _outbox = new DurableEventOutbox(
                    outboxPath, SendDurableItemAsync, _log);
            }
        }

        /// <summary>
        /// Persists a money/state-critical event before any network attempt.
        /// Returns true once the event is safely on disk; delivery continues in
        /// the background with the same envelope id until the backend ACKs it.
        /// </summary>
        public bool EnqueueDurableEvent(
            string moduleId, string eventType, string dataJson = "{}")
        {
            if (_outbox == null)
            {
                _log($"durable event {eventType} rejected — module_token/outbox unavailable");
                return false;
            }
            return _outbox.Enqueue(moduleId, eventType, dataJson);
        }

        private async Task<bool> SendDurableItemAsync(DurableEventOutbox.Item item)
        {
            Newtonsoft.Json.Linq.JToken parsedData;
            try { parsedData = Newtonsoft.Json.Linq.JToken.Parse(item.DataJson ?? "{}"); }
            catch (Exception ex)
            {
                _log($"[outbox] corrupt payload {item.EventType}: {ex.Message}");
                return false;
            }

            string body = Newtonsoft.Json.JsonConvert.SerializeObject(new
            {
                channel_id = _config.ChannelId,
                envelopes = new[]
                {
                    new
                    {
                        id = item.Id,
                        kind = "event",
                        type = item.EventType,
                        ts = item.TimestampMs,
                        data = parsedData,
                    },
                },
            });

            string response = await PostJsonAsync(
                $"/v1/module/{item.ModuleId}/events", body).ConfigureAwait(false);
            if (response == null) return false;
            bool ok = response.Contains("\"status\":\"ok\"")
                || response.Contains("\"status\": \"ok\"");
            if (!ok)
                _log($"[outbox] backend rejected {item.EventType}: {Truncate(response, 200)}");
            return ok;
        }

        /// <summary>Health check — GET /api/bannerlord/ping (public, no auth).
        /// Возвращает true если backend ответил 200 с ok=true.</summary>
        public async Task<bool> PingAsync()
        {
            try
            {
                var response = await _http.GetAsync("/api/bannerlord/ping");
                string body = await response.Content.ReadAsStringAsync();
                if (!response.IsSuccessStatusCode)
                {
                    _log($"ping FAILED: HTTP {(int)response.StatusCode} body={Truncate(body, 200)}");
                    return false;
                }
                if (body.Contains("\"ok\":true") || body.Contains("\"ok\": true"))
                {
                    _log($"ping OK: {Truncate(body, 200)}");
                    return true;
                }
                _log($"ping unexpected body: {Truncate(body, 200)}");
                return false;
            }
            catch (TaskCanceledException)
            {
                _log("ping TIMEOUT (>10s)");
                return false;
            }
            catch (Exception ex)
            {
                _log($"ping ERROR: {ex.GetType().Name}: {ex.Message}");
                return false;
            }
        }

        /// <summary>POST одиночный module envelope на /v1/module/&lt;id&gt;/events.
        ///
        /// Envelope wrapper: {channel_id, envelopes:[{id, kind, type, ts, data}]}
        /// Auth: Bearer module_token (выставлен в ctor если есть в config).
        /// </summary>
        /// <param name="moduleId">id модуля (bannerlord)</param>
        /// <param name="eventType">type из manifest, e.g. module.session_start, player.linked</param>
        /// <param name="data">extra fields в data{} envelope'а</param>
        /// <returns>true если backend ACK'нул success</returns>
        public async Task<bool> PostEventAsync(string moduleId, string eventType, string dataJson = "{}")
        {
            if (string.IsNullOrEmpty(_config.ModuleToken))
            {
                _log($"PostEvent {eventType} skipped — module_token не задан в config");
                return false;
            }

            string envelopeId = Guid.NewGuid().ToString("N");
            long ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            // Sprint 5.31 #45e (audit MED-4) — раньше string.Format'или JSON
            // руками. eventType с " или \ ломал envelope; dataJson мог
            // быть уже-сериализованным (через JsonConvert) или ручным
            // (с разным escaping) → inconsistency. Теперь:
            //   1. eventType serialized через JsonConvert (escape гарантирован)
            //   2. data — pre-serialized raw JSON; чтобы вставить без двойного
            //      escape, парсим в JToken и кладём в anon object'ный wrap.
            Newtonsoft.Json.Linq.JToken parsedData;
            try
            {
                parsedData = Newtonsoft.Json.Linq.JToken.Parse(
                    string.IsNullOrEmpty(dataJson) ? "{}" : dataJson);
            }
            catch (Exception ex)
            {
                _log($"PostEvent {eventType} — bad dataJson, skipping: {ex.Message}");
                return false;
            }
            string body = Newtonsoft.Json.JsonConvert.SerializeObject(new
            {
                channel_id = _config.ChannelId,
                envelopes = new[]
                {
                    new
                    {
                        id = envelopeId,
                        kind = "event",
                        type = eventType,
                        ts = ts,
                        data = parsedData,
                    },
                },
            });

            string response = await PostJsonAsync($"/v1/module/{moduleId}/events", body);
            if (response == null) return false;

            // Простой проверочный check — должен содержать "status":"ok"
            bool ok = response.Contains("\"status\":\"ok\"") || response.Contains("\"status\": \"ok\"");
            _log($"event {eventType} → {(ok ? "ACK" : "REJECTED")}: {Truncate(response, 200)}");
            return ok;
        }

        /// <summary>POST нескольких событий одного типа одним HTTP-запросом.</summary>
        public async Task<bool> PostEventsAsync(
            string moduleId, string eventType, IEnumerable<string> dataJsonItems)
        {
            if (string.IsNullOrEmpty(_config.ModuleToken)) return false;

            var envelopes = new Newtonsoft.Json.Linq.JArray();
            try
            {
                foreach (string dataJson in dataJsonItems ?? new string[0])
                {
                    envelopes.Add(new Newtonsoft.Json.Linq.JObject
                    {
                        ["id"] = Guid.NewGuid().ToString("N"),
                        ["kind"] = "event",
                        ["type"] = eventType,
                        ["ts"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                        ["data"] = Newtonsoft.Json.Linq.JToken.Parse(
                            string.IsNullOrEmpty(dataJson) ? "{}" : dataJson),
                    });
                }
            }
            catch (Exception ex)
            {
                _log($"PostEvents {eventType} — bad dataJson, skipping batch: {ex.Message}");
                return false;
            }
            if (envelopes.Count == 0) return true;

            string body = new Newtonsoft.Json.Linq.JObject
            {
                ["channel_id"] = _config.ChannelId,
                ["envelopes"] = envelopes,
            }.ToString(Newtonsoft.Json.Formatting.None);
            string response = await PostJsonAsync($"/v1/module/{moduleId}/events", body);
            if (response == null) return false;

            try
            {
                var parsed = Newtonsoft.Json.Linq.JObject.Parse(response);
                var acks = parsed["acks"] as Newtonsoft.Json.Linq.JArray;
                bool ok = parsed["status"]?.ToString() == "ok"
                          && acks != null
                          && acks.Count == envelopes.Count;
                if (ok)
                    foreach (var ack in acks)
                        if ((bool?)ack["success"] != true) { ok = false; break; }
                _log($"events {eventType} batch={envelopes.Count} → " +
                     (ok ? "ACK ALL" : "PARTIAL/REJECTED"));
                return ok;
            }
            catch (Exception ex)
            {
                _log($"PostEvents {eventType} — bad ACK: {ex.Message}");
                return false;
            }
        }

        /// <summary>POST произвольного JSON-payload'а. Для будущих event-передач.
        /// Возвращает response body как string, либо null если упало.</summary>
        public async Task<string> PostJsonAsync(string path, string jsonBody)
        {
            try
            {
                var content = new StringContent(jsonBody, Encoding.UTF8, "application/json");
                var response = await _http.PostAsync(path, content);
                string body = await response.Content.ReadAsStringAsync();
                if (!response.IsSuccessStatusCode)
                {
                    _log($"POST {path} FAILED: HTTP {(int)response.StatusCode} body={Truncate(body, 200)}");
                    return null;
                }
                return body;
            }
            catch (Exception ex)
            {
                _log($"POST {path} ERROR: {ex.GetType().Name}: {ex.Message}");
                return null;
            }
        }

        /// <summary>GET arbitrary path. Возвращает body или null.
        /// Cancellation вызывающего кода — штатная остановка, не ERROR.</summary>
        public async Task<string> GetAsync(
            string path,
            CancellationToken cancellationToken = default(CancellationToken))
        {
            try
            {
                var response = await _http.GetAsync(path, cancellationToken);
                string body = await response.Content.ReadAsStringAsync();
                if (!response.IsSuccessStatusCode)
                {
                    _log($"GET {path} FAILED: HTTP {(int)response.StatusCode} body={Truncate(body, 200)}");
                    return null;
                }
                return body;
            }
            catch (OperationCanceledException)
            {
                if (cancellationToken.IsCancellationRequested)
                    return null;

                // HttpClient timeout наследуется от TaskCanceledException.
                // Это транспортный таймаут, а не падение мода; не маркируем
                // как ERROR, чтобы один эпизод не считался дважды вместе с
                // сообщением poller'а о retry.
                _log($"GET {path} TIMEOUT (>{_http.Timeout.TotalSeconds:0}s)");
                return null;
            }
            catch (Exception ex)
            {
                _log($"GET {path} ERROR: {ex.GetType().Name}: {ex.Message}");
                return null;
            }
        }

        public void Dispose()
        {
            try { _outbox?.Dispose(); } catch { }
            _http?.Dispose();
        }

        private static string Truncate(string s, int max)
        {
            if (string.IsNullOrEmpty(s) || s.Length <= max) return s;
            return s.Substring(0, max) + "...";
        }
    }
}
