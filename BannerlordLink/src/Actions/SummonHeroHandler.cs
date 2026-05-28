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

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Summon(username, isPlayerSide, retinueIds, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Summon(string username, bool isPlayerSide,
            System.Collections.Generic.List<string> retinueIds, string actionId)
        {
            string sideLabel = isPlayerSide ? "ally" : "enemy";
            try
            {
                if (!IsMissionReadyForSummon(out string reason))
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] REFUSE @{username}: {reason}");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "mission_not_ready:" + reason);
                    return;
                }

                Hero hero = HeroLookup.FindByUsername(username);
                if (hero == null)
                {
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] REFUSE @{username}: hero not found");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }

                // Sprint 5.27r: block ENEMY summon в hideout (BLT pattern
                // — SummonHero.cs:309 "!settings.OnPlayerSide" block).
                // Hideout — асимметричная миссия, enemy spawn ломает баланс
                // (player + 7 troops vs ~5 бандитов; +viewer enemy = unfair).
                bool isHideoutMission = false;
                try { isHideoutMission = (Mission.Current?.Mode.ToString() == "Stealth"); }
                catch { }
                if (isHideoutMission && !isPlayerSide)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] REFUSE @{username}: enemy summon в hideout запрещён");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "enemy_in_hideout_blocked");
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
                    // Sprint 5.31 #45c — REFUSE prefix + refund. Раньше viewer
                    // платил и ничего не происходило молча.
                    BannerlordLinkModule.Log($"[player.spawn:{sideLabel}] REFUSE @{username}: no origin party (даже MainParty=null?!)");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_origin_party");
                    return;
                }

                // Sprint 5.7 — track original party for restoration on OnEndMission.
                // BLT pattern: hero временно добавляется в spawn party (для proper
                // engine integration — formations, reinforcement counts), затем на
                // mission end восстанавливается обратно в свою vanilla party.
                //
                // Sprint 5.28 fix (дубли в отряде): раньше +1 шёл БЕЗУСЛОВНО
                // даже когда hero уже в target party (e.g. re-summon того же
                // viewer'а во время боя, или engine auto-spawn'нул как clan-
                // member'а). Каждый повторный summon → ещё +1 → у юзера
                // накопилось 17 копий kuro_gothic.
                //
                // BLT решает это правильно (BLT SummonHero.cs:358-361):
                //     if (originalParty?.Party != party) {
                //         originalParty?.Party?.AddMember(hero, -1);
                //         party.AddMember(hero, 1);
                //     }
                // — и `+1`, и `-1` ОБА внутри одного if'а. Если hero уже в
                // target party — не трогаем roster вообще.
                //
                // Также проверяем GetTroopCount(target) > 0 как safety:
                // если engine уже добавил hero как PlayerClan member, мы
                // не должны его дублировать.
                PartyBase originalHeroParty = hero.PartyBelongedTo?.Party;
                bool wasLeader = originalHeroParty?.LeaderHero == hero;
                int oldHP = hero.HitPoints;

                int alreadyInTarget = 0;
                try { alreadyInTarget = originParty.MemberRoster?.GetTroopCount(hero.CharacterObject) ?? 0; }
                catch { }

                bool didRosterTransfer = false;
                if (originalHeroParty != originParty && alreadyInTarget == 0)
                {
                    // Real transfer: hero не в target. Делаем -1/+1 атомарно.
                    if (originalHeroParty != null)
                    {
                        int curOrig = 0;
                        try { curOrig = originalHeroParty.MemberRoster?.GetTroopCount(hero.CharacterObject) ?? 0; }
                        catch { }
                        if (curOrig > 0)
                        {
                            try { originalHeroParty.MemberRoster.AddToCounts(hero.CharacterObject, -1); }
                            catch (Exception ex)
                            {
                                BannerlordLinkModule.Log(
                                    $"[player.spawn:{sideLabel}] @{username}: remove from " +
                                    $"original party failed: {ex.Message}");
                            }
                        }
                    }
                    try
                    {
                        originParty.MemberRoster.AddToCounts(hero.CharacterObject, 1);
                        didRosterTransfer = true;
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username}: add to spawn party failed: {ex.Message}");
                    }
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username}: hero уже в target party " +
                        $"(count={alreadyInTarget}, originSame={originalHeroParty == originParty}) " +
                        "— skip +1 (BLT pattern, avoid dupe)");
                }

                // Sprint 5.28: register restore ТОЛЬКО если мы реально
                // transfer'или hero. Иначе на OnEndMission делать нечего —
                // hero остаётся где был.
                if (didRosterTransfer)
                {
                    BannerlordLink.Behaviors.KillRewardBehavior.RegisterPartyRestore(
                        hero, originalHeroParty, wasLeader, oldHP);
                }

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

                // 2026-05-28 REVERT (post-crash): возврат к BLT-Lait pattern.
                // SPAWN-CLOSE override (perp offset 3.5-6.5m от Agent.Main) был
                // intentional deviation от BLT. После crash session 19:59:22 с
                // long battle (multiple viewer spawns + retinue + kill rewards
                // every second) — возможный contributing factor: invalid pos
                // когда Agent.Main moved между position read + SpawnTroop.
                //
                // BLT-Lait pattern (BLTSummonBehavior.cs):
                //   initialPosition: null
                //   initialDirection: null
                //   isReinforcement: !DeploymentFlag (true в обычном бою)
                //
                // Engine reinforcement spawn zone:
                //   • Ally side  → behind/within player formation backline
                //   • Enemy side → behind/within enemy formation backline
                //   • Proper formation integration (AI commander видит как
                //     proper reinforcement, не loose Agent)
                //   • Safe в siege / arena / hideout (engine validates pos)
                //
                // User feedback ранее: «спавн далеко от мейн отряда». Это
                // intended engine behavior — viewer reinforcement из backline.
                // Принимаем как BLT-canonical. Если позже понадобится closer
                // spawn — отдельный re-implement через Mission.GetSpawnPoint
                // (engine-validated path), не Agent.Main + raw offset.
                Vec3? heroSpawnPos = null;
                Vec2? heroSpawnDir = null;
                BannerlordLinkModule.Log(
                    $"[player.spawn:{sideLabel}] @{username} → engine reinforcement zone " +
                    "(BLT-canonical, no position override)");
                if (!heroSpawnPos.HasValue)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} → engine default " +
                        "reinforcement zone (no Agent.Main или enemy side)");
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

                // Sprint 5.29: in-game popup + audio cue для стримера (BLT pattern).
                // Раньше стример не понимал что viewer призван — только log в файле.
                // Цветной popup в top-left ленте + sound notification.
                if (!heroAlreadySpawned)
                {
                    try
                    {
                        var col = isPlayerSide
                            ? new TaleWorlds.Library.Color(0.32f, 0.83f, 0.45f)  // green
                            : new TaleWorlds.Library.Color(0.87f, 0.21f, 0.21f); // red
                        TaleWorlds.Library.InformationManager.DisplayMessage(
                            new TaleWorlds.Library.InformationMessage(
                                $"{(isPlayerSide ? "📯" : "⚔️")} @{username} {(isPlayerSide ? "за тебя" : "ПРОТИВ тебя")} ({(withHorse ? "конный" : "пеший")})",
                                col));
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} popup failed: {ex.Message}");
                    }
                }

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
                                BannerlordLinkModule.LogVerbose(() =>
                                    $"[player.spawn V] @{username} retinue spawned " +
                                    $"idx={retinueAgent.Index} troop={troop.StringId} " +
                                    $"hp={(int)retinueAgent.Health}/{(int)retinueAgent.HealthLimit} " +
                                    $"team={retinueAgent.Team?.Side} formation={retinueAgent.Formation?.FormationIndex}");
                                Team t = isPlayerSide
                                    ? Mission.Current.PlayerTeam
                                    : Mission.Current.PlayerEnemyTeam;
                                if (t != null && retinueAgent.Team != t)
                                    retinueAgent.SetTeam(t, false);

                                // Sprint 5.32 ROLLBACK M13 — Crash dump 28004 (22:12):
                                // native crash в Mission tick через 5-10s после
                                // retinue HP×2 setter на 5 troops. Engine corrupts
                                // internal state когда BaseHealthLimit мутируется
                                // ПОСЛЕ Agent creation (Bannerlord 1.3.15).
                                //
                                // Disable ×2 multiplier. Retinue spawnится с default
                                // engine HP — это restoration к pre-M13 behavior
                                // (раньше работало стабильно). Если streamer хочет
                                // более прочную свиту — buy elite troops через
                                // hero.recruit_troops с is_elite=true (×3 cost).
                                //
                                // BLT pattern в Randomchair22-fork: BLTSummonBehavior
                                // делает aналогичный setter, но возможно у них
                                // другая Agent API surface (1.2.x), либо они setter
                                // используют ВО ВРЕМЯ SpawnTroop call вместо
                                // post-spawn mutation.
                                // try
                                // {
                                //     float origLimit = retinueAgent.HealthLimit;
                                //     if (origLimit > 0f)
                                //     {
                                //         retinueAgent.BaseHealthLimit = origLimit * 2f;
                                //         retinueAgent.HealthLimit = origLimit * 2f;
                                //         retinueAgent.Health = retinueAgent.HealthLimit;
                                //     }
                                // }
                                // catch (Exception hpEx)
                                // {
                                //     BannerlordLinkModule.Log(
                                //         $"[player.spawn:{sideLabel}] @{username} retinue HP×2 warn: {hpEx.Message}");
                                // }

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

            // Sprint 5.32 CRASH FIX — в Bannerlord 1.3.x tournament mission
            // имеет Mode=Battle (НЕ "Tournament"), но содержит TournamentBehavior /
            // TournamentFightMissionController как mission behavior. Без этой
            // проверки player.spawn proходит mode-check, потом engine крашит с
            // "Nullable object must have a value" в SpawnTroop (нет default
            // reinforcement zone для tournament arena → engine .Value на
            // Nullable<Vec3> внутри своего SpawnPathFinder).
            //
            // Лог crash'а (17:18:24): tournament в town_B5 → @z_pot купил player.spawn
            // → [player.spawn:ally] CRASHED: InvalidOperationException.
            try
            {
                // TournamentBehavior — campaign-level, TournamentFightMissionController
                // или *TournamentMissionBehavior — mission-level. Сканим MissionBehaviors
                // по имени типа (надёжнее чем typed generic — namespace может
                // меняться между версиями TaleWorlds).
                bool isTournamentMission = false;
                foreach (var b in m.MissionBehaviors)
                {
                    if (b == null) continue;
                    var n = b.GetType().Name;
                    if (n.IndexOf("Tournament", StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        // Skip наш собственный TournamentMissionBehavior — он
                        // используется для tracking, но не блокирует summon.
                        // Хотя в текущей логике мы вообще НЕ хотим summon во время
                        // tournament — так что блокируем.
                        isTournamentMission = true;
                        BannerlordLinkModule.Log(
                            $"[player.spawn] tournament detected via behavior: {b.GetType().FullName}");
                        break;
                    }
                }
                if (isTournamentMission)
                {
                    reason = "tournament mission (engine не имеет reinforcement zone, " +
                             "spawn → InvalidOperationException)";
                    return false;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[player.spawn] tournament-detect warn: {ex.Message}");
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
        /// Cached reflection field — устанавливается один раз.
        ///
        /// Sprint 5.31 #45e (audit MED-2) — раньше при отвале reflection
        /// (Agent._name переименован в новой версии TaleWorlds) warning
        /// логировался ОДИН раз, потом все @username markers просто пропадали
        /// молча. Теперь:
        ///   1. Reflection пробует поочерёдно несколько кандидатов
        ///      (`_name`, `<Name>k__BackingField`).
        ///   2. Failures периодически re-log'аются (каждые 100 пропущенных
        ///      вызовов) чтобы streamer видел "почему имена пропали".
        ///   3. Не пытаемся fallback на native Agent.Name property —
        ///      она read-only во всех известных версиях.</summary>
        private static System.Reflection.FieldInfo _agentNameField;
        private static bool _agentNameFieldFailed;
        private static int _agentNameSkippedCount;
        private static readonly string[] _AGENT_NAME_FIELD_CANDIDATES = new[]
        {
            "_name",                  // Bannerlord 1.0–1.2.x
            "<Name>k__BackingField",  // если переведут на auto-property
        };

        private static void SetAgentDisplayName(Agent agent, string newName)
        {
            if (agent == null || string.IsNullOrEmpty(newName)) return;
            if (_agentNameFieldFailed)
            {
                // Periodic re-log так багрепорт "имена не показываются"
                // легко найти grep'ом в логе.
                _agentNameSkippedCount++;
                if (_agentNameSkippedCount % 100 == 1)
                {
                    BannerlordLinkModule.Log(
                        $"[SetAgentDisplayName] reflection broken — " +
                        $"skipped {_agentNameSkippedCount} rename'ов. " +
                        $"Tried fields: {string.Join(",", _AGENT_NAME_FIELD_CANDIDATES)}");
                }
                return;
            }
            if (_agentNameField == null)
            {
                foreach (var fieldName in _AGENT_NAME_FIELD_CANDIDATES)
                {
                    _agentNameField = HarmonyLib.AccessTools.Field(typeof(Agent), fieldName);
                    if (_agentNameField != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[SetAgentDisplayName] resolved Agent.{fieldName} via reflection");
                        break;
                    }
                }
                if (_agentNameField == null)
                {
                    _agentNameFieldFailed = true;
                    BannerlordLinkModule.Log(
                        "[SetAgentDisplayName] CRITICAL: Agent name field not found! " +
                        "Tried: " + string.Join(",", _AGENT_NAME_FIELD_CANDIDATES) +
                        " — @username markers недоступны до фикса. Проверь версию игры.");
                    return;
                }
            }
            try
            {
                _agentNameField.SetValue(agent, new TaleWorlds.Localization.TextObject(newName));
            }
            catch (Exception ex)
            {
                // SetValue может бросить если тип поля изменился.
                BannerlordLinkModule.Log(
                    $"[SetAgentDisplayName] SetValue failed: {ex.GetType().Name}: {ex.Message}");
                _agentNameFieldFailed = true;
            }
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
