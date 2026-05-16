using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Кеш per-class powers + per-viewer class. Заполняется через
    /// GET /api/bannerlord/class-state. Используется MissionLogic'ом
    /// при agent build для apply HP/scale/skill modifiers.
    ///
    /// Refresh: при session_start handshake + при ClassChanged events.
    /// </summary>
    public static class PowerCache
    {
        // username (lowercase) → (class_key, class_level)
        private static Dictionary<string, (string classKey, int level)> _heroClass =
            new Dictionary<string, (string, int)>(StringComparer.OrdinalIgnoreCase);

        // class_key → { power_key → [lvl1, lvl2, lvl3] }
        private static Dictionary<string, Dictionary<string, double[]>> _powers =
            new Dictionary<string, Dictionary<string, double[]>>(StringComparer.OrdinalIgnoreCase);

        private static readonly object _lock = new object();

        /// <summary>Get power value для hero's current class + level.</summary>
        public static double? GetPowerValue(string username, string powerKey)
        {
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(powerKey))
                return null;
            lock (_lock)
            {
                if (!_heroClass.TryGetValue(username, out var hc)) return null;
                if (!_powers.TryGetValue(hc.classKey, out var classPowers)) return null;
                if (!classPowers.TryGetValue(powerKey, out var levels)) return null;
                int idx = Math.Max(0, Math.Min(hc.level - 1, levels.Length - 1));
                return levels[idx];
            }
        }

        /// <summary>Получить class_key и level для viewer'а.</summary>
        public static (string classKey, int level)? GetHeroClass(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            lock (_lock)
            {
                return _heroClass.TryGetValue(username, out var hc) ? hc : ((string, int)?)null;
            }
        }

        /// <summary>Async fetch + populate из backend.</summary>
        public static async Task RefreshAsync(BackendClient backend)
        {
            try
            {
                string body = await backend.GetAsync("/api/bannerlord/class-state");
                if (body == null)
                {
                    BannerlordLinkModule.Log("PowerCache refresh failed: no body");
                    return;
                }
                var parsed = JObject.Parse(body);
                if (parsed["success"]?.ToObject<bool>() != true)
                {
                    BannerlordLinkModule.Log($"PowerCache refresh: success=false: {body}");
                    return;
                }

                var newHeroes = new Dictionary<string, (string, int)>(StringComparer.OrdinalIgnoreCase);
                var newPowers = new Dictionary<string, Dictionary<string, double[]>>(StringComparer.OrdinalIgnoreCase);

                if (parsed["heroes"] is JArray heroesArr)
                {
                    foreach (JObject h in heroesArr)
                    {
                        string u = h["username"]?.ToString()?.ToLowerInvariant() ?? "";
                        string ck = h["class_key"]?.ToString();
                        int lvl = (int?)h["class_level"] ?? 1;
                        if (!string.IsNullOrEmpty(u) && !string.IsNullOrEmpty(ck))
                        {
                            newHeroes[u] = (ck, lvl);
                        }
                    }
                }

                if (parsed["powers"] is JObject powersObj)
                {
                    foreach (var classProp in powersObj.Properties())
                    {
                        var classPowers = new Dictionary<string, double[]>(StringComparer.OrdinalIgnoreCase);
                        if (classProp.Value is JObject pp)
                        {
                            foreach (var powerProp in pp.Properties())
                            {
                                if (powerProp.Value is JArray arr && arr.Count >= 3)
                                {
                                    classPowers[powerProp.Name] = new[]
                                    {
                                        (double)arr[0],
                                        (double)arr[1],
                                        (double)arr[2],
                                    };
                                }
                            }
                        }
                        newPowers[classProp.Name] = classPowers;
                    }
                }

                lock (_lock)
                {
                    _heroClass = newHeroes;
                    _powers = newPowers;
                }
                BannerlordLinkModule.Log(
                    $"PowerCache: refreshed — {newHeroes.Count} heroes, {newPowers.Count} classes");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"PowerCache refresh ERROR: {ex.Message}");
            }
        }

        /// <summary>Synchronously update single viewer (после class change).</summary>
        public static void UpdateHero(string username, string classKey, int level)
        {
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(classKey)) return;
            lock (_lock)
            {
                _heroClass[username.ToLowerInvariant()] = (classKey, level);
            }
        }
    }
}
