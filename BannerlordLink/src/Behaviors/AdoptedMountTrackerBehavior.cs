using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// 2026-05-29 Stage 6 (BLT-RC22 pattern) — отслеживает MountAgent'ов
    /// adopted heroes чтобы их лошадь не убивали в бою (защита через
    /// AdoptedHeroDeathPatch Mission.OnAgentRemoved Prefix → Killed → Unconscious).
    ///
    /// Pattern из BLT BLTAdoptAHeroCommonMissionBehavior.cs:104-107:
    ///   if (agent.MountAgent != null) { adoptedHeroMounts.Add(agent.MountAgent); }
    ///
    /// Why important:
    ///   Без этого: viewer-rider's horse umirayet в бою → теряется saddle +
    ///   horse harness equipment (часто dear, custom). После battle viewer
    ///   appears без лошади → нужен новый mount. Frustration loop.
    ///
    ///   С этим: horse Killed → Unconscious в том же patch который защищает
    ///   самих heroes. Engine treats horse как KO'd → подбирается во время
    ///   post-battle cleanup → equipment preserved.
    ///
    /// Lifecycle:
    ///   - OnAgentBuild: если spawned agent — adopted hero AND имеет MountAgent
    ///     → add MountAgent в _trackedMounts HashSet
    ///   - OnAgentDeleted: cleanup (remove из HashSet даже если не died — agent
    ///     may be deleted в other ways)
    ///   - OnEndMission: clear all
    ///
    /// Thread safety:
    ///   HashSet НЕ thread-safe — но engine OnAgentBuild + OnAgentDeleted всегда
    ///   на main thread. Mission.OnAgentRemoved Prefix также main thread. Safe.
    /// </summary>
    public class AdoptedMountTrackerBehavior : MissionBehavior
    {
        private static AdoptedMountTrackerBehavior _cachedCurrent;

        public static AdoptedMountTrackerBehavior Current
        {
            get
            {
                if (Mission.Current == null) return null;
                if (_cachedCurrent == null || _cachedCurrent.Mission != Mission.Current)
                {
                    _cachedCurrent = Mission.Current.GetMissionBehavior<AdoptedMountTrackerBehavior>();
                }
                return _cachedCurrent;
            }
        }

        public override MissionBehaviorType BehaviorType => MissionBehaviorType.Other;

        private readonly HashSet<Agent> _trackedMounts = new HashSet<Agent>();

        /// <summary>True если agent зарегистрирован как mount adopted hero.
        /// Используется AdoptedHeroDeathPatch.Mission_OnAgentRemoved_Patch
        /// для решения protect Killed → Unconscious convert или нет.</summary>
        public bool IsTracked(Agent agent)
        {
            return agent != null && _trackedMounts.Contains(agent);
        }

        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            try
            {
                if (agent == null) return;
                if (agent.MountAgent == null) return;

                // Только adopted heroes — vanilla mounts vanilla behavior.
                var hero = (agent.Character as CharacterObject)?.HeroObject;
                if (hero == null || !HeroNaming.IsAdopted(hero)) return;

                _trackedMounts.Add(agent.MountAgent);
                BannerlordLinkModule.LogVerbose(() =>
                    $"[MountTracker] Registered mount of @{hero.Name} " +
                    $"(rider idx={agent.Index}, mount idx={agent.MountAgent.Index})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[MountTracker] OnAgentBuild error: {ex.Message}");
            }
        }

        public override void OnAgentDeleted(Agent affectedAgent)
        {
            try
            {
                if (affectedAgent == null) return;
                _trackedMounts.Remove(affectedAgent);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[MountTracker] OnAgentDeleted error: {ex.Message}");
            }
            base.OnAgentDeleted(affectedAgent);
        }

        protected override void OnEndMission()
        {
            try
            {
                _trackedMounts.Clear();
            }
            catch { /* swallow */ }
            finally
            {
                _cachedCurrent = null;
            }
            base.OnEndMission();
        }
    }
}
