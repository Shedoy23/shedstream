using System;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// MissionLogic: kill reward для adopted heroes (BLT pattern,
    /// BLTAdoptAHeroCommonMissionBehavior.OnAgentRemoved).
    ///
    /// Когда любой agent умирает в Mission:
    ///   • если affector (убийца) — adopted hero → +gold +XP +heal
    ///   • если affected (умерший) — adopted hero → log + push player.died
    ///     (это уже делает MainCampaignBehavior через CampaignEvents)
    ///
    /// Reward values (per kill против человека):
    ///   GOLD_PER_KILL  = 50 динаров
    ///   XP_PER_KILL    = 25 XP в weapon class skill
    ///   HEAL_PER_KILL  = 10 HP
    ///
    /// horseFactor = 0.25 если убил mount (не человек) — BLT pattern.
    ///
    /// XP идёт в skill соответствующий weapon class:
    ///   OneHanded/TwoHanded/Polearm/Bow/Crossbow/Throwing → engine maps.
    ///   Если weapon unknown — Athletics fallback.
    /// </summary>
    public class KillRewardBehavior : MissionLogic
    {
        // Tunable from CommonConfig style; для MVP hardcoded.
        // После live test перенесём в Backend admin panel.
        private const int   GOLD_PER_KILL = 50;
        private const int   XP_PER_KILL   = 25;
        private const float HEAL_PER_KILL = 10f;
        private const float HORSE_FACTOR  = 0.25f;  // multiplier для kill mount

        public override void OnAgentRemoved(Agent affectedAgent, Agent affectorAgent,
            AgentState agentState, KillingBlow blow)
        {
            base.OnAgentRemoved(affectedAgent, affectorAgent, agentState, blow);
            if (affectorAgent == null || affectedAgent == null) return;
            if (affectorAgent == affectedAgent) return;  // self-kill skip

            try
            {
                // Только если убийца — adopted hero
                string killerName = GetAdoptedUsername(affectorAgent);
                if (killerName == null) return;

                Hero killer = (affectorAgent.Character as CharacterObject)?.HeroObject;
                if (killer == null || !killer.IsAlive) return;

                bool isHumanTarget = affectedAgent.IsHuman;
                float factor = isHumanTarget ? 1f : HORSE_FACTOR;

                int gold = (int)(GOLD_PER_KILL * factor);
                int xp = (int)(XP_PER_KILL * factor);
                float heal = HEAL_PER_KILL * factor;

                // Gold deposit (in-game). null giver → "из воздуха" (это reward).
                if (gold > 0)
                {
                    try { GiveGoldAction.ApplyBetweenCharacters(null, killer, gold, true); }
                    catch (Exception gex)
                    { BannerlordLinkModule.Log($"[KillReward] gold give failed: {gex.Message}"); }
                }

                // XP — в weapon class skill (BLT использует blow.WeaponClass).
                // Engine WeaponClass enum: OneHandedSword/TwoHandedAxe/Bow/etc.
                SkillObject skill = ResolveSkillFromBlow(blow);
                if (skill != null && xp > 0)
                {
                    try { killer.HeroDeveloper.AddSkillXp(skill, xp); }
                    catch (Exception sex)
                    { BannerlordLinkModule.Log($"[KillReward] xp add failed: {sex.Message}"); }
                }

                // Heal — live HP regen affector (только если он жив и agent active).
                if (heal > 0f && affectorAgent.IsActive())
                {
                    affectorAgent.Health = Math.Min(
                        affectorAgent.HealthLimit,
                        affectorAgent.Health + heal);
                }

                string victimName = affectedAgent.Name ?? "?";
                BannerlordLinkModule.Log(
                    $"[KillReward] @{killerName} killed {victimName} " +
                    $"({(isHumanTarget ? "human" : "mount")}): +{gold}💰 +{xp} XP " +
                    $"({skill?.StringId ?? "—"}) +{heal:F0} HP");

                // Push state_update — frontend увидит обновлённый gold/level.
                HeroStateSyncSafe(killer);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] OnAgentRemoved CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static string GetAdoptedUsername(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return null;
            var hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero?.Name == null) return null;
            string name = hero.Name.ToString()?.ToLowerInvariant();
            if (string.IsNullOrEmpty(name)) return null;
            // Filter only adopted heroes — у нас в PowerCache._heroClass list
            // viewer'ов с class. Если name есть → adopted.
            return PowerCache.GetHeroClass(name) != null ? name : null;
        }

        // Map blow.WeaponClass → DefaultSkills. Engine WeaponClass enum
        // охватывает OneHandedSword/Axe/Mace, TwoHand*, Polearm, Bow, Crossbow,
        // Javelin/Throwing*. Без match → fallback Athletics (kill вручную).
        private static SkillObject ResolveSkillFromBlow(KillingBlow blow)
        {
            try
            {
                int wcInt = blow.WeaponClass;
                WeaponClass wc = (WeaponClass)wcInt;
                switch (wc)
                {
                    case WeaponClass.OneHandedSword:
                    case WeaponClass.OneHandedAxe:
                    case WeaponClass.Mace:
                    case WeaponClass.Dagger:
                        return DefaultSkills.OneHanded;
                    case WeaponClass.TwoHandedSword:
                    case WeaponClass.TwoHandedAxe:
                    case WeaponClass.TwoHandedMace:
                        return DefaultSkills.TwoHanded;
                    case WeaponClass.OneHandedPolearm:
                    case WeaponClass.TwoHandedPolearm:
                    case WeaponClass.LowGripPolearm:
                        return DefaultSkills.Polearm;
                    case WeaponClass.Bow:
                    case WeaponClass.Arrow:
                        return DefaultSkills.Bow;
                    case WeaponClass.Crossbow:
                    case WeaponClass.Bolt:
                        return DefaultSkills.Crossbow;
                    case WeaponClass.Javelin:
                    case WeaponClass.ThrowingAxe:
                    case WeaponClass.ThrowingKnife:
                    case WeaponClass.Stone:
                        return DefaultSkills.Throwing;
                    default:
                        return DefaultSkills.Athletics;  // melee kick, fall, etc.
                }
            }
            catch
            {
                return DefaultSkills.Athletics;
            }
        }

        private static void HeroStateSyncSafe(Hero hero)
        {
            try { BannerlordLink.Util.HeroStateSync.Push(hero); }
            catch { }
        }
    }
}
