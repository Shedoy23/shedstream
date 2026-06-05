using System;
using System.Collections.Generic;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// 2026-06-05 (BLT-parity) — свита зрителя спавнится в бою ТОЛЬКО ОДИН РАЗ.
    /// Первый summon в этом бою → герой + свита; повторные вызовы того же
    /// зрителя в ТОМ ЖЕ бою → только герой (без повторного спавна свиты).
    ///
    /// Раньше свита спавнилась на КАЖДЫЙ summon → дублирование при ре-вызове в
    /// одном бою. BLT (BLTSummonBehavior: TimesSummoned==0 gate) спавнит свиту
    /// один раз; нам не нужна вся машина HeroSummonState — достаточно HashSet
    /// username'ов, получивших свиту в этом бою.
    ///
    /// Per-mission: HashSet живёт ровно столько, сколько Mission.Current. Instance
    /// резолвится из текущей миссии (авторитетно), static — fallback (паттерн
    /// HeroDetachmentBehavior: overlapping миссия не затирает живой Instance).
    /// </summary>
    public class RetinueSpawnTracker : MissionBehavior
    {
        public override MissionBehaviorType BehaviorType => MissionBehaviorType.Other;

        private static RetinueSpawnTracker _instance;
        public static RetinueSpawnTracker Instance
        {
            get
            {
                try
                {
                    var b = Mission.Current?.GetMissionBehavior<RetinueSpawnTracker>();
                    if (b != null) return b;
                }
                catch { }
                return _instance;
            }
            private set { _instance = value; }
        }

        private readonly HashSet<string> _usersWithRetinue =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Уже спавнили свиту этому зрителю в текущем бою?</summary>
        public bool AlreadySpawned(string username)
            => !string.IsNullOrEmpty(username) && _usersWithRetinue.Contains(username);

        /// <summary>Отметить, что свита зрителя заспавнена в этом бою.</summary>
        public void MarkSpawned(string username)
        {
            if (!string.IsNullOrEmpty(username)) _usersWithRetinue.Add(username);
        }

        public override void OnBehaviorInitialize()
        {
            base.OnBehaviorInitialize();
            Instance = this;
        }

        protected override void OnEndMission()
        {
            base.OnEndMission();
            _usersWithRetinue.Clear();
            // обнуляем static ТОЛЬКО если это мы — overlapping миссия (hideout)
            // не должна затирать Instance живого behavior'а.
            if (ReferenceEquals(_instance, this)) _instance = null;
        }
    }
}
