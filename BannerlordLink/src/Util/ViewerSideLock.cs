using System;
using System.Collections.Generic;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Одна сторона на весь бой (владелец 25.09: «зритель умер в бою за меня и
    /// следующим призывом заходит против меня — люди меняют стороны»). Первый
    /// удачный призыв в бою запоминает сторону; до конца этого боя призыв за
    /// другую сторону — отказ с возвратом. Бой — событие на карте (MapEvent),
    /// поэтому сцены одной осады считаются одним боем; новый бой всё сбрасывает.
    /// </summary>
    internal static class ViewerSideLock
    {
        private static object _battle;
        private static readonly Dictionary<string, bool> _sides =
            new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);

        internal static bool Allows(object battle, string username, bool playerSide)
        {
            Reset(battle);
            return battle == null || !_sides.TryGetValue(username ?? "", out bool locked) || locked == playerSide;
        }

        internal static void Remember(object battle, string username, bool playerSide)
        {
            Reset(battle);
            if (battle != null && !string.IsNullOrEmpty(username) && !_sides.ContainsKey(username))
                _sides[username] = playerSide;
        }

        private static void Reset(object battle)
        {
            if (ReferenceEquals(battle, _battle)) return;
            _battle = battle;
            _sides.Clear();
        }
    }
}
