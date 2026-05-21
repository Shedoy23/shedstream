using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.AgentOrigins;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.Library;
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

                // Sprint 5.15: если hero уже в Mission (auto-spawned engine'ом
                // как клан-член), НЕ пропускаем — spawn только retinue + heal.
                // Свита фантомная (только в нашем backend), engine её не знает.
                Agent existingAgent = FindExistingHeroAgent(hero);
                bool heroAlreadySpawned = existingAgent != null;
                if (heroAlreadySpawned)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username}: hero уже в Mission " +
                        "(engine auto-spawn) — спавним только retinue + heal");
                }

                // Sprint 5.7 — BLT-aligned party selection:
                //   ally  → MobileParty.MainParty.Party (player party)
                //   enemy → RANDOM enemy team party. Если нет — REFUSE (НЕ
                //           fallback на MainParty, чтобы не спавнить enemy
                //           на стороне стримера).
                // Sprint 5.15: если hero уже spawned, party селект всё равно
                // нужен — для retinue spawning (тот же origin).
                // Sprint 5.27p: enemy spawn больше не refuse'ит когда нет
                // enemy PartyBase. Hideout / arena / tournament агентыхnave не
                // PartyAgentOrigin → SelectRandomEnemyParty возвращает null.
                // Раньше: отказ. Теперь: fallback на MainParty + forced
                // SetTeam(PlayerEnemyTeam) ниже (engine ignored origin'овский
                // side когда мы explicit SetTeam'им). BLT тоже использует
                // MainParty для enemy если ничего лучше нет.
                PartyBase originParty;
                if (isPlayerSide)
                {
                    originParty = MobileParty.MainParty?.Party;
                }
                else
                {
                    originParty = SelectRandomEnemyParty();
                    if (originParty == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username}: enemy party " +
                            "не найдена → fallback на MainParty (forced SetTeam fix'нет side)");
                        originParty = MobileParty.MainParty?.Party;
                    }
                }
                if (originParty == null)
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] @{username}: no origin party (даже MainParty=null?!)");
                    return;
                }

                // Sprint 5.7 — track original party for restoration on OnEndMission.
                // BLT pattern: hero временно добавляется в spawn party (для proper
                // engine integration — formations, reinforcement counts), затем на
                // mission end восстанавливается обратно в свою vanilla party.
                PartyBase originalHeroParty = hero.PartyBelongedTo?.Party;
                bool wasLeader = originalHeroParty?.LeaderHero == hero;
                int oldHP = hero.HitPoints;

                if (originalHeroParty != null && originalHeroParty != originParty)
                {
                    try { originalHeroParty.AddMember(hero.CharacterObject, -1); }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username}: remove from " +
                            $"original party failed: {ex.Message}");
                    }
                }
                try { originParty.AddMember(hero.CharacterObject, 1); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username}: add to spawn party failed: {ex.Message}");
                }

                // Зарегистрировать восстановление на OnEndMission.
                BannerlordLink.Behaviors.KillRewardBehavior.RegisterPartyRestore(
                    hero, originalHeroParty, wasLeader, oldHP);

                // Sprint 5.7 — formation preference (player side only). BLT:
                //   Campaign.SetPlayerFormationPreference(char, formationClass)
                // Без этого engine кидает hero в default Infantry даже если archer.
                if (isPlayerSide)
                {
                    try
                    {
                        var formationClass = ResolveFormationClass(username);
                        Campaign.Current.SetPlayerFormationPreference(
                            hero.CharacterObject, formationClass);
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} formation pref → {formationClass}");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} SetPlayerFormationPreference failed: {ex.Message}");
                    }
                }

                bool withHorse = ResolveWithHorse(username);

                // Sprint 5.27f: spawn hero РЯДОМ с стримером (Agent.Main),
                // не в default reinforcement zone (backline).
                // 5.27p: enemy spawn — 10m ВПЕРЕДИ стримера (looking direction),
                // ally — 3m perpendicular от него.
                Vec3? heroSpawnPos = null;
                Vec2? heroSpawnDir = null;
                try
                {
                    var streamer = Agent.Main;
                    if (streamer != null && streamer.IsActive())
                    {
                        var look = streamer.LookDirection;
                        if (isPlayerSide)
                        {
                            // Ally: 3m влево/право (alternating по хэшу username).
                            int hashSign = (username.GetHashCode() & 1) == 0 ? 1 : -1;
                            float perpX = -look.y;
                            float perpY = look.x;
                            heroSpawnPos = new Vec3(
                                streamer.Position.x + perpX * 3f * hashSign,
                                streamer.Position.y + perpY * 3f * hashSign,
                                streamer.Position.z);
                            heroSpawnDir = look.AsVec2;
                        }
                        else
                        {
                            // Enemy: 10m ВПЕРЕДИ стримера, looking назад (face-to-face).
                            heroSpawnPos = new Vec3(
                                streamer.Position.x + look.x * 10f,
                                streamer.Position.y + look.y * 10f,
                                streamer.Position.z);
                            // Face the streamer (opposite of his look direction)
                            heroSpawnDir = new Vec2(-look.x, -look.y);
                        }
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} anchor resolve failed: {ex.Message}");
                }

                // Sprint 5.15: re-use existing agent если hero auto-spawned;
                // иначе spawn fresh agent через engine API.
                Agent agent;
                if (heroAlreadySpawned)
                {
                    agent = existingAgent;
                }
                else
                {
                    agent = Mission.Current.SpawnTroop(
                        new PartyAgentOrigin(originParty, hero.CharacterObject),
                        isPlayerSide:        isPlayerSide,
                        hasFormation:        true,
                        spawnWithHorse:      withHorse,
                        isReinforcement:     !heroSpawnPos.HasValue,
                        formationTroopCount: 1,
                        formationTroopIndex: 0,
                        isAlarmed:           true,
                        wieldInitialWeapons: true,
                        forceDismounted:     !withHorse,
                        initialPosition:     heroSpawnPos,
                        initialDirection:    heroSpawnDir);
                }

                if (agent != null && !heroAlreadySpawned)
                {
                    // Sprint 5.27q: BLT pattern — переименование agent через
                    // reflection (_name field). Engine показывает Name при
                    // hover/target на agent'a. Для hero: чистое "@username"
                    // (без [BLink] prefix), чтобы стример сразу видел чей это
                    // hero без визуального мусора.
                    try
                    {
                        SetAgentDisplayName(agent, $"@{username}");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} rename failed: {ex.Message}");
                    }

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

                    // Sprint 5.5: force-heal hero до 100% HP при призыве.
                    // Sprint 5.15: НЕ healим если hero уже spawned (был бы exploit
                    // "вызови во время боя чтобы залечиться"). Heal только при
                    // настоящем fresh spawn.
                    try
                    {
                        hero.HitPoints = hero.MaxHitPoints;
                        if (agent.IsActive())
                        {
                            agent.Health = agent.HealthLimit;
                        }
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} HP restored → " +
                            $"{(int)agent.HealthLimit}/{(int)agent.HealthLimit}");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} HP heal failed: {ex.Message}");
                    }
                }

                BannerlordLinkModule.Log(
                    $"[player.spawn:{sideLabel}] @{username} → " +
                    $"{(heroAlreadySpawned ? "retinue-only" : "summoned")} " +
                    $"(horse={withHorse}, agent={(agent != null ? "OK" : "NULL")}, " +
                    $"team={agent?.Team?.Side.ToString() ?? "?"})");

                // Sprint 5.7 — expire team query caches + reset formation spawn
                // indices. BLT pattern — без этого engine AI может не сразу
                // заметить нового agent'a (продолжит игнорировать в формации).
                try
                {
                    foreach (var t in Mission.Current.Teams)
                    {
                        t.QuerySystem.Expire();
                    }
                    foreach (var f in Mission.Current.Teams
                                 .SelectMany(t => t.FormationsIncludingSpecialAndEmpty))
                    {
                        f.SetSpawnIndex(0);
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} cache expire failed: {ex.Message}");
                }

                // Sprint M23 retinue spawn: после hero — также spawn'им свиту.
                // BLT pattern (BLTSummonBehavior.SpawnAgent для каждого troop).
                //
                // Sprint 5.27d: spawn retinue РЯДОМ с hero (ring 60° × 2m), не в
                // default reinforcement zone.
                //
                // Sprint 5.27n: skip retinue в hideout missions. Hideout имеет
                // 8-troop limit + tight indoor map. 1 viewer × hero + 5 retinue
                // = 6 agents → быстро упирается в limit, мешает геймплею.
                // Detection: MissionMode == Stealth (в vanilla Bannerlord этот
                // mode почти exclusively используется в hideouts).
                bool inHideout = false;
                try
                {
                    inHideout = (Mission.Current?.Mode.ToString() == "Stealth");
                }
                catch { }

                if (inHideout && retinueIds != null && retinueIds.Count > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} hideout detected — " +
                        $"skip retinue ({retinueIds.Count} troops) для 8-limit");
                }
                if (retinueIds != null && retinueIds.Count > 0 && agent != null && !inHideout)
                {
                    Vec3? anchorPos = null;
                    Vec2? anchorDir = null;
                    if (agent.IsActive())
                    {
                        try
                        {
                            anchorPos = agent.Position;
                            anchorDir = agent.LookDirection.AsVec2;
                        }
                        catch { }
                    }

                    int spawned = 0;
                    int ringIdx = 0;
                    foreach (var troopId in retinueIds)
                    {
                        var troop = MBObjectManager.Instance.GetObject<CharacterObject>(troopId);
                        if (troop == null) continue;

                        // Ring offset: 60° step × 2m radius (формация полукольцом).
                        // 5 slots → углы 0/60/120/180/240/300°.
                        Vec3? spawnPos = null;
                        if (anchorPos.HasValue)
                        {
                            float angleRad = (ringIdx * 60f) * 0.0174533f;
                            float dx = (float)Math.Cos(angleRad) * 2f;
                            float dy = (float)Math.Sin(angleRad) * 2f;
                            spawnPos = new Vec3(
                                anchorPos.Value.x + dx,
                                anchorPos.Value.y + dy,
                                anchorPos.Value.z);
                        }
                        ringIdx++;

                        try
                        {
                            var retinueAgent = Mission.Current.SpawnTroop(
                                new PartyAgentOrigin(originParty, troop),
                                isPlayerSide:        isPlayerSide,
                                hasFormation:        true,
                                spawnWithHorse:      troop.Equipment != null && troop.HasMount(),
                                isReinforcement:     !spawnPos.HasValue,
                                formationTroopCount: 1,
                                formationTroopIndex: 0,
                                isAlarmed:           true,
                                wieldInitialWeapons: true,
                                forceDismounted:     false,
                                initialPosition:     spawnPos,
                                initialDirection:    anchorDir);
                            if (retinueAgent != null)
                            {
                                Team t = isPlayerSide
                                    ? Mission.Current.PlayerTeam
                                    : Mission.Current.PlayerEnemyTeam;
                                if (t != null && retinueAgent.Team != t)
                                    retinueAgent.SetTeam(t, false);
                                try { retinueAgent.MountAgent?.FadeIn(); retinueAgent.FadeIn(); } catch { }
                                // Sprint 5.6: register attribution для kill credit
                                try {
                                    BannerlordLink.Behaviors.KillRewardBehavior
                                        .RegisterRetinue(retinueAgent, username);
                                } catch { }
                                // Sprint 5.27q: rename "{TroopName} (@username)"
                                // BLT pattern (BLTSummonBehavior:307).
                                try
                                {
                                    string orig = retinueAgent.Name ?? troop.Name?.ToString() ?? troop.StringId;
                                    SetAgentDisplayName(retinueAgent, $"{orig} (@{username})");
                                }
                                catch { }
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
            // Sprint 5.27m: BLT-aligned mode filter.
            //
            // BLOCK (BLT pattern, BLTSummonBehavior SpawnAgent block-list):
            //   - Deployment   — SpawnAgent crashes (BLT line 285)
            //   - CutScene     — engine не учитывает наших agents
            //   - Conversation — dialog UI
            //   - Replay       — playback mode, no spawn
            //   - Barter       — trade UI
            //   - Duel         — 1×1, нельзя добавлять third party
            //   - Tournament   — у нас отдельный TournamentMissionBehavior
            //
            // ALLOW:
            //   - Battle (field/siege/hideout combat)
            //   - Stealth (hideout sneak — combat начинается в Battle, но
            //     иногда вся миссия в Stealth mode → разрешаем для зачистки)
            //   - StartUp (mission setup — обычно затухает быстро в Battle)
            //
            // Для таверны / lord-halls / town visits нужен SummonInLocation
            // flow (CampaignMission.Current.Location) — это отдельная фича
            // (BLT 200+ строк отдельного метода). Не делаем пока.
            string modeStr;
            try { modeStr = m.Mode.ToString(); }
            catch { modeStr = null; }

            if (modeStr == "Deployment" || modeStr == "CutScene"
                || modeStr == "Conversation" || modeStr == "Replay"
                || modeStr == "Barter"      || modeStr == "Duel"
                || modeStr == "Tournament")
            {
                reason = $"mission mode {modeStr} (BLT block-list)";
                return false;
            }
            reason = null;
            return true;
        }

        private static bool IsAlreadySpawned(Hero hero)
        {
            return FindExistingHeroAgent(hero) != null;
        }

        /// <summary>Sprint 5.27q: переименовывает agent через reflection.
        /// Engine показывает Name при hover/target на agent. BLT pattern
        /// (BLTSummonBehavior:280 — AccessTools.Field(typeof(Agent), "_name")).
        /// Cached reflection field — устанавливается один раз.</summary>
        private static System.Reflection.FieldInfo _agentNameField;
        private static void SetAgentDisplayName(Agent agent, string newName)
        {
            if (agent == null || string.IsNullOrEmpty(newName)) return;
            if (_agentNameField == null)
            {
                _agentNameField = HarmonyLib.AccessTools.Field(typeof(Agent), "_name");
                if (_agentNameField == null)
                {
                    BannerlordLinkModule.Log(
                        "[SetAgentDisplayName] Agent._name field not found via reflection!");
                    return;
                }
            }
            _agentNameField.SetValue(agent, new TaleWorlds.Localization.TextObject(newName));
        }

        /// <summary>Sprint 5.15: возвращает existing Agent для hero в Mission
        /// или null. Используется чтобы re-attach retinue к auto-spawned'у hero.</summary>
        private static Agent FindExistingHeroAgent(Hero hero)
        {
            if (hero?.CharacterObject == null || Mission.Current == null) return null;
            foreach (var a in Mission.Current.Agents)
            {
                if (a == null || !a.IsActive()) continue;
                if (a.Character == hero.CharacterObject) return a;
            }
            return null;
        }

        private static bool ResolveWithHorse(string username)
        {
            var hc = PowerCache.GetHeroClass(username);
            if (hc == null) return false;
            return MountedClasses.Contains(hc.Value.classKey);
        }

        // Sprint 5.7 — RANDOM enemy party (BLT pattern). Раньше брали FIRST
        // встречного — однообразный spawn point + предсказуемо. Теперь — uniqe
        // parties → SelectRandom(). null → fallback на MainParty (см. caller).
        //
        // Sprint 5.27p: diagnostic log с подсчётом agents (понять что блокирует
        // если viewer'ы получают "против стримера не вызывается").
        private static PartyBase SelectRandomEnemyParty()
        {
            if (Mission.Current == null) return null;
            var enemyTeam = Mission.Current.PlayerEnemyTeam;
            if (enemyTeam == null)
            {
                BannerlordLinkModule.Log("[SelectEnemyParty] PlayerEnemyTeam == null");
                return null;
            }

            var unique = new System.Collections.Generic.HashSet<PartyBase>();
            // TeamAgents может быть null если team только что spawn'нулась — fallback
            // на Mission.Agents filter.
            var source = (System.Collections.Generic.IEnumerable<Agent>)enemyTeam.TeamAgents
                        ?? Mission.Current.Agents;

            int total = 0, inactive = 0, wrongTeam = 0, noOrigin = 0;
            foreach (var a in source)
            {
                total++;
                if (a == null || !a.IsActive()) { inactive++; continue; }
                if (a.Team != enemyTeam && !(a.Team?.IsEnemyOf(Mission.Current.PlayerTeam) ?? false))
                { wrongTeam++; continue; }
                var origin = a.Origin as PartyAgentOrigin;
                if (origin?.BattleCombatant is PartyBase pb) { unique.Add(pb); }
                else { noOrigin++; }
            }
            BannerlordLinkModule.Log(
                $"[SelectEnemyParty] scanned={total} inactive={inactive} " +
                $"wrongTeam={wrongTeam} noPartyOrigin={noOrigin} → uniqueParties={unique.Count}");
            if (unique.Count == 0) return null;
            var list = unique.ToList();
            return list[new Random().Next(list.Count)];
        }

        // Sprint 5.7 — map class_key → FormationClass для
        // SetPlayerFormationPreference. Соответствует M15 bannerlord_classes.
        private static FormationClass ResolveFormationClass(string username)
        {
            try
            {
                var hc = PowerCache.GetHeroClass(username);
                string classKey = (hc?.classKey ?? "").ToLowerInvariant();
                switch (classKey)
                {
                    case "archer":          return FormationClass.Ranged;
                    case "horse_archer":
                    case "camel_archer":    return FormationClass.HorseArcher;
                    case "cavalry":
                    case "camel_cavalry":
                    case "knight":          return FormationClass.Cavalry;
                    case "tank":
                    case "berserk":
                    case "psycho":
                    case "infantry":
                    default:                return FormationClass.Infantry;
                }
            }
            catch
            {
                return FormationClass.Infantry;
            }
        }
    }
}
