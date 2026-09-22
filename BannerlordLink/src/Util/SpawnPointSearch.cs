using System;

namespace BannerlordLink.Util
{
    /// <summary>
    /// 2026-09-22 — выбор точки появления призванного героя. Чистая геометрия,
    /// без движка: сам перебор проверяется гейтом `tests/SpawnPlacementHarness`,
    /// а что считать «можно здесь» решает вызывающий
    /// (`SafeSummonPlacement` спрашивает у сцены навигацию, путь, высоту и
    /// занятость).
    ///
    /// Почему перебор ОГРАНИЧЕН: раньше координата считалась одной формулой
    /// (перпендикуляр к якорю, 2–4 м) и отдавалась движку вслепую — если там
    /// стена, телега или другой боец, герой появлялся внутри модели. Бесконечно
    /// искать тоже нельзя: это главный поток игры на призыве зрителя.
    /// Поэтому ровно 3 кольца × 8 направлений = 24 кандидата, дальше отказ,
    /// а дальше вызывающий честно уходит в зону подкреплений.
    ///
    /// Конный занимает больше места и хуже разворачивается в тесноте, поэтому у
    /// него кольца дальше от якоря.
    /// </summary>
    public static class SpawnPointSearch
    {
        // 8 направлений через 45°, по возрастанию угла.
        private const int Directions = 8;
        private static readonly float[] Cos = new float[Directions];
        private static readonly float[] Sin = new float[Directions];

        private static readonly float[] FootRings    = { 2.0f, 3.0f, 4.5f };
        private static readonly float[] MountedRings = { 4.0f, 5.5f, 7.0f };

        static SpawnPointSearch()
        {
            for (int i = 0; i < Directions; i++)
            {
                double angle = i * (2.0 * Math.PI / Directions);
                Cos[i] = (float)Math.Cos(angle);
                Sin[i] = (float)Math.Sin(angle);
            }
        }

        /// <summary>
        /// Ищет ближайшую подходящую точку вокруг якоря.
        /// <paramref name="isAllowed"/> — «здесь можно появиться»; вызывается
        /// ровно один раз на кандидата.
        /// <paramref name="seed"/> разводит зрителей по разным направлениям;
        /// берётся как есть, включая <c>int.MinValue</c> — знак и переполнение
        /// здесь уже ломали призыв (`Math.Abs(hash)` бросает на MinValue).
        /// </summary>
        public static bool TryFind(
            float anchorX, float anchorY, int seed, bool mounted,
            Func<float, float, bool> isAllowed,
            out float x, out float y)
        {
            x = anchorX;
            y = anchorY;
            if (isAllowed == null) return false;

            // seed & 7 не переполняется ни на одном int, в отличие от Math.Abs.
            int startDir = seed & (Directions - 1);
            var rings = mounted ? MountedRings : FootRings;

            for (int r = 0; r < rings.Length; r++)
            {
                for (int d = 0; d < Directions; d++)
                {
                    int dir = (startDir + d) & (Directions - 1);
                    float cx = anchorX + rings[r] * Cos[dir];
                    float cy = anchorY + rings[r] * Sin[dir];
                    if (!isAllowed(cx, cy)) continue;
                    x = cx;
                    y = cy;
                    return true;
                }
            }
            return false;
        }
    }
}
