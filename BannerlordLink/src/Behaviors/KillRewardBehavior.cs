using System;
using System.Collections.Generic;
using System.Linq;
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
    /// MissionLogic: kill reward + battle participation для adopted heroes.
    /// BLT-aligned (Sprint 5.27g): all constants × 0.5 от BLT defaults.
    ///
    /// Personal kill (OnAgentRemoved, affector == наш hero):
    ///   gold = GOLD_PER_KILL × horseFactor × max(levelBoost, MinGold)
    ///   xp   = XP_PER_KILL   × horseFactor × levelBoost     → AddSkillXp(weaponSkill)
    ///   heal = HEAL_PER_KILL × horseFactor × levelBoost     → affector.Health
    ///
    /// Retinue kill (affector == свита нашего hero):
    ///   gold = RETINUE_GOLD_PER_KILL × horseFactor × max(levelBoost, MinGold)
    ///         → owner.Hero
    ///   heal = RETINUE_HEAL_PER_KILL × horseFactor × levelBoost
    ///         → САМ retinue agent (не owner)
    ///   xp   = 0                                          (BLT: свита XP не даёт)
    ///
    /// Killed (наш hero был убит — consolation):
    ///   xp = XP_PER_KILLED × levelBoost(killerLevel)
    ///
    /// Level scaling (BLT formula):
    ///   factor = (1 - (killedLvl - killerLvl) / 30) ^ (-10 × n)
    ///   gold-only clamp: max(factor, MinGold) для human kills
    ///
    /// Kill streaks: 5/10/15 — extra gold+XP bonus. Reset на смерть.
    ///
    /// Overlay stats push каждые 1.5с (snapshot участников).
    /// </summary>
    public class KillRewardBehavior : MissionLogic
    {
        // ── Sprint 5.27g: BLT defaults × 0.5 ────────────────────────────────

        // Personal kill (trooper)
        private const int   GOLD_PER_KILL = 2500;   // BLT 5000
        private const int   XP_PER_KILL   = 2500;   // BLT 5000
        private const float HEAL_PER_KILL = 10f;    // BLT 20
        private const float HORSE_FACTOR  = 0.25f;  // BLT 0.25 (mount kill multiplier)

        // Killed (consolation XP за смерть нашего hero)
        private const int   XP_PER_KILLED = 1000;   // BLT 2000

        // Retinue kill — gold owner'у, heal retinue agent'у самому.
        private const int   RETINUE_GOLD_PER_KILL = 1250;  // BLT 2500
        private const float RETINUE_HEAL_PER_KILL = 25f;   // BLT 50

        // Relative level scaling (BLT pattern):
        // levelBoost = (1 - (killedLvl - killerLvl) / 30)^(-10 × n).
        // n = 1.0 → full BLT effect; cap = 5 → max ×5 boost.
        // MinGold = 0.5 — gold factor clamp (только для human kills).
        private const int   MAX_LEVEL_IN_PRACTICE = 30;
        private const float REL_LEVEL_SCALING_N   = 1f;
        private const float LEVEL_SCALING_CAP     = 5f;
        private const float MINIMUM_GOLD_PER_KILL = 0.5f;

        // Kill streak milestones (BLT × 0.5): kills → +gold/+xp награда.
        private static readonly (int kills, int gold, int xp)[] KILL_STREAKS =
        {
            ( 5,  2500,  2500),
            (10,  5000,  5000),
            (15, 10000, 10000),
        };

        // Static registry: retinue agent → owner username. Populated
        // SummonHeroHandler'ом при spawn'е retinue. Cleared OnEndMission.
        private static readonly Dictionary<Agent, string> _retinueOwners =
            new Dictionary<Agent, string>();

        /// <summary>Called от SummonHeroHandler после spawn'a retinue agent'a.
        /// Регистрирует attribution: kill этого agent'a кредитится owner'у.</summary>
        public static void RegisterRetinue(Agent agent, string ownerUsername)
        {
            if (agent == null || string.IsNullOrEmpty(ownerUsername)) return;
            _retinueOwners[agent] = ownerUsername.ToLowerInvariant();
        }

        // Sprint 5.7: registry для restore hero обратно в original party
        // после Mission end. BLT pattern (SummonHero.cs onMissionOver).
        private class PartyRestoreEntry
        {
            public Hero Hero;
            public TaleWorlds.CampaignSystem.Party.PartyBase OriginalParty;
            public bool WasLeader;
            public int OldHP;
        }
        private static readonly List<PartyRestoreEntry> _partyRestores =
            new List<PartyRestoreEntry>();

        /// <summary>Called от SummonHeroHandler перед spawn'ом hero.
        /// На OnEndMission hero возвращается в OriginalParty с восстановлением HP.</summary>
        public static void RegisterPartyRestore(
            Hero hero,
            TaleWorlds.CampaignSystem.Party.PartyBase originalParty,
            bool wasLeader,
            int oldHP)
        {
            if (hero == null) return;
            _partyRestores.Add(new PartyRestoreEntry
            {
                Hero          = hero,
                OriginalParty = originalParty,
                WasLeader     = wasLeader,
                OldHP         = oldHP,
            });
        }

        /// <summary>Восстановить hero в его original party. Вызывается из OnEndMission.
        ///
        /// Sprint 5.27e fix: раньше restore требовал OriginalParty != null —
        /// но у адоптированных viewer'ов чаще НЕТ своей party (PartyBelongedTo
        /// == null). SpawnHero всё равно делал AddMember(MainParty), и без
        /// restore эти герои оставались в streamer'овском party навсегда.
        /// Теперь removal делается ВСЕГДА (если current != original),
        /// а add-back в original — только если он был.</summary>
        private static void RestorePartyMembership()
        {
            foreach (var entry in _partyRestores.ToList())
            {
                if (entry?.Hero == null) continue;
                try
                {
                    var currentParty = entry.Hero.PartyBelongedTo?.Party;

                    // Skip если hero уже в нужном месте (либо в original,
                    // либо без party — тогда мы ничего не меняли).
                    if (currentParty == entry.OriginalParty) continue;

                    // 1) Remove from current party (обычно MainParty стримера).
                    //    Делается ВСЕГДА — иначе viewer остаётся в roster'е.
                    if (currentParty != null)
                    {
                        try { currentParty.AddMember(entry.Hero.CharacterObject, -1); }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[PartyRestore] {entry.Hero.Name} remove from " +
                                $"{currentParty.Name} failed: {ex.Message}");
                        }
                    }

                    // 2) Restore HP.
                    try { entry.Hero.HitPoints = entry.OldHP; } catch { }

                    // 3) Re-add в original party ТОЛЬКО если он был и ещё жив.
                    if (entry.OriginalParty != null
                        && entry.OriginalParty.MemberRoster != null
                        && entry.OriginalParty.MemberRoster.TotalHealthyCount > 0)
                    {
                        try
                        {
                            entry.OriginalParty.MemberRoster.AddToCounts(
                                entry.Hero.CharacterObject, 1, insertAtFront: entry.WasLeader);
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[PartyRestore] add to {entry.OriginalParty.Name} failed: {ex.Message}");
                        }
                        if (entry.WasLeader)
                        {
                            try
                            {
                                entry.OriginalParty.MobileParty?.PartyComponent?.ChangePartyLeader(entry.Hero);
                            }
                            catch { }
                        }
                        BannerlordLinkModule.Log(
                            $"[PartyRestore] {entry.Hero.Name} → {entry.OriginalParty.Name} " +
                            $"(was_leader={entry.WasLeader}, hp={entry.OldHP})");
                    }
                    else
                    {
                        // Viewer был "свободным" (no party / clan ledger only) —
                        // после removal он туда же и вернётся (engine оставит
                        // его в clan.Heroes / Settlement.HeroesWithoutParty).
                        BannerlordLinkModule.Log(
                            $"[PartyRestore] {entry.Hero.Name} → detached from " +
                            $"{currentParty?.Name?.ToString() ?? "?"} (no original party)");
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[PartyRestore] entry failed: {ex.Message}");
                }
            }
            _partyRestores.Clear();
        }

        // Overlay state push interval (sec)
        private const float STATS_PUSH_INTERVAL = 1.5f;

        // username → BattleStats (per-Mission tracker)
        private readonly Dictionary<string, BattleStats> _participants =
            new Dictionary<string, BattleStats>();
        private float _nextStatsPushAt = 0f;

        private class BattleStats
        {
            public string Username;
            public Hero Hero;
            public Agent Agent;          // последний known agent (для HP read)
            public bool IsPlayerSide;    // sticky — сохраняется даже после смерти
            public int Kills;
            public int RetinueKills;     // киллы свиты, кредитятся owner'у
            public int GoldEarned;
            public int XpEarned;
            public int KillStreak;       // BLT pattern — reset on death/kill
        }

        /// <summary>BLT formula: (1 − (killedLvl − killerLvl) / 30) ^ (−10×n).
        /// killerLvl > killedLvl → factor &lt; 1 (penalty за слабую цель).
        /// killerLvl &lt; killedLvl → factor &gt; 1 (boost за сильную цель).
        /// Capped к cap (BLT default 5×).</summary>
        private static float RelativeLevelScaling(int killerLevel, int killedLevel,
            float n, float cap)
        {
            try
            {
                int delta = Math.Min(MAX_LEVEL_IN_PRACTICE - 1, killedLevel - killerLevel);
                float baseFactor = 1f - delta / (float)MAX_LEVEL_IN_PRACTICE;
                if (baseFactor <= 0f) return cap;  // killed много выше — max boost
                float exponent = -10f * Math.Max(0f, Math.Min(1f, n));
                float boost = (float)Math.Pow(baseFactor, exponent);
                if (float.IsNaN(boost) || float.IsInfinity(boost)) return cap;
                return Math.Min(boost, cap);
            }
            catch { return 1f; }
        }

        /// <summary>True если agent на team стримера (alliance OK).</summary>
        private static bool ComputeIsPlayerSide(Agent agent)
        {
            try
            {
                if (agent?.Team == null) return false;
                var playerTeam = Mission.Current?.PlayerTeam;
                if (playerTeam == null) return false;
                return agent.Team.Side == playerTeam.Side;
            }
            catch { return false; }
        }

        /// <summary>Возвращает state string для overlay: active/routed/unconscious/killed.</summary>
        private static string ComputeAgentState(Agent agent)
        {
            try
            {
                if (agent == null) return "killed";
                switch (agent.State)
                {
                    case AgentState.Active: return "active";
                    case AgentState.Routed: return "routed";
                    case AgentState.Unconscious: return "unconscious";
                    case AgentState.Killed: return "killed";
                    case AgentState.Deleted: return "killed";
                    default: return "active";
                }
            }
            catch { return "killed"; }
        }

        public override void OnAgentBuild(Agent agent, Banner banner)
        {
            base.OnAgentBuild(agent, banner);
            // Для overlay tracking используем STRICT [BLink] prefix check —
            // НЕ filter'ем по PowerCache (viewer мог адоптнуться, но не
            // выбрать класс — он всё равно должен показаться в overlay).
            string username = GetBLinkUsername(agent);
            if (username == null) return;

            if (!_participants.TryGetValue(username, out var s))
            {
                s = new BattleStats
                {
                    Username = username,
                    Hero     = (agent.Character as CharacterObject)?.HeroObject,
                };
                _participants[username] = s;
            }
            s.Agent = agent;
            // Side detection sticky (определяем при первом OnAgentBuild)
            if (!s.IsPlayerSide)
            {
                s.IsPlayerSide = ComputeIsPlayerSide(agent);
            }
            BannerlordLinkModule.Log(
                $"[KillReward] @{username} entered Mission " +
                $"(side={(s.IsPlayerSide ? "player" : "enemy")}, tracking)");
        }

        /// <summary>STRICT check: agent имеет [BLink] prefix в имени.
        /// Используется для overlay tracking — НЕ требует PowerCache class.</summary>
        private static string GetBLinkUsername(Agent agent)
        {
            if (agent == null || !agent.IsHuman) return null;
            var hero = (agent.Character as CharacterObject)?.HeroObject;
            if (hero?.Name == null) return null;
            string name = hero.Name.ToString();
            if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) return null;
            string username = BannerlordLink.Util.HeroNaming.ExtractUsername(name);
            return string.IsNullOrEmpty(username) ? null : username;
        }

        public override void OnAgentRemoved(Agent affectedAgent, Agent affectorAgent,
            AgentState agentState, KillingBlow blow)
        {
            base.OnAgentRemoved(affectedAgent, affectorAgent, agentState, blow);
            if (affectedAgent == null) return;

            // ── Killed leg: наш hero был убит → consolation XP (BLT XPPerKilled) ─
            try
            {
                HandleAffectedKilled(affectedAgent, affectorAgent, agentState, blow);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] HandleAffectedKilled CRASHED: {ex.GetType().Name}: {ex.Message}");
            }

            // ── Killer leg: наш hero / его retinue убил кого-то → award reward ──
            if (affectorAgent == null || affectorAgent == affectedAgent) return;

            try
            {
                HandleAffectorKill(affectedAgent, affectorAgent, agentState, blow);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] HandleAffectorKill CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        /// <summary>Если affected это наш hero и его прибили — даём consolation XP
        /// (BLT XPPerKilled) с level-scaling. Reset kill streak.</summary>
        private void HandleAffectedKilled(Agent affectedAgent, Agent affectorAgent,
            AgentState state, KillingBlow blow)
        {
            if (affectedAgent == null || !affectedAgent.IsHuman) return;
            if (state != AgentState.Unconscious && state != AgentState.Killed) return;

            string victimUsername = GetBLinkUsername(affectedAgent);
            if (victimUsername == null) return;

            Hero victim = (affectedAgent.Character as CharacterObject)?.HeroObject;
            if (victim == null) return;

            // Reset streak
            if (_participants.TryGetValue(victimUsername, out var vstats))
            {
                vstats.KillStreak = 0;
            }

            // Consolation XP. Level scaling: убит higher-level → больше xp.
            int killerLevel = victim.Level;
            try
            {
                var killerChar = affectorAgent?.Character as CharacterObject;
                if (killerChar != null) killerLevel = killerChar.Level;
            }
            catch { }

            float levelBoost = RelativeLevelScaling(
                victim.Level, killerLevel,
                REL_LEVEL_SCALING_N, LEVEL_SCALING_CAP);
            int xp = (int)(XP_PER_KILLED * levelBoost);
            if (xp <= 0) return;

            SkillObject skill = ResolveSkillFromBlow(blow) ?? DefaultSkills.Athletics;
            try { victim.HeroDeveloper.AddSkillXp(skill, xp); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] @{victimUsername} XPPerKilled failed: {ex.Message}");
                return;
            }

            if (vstats != null) vstats.XpEarned += xp;

            BannerlordLinkModule.Log(
                $"[KillReward] @{victimUsername} killed by {affectorAgent?.Name?.ToString() ?? "?"} → " +
                $"consolation +{xp} XP ({skill.StringId}, levelBoost={levelBoost:F2})");

            HeroStateSyncSafe(victim);
        }

        /// <summary>Affector — наш hero или его retinue → выдать gold/xp/heal.
        /// BLT pattern: личный kill даёт всё, retinue kill даёт gold owner'у +
        /// heal САМОМУ retinue agent'у (не owner'у), XP не даёт.</summary>
        private void HandleAffectorKill(Agent affectedAgent, Agent affectorAgent,
            AgentState state, KillingBlow blow)
        {
            // Identify killer как personal hero / retinue owner.
            string killerName = GetBLinkUsername(affectorAgent);
            bool isRetinueKill = false;
            Hero killer = null;

            if (killerName != null)
            {
                killer = (affectorAgent.Character as CharacterObject)?.HeroObject;
                if (killer == null || !killer.IsAlive) return;
            }
            else if (_retinueOwners.TryGetValue(affectorAgent, out var ownerUsername))
            {
                killerName = ownerUsername;
                isRetinueKill = true;
                if (_participants.TryGetValue(ownerUsername, out var ownerStats))
                    killer = ownerStats.Hero;
                if (killer == null || !killer.IsAlive) return;
            }
            else
            {
                return;  // не наш killer
            }

            bool isHumanTarget = affectedAgent.IsHuman;
            bool isHeroTarget = isHumanTarget
                && (affectedAgent.Character as CharacterObject)?.HeroObject != null;

            // Base reward по типу kill'a
            int baseGold;
            int baseXp;
            float baseHeal;
            if (isRetinueKill)
            {
                baseGold = RETINUE_GOLD_PER_KILL;
                baseXp   = 0;                       // BLT: свита XP не даёт
                baseHeal = RETINUE_HEAL_PER_KILL;   // heal — самому retinue agent'у
            }
            else
            {
                baseGold = GOLD_PER_KILL;
                baseXp   = XP_PER_KILL;
                baseHeal = HEAL_PER_KILL;
            }

            // Horse factor (×0.25 если убил mount)
            float horseFactor = isHumanTarget ? 1f : HORSE_FACTOR;
            baseGold = (int)(baseGold * horseFactor);
            baseXp   = (int)(baseXp   * horseFactor);
            baseHeal = baseHeal * horseFactor;

            // Level scaling (BLT): killer-level vs killed-level
            int killerLevel = killer.Level;
            int killedLevel = killerLevel;
            try
            {
                var killedChar = affectedAgent.Character as CharacterObject;
                if (killedChar != null) killedLevel = killedChar.Level;
            }
            catch { }

            float levelBoost = RelativeLevelScaling(
                killerLevel, killedLevel,
                REL_LEVEL_SCALING_N, LEVEL_SCALING_CAP);

            // Gold factor: max(levelBoost, MinGold) для human, для mount без clamp.
            float goldBoost = isHumanTarget
                ? Math.Max(levelBoost, MINIMUM_GOLD_PER_KILL)
                : levelBoost;

            int gold = (int)(baseGold * goldBoost);
            int xp   = (int)(baseXp   * levelBoost);
            float heal = baseHeal * levelBoost;

            // Apply gold (owner)
            if (gold > 0)
            {
                try { GiveGoldAction.ApplyBetweenCharacters(null, killer, gold, true); }
                catch (Exception ex)
                { BannerlordLinkModule.Log($"[KillReward] gold give failed: {ex.Message}"); }
            }

            // Apply XP (personal only — свита XP не даёт)
            SkillObject skill = ResolveSkillFromBlow(blow) ?? DefaultSkills.Athletics;
            if (xp > 0 && !isRetinueKill)
            {
                try { killer.HeroDeveloper.AddSkillXp(skill, xp); }
                catch (Exception ex)
                { BannerlordLinkModule.Log($"[KillReward] xp add failed: {ex.Message}"); }
            }

            // Apply heal:
            //   personal kill → affector это hero, heal hero agent
            //   retinue kill  → affector это retinue agent, heal САМ retinue
            if (heal > 0f && affectorAgent.IsActive())
            {
                try
                {
                    affectorAgent.Health = Math.Min(
                        affectorAgent.HealthLimit,
                        affectorAgent.Health + heal);
                }
                catch { }
            }

            // Update stats + kill streak (BLT pattern: streak только за personal)
            int streakReward = 0;
            int streakXp = 0;
            int streakLevel = 0;
            if (_participants.TryGetValue(killerName, out var s))
            {
                if (isRetinueKill)
                {
                    s.RetinueKills++;
                }
                else
                {
                    s.Kills++;
                    if (isHumanTarget)  // streak только за людей
                    {
                        s.KillStreak++;
                        foreach (var ks in KILL_STREAKS)
                        {
                            if (s.KillStreak == ks.kills)
                            {
                                streakReward = ks.gold;
                                streakXp     = ks.xp;
                                streakLevel  = ks.kills;
                                break;
                            }
                        }
                    }
                }
                s.GoldEarned += gold;
                s.XpEarned += xp;
                if (!isRetinueKill) s.Agent = affectorAgent;
            }

            // Apply kill-streak bonus (если milestone reached)
            if (streakReward > 0 || streakXp > 0)
            {
                try
                {
                    if (streakReward > 0)
                        GiveGoldAction.ApplyBetweenCharacters(null, killer, streakReward, true);
                    if (streakXp > 0)
                        killer.HeroDeveloper.AddSkillXp(skill, streakXp);
                    if (s != null)
                    {
                        s.GoldEarned += streakReward;
                        s.XpEarned   += streakXp;
                    }
                    BannerlordLinkModule.Log(
                        $"[KillReward] @{killerName} 🔥 STREAK ×{streakLevel}: " +
                        $"+{streakReward}💰 +{streakXp} XP ({skill.StringId})");
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] streak award failed: {ex.Message}");
                }
            }

            string targetLabel = isHeroTarget ? "HERO"
                : (isHumanTarget ? "human" : "mount");
            if (isRetinueKill) targetLabel += "/retinue";

            string victimName = affectedAgent.Name?.ToString() ?? "?";
            BannerlordLinkModule.Log(
                $"[KillReward] @{killerName} {(isRetinueKill ? "retinue" : "personal")} " +
                $"killed {victimName} ({targetLabel}): " +
                $"+{gold}💰 +{xp} XP ({skill.StringId}) +{heal:F0} HP " +
                $"[lvl K{killerLevel}/T{killedLevel} → boost ×{levelBoost:F2}]");

            HeroStateSyncSafe(killer);
        }

        public override void OnMissionTick(float dt)
        {
            base.OnMissionTick(dt);
            try
            {
                if (Mission == null) return;
                float now;
                try { now = Mission.CurrentTime; }
                catch { return; }
                if (now < _nextStatsPushAt) return;
                if (_participants.Count == 0) return;
                _nextStatsPushAt = now + STATS_PUSH_INTERVAL;
                PushStatsSnapshot();
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] OnMissionTick CRASHED: {ex.Message}");
            }
        }

        protected override void OnEndMission()
        {
            base.OnEndMission();
            // Sprint 5.27g: убрали flat VICTORY bonus. BLT-pattern награждает
            // через per-kill + kill streaks, отдельной "победы" нет.
            try { PushStatsSnapshot(isFinal: true); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] PushStatsSnapshot final crashed: {ex.Message}");
            }
            // Clear retinue registry — agent references умирают вместе с Mission
            try { _retinueOwners.Clear(); } catch { }
            // Restore heroes в их original parties (BLT pattern)
            try { RestorePartyMembership(); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] RestorePartyMembership crashed: {ex.Message}");
            }
        }

        /// <summary>Push current participants snapshot для overlay.
        ///
        /// IMPORTANT: snapshot копия dict.Values ДО iteration — защита от
        /// `Collection was modified` (OnAgentBuild может вклиниться mid-frame).
        /// Wrapped в try/catch на каждом уровне чтобы не уронить game.</summary>
        private void PushStatsSnapshot(bool isFinal = false)
        {
            try
            {
                // Snapshot копия — устраняет race с OnAgentBuild.
                List<BattleStats> snapshot;
                try
                {
                    snapshot = _participants.Values.ToList();
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] snapshot copy failed: {ex.Message}");
                    return;
                }

                var items = new List<object>();
                foreach (var s in snapshot)
                {
                    if (s == null || string.IsNullOrEmpty(s.Username)) continue;
                    int hp = 0, hpMax = 100;
                    bool alive = false;
                    string state = "killed";
                    bool isPlayerSide = s.IsPlayerSide;
                    try
                    {
                        if (s.Agent != null)
                        {
                            hp = (int)s.Agent.Health;
                            hpMax = (int)s.Agent.HealthLimit;
                            if (hpMax <= 0) hpMax = 100;
                            alive = s.Agent.IsActive() && hp > 0;
                            state = ComputeAgentState(s.Agent);
                            // Refresh side если не определён (mutating one field
                            // на копии — безопасно)
                            if (!isPlayerSide)
                            {
                                isPlayerSide = ComputeIsPlayerSide(s.Agent);
                                s.IsPlayerSide = isPlayerSide;
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        // Per-participant errors не должны валить весь snapshot
                        BannerlordLinkModule.Log(
                            $"[KillReward] snapshot @{s.Username} read error: {ex.Message}");
                    }
                    items.Add(new
                    {
                        username = s.Username,
                        hp = hp,
                        hp_max = hpMax,
                        alive = alive,
                        state = state,
                        is_player_side = isPlayerSide,
                        kills = s.Kills,
                        retinue_kills = s.RetinueKills,
                        gold_earned = s.GoldEarned,
                        xp_earned = s.XpEarned,
                    });
                }
                if (items.Count == 0 && !isFinal) return;

                string json;
                try
                {
                    json = JsonConvert.SerializeObject(new
                    {
                        final = isFinal,
                        participants = items,
                    });
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] JSON serialize failed: {ex.Message}");
                    return;
                }
                Task.Run(async () =>
                {
                    try
                    {
                        await BannerlordLinkModule.Backend.PostEventAsync(
                            "bannerlord", "battle.stats_snapshot", json);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[KillReward] HTTP push failed: {ex.Message}");
                    }
                });
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] PushStatsSnapshot CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

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
                        return DefaultSkills.Athletics;
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
