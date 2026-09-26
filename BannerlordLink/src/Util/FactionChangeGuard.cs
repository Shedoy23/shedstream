using System;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.MapEvents;
using TaleWorlds.CampaignSystem.Party;

namespace BannerlordLink.Util
{
    /// <summary>Смена королевства или мир — не во время боя стримера с участием затронутых сторон.
    ///
    /// 26.09.2026 20:58, краш: зритель stepuhatgn нажал «покинуть королевство» (Вландия),
    /// пока вландийцы штурмовали Усанк в бою стримера. Игра сразу закрыла событие боя на
    /// карте («Player MapEvent State: WaitingRemoval»), а сцена боя шла дальше — на
    /// следующем ударе SandBox BattleAgentLogic.CheckUpgrade читает
    /// MapEvent.PlayerMapEvent.TroopUpgradeTracker, PlayerMapEvent уже null → NRE в нативном
    /// тике миссии → вылет (дамп 2026-09-26_15.58.51). Выход из клана такой гейт имел
    /// (LeaveClanHandler, «in_battle»), выход/вступление/создание королевства и мир — нет.
    /// Отказ «in_battle» бэкенд объясняет зрителю («Сейчас идёт бой — действие недоступно»)
    /// и возвращает деньги.</summary>
    internal static class FactionChangeGuard
    {
        /// <summary>Чистое решение: в бою стримера есть отряд, чей клан или королевство среди
        /// затронутых сменой. partySides — для каждого отряда боя его клан и его королевство.</summary>
        internal static bool Blocks(bool playerBattle, IEnumerable<object[]> partySides, IEnumerable<object> affected)
        {
            if (!playerBattle) return false;
            var hit = new HashSet<object>((affected ?? Enumerable.Empty<object>()).Where(a => a != null));
            if (hit.Count == 0) return false;
            return (partySides ?? Enumerable.Empty<object[]>()).Any(sides => sides != null && sides.Any(s => s != null && hit.Contains(s)));
        }

        /// <summary>true — менять сейчас нельзя. При сбое чтения тоже нельзя: отказ с
        /// возвратом денег лучше вылета игры.</summary>
        internal static bool TouchesPlayerBattle(params object[] affected)
        {
            try
            {
                MapEvent battle = MapEvent.PlayerMapEvent;
                if (battle == null) return false;
                var sides = battle.InvolvedParties.Select(p => new object[] {
                    p?.MobileParty?.ActualClan ?? p?.Owner?.Clan, p?.MapFaction }).ToList();
                return Blocks(true, sides, affected);
            }
            catch (Exception)
            {
                return MapEvent.PlayerMapEvent != null;
            }
        }
    }
}
