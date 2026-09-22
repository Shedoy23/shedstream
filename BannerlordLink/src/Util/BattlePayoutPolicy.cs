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
        // 21.09.2026, решение владельца: заработок за бой ×2 при тех же показателях.
        // Возражение зафиксировано в DEFERRED.md: динары уже печатаются быстрее,
        // чем тратятся. Всё остальное — очки, масштаб боя, множитель победы,
        // RewardBoostCache — не менялось.
        internal const int Multiplier = 2;

        /// <summary>С какого личного вклада начинается «сверхусилие».
        /// 6724.8 очка — максимум, наблюдённый 21.09 (59 убийств человека).</summary>
        internal const double OverExertionFrom = 6700;
        /// <summary>Потолок надбавки за сверхусилие (до множителя и масштаба боя).</summary>
        internal const double OverExertionCeiling = 386000;
        /// <summary>На сколько очков СВЕРХ порога набирается половина надбавки.</summary>
        internal const double OverExertionHalf = 4000;

        /// <summary>До какого вклада растёт участие. Раньше упиралось в 8000.</summary>
        internal const double ParticipationFullAt = 20000;
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
                // Scores are useful damage, not kill counts. Preserve original ceilings;
                // Calibrated to observed 28-65 human-kill efforts: ~2750-6725 personal points.
                // Multiplier is applied AFTER rounding, so every part and the total are
                // exactly Multiplier times the previous payout for the same inputs.
                // 22.09, решение владельца: поднять потолок участия. Наклон и
                // всё до 8000 очков вклада НЕ меняются — там выплата ровно та
                // же, что вчера. Просто кривая больше не упирается в потолок на
                // 8000, а продолжается тем же темпом до 20000: в осадах все
                // были за старым порогом, и участие переставало различать вклад.
                Participation = Multiplier * (int)(50000
                    * Math.Min(ParticipationFullAt, contribution) / 8000 * result),
                // 22.09, решение владельца: «такие вклады оцениваются не меньше
                // миллиона», но «такие осады не часто и надо попотеть». Поэтому
                // прежняя кривая НЕ тронута — до 6700 очков платится ровно
                // столько же, сколько вчера. Выше порога включается вторая,
                // отдельная кривая «сверхусилие»: она и даёт верх.
                // Порог 6700 — потолок наблюдённых усилий 21.09 (59 убийств
                // человека = 6724.8 очка), то есть надбавку получает только тот,
                // кто вышел за прежний максимум.
                Personal = Multiplier * (int)((100000 * personal / (personal + 4000)
                          + OverExertionCeiling * Math.Max(0, personal - OverExertionFrom)
                            / (Math.Max(0, personal - OverExertionFrom) + OverExertionHalf)) * result),
                Retinue = Multiplier * (int)(58000 * retinue / (retinue + 2000) * result),
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
