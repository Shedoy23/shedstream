using System.Runtime.CompilerServices;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Net
{
    /// <summary>
    /// 2026-05-29 (BLT-parity RetinueDeathChance) — реестр призванных войск свиты
    /// в текущей Mission: Agent → (owner username, troopId).
    ///
    /// Заполняется в SummonHeroHandler при spawn'е каждого retinue-войска,
    /// читается в KillRewardBehavior.OnAgentRemoved для ролла шанса гибели
    /// (BLTSummonBehavior pattern). ConditionalWeakTable → записи авто-GC'ятся
    /// вместе с Agent'ом, поэтому нет утечки между миссиями и не нужен ручной
    /// clear на конец боя.
    /// </summary>
    public static class RetinueRegistry
    {
        public sealed class Tag
        {
            public string User;
            public string TroopId;
        }

        private static readonly ConditionalWeakTable<Agent, Tag> _map =
            new ConditionalWeakTable<Agent, Tag>();

        public static void Register(Agent agent, string user, string troopId)
        {
            if (agent == null || string.IsNullOrEmpty(user)) return;
            _map.Remove(agent);   // на случай переиспользования индекса
            _map.Add(agent, new Tag { User = user, TroopId = troopId });
        }

        public static Tag Get(Agent agent)
        {
            if (agent == null) return null;
            return _map.TryGetValue(agent, out var tag) ? tag : null;
        }

        public static void Remove(Agent agent)
        {
            if (agent != null) _map.Remove(agent);
        }
    }
}
