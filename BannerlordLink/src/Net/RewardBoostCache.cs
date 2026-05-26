using System;
using System.Collections.Concurrent;

namespace BannerlordLink.Net
{
    /// <summary>
    /// Sprint 5.30 #42 — per-user reward boost (gold/XP multiplier).
    ///
    /// Backend пушит reward_boost в data при каждом action (см. bannerlord.py
    /// _user_role + Helix sub detection). Mod кэширует значение per-username
    /// и применяет в кapitalIzationKillRewardBehavior и TournamentMissionBehavior
    /// — для kill gold/XP, tournament win/final reward, и т.д.
    ///
    /// До этого reward_boost применялся ТОЛЬКО в AddSkillXp (одно место).
    /// Sub-tier 1/2/3 платил меньше за купленные powers (price discount), но
    /// per-kill gold/XP не умножался — обещание «sub ×3 rewards» было broken.
    ///
    /// Cache updated:
    ///   - ActionPoller перехватывает data._reward_boost из каждого action'а
    ///     (set'нутый backend'ом)
    ///   - Cache живёт пока mod loaded (никакого save/restore — не нужен)
    ///
    /// Cache read:
    ///   - KillRewardBehavior.HandleAffectorKill — gold/XP применение
    ///   - KillRewardBehavior streak award
    ///   - TournamentMissionBehavior.HandleMatchEnd (round win)
    ///   - TournamentMissionBehavior.OnTournamentEnd (final + bonus)
    ///
    /// Thread-safe через ConcurrentDictionary (Mission engine threads read,
    /// ActionPoller background thread пишет).
    /// </summary>
    public static class RewardBoostCache
    {
        private static readonly ConcurrentDictionary<string, double> _boosts =
            new ConcurrentDictionary<string, double>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Backend пушит каждый action с reward_boost. Mod updates cache.</summary>
        public static void Set(string username, double boost)
        {
            if (string.IsNullOrEmpty(username))
            {
                // Sprint 5.31 #45c — было silent. Теперь логируем чтобы
                // backend bug "забыли target field" был видим в моде.
                BannerlordLinkModule.Log("[reward_boost] Set rejected: empty username");
                return;
            }
            if (boost <= 0 || boost > 10)
            {
                // Out-of-bounds — sanity protection. Логируем чтобы было видно
                // если backend случайно пушит boost=15 или -1.
                BannerlordLinkModule.Log(
                    $"[reward_boost] Set rejected for @{username}: boost={boost} out of (0,10] range");
                return;
            }
            _boosts[username.ToLowerInvariant()] = boost;
        }

        /// <summary>Get current boost, defaults to 1.0 если viewer ещё не дёргал
        /// action (или backend не послал поле).</summary>
        public static double Get(string username)
        {
            if (string.IsNullOrEmpty(username)) return 1.0;
            return _boosts.TryGetValue(username.ToLowerInvariant(), out var b) ? b : 1.0;
        }

        /// <summary>Apply boost к int reward (rounded). Convenience helper.</summary>
        public static int ApplyToInt(string username, int baseValue)
        {
            double boost = Get(username);
            if (Math.Abs(boost - 1.0) < 0.001) return baseValue;
            return (int)Math.Round(baseValue * boost);
        }

        /// <summary>Apply boost к float reward.</summary>
        public static float ApplyToFloat(string username, float baseValue)
        {
            double boost = Get(username);
            if (Math.Abs(boost - 1.0) < 0.001) return baseValue;
            return (float)(baseValue * boost);
        }
    }
}
