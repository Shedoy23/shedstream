using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
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
                Timeout = TimeSpan.FromSeconds(10),
            };
            _http.DefaultRequestHeaders.UserAgent.ParseAdd(
                "BannerlordLink/0.1.0 (+https://shedoy23.ru)");

            if (!string.IsNullOrEmpty(_config.ModuleToken))
            {
                _http.DefaultRequestHeaders.Authorization =
                    new AuthenticationHeaderValue("Bearer", _config.ModuleToken);
            }
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

        /// <summary>GET arbitrary path. Возвращает body или null.</summary>
        public async Task<string> GetAsync(string path)
        {
            try
            {
                var response = await _http.GetAsync(path);
                string body = await response.Content.ReadAsStringAsync();
                if (!response.IsSuccessStatusCode)
                {
                    _log($"GET {path} FAILED: HTTP {(int)response.StatusCode} body={Truncate(body, 200)}");
                    return null;
                }
                return body;
            }
            catch (Exception ex)
            {
                _log($"GET {path} ERROR: {ex.GetType().Name}: {ex.Message}");
                return null;
            }
        }

        public void Dispose()
        {
            _http?.Dispose();
        }

        private static string Truncate(string s, int max)
        {
            if (string.IsNullOrEmpty(s) || s.Length <= max) return s;
            return s.Substring(0, max) + "...";
        }
    }
}
