using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.AgentOrigins;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.0 — `player.spawn` (summon hero в текущую Mission).
    ///
    /// MVP scope:
    ///   • Только Mission.Mode == Battle (skip Tournament / Siege deployment
    ///     — там своя логика, BLT обрабатывает отдельно).
    ///   • isPlayerSide = true (всегда allies стримера).
    ///   • party = MobileParty.MainParty.Party (player party).
    ///   • spawnWithHorse = по class_key (cavalry/horse_archer/etc.).
    ///   • Equipment — то что у hero уже set'нуто SetClassHandler'ом.
    ///   • No-spawn checks: Mission alive + Continuing + hero не уже в Mission.
    ///
    /// Out of scope (Sprint 5.1+):
    ///   • Tournament / Siege spawn logic.
    ///   • Custom position / direction (BLT поддерживает spawn near attacker).
    ///   • Reinforcement waves (BLT IsSideDepleted Harmony patch).
    ///   • Formation join / leader follow.
    ///
    /// Heroes которые умирают в Mission triggrят HeroKilledEvent →
    /// MainCampaignBehavior пушит player.died на backend (existing flow).
    /// </summary>
    public class SummonHeroHandler : IActionHandler
    {
        public string ActionType => "player.spawn";

        // Class keys которые spawn'ятся с лошадью (соответствует M15 bannerlord_classes).
        // Если PowerCache знает class viewer'а — используем; иначе fallback на dismounted.
        private static readonly System.Collections.Generic.HashSet<string> MountedClasses =
            new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "cavalry", "camel_cavalry", "horse_archer", "camel_archer", "knight",
            };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            string side = (data["side"]?.ToString() ?? "").Trim().ToLowerInvariant();
            bool isPlayerSide = side != "enemy";

            // Backend пердаёт retinue snapshot — список troop_ids для spawn'a.
            var retinueIds = new System.Collections.Generic.List<string>();
            if (data["retinue"] is JArray arr)
            {
                foreach (var item in arr)
                {
                    var id = item["troop_id"]?.ToString();
                    if (!string.IsNullOrEmpty(id)) retinueIds.Add(id);
                }
            }

            MainThreadDispatcher.Enqueue(() => Summon(username, isPlayerSide, retinueIds));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Summon(string username, bool isPlayerSide,
            System.Collections.Generic.List<string> retinueIds)
        {
            string sideLabel = isPlayerSide ? "ally" : "enemy";
            try
            {
                if (!IsMissionReadyForSummon(out string reason))
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] @{username}: skip — {reason}");
                    return;
                }

                Hero hero = HeroLookup.FindByUsername(username);
                if (hero == null)
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] @{username}: hero not found in AliveHeroes");
                    return;
                }

                if (IsAlreadySpawned(hero))
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] @{username}: уже spawned в Mission");
                    return;
                }

                // Resolve party origin for spawn:
                //   ally  → MobileParty.MainParty.Party (player party)
                //   enemy → first enemy team's party (iter agents, найти origin
                //           агента противника). Если не нашли — fallback MainParty
                //           но с log warning.
                // engine ставит side по origin.party.MapFaction.IsAtWarWith(player),
                // НЕ только по isPlayerSide flag. Без правильного origin — даже
                // isPlayerSide:false спавнит агента в player team.
                PartyBase originParty;
                if (isPlayerSide)
                {
                    originParty = MobileParty.MainParty?.Party;
                }
                else
                {
                    originParty = FindEnemyParty() ?? MobileParty.MainParty?.Party;
                    if (originParty == MobileParty.MainParty?.Party)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username}: WARNING enemy party not found, " +
                            "fallback на MainParty (агент может спавниться за стримера)");
                    }
                }
                if (originParty == null)
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] @{username}: no origin party");
                    return;
                }

                bool withHorse = ResolveWithHorse(username);

                Agent agent = Mission.Current.SpawnTroop(
                    new PartyAgentOrigin(originParty, hero.CharacterObject),
                    isPlayerSide:        isPlayerSide,
                    hasFormation:        true,
                    spawnWithHorse:      withHorse,
                    isReinforcement:     true,
                    formationTroopCount: 1,
                    formationTroopIndex: 0,
                    isAlarmed:           true,
                    wieldInitialWeapons: true,
                    forceDismounted:     !withHorse,
                    initialPosition:     null,
                    initialDirection:    null);

                if (agent != null)
                {
                    // BLT pattern (SummonHero.cs:744-746): forced SetTeam после
                    // spawn'a — engine может проигнорировать isPlayerSide и
                    // ставить team по origin.party.MapFaction. SetTeam гарантирует
                    // правильную сторону независимо от party origin.
                    try
                    {
                        Team targetTeam = isPlayerSide
                            ? Mission.Current.PlayerTeam
                            : Mission.Current.PlayerEnemyTeam;
                        if (targetTeam != null && agent.Team != targetTeam)
                        {
                            agent.SetTeam(targetTeam, false);
                            BannerlordLinkModule.Log(
                                $"[player.spawn:{sideLabel}] @{username} forced SetTeam → " +
                                $"{(isPlayerSide ? "PlayerTeam" : "PlayerEnemyTeam")}");
                        }
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} SetTeam failed: {ex.Message}");
                    }
                    try { agent.MountAgent?.FadeIn(); agent.FadeIn(); } catch { }
                }

                BannerlordLinkModule.Log(
                    $"[player.spawn:{sideLabel}] @{username} → summoned " +
                    $"(horse={withHorse}, agent={(agent != null ? "OK" : "NULL")}, " +
                    $"team={agent?.Team?.Side.ToString() ?? "?"})");

                // Sprint M23 retinue spawn: после hero — также spawn'им свиту.
                // BLT pattern (BLTSummonBehavior.SpawnAgent для каждого troop).
                if (retinueIds != null && retinueIds.Count > 0 && agent != null)
                {
                    int spawned = 0;
                    foreach (var troopId in retinueIds)
                    {
                        var troop = MBObjectManager.Instance.GetObject<CharacterObject>(troopId);
                        if (troop == null) continue;
                        try
                        {
                            var retinueAgent = Mission.Current.SpawnTroop(
                                new PartyAgentOrigin(originParty, troop),
                                isPlayerSide:        isPlayerSide,
                                hasFormation:        true,
                                spawnWithHorse:      troop.Equipment != null && troop.HasMount(),
                                isReinforcement:     true,
                                formationTroopCount: 1,
                                formationTroopIndex: 0,
                                isAlarmed:           true,
                                wieldInitialWeapons: true,
                                forceDismounted:     false,
                                initialPosition:     null,
                                initialDirection:    null);
                            if (retinueAgent != null)
                            {
                                Team t = isPlayerSide
                                    ? Mission.Current.PlayerTeam
                                    : Mission.Current.PlayerEnemyTeam;
                                if (t != null && retinueAgent.Team != t)
                                    retinueAgent.SetTeam(t, false);
                                try { retinueAgent.MountAgent?.FadeIn(); retinueAgent.FadeIn(); } catch { }
                                spawned++;
                            }
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[player.spawn:{sideLabel}] retinue {troopId} failed: {ex.Message}");
                        }
                    }
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} retinue: {spawned}/{retinueIds.Count} spawned");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[player.spawn:{sideLabel}] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        private static bool IsMissionReadyForSummon(out string reason)
        {
            var m = Mission.Current;
            if (m == null) { reason = "Mission.Current == null"; return false; }
            if (!m.IsLoadingFinished) { reason = "mission not loaded"; return false; }
            if (m.CurrentState != Mission.State.Continuing)
            {
                reason = $"mission state {m.CurrentState} (нужен Continuing)";
                return false;
            }
            // Sprint 5.1: MissionMode resolve через .ToString() — reflection-safe
            // (enum может быть в TaleWorlds.MountAndBlade.View или другой DLL'е
            // которой нет в наших reference). Battle/Deployment/Tournament/Siege/
            // Conversation/Stealth/Duel/StartUp — known modes.
            // Skip всё кроме Battle: deployment чреват крашем (см. BLT строка 285
            // — "SpawnAgent crashes if called in MissionMode.Deployment"), остальные
            // имеют свою spawn logic + UI которая не учитывает наших агентов.
            string modeStr;
            try { modeStr = m.Mode.ToString(); }
            catch { modeStr = null; }
            if (modeStr != null && modeStr != "Battle")
            {
                reason = $"mission mode {modeStr} (MVP supports только Battle)";
                return false;
            }
            reason = null;
            return true;
        }

        private static bool IsAlreadySpawned(Hero hero)
        {
            if (hero?.CharacterObject == null || Mission.Current == null) return false;
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || !a.IsActive()) continue;
                if (a.Character == hero.CharacterObject) return true;
            }
            return false;
        }

        private static bool ResolveWithHorse(string username)
        {
            var hc = PowerCache.GetHeroClass(username);
            if (hc == null) return false;
            return MountedClasses.Contains(hc.Value.classKey);
        }

        // Find any party belonging to enemy team. Itersует Mission.Agents
        // и берёт origin'у первого живого enemy hero/troop agent'а.
        // BattleCombatant → PartyBase cast (BattleCombatant — это PartyBase или
        // CustomBattleCombatant, обычно PartyBase).
        private static PartyBase FindEnemyParty()
        {
            if (Mission.Current == null) return null;
            var playerTeam = Mission.Current.PlayerTeam;
            if (playerTeam == null) return null;

            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || !a.IsActive() || !a.IsHuman) continue;
                if (a.Team == null) continue;
                if (a.Team == playerTeam) continue;
                if (!a.Team.IsEnemyOf(playerTeam)) continue;

                // Origin может быть PartyAgentOrigin (PartyBase) или SimpleAgentOrigin.
                // BattleCombatant — interface; cast'имся на PartyBase.
                var origin = a.Origin as PartyAgentOrigin;
                if (origin?.BattleCombatant is PartyBase pb) return pb;
            }
            return null;
        }
    }
}
