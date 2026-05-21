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
    /// MissionLogic: kill reward + battle participation для adopted heroes
    /// (BLT pattern, BLTAdoptAHeroCommonMissionBehavior.OnAgentRemoved).
    ///
    /// Per-kill reward (OnAgentRemoved):
    ///   • Trooper kill   : +50💰 +25 XP в weapon skill +10 HP
    ///   • Hero kill bonus: +500💰 +200 XP (10× за убийство Hero NPC)
    ///   • Horse/mount kill: × 0.25 multiplier (BLT pattern)
    ///
    /// Battle-end participation bonus (OnEndMission):
    ///   • Каждому участвовавшему alive adopted hero (PlayerVictory):
    ///     +200💰 +100 XP random skill
    ///
    /// Overlay stats push: каждые 1.5с пушим snapshot активных summoned
    /// heroes на backend → overlay.html отображает HP/kills/gold/xp.
    /// </summary>
    public class KillRewardBehavior : MissionLogic
    {
        // Per-kill (trooper)
        private const int   GOLD_PER_KILL = 50;
        private const int   XP_PER_KILL   = 25;
        private const float HEAL_PER_KILL = 10f;
        private const float HORSE_FACTOR  = 0.25f;

        // Per-kill (Hero NPC, e.g. лорд / claimant)
        private const int HERO_KILL_GOLD = 500;
        private const int HERO_KILL_XP   = 200;

        // Retinue kill — half reward owner'у (indirect, не сам убил)
        private const float RETINUE_KILL_FACTOR = 0.5f;

        // Battle-end participation (PlayerVictory)
        private const int VICTORY_GOLD = 200;
        private const int VICTORY_XP   = 100;

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
        private bool _resultsApplied;

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
            if (affectorAgent == null || affectedAgent == null) return;
            if (affectorAgent == affectedAgent) return;

            try
            {
                // Kill reward — два пути:
                //   1. Personal kill: affector сам adopted hero ([BLink] prefix)
                //   2. Retinue kill: affector — troop из свиты (registry lookup)
                //      → credit owner с RETINUE_KILL_FACTOR (0.5×)
                string killerName = GetBLinkUsername(affectorAgent);
                bool isRetinueKill = false;
                Hero killer = null;

                if (killerName != null)
                {
                    // Personal kill — affector сам hero
                    killer = (affectorAgent.Character as CharacterObject)?.HeroObject;
                    if (killer == null || !killer.IsAlive) return;
                }
                else if (_retinueOwners.TryGetValue(affectorAgent, out var ownerUsername))
                {
                    // Retinue kill — credit owner
                    killerName = ownerUsername;
                    isRetinueKill = true;
                    if (_participants.TryGetValue(ownerUsername, out var ownerStats))
                    {
                        killer = ownerStats.Hero;
                    }
                    if (killer == null || !killer.IsAlive) return;
                }
                else
                {
                    return;  // не наш killer
                }

                bool isHumanTarget = affectedAgent.IsHuman;
                bool isHeroTarget = isHumanTarget
                    && (affectedAgent.Character as CharacterObject)?.HeroObject != null;

                int gold;
                int xp;
                float heal;
                string label;

                if (isHeroTarget)
                {
                    gold = HERO_KILL_GOLD;
                    xp = HERO_KILL_XP;
                    heal = HEAL_PER_KILL;
                    label = "HERO";
                }
                else
                {
                    float factor = isHumanTarget ? 1f : HORSE_FACTOR;
                    gold = (int)(GOLD_PER_KILL * factor);
                    xp = (int)(XP_PER_KILL * factor);
                    heal = HEAL_PER_KILL * factor;
                    label = isHumanTarget ? "human" : "mount";
                }

                // Retinue kill — половина reward'а owner'у (indirect, не сам убил).
                // Heal не применяется (retinue далеко от owner'a).
                if (isRetinueKill)
                {
                    gold = (int)(gold * RETINUE_KILL_FACTOR);
                    xp = (int)(xp * RETINUE_KILL_FACTOR);
                    heal = 0f;
                    label += "/retinue";
                }

                if (gold > 0)
                {
                    try { GiveGoldAction.ApplyBetweenCharacters(null, killer, gold, true); }
                    catch (Exception gex)
                    { BannerlordLinkModule.Log($"[KillReward] gold give failed: {gex.Message}"); }
                }

                SkillObject skill = ResolveSkillFromBlow(blow);
                if (skill != null && xp > 0)
                {
                    try { killer.HeroDeveloper.AddSkillXp(skill, xp); }
                    catch (Exception sex)
                    { BannerlordLinkModule.Log($"[KillReward] xp add failed: {sex.Message}"); }
                }

                if (heal > 0f && affectorAgent.IsActive())
                {
                    affectorAgent.Health = Math.Min(
                        affectorAgent.HealthLimit,
                        affectorAgent.Health + heal);
                }

                // Track stats per participant
                if (_participants.TryGetValue(killerName, out var s))
                {
                    if (isRetinueKill) s.RetinueKills++;
                    else s.Kills++;
                    s.GoldEarned += gold;
                    s.XpEarned += xp;
                    if (!isRetinueKill) s.Agent = affectorAgent;
                }

                string victimName = affectedAgent.Name ?? "?";
                BannerlordLinkModule.Log(
                    $"[KillReward] @{killerName} {(isRetinueKill ? "retinue" : "personal")} killed {victimName} " +
                    $"({label}): +{gold}💰 +{xp} XP " +
                    $"({skill?.StringId ?? "—"}) +{heal:F0} HP");

                HeroStateSyncSafe(killer);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] OnAgentRemoved CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
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
            try
            {
                ApplyVictoryRewards();
                PushStatsSnapshot(isFinal: true);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] OnEndMission CRASHED: {ex.Message}");
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

        /// <summary>Mission закончилась — если PlayerVictory, выдать
        /// participation bonus каждому alive adopted hero.</summary>
        private void ApplyVictoryRewards()
        {
            if (_resultsApplied) return;
            _resultsApplied = true;

            bool victory = false;
            try
            {
                var mr = Mission?.MissionResult;
                if (mr != null && mr.PlayerVictory) victory = true;
            }
            catch { /* MissionResult может быть null на abort */ }

            if (!victory)
            {
                BannerlordLinkModule.Log(
                    $"[KillReward] battle ended (no PlayerVictory) — " +
                    $"{_participants.Count} participants, no bonus");
                return;
            }

            int rewarded = 0;
            // Snapshot копия (defensive — engine может вклиниться)
            List<BattleStats> snapshot;
            try { snapshot = _participants.Values.ToList(); }
            catch { return; }

            foreach (var s in snapshot)
            {
                if (s?.Hero == null || !s.Hero.IsAlive) continue;
                try
                {
                    GiveGoldAction.ApplyBetweenCharacters(null, s.Hero, VICTORY_GOLD, true);
                    var skill = PickRandomSkill();
                    if (skill != null)
                        s.Hero.HeroDeveloper.AddSkillXp(skill, VICTORY_XP);

                    s.GoldEarned += VICTORY_GOLD;
                    s.XpEarned += VICTORY_XP;
                    rewarded++;

                    BannerlordLinkModule.Log(
                        $"[KillReward] @{s.Username} VICTORY bonus: " +
                        $"+{VICTORY_GOLD}💰 +{VICTORY_XP}XP ({skill?.StringId ?? "?"})");
                    HeroStateSyncSafe(s.Hero);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KillReward] victory reward @{s.Username} failed: {ex.Message}");
                }
            }
            BannerlordLinkModule.Log(
                $"[KillReward] PlayerVictory — rewarded {rewarded}/{_participants.Count} heroes");
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

        private static SkillObject PickRandomSkill()
        {
            try
            {
                var all = TaleWorlds.ObjectSystem.MBObjectManager.Instance
                    .GetObjectTypeList<SkillObject>();
                if (all == null || all.Count == 0) return null;
                return all[new Random().Next(all.Count)];
            }
            catch { return null; }
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
