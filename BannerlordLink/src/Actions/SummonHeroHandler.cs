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
                // 2026-06-18 (Phase 1): mounted classes + legacy aliases.
                "knight", "lancer", "horse_archer",
                "cavalry", "camel_cavalry", "camel_archer",
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
                // как клан-член), НЕ пропускаем — spawn только retinue.
                // Свита фантомная (только в нашем backend), engine её не знает.
                Agent existingAgent = FindExistingHeroAgent(hero);
                bool heroAlreadySpawned = existingAgent != null;
                if (heroAlreadySpawned)
                {
                    // 2026-09-03 — раньше строка обещала "спавним только retinue
                    // + heal", но и лечение, и перевод стороны стоят ниже под
                    // гейтом `!heroAlreadySpawned`. Обещание было ложным и увело
                    // разбор в сторону: heal здесь не происходит.
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username}: hero уже в Mission " +
                        "(engine auto-spawn) — спавнить можно только свиту");

                    // 2026-09-03 — платный тихий no-op. Герой уже на поле: спавнить
                    // его не нужно, сторону не переводим и не лечим (оба под гейтом
                    // ниже). Если и свите выходить некуда — действие не сделает
                    // РОВНО НИЧЕГО, поэтому отказ с возвратом ДО работы, а не
                    // PostApplied в конце. Найдено живым прогоном 03.09: "призвать
                    // против стримера" списал 100💎 вчистую и отчитался успехом.
                    bool retinueCanSpawn = retinueIds != null && retinueIds.Count > 0;
                    if (retinueCanSpawn && isHideoutMission)
                    {
                        // в убежище свита не выходит (лимит 8 агентов) — ниже skip
                        retinueCanSpawn = false;
                    }
                    if (retinueCanSpawn)
                    {
                        try
                        {
                            retinueCanSpawn = !(BannerlordLink.Behaviors.RetinueSpawnTracker
                                .Instance?.AlreadySpawned(username) ?? false);
                        }
                        catch { }
                    }
                    if (!retinueCanSpawn)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] REFUSE @{username}: hero уже в бою, " +
                            "свите выходить некуда — эффекта не будет, возврат");
                        BannerlordLink.Util.ActionFeedback.PostFailed(
                            actionId, "already_in_battle_nothing_to_do");
                        return;
                    }
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

                // Summoned units are mission-only. Mutating MemberRoster while
                // its party participates in an active MapEvent invalidates the
                // engine's UniqueTroopDescriptor indices and was the root cause
                // of MapEventParty.OnTroopWounded/OnTroopKilled crashes. A
                // SimpleAgentOrigin deliberately has no campaign-party removal
                // side effect, so the campaign roster remains untouched.

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

                // 2026-05-29 Stage 5 (BLT-RC22 pattern) — ShouldUseMount adds
                // Mission-context guards on top of class check. Cavalry-class
                // в siege/stealth/naval → forced dismount чтобы не stuck'ились
                // в geometry. См. ShouldUseMount() ниже для full pattern.
                bool withHorse = ShouldUseMount(username);

                // 2026-05-28 v2: ally → null (BLT-canonical engine zone),
                // enemy → near random enemy agent чтобы спавнить в их формацию.
                //
                // User feedback (post crash recovery): «"против стримера"
                // спавнится прям рядом со стримером, а не во вражеский отряд».
                //
                // Root cause: engine reinforcement zone иногда даёт enemy spawn
                // близко к streamer formation если battle mid-clash (обе formations
                // сошлись, backlines перекрылись). + если fallback на MainParty
                // (когда нет enemy party origin), engine реально кладёт near
                // MainParty position игнорируя isPlayerSide.
                //
                // Fix: для enemy side берём position существующего enemy agent
                // (any alive enemy in PlayerEnemyTeam) + small offset. Engine
                // SpawnTroop validates ground там, safe. Не используем Agent.Main
                // (prev crash-attributed). Не raw-calculate enemy formation
                // center (heavy, требует Formation iteration).
                Vec3? heroSpawnPos = null;
                Vec2? heroSpawnDir = null;

                // 2026-08-02 — формация по КЛАССУ зрителя. Считаем ДО позиции:
                // к этой же формации привязываемся при спавне за своих (ниже).
                //
                // ЧТО ДЕЛАЛ ДВИЖОК САМ (декомпиляция, чтобы не переоценивать
                // масштаб правки). У `Mission.SpawnTroop` есть параметр
                // `formationIndex` со значением по умолчанию
                // `NumberOfAllFormations` = «не задан». Мы его не передавали, и
                // движок шёл в `agentTeam.GetFormation(GetAgentTroopClass(...))`
                // → `CharacterObject.GetFormationClass()`, а тот для ГЕРОЯ
                // считает формацию по снаряжению:
                //     конь в слоте? лук/арбалет? → Infantry / Ranged /
                //     Cavalry / HorseArcher.
                // То есть формация назначалась, и для лучника с луком она была
                // ВЕРНОЙ. Это не «класс не доезжал» — это «класс доезжал
                // косвенно, через шмот».
                //
                // ЗАЧЕМ ТОГДА ПРАВКА. Два случая, где косвенный вывод врёт:
                //  1. Снаряжение разошлось с классом (лоадаут не применился,
                //     низкий тир, руками сняли лук) — зритель заплатил за класс
                //     лучника, а стоит в пехоте. Теперь источник истины —
                //     класс, а не то, что оказалось в слотах.
                //  2. Принудительное спешивание. `GetFormationClass` смотрит на
                //     КОНЯ В ШАБЛОНЕ, а не на то, спавнимся ли мы верхом.
                //     В осаде `ShouldUseMount` ссаживает конника, но движок всё
                //     равно считал его Cavalry → пеший боец в конной формации.
                //
                // Осадная оговорка: `GetAgentTroopClass` сам приводит класс к
                // пешему через `DismountedClass()` в осаде и в вылазке у
                // атакующего. Передавая formationIndex явно, мы этот шаг
                // обходим — значит повторяем его сами по уже посчитанному
                // `withHorse` (ShouldUseMount учитывает осаду, стелс и море).
                //
                // `SetPlayerFormationPreference` выше не помогала и помочь не
                // могла: это кампанийная настройка расстановки ПЕРЕД боем, на
                // `SpawnTroop` посреди боя она не смотрит. Оставлена — на своём
                // месте она работает.
                var spawnFormation = ResolveFormationClass(username);
                if (!withHorse)
                {
                    try { spawnFormation = spawnFormation.DismountedClass(); }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} dismount-class warn: {ex.Message}");
                    }
                }

                // 2026-08-02 — спавн за СВОИХ больше не в зоне подкреплений.
                //
                // Симптом владельца: «на некоторых картах зрители со свитой
                // спавнятся очень далеко за спиной, около края карты».
                // Причина ровно здесь: для союзной стороны позиция оставалась
                // null (см. ниже «Ally side → null»), поэтому уходило
                // `isReinforcement: true`, и движок клал агента в зону
                // подкреплений. На больших картах она у самого края.
                //
                // Для вражеской стороны позицию считали давно — по живому
                // вражескому агенту. Делаем то же для своей, только якорь
                // выбираем ИЗ ЦЕЛЕВОЙ ФОРМАЦИИ: лучник появится у стрелков, а
                // не в куче пехоты. Если в его формации ещё никого нет —
                // берём любого своего; если своих нет вообще — оставляем
                // прежнее поведение (зона подкреплений), это не хуже, чем было.
                //
                // Agent.Main намеренно НЕ используем — он уже был причиной
                // краша, о чём написано в комментарии выше.
                if (isPlayerSide)
                {
                    try
                    {
                        var allyTeam = Mission.Current?.PlayerTeam;
                        if (allyTeam != null)
                        {
                            Agent anchor = null;
                            Agent anchorSameFormation = null;
                            foreach (var a in Mission.Current.Agents)
                            {
                                if (a == null || !a.IsActive() || !a.IsHuman) continue;
                                if (a.Team != allyTeam) continue;
                                if (a == Agent.Main) continue;      // не якоримся на стримере
                                if (anchor == null) anchor = a;
                                if (a.Formation != null
                                    && a.Formation.FormationIndex == spawnFormation)
                                {
                                    anchorSameFormation = a;
                                    break;
                                }
                            }
                            var chosen = anchorSameFormation ?? anchor;
                            if (chosen != null)
                            {
                                var anchorPos = chosen.Position;
                                var anchorDir = chosen.LookDirection.AsVec2;
                                var perp = new Vec2(-anchorDir.y, anchorDir.x);
                                int hash = Math.Abs(username.GetHashCode());
                                float offsetDist = 2f + (hash % 30) / 15f;   // 2–4 м
                                float sideSign = (hash % 2 == 0) ? 1f : -1f;
                                var offset = perp * (offsetDist * sideSign);
                                heroSpawnPos = new Vec3(
                                    anchorPos.x + offset.x,
                                    anchorPos.y + offset.y,
                                    anchorPos.z);
                                heroSpawnDir = anchorDir;
                                BannerlordLinkModule.Log(
                                    $"[player.spawn:{sideLabel}] @{username} → рядом со своими " +
                                    $"({(anchorSameFormation != null ? "своя формация " + spawnFormation : "любой союзник")}, " +
                                    $"offset {offsetDist:F1}м)");
                            }
                        }
                    }
                    catch (Exception posEx)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} ally-anchor pos calc failed: " +
                            $"{posEx.Message} — fallback зона подкреплений");
                        heroSpawnPos = null;
                        heroSpawnDir = null;
                    }
                }

                if (!isPlayerSide)
                {
                    try
                    {
                        var enemyTeam = Mission.Current?.PlayerEnemyTeam;
                        if (enemyTeam != null)
                        {
                            Agent enemyAnchor = null;
                            // Find ANY alive enemy human agent. Prefer non-mounted
                            // чтобы pos не плыла со скакуном.
                            foreach (var a in Mission.Current.Agents)
                            {
                                if (a == null || !a.IsActive() || !a.IsHuman) continue;
                                if (a.Team != enemyTeam) continue;
                                enemyAnchor = a;
                                if (!a.HasMount) break;   // prefer dismounted
                            }
                            if (enemyAnchor != null)
                            {
                                // Small 2-4m perp offset от anchor чтобы не overlap.
                                var anchorPos = enemyAnchor.Position;
                                var anchorDir = enemyAnchor.LookDirection.AsVec2;
                                var perp = new Vec2(-anchorDir.y, anchorDir.x);
                                int hash = Math.Abs(username.GetHashCode());
                                float offsetDist = 2f + (hash % 30) / 15f;  // 2-4m
                                float sideSign = (hash % 2 == 0) ? 1f : -1f;
                                var offset = perp * (offsetDist * sideSign);
                                heroSpawnPos = new Vec3(
                                    anchorPos.x + offset.x,
                                    anchorPos.y + offset.y,
                                    anchorPos.z);
                                heroSpawnDir = anchorDir;
                                BannerlordLinkModule.Log(
                                    $"[player.spawn:{sideLabel}] @{username} → near enemy agent " +
                                    $"(anchor idx={enemyAnchor.Index} offset {offsetDist:F1}m " +
                                    $"side={(sideSign > 0 ? "R" : "L")})");
                            }
                        }
                    }
                    catch (Exception posEx)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.spawn:{sideLabel}] @{username} enemy-anchor pos calc failed: " +
                            $"{posEx.Message} — fallback engine default");
                        heroSpawnPos = null;
                        heroSpawnDir = null;
                    }
                }
                // Ally side → null (BLT-canonical, engine reinforcement zone).
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
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} formation → {spawnFormation} " +
                        $"(класс зрителя, конь={withHorse}, " +
                        $"позиция={(heroSpawnPos.HasValue ? "у своих/врага" : "зона подкреплений")})");

                    agent = Mission.Current.SpawnTroop(
                        new SimpleAgentOrigin(hero.CharacterObject),
                        isPlayerSide:        isPlayerSide,
                        hasFormation:        true,
                        spawnWithHorse:      withHorse,
                        isReinforcement:     !heroSpawnPos.HasValue,
                        formationTroopCount: 1,
                        formationTroopIndex: 0,
                        isAlarmed:           true,
                        wieldInitialWeapons: true,
                        // 2026-09-02 (1.4.8): параметра forceDismounted в SpawnTroop
                        // больше нет. Смысл он дублировал: стоял `!withHorse` при
                        // `spawnWithHorse: withHorse`. Удаление ничего не меняет.
                        initialPosition:     heroSpawnPos,
                        initialDirection:    heroSpawnDir,
                        formationIndex:      spawnFormation);
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
                            // Учёт боя зафиксировал сторону в OnAgentBuild, то
                            // есть ДО этой строки. Не сказать ему — награда за
                            // бой посчитается по стороне «до», и призванный
                            // врагом получит деньги за победу стримера
                            // (пост-стрим-триаж 31.07: 43 выплаты не в ту
                            // сторону за вечер).
                            BannerlordLink.Behaviors.KillRewardBehavior
                                .RefreshSide(username);
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

                // 2026-05-29 Stage 6 (BLT-RC22 pattern) — extended retinue guards.
                // BLT MissionHelpers.RetinueAllowed() = InSiegeMission OR
                // InFieldBattleMission. Everything else → no retinue (arena
                // practice, tournament, conversation, deployment, cutscene).
                //
                // У нас уже skip hideout. Добавляем arena (training arena в town):
                //   - LocationComplex.Current?.GetLocationWithId("arena") detection
                //   - Or simpler: MissionMode != Battle → no retinue
                //
                // Также Deployment / Conversation / CutScene / Replay через
                // MissionMode check (BLT block list pattern).
                bool retinueAllowed = true;
                string retinueBlockReason = null;
                try
                {
                    var m = Mission.Current;
                    if (m != null)
                    {
                        // Block 1: not in Battle mode (covers Conversation,
                        // Deployment, CutScene, Replay, etc.).
                        if (m.Mode != MissionMode.Battle && m.Mode != MissionMode.StartUp)
                        {
                            retinueAllowed = false;
                            retinueBlockReason = $"mode={m.Mode} (need Battle)";
                        }

                        // Block 2: Arena practice (training arena в town). Detection
                        // через CampaignMission Location.StringId == "arena".
                        try
                        {
                            var loc = CampaignMission.Current?.Location?.StringId;
                            if (loc == "arena")
                            {
                                retinueAllowed = false;
                                retinueBlockReason = "arena practice";
                            }
                        }
                        catch { /* CampaignMission may не loaded — fallthrough */ }
                    }
                }
                catch { /* defensive */ }

                if (!retinueAllowed && retinueIds != null && retinueIds.Count > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} retinue BLOCKED " +
                        $"({retinueBlockReason}) — skip {retinueIds.Count} troops");
                }

                if (inHideout && retinueIds != null && retinueIds.Count > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} hideout detected — " +
                        $"skip retinue ({retinueIds.Count} troops) для 8-limit");
                }

                // 2026-06-05 (BLT-parity) — свита спавнится ОДИН раз за бой.
                // Первый summon → герой+свита; повторные в ЭТОМ же бою → только
                // герой (BLTSummonBehavior: TimesSummoned==0 gate, упрощённо HashSet).
                bool retinueAlreadySpawned = false;
                try { retinueAlreadySpawned = BannerlordLink.Behaviors.RetinueSpawnTracker.Instance?.AlreadySpawned(username) ?? false; }
                catch { }
                if (retinueAlreadySpawned && retinueIds != null && retinueIds.Count > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn:{sideLabel}] @{username} retinue SKIP — " +
                        $"already spawned this battle (re-summon = hero only)");
                }

                if (retinueIds != null && retinueIds.Count > 0 && agent != null && !inHideout && retinueAllowed && !retinueAlreadySpawned)
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
                            // 2026-06-02 (BLT-parity POWER) — retinue HP×2 через
                            // OnAgentBuild: pending-флаг ВОКРУГ SpawnTroop, применит
                            // PowersMissionBehavior в build-хуке (тайминг не крашит,
                            // в отличие от старого inline post-spawn сеттера).
                            BannerlordLink.Behaviors.PowersMissionBehavior.PendingRetinueHpMult =
                                BannerlordLink.Behaviors.PowersMissionBehavior.RETINUE_HP_MULT;
                            Agent retinueAgent;
                            try
                            {
                                retinueAgent = Mission.Current.SpawnTroop(
                                    new SimpleAgentOrigin(troop),
                                    isPlayerSide:        isPlayerSide,
                                    hasFormation:        true,
                                    spawnWithHorse:      !SiegeForcesDismount() && troop.Equipment != null && troop.HasMount(),
                                    isReinforcement:     !spawnPos.HasValue,
                                    formationTroopCount: 1,
                                    formationTroopIndex: 0,
                                    isAlarmed:           true,
                                    wieldInitialWeapons: true,
                                    // 2026-09-02 (1.4.8): forceDismounted убран из
                                    // сигнатуры. Дублировал spawnWithHorse выше:
                                    // при SiegeForcesDismount()==true тот уже false.
                                    initialPosition:     spawnPos,
                                    initialDirection:    anchorDir);
                            }
                            finally
                            {
                                BannerlordLink.Behaviors.PowersMissionBehavior.PendingRetinueHpMult = 1f;
                            }
                            if (retinueAgent != null)
                            {
                                // 2026-05-29 (BLT RetinueDeathChance) — регистрируем
                                // войско свиты для ролла гибели в KillRewardBehavior.
                                BannerlordLink.Net.RetinueRegistry.Register(
                                    retinueAgent, username, troop.StringId);
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

                                // 2026-06-02 (BLT-parity POWER) — retinue HP×2 теперь
                                // в PowersMissionBehavior.OnAgentBuild через pending-флаг
                                // (выставлен вокруг SpawnTroop выше). Старый inline
                                // post-spawn сеттер (M13, dump 28004) удалён: краш был
                                // от ТАЙМИНГА мутации после build, не от сеттера —
                                // BLT (BLTSummonBehavior:309) делает идентичный *= и
                                // стабилен на 1.3.15; OnAgentBuild — санкционированный тайминг.

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
                    // Свита пришла не вся — сказать зрителю. Раньше это была
                    // только строка в логе: он платил за «героя со свитой» и не
                    // узнавал, что бойцов не нашлось (сборка заменила юнитов —
                    // сохранённые идентификаторы больше не резолвятся).
                    BannerlordLink.Util.ActionFeedback.PostPartial(
                        actionId, "свита", spawned, retinueIds.Count);
                    // 2026-06-05 — отметить ТОЛЬКО при реальном спавне (spawned>0):
                    // полный провал не блокирует повтор свиты в следующий summon.
                    if (spawned > 0)
                    {
                        try { BannerlordLink.Behaviors.RetinueSpawnTracker.Instance?.MarkSpawned(username); }
                        catch { }
                    }
                }
                BannerlordLink.Util.ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[player.spawn:{sideLabel}] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                BannerlordLink.Util.ActionFeedback.PostFailed(
                    actionId, "crashed:" + ex.GetType().Name);
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
                // 2026-06-06 — расширено: ВСЕ mission-типы БЕЗ reinforcement zone,
                // где engine SpawnTroop кидает "Nullable object must have a value"
                // → краш игры (повторялся 2× за день: @antitail/@linewolf51). Детект
                // по ИМЕНИ behavior'а (надёжнее typed generic — namespace меняется
                // между версиями TaleWorlds + не нужен лишний assembly-ref). Маркеры
                // (по BLT MissionHelpers, clean-room — только идея/API):
                //   Tournament    — TournamentFightMissionController (турнир)
                //   LordsHall     — LordsHallFightMissionController (штурм донжона)
                //   TrainingField — TrainingFieldMissionController (полигон)
                // Арена — отдельно ниже (детект по Location, имя без маркера).
                string[] noReinforcementMarkers = { "Tournament", "LordsHall", "TrainingField" };
                foreach (var b in m.MissionBehaviors)
                {
                    if (b == null) continue;
                    var n = b.GetType().Name;
                    foreach (var marker in noReinforcementMarkers)
                    {
                        if (n.IndexOf(marker, StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            BannerlordLinkModule.Log(
                                $"[player.spawn] blocked: {marker} mission (no reinforcement zone) " +
                                $"via {b.GetType().FullName}");
                            reason = $"{marker} mission (нет reinforcement zone → spawn crash)";
                            return false;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[player.spawn] tournament-detect warn: {ex.Message}");
            }

            // 2026-06-06 CRASH FIX — арена-практика (town training arena) ТОЖЕ без
            // reinforcement zone, но НЕ ловится tournament-гардом выше (другой
            // контроллер ArenaPracticeFightMissionController, имя без "Tournament").
            // Призыв туда → engine SpawnTroop кидает "Nullable object must have a
            // value" → КРАШ игры (managed-catch НЕ спасает: native agent уже частично
            // создан в SpawnPathFinder до throw). Детект как в retinue-блоке:
            // CampaignMission Location.StringId == "arena". (Лог: @antitail 20:13:37.)
            try
            {
                if (CampaignMission.Current?.Location?.StringId == "arena")
                {
                    reason = "arena practice (нет reinforcement zone → spawn crash)";
                    return false;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[player.spawn] arena-detect warn: {ex.Message}");
            }

            // 2026-06-11 CRASH FIX — catch-all: миссии БЕЗ reinforcement-spawn-логики
            // (город/деревня walk-around и пр.) проскакивают денилист по именам
            // (Tournament/Arena), а потом SpawnTroop(isReinforcement) кидает
            // "Nullable object must have a value" → краш (managed-catch не спасает,
            // native agent уже частично создан в SpawnPathFinder). Лог 21:29:17:
            // @slopkom призван в город Лагета. Реальные бои/осады имеют
            // MissionAgentSpawnLogic; не-боевые миссии — нет → требуем её наличие
            // (allowlist надёжнее денилиста; worst case — graceful refuse, не краш).
            // Детект по имени (как tournament-гард — без assembly-ref). Hideout
            // (Stealth) исключён: мод его явно разрешает (5.27m), его spawn-handling
            // отдельный — не трогаем.
            try
            {
                if (m.Mode != MissionMode.Stealth)
                {
                    bool hasSpawnLogic = false;
                    foreach (var b in m.MissionBehaviors)
                    {
                        // Bannerlord <=1.3.x used MissionAgentSpawnLogic directly;
                        // 1.4.8 registers DefaultBattleMissionAgentSpawnLogic.
                        // Accept both concrete names so real battles are not
                        // mistaken for town/arena walk-around missions.
                        string behaviorName = b?.GetType().Name;
                        if (behaviorName == "MissionAgentSpawnLogic"
                            || behaviorName == "DefaultBattleMissionAgentSpawnLogic")
                        {
                            hasSpawnLogic = true;
                            break;
                        }
                    }
                    if (!hasSpawnLogic)
                    {
                        BannerlordLinkModule.Log(
                            "[player.spawn] blocked: миссия без battle spawn logic " +
                            "(не боевая → нет reinforcement zone → SpawnTroop crash)");
                        reason = "не боевая миссия (нет зоны подкреплений → краш спавна)";
                        return false;
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[player.spawn] spawn-logic check warn: {ex.Message}");
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

        /// <summary>2026-05-29 Stage 5 (BLT-RC22 pattern) — Mission-context
        /// aware mount selection. Wraps ResolveWithHorse с guards для конкретных
        /// Mission types где cavalry должна быть dismounted независимо от class.
        ///
        /// Pattern из BLT-RC22 BLTSummonBehavior.cs:410-420 (ShouldBeMounted):
        ///   public static bool ShouldBeMounted(FormationClass formationClass)
        ///       => Mission.Current.Mode != MissionMode.Stealth
        ///          && !MissionHelpers.InSiegeMission()
        ///          && Mission.Current?.IsNavalBattle == false
        ///          && formationClass is Cavalry or LightCavalry or HeavyCavalry or HorseArcher;
        ///
        /// Why это важно:
        ///   - Siege: лошади бесполезны на стенах/в воротах. Engine SpawnTroop
        ///     может вернуть mount но всадник застрянет geometrically.
        ///   - Stealth (vanilla rare — escape sequences): mounted units выдают
        ///     position. Tactical fail.
        ///   - Naval: на корабле верхом не повоюешь (если что — лошади падают
        ///     за борт через physics).
        ///
        /// Без этого guard'а cavalry-class viewer в siege получает horse и:
        ///   - либо застревает (visible bug)
        ///   - либо engine крашится при попытке pathfind с mount в narrow geometry
        ///
        /// Naval check (IsNavalBattle) — для War Sails compat. В Bannerlord
        /// 1.3.15 без War Sails DLC всегда false.</summary>
        /// <summary>2026-07-20 (#37) — в осаде/на стенах верхом никто не сражается: на
        /// стены/лестницы на коне не залезть. У ГЕРОЯ это уже гейтил ShouldUseMount, а
        /// СВИТА спавнилась по troop.HasMount() без проверки → всадники на осаде (репорт).
        /// Общий гейт для retinue-спавна.</summary>
        private static bool SiegeForcesDismount()
        {
            try
            {
                var m = Mission.Current;
                return m != null && (m.IsSiegeBattle || m.Mode == MissionMode.Stealth);
            }
            catch { return false; }
        }

        private static bool ShouldUseMount(string username)
        {
            // Base: check class compatibility (existing logic).
            if (!ResolveWithHorse(username)) return false;

            var m = Mission.Current;
            if (m == null) return false;

            // Guard 1: Stealth mode — never mounted.
            if (m.Mode == MissionMode.Stealth)
            {
                BannerlordLinkModule.Log(
                    $"[player.spawn] @{username} cavalry-class → forced dismount (stealth mode)");
                return false;
            }

            // Guard 2: Siege battle — never mounted. Check IsSiegeBattle
            // напрямую (не через MissionHelpers — у нас нет того class'а).
            try
            {
                if (m.IsSiegeBattle)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn] @{username} cavalry-class → forced dismount (siege)");
                    return false;
                }
            }
            catch { /* IsSiegeBattle may not exist on all 1.3.x sub-versions */ }

            // Guard 3: Naval battle — never mounted. IsNavalBattle accessor
            // присутствует в Bannerlord 1.3.15 (returns false если no War Sails).
            try
            {
                if (m.IsNavalBattle)
                {
                    BannerlordLinkModule.Log(
                        $"[player.spawn] @{username} cavalry-class → forced dismount (naval)");
                    return false;
                }
            }
            catch { /* IsNavalBattle may не exist в strict 1.3.15 без DLC */ }

            return true;
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
                    // 2026-06-18 (Phase 1) — 12-class roster + legacy aliases.
                    case "archer":
                    case "crossbow":
                    case "heavy_archer":    // legacy
                    case "heavy_crossbow":  return FormationClass.Ranged;
                    case "horse_archer":
                    case "camel_archer":    return FormationClass.HorseArcher;
                    case "knight":
                    case "lancer":
                    case "cavalry":         // legacy
                    case "camel_cavalry":   return FormationClass.Cavalry;
                    case "tank":
                    case "berserk":
                    case "legionnaire":
                    case "assassin":
                    case "spearman":
                    case "maul":
                    case "skirmisher":
                    case "psycho":          // legacy
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
