using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Sprint 4.5 — runtime state для active powers с длительностью (rage,
    /// retribution_toggle). Singleton, ConcurrentDictionary т.к. читается из
    /// Harmony patch'а во время Mission.RegisterBlow и пишется из main-thread
    /// dispatcher (ActivatePowerHandler).
    ///
    /// Expiry source: Mission.Current.CurrentTime — паузо-чувствительный
    /// (стопится во время Esc-menu), что критично — buff не должен утекать
    /// во время паузы.
    ///
    /// Cleanup: PowersMissionBehavior.OnMissionTick дёргает RemoveExpired()
    /// каждые ~2 сек. Tolerance ±2 сек acceptable для 30-60 сек buff'ов.
    ///
    /// Структура: username (lowercase) → { powerKey → BuffEntry }.
    /// Один зритель может одновременно держать rage + retribution.
    /// </summary>
    public static class ActiveBuffState
    {
        public struct BuffEntry
        {
            public string PowerKey;   // "rage" / "retribution_toggle"
            public float ExpiresAt;   // mission.CurrentTime в момент expiry
            public double Value;      // damage multi (1.5) или reflect % (50)
        }

        // username → powerKey → entry
        private static readonly ConcurrentDictionary<string,
            ConcurrentDictionary<string, BuffEntry>> _buffs =
            new ConcurrentDictionary<string, ConcurrentDictionary<string, BuffEntry>>(
                StringComparer.OrdinalIgnoreCase);

        public static void Activate(string username, string powerKey, float duration, double value)
        {
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(powerKey)) return;
            if (Mission.Current == null) return;

            float now = Mission.Current.CurrentTime;
            var entry = new BuffEntry
            {
                PowerKey = powerKey,
                ExpiresAt = now + duration,
                Value = value,
            };
            var perUser = _buffs.GetOrAdd(username,
                _ => new ConcurrentDictionary<string, BuffEntry>(StringComparer.OrdinalIgnoreCase));
            perUser[powerKey] = entry;

            BannerlordLinkModule.Log(
                $"[BuffState] @{username} {powerKey} activated value={value:F2} duration={duration}s");
        }

        /// <summary>Resolve active buff value, или null если нет / expired.</summary>
        public static double? GetValue(string username, string powerKey)
        {
            if (string.IsNullOrEmpty(username) || Mission.Current == null) return null;
            if (!_buffs.TryGetValue(username, out var perUser)) return null;
            if (!perUser.TryGetValue(powerKey, out var entry)) return null;
            if (Mission.Current.CurrentTime >= entry.ExpiresAt) return null;
            return entry.Value;
        }

        /// <summary>Dropped expired buffs. Called from MissionLogic slow tick.</summary>
        public static int RemoveExpired()
        {
            if (Mission.Current == null) return 0;
            float now = Mission.Current.CurrentTime;
            int removed = 0;

            foreach (var userKvp in _buffs)
            {
                var expired = new List<string>();
                foreach (var bk in userKvp.Value)
                {
                    if (now >= bk.Value.ExpiresAt) expired.Add(bk.Key);
                }
                foreach (var k in expired)
                {
                    if (userKvp.Value.TryRemove(k, out _))
                    {
                        removed++;
                        BannerlordLinkModule.Log(
                            $"[BuffState] @{userKvp.Key} {k} expired");
                    }
                }
            }
            return removed;
        }

        /// <summary>Drop ALL buffs (mission ended).</summary>
        public static void Clear()
        {
            _buffs.Clear();
        }
    }
}
