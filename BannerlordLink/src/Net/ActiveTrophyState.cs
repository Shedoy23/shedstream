using System;
using System.Collections.Concurrent;
using System.Threading.Tasks;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity ITEM) — runtime registry equipped trophy bonuses
    /// для viewer'ов. EquipTrophyHandler регистрирует rolled stats; DamageHookPatch
    /// читает в Prefix.
    ///
    /// Один active trophy per viewer (newest overrides). Если viewer equip'нет
    /// new trophy — старый bonuses replaced. На death viewer'a — НЕ clear'им
    /// (heir succession в M2.1 will inherit). На mission end — НЕ clear'им
    /// (буфы persistent через battles).
    ///
    /// ConcurrentDictionary because DamageHook Prefix runs hot-path в native
    /// thread, EquipTrophyHandler — main thread. Avoid TryGetValue contention.
    /// </summary>
    public static class ActiveTrophyState
    {
        public struct TrophyStats
        {
            public int DamageBonus;     // weapon +N outgoing damage
            public int ArmorBonus;      // armor +N absorption (incoming reduction)
            public float WeightFactor;  // armor weight multi (visual / future)
            public float SpeedFactor;   // horse speed multi (future apply)
            public string CustomName;   // для logging
            public string BaseType;     // weapon / armor / horse
        }

        // username (lowercased) → most recent TrophyStats.
        private static readonly ConcurrentDictionary<string, TrophyStats> _trophies =
            new ConcurrentDictionary<string, TrophyStats>(StringComparer.OrdinalIgnoreCase);

        public static void Register(string username, TrophyStats stats)
        {
            if (string.IsNullOrEmpty(username)) return;
            _trophies[username] = stats;
            BannerlordLinkModule.Log(
                $"[ActiveTrophy] @{username} active='{stats.CustomName}' " +
                $"({stats.BaseType}: dmg+{stats.DamageBonus} arm+{stats.ArmorBonus} " +
                $"weight×{stats.WeightFactor:F2} speed×{stats.SpeedFactor:F2})");
        }

        /// <summary>Resolve current active trophy для viewer'а. null = none.</summary>
        public static TrophyStats? Get(string username)
        {
            if (string.IsNullOrEmpty(username)) return null;
            if (_trophies.TryGetValue(username, out var s)) return s;
            return null;
        }

        public static void Remove(string username)
        {
            if (string.IsNullOrEmpty(username)) return;
            _trophies.TryRemove(username, out _);
        }

        public static void Clear() => _trophies.Clear();
    }
}
