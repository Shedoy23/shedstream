using System;
using System.Collections.Generic;

namespace BannerlordLink.Util
{
    // Gold only. XP/healing have their existing independent progression rules.
    internal static class BattlePayoutPolicy
    {
        internal struct Payout
        {
            public int Participation, Personal, Retinue;
            public int Total => Participation + Personal + Retinue;
        }
        internal static double Threat(int level) => Math.Max(0.4, Math.Min(1.5, level / 26.0));
        internal static Payout Calculate(double personal, double retinue, int enemies, bool siege, bool won)
        {
            if (double.IsNaN(personal) || double.IsInfinity(personal)
                || double.IsNaN(retinue) || double.IsInfinity(retinue)) return default;
            personal = Math.Max(0, personal);
            retinue = Math.Max(0, retinue) * 0.5;
            double contribution = personal + retinue;
            if (contribution <= 0) return default;
            double scale = enemies < 50 ? 0.24 : enemies < 200 ? 1.0 : siege ? 1.6 : 1.2;
            double result = scale * (won ? 1.2 : 1.0);
            return new Payout {
                Participation = (int)(50000 * Math.Min(1, contribution / 300) * result),
                Personal = (int)(100000 * personal / (personal + 800) * result),
                Retinue = (int)(58000 * retinue / (retinue + 1000) * result),
            };
        }
    }

    // A target has one health budget per mission, shared by ALL attackers.
    // No reward for healing loops, overkill or repeated death callbacks.
    internal sealed class BattleDamageLedger<T> where T : class
    {
        private readonly Dictionary<T, double> _remaining = new Dictionary<T, double>();
        private readonly Dictionary<T, double> _health = new Dictionary<T, double>();
        private readonly HashSet<T> _finished = new HashSet<T>();
        internal void Track(T target, double health)
        {
            if (target == null || health <= 0 || double.IsNaN(health) || double.IsInfinity(health)
                || _health.ContainsKey(target)) return;
            _health[target] = health;
            _remaining[target] = health;
        }
        internal double Hit(T target, double damage, double healthAfter)
        {
            if (target == null || double.IsNaN(damage) || double.IsInfinity(damage)
                || damage < 0 || double.IsNaN(healthAfter) || double.IsInfinity(healthAfter)
                || _finished.Contains(target) || !_health.TryGetValue(target, out double previous)) return 0;
            healthAfter = Math.Max(0, healthAfter);
            double actual = Math.Min(damage, Math.Max(0, previous - healthAfter));
            _health[target] = healthAfter;
            double useful = Math.Min(_remaining[target], actual);
            _remaining[target] -= useful;
            return useful;
        }
        internal bool Finish(T target) => target != null && _finished.Add(target);
    }
}
