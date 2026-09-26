using System;
using System.Collections.Generic;
using System.Linq;

namespace BannerlordLink.Util
{
    /// <summary>Точка на карте без типов движка — чтобы выбор цели проверялся тестом.</summary>
    internal struct SiegePoint
    {
        public float X, Y, Z;
        public SiegePoint(float x, float y, float z) { X = x; Y = y; Z = z; }
        public float Distance(SiegePoint o) => (float)Math.Sqrt((X - o.X) * (X - o.X) + (Y - o.Y) * (Y - o.Y) + (Z - o.Z) * (Z - o.Z));
    }

    /// <summary>Одни ворота глазами приказа: метки внешних/внутренних, открыты ли
    /// (разбиты тоже считаются открытыми — CastleGate.IsGateOpen), середина проёма и
    /// точка, где защитники ждут у ворот (CastleGate.DefenseWaitFrame, со стороны двора).</summary>
    internal sealed class SiegeGate
    {
        public bool Outer, Inner, Open;
        public SiegePoint Middle, Wait;
    }

    internal enum GateGoal { None, Hold, Breach }

    /// <summary>26.09, владелец: «улучшить приказы "к стенам" и "к воротам", чтобы они
    /// логично и верно работали и в защите, и в атаке». До этого «к воротам» вело к
    /// ближайшим воротам любой стороны, а «к стенам» — к ближайшему своему бойцу на
    /// забрале; дойдя, герой отдавался строю и уходил обратно.</summary>
    internal static class SiegeOrderPolicy
    {
        /// <summary>Насколько снаружи проёма встаёт атакующий у закрытых ворот.</summary>
        internal const float OutsideOffset = 4f;

        /// <summary>Защитник держит ворота, которые враг ломает сейчас (первые целые снаружи
        /// внутрь), стоя в их точке ожидания; все разбиты — держит последний рубеж.
        /// Атакующий встаёт снаружи первых целых ворот; все разбиты — проходит внутрь
        /// (Breach) и дальше дерётся как «в атаку».</summary>
        internal static (GateGoal Goal, SiegePoint Point, SiegeGate Gate) PickGate(bool defender, IList<SiegeGate> gates, SiegePoint me)
        {
            var ordered = (gates ?? new List<SiegeGate>()).Where(g => g != null)
                .OrderBy(g => g.Outer && !g.Inner ? 0 : g.Outer ? 1 : g.Inner ? 2 : 1)
                .ThenBy(g => g.Middle.Distance(me)).ToList();
            if (ordered.Count == 0) return (GateGoal.None, default(SiegePoint), null);
            var closed = ordered.FirstOrDefault(g => !g.Open);
            if (defender)
            {
                var hold = closed ?? ordered.Last();
                return (GateGoal.Hold, hold.Wait, hold);
            }
            if (closed != null) return (GateGoal.Hold, Outside(closed), closed);
            var last = ordered.Last();
            return (GateGoal.Breach, last.Wait, last);
        }

        /// <summary>Точка снаружи проёма: от точки защитников через середину ворот дальше наружу.</summary>
        internal static SiegePoint Outside(SiegeGate g)
        {
            float dx = g.Middle.X - g.Wait.X, dy = g.Middle.Y - g.Wait.Y;
            float len = (float)Math.Sqrt(dx * dx + dy * dy);
            if (len < 0.1f) return g.Middle;
            return new SiegePoint(g.Middle.X + dx / len * OutsideOffset, g.Middle.Y + dy / len * OutsideOffset, g.Middle.Z);
        }

        /// <summary>Порядок мест на стене. Защитник — туда, где ближе враг (у лестниц и
        /// башен), с поправкой на путь до места; атакующий — ближайшее к себе.</summary>
        internal static List<int> RankWallSpots(IList<SiegePoint> spots, SiegePoint me, IList<SiegePoint> enemies, bool defender)
        {
            var score = new List<(int I, float S)>();
            for (int i = 0; i < spots.Count; i++)
            {
                float self = spots[i].Distance(me);
                float s = self;
                if (defender && enemies != null && enemies.Count > 0)
                    s = enemies.Min(e => spots[i].Distance(e)) + 0.5f * self;
                score.Add((i, s));
            }
            return score.OrderBy(x => x.S).Select(x => x.I).ToList();
        }
    }
}
