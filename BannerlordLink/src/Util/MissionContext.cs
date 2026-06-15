using System;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using SandBox.Tournaments.MissionLogics;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Контекст текущей Mission — арена/турнир. Единый источник правды для гейтов
    /// «честный бой»: модовые баффы/способности/хил не должны ломать турниры.
    /// Раньше детект жил приватно в ActivatePowerHandler; вынесен сюда, чтобы
    /// PowersMissionBehavior (HP-buff на спавне) и HealHeroHandler тоже его звали
    /// без дублирования (bug #12 — пассивный HP×2.5 делал турнирный бой бесконечным).
    /// </summary>
    public static class MissionContext
    {
        /// <summary>Турнир/арена МИССИЯ в любой фазе (спавн/меню/бой). Для
        /// spawn-time гейтов (OnAgentBuild), где Mode ещё может быть StartUp,
        /// а не Battle — потому Mode здесь НЕ проверяется.</summary>
        public static bool IsArenaOrTournamentMission()
        {
            try
            {
                if (Mission.Current?.GetMissionBehavior<TournamentFightMissionController>() != null)
                    return true;
                return CampaignMission.Current?.Location?.StringId == "arena";
            }
            catch { return false; }
        }

        /// <summary>Идёт сам БОЙ арены/турнира (Mode==Battle) — отличает живой бой
        /// от меню/загрузки/зоны посещения. Для гейтов активных действий зрителя
        /// (power.activate / player.heal), которые ломают честный бой.</summary>
        public static bool IsArenaOrTournamentFight()
        {
            try
            {
                return IsArenaOrTournamentMission()
                    && Mission.Current?.Mode == MissionMode.Battle;
            }
            catch { return false; }
        }
    }
}
