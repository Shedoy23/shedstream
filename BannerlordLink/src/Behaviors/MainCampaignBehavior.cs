using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Behaviors
{
    /// <summary>
    /// CampaignBehavior который подписан на ключевые CampaignEvents и
    /// шлёт соответствующие module envelopes на backend.
    ///
    /// Subscribed:
    ///   - HeroKilledEvent → player.died
    ///   - HeroLevelledUp  → player.state_update
    ///
    /// Filter strategy: posts events ДЛЯ ВСЕХ heroes (не только adopted).
    /// Backend сам матчит username с bannerlord_heroes таблицей — если
    /// match есть, update'ит row + audit log. Если нет — silent skip.
    /// Это упрощает mod (нет sync'а с backend о том кто adopted).
    ///
    /// Registered в BannerlordLinkModule.OnGameStart через
    /// CampaignGameStarter.AddBehavior.
    /// </summary>
    public class MainCampaignBehavior : CampaignBehaviorBase
    {
        // M22: dedupe push session_start между OnGameLoadFinished + OnSessionLaunched.
        // RimLink pattern — sync на каждый save load, не только при первом запуске
        // mod'a. OnGameLoadFinishedEvent fires только при first load (per Game
        // instance) — для switch save в одной session нужен OnSessionLaunched.
        private string _lastPushedSaveId;

        public override void RegisterEvents()
        {
            CampaignEvents.HeroKilledEvent.AddNonSerializedListener(this, OnHeroKilled);
            CampaignEvents.HeroLevelledUp.AddNonSerializedListener(this, OnHeroLevelledUp);
            // Multiple events для надёжности — каждый load save должен пушить
            // session_start. Dedupe by save_id (если тот же save reloaded —
            // backend сам skip reset).
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
            CampaignEvents.OnSessionLaunchedEvent.AddNonSerializedListener(this, OnSessionLaunched);
            // Sprint 5.27l: MapEventEnded — campaign-level event "битва завершилась".
            // BLT тоже использует (BLTAdoptAHeroCampaignBehavior:272). Триггерит
            // после ВСЕХ battle/raid/siege независимо от того сработал ли
            // MissionLogic.OnEndMission. Safe cleanup через BLT pattern
            // (EnterSettlementAction.ApplyForCharacterOnly).
            CampaignEvents.MapEventEnded.AddNonSerializedListener(this, OnMapEventEnded);

            // Sprint 5.32 (BLT-parity H5) — daily wounded-state sync.
            // M43 column `bannerlord_heroes.is_wounded` уже добавлена.
            // HeroStateSync.Push пушит `is_wounded = hero.IsWounded ? 1 : 0`.
            // Без daily tick wounded state менялось бы только когда viewer
            // покупает action — recovery (HP restore через несколько дней
            // engine'ом) не отражался бы в UI badge. DailyTickHero fires
            // per-hero — мы фильтруем только BLink (адопт'нутые) + push'им
            // когда IsWounded transition'ит. Это lightweight: ~50-200 viewers
            // × ~1 HTTP-PUSH per day = ничтожная нагрузка.
            CampaignEvents.DailyTickHeroEvent.AddNonSerializedListener(this, OnDailyTickHero);

            // Sprint 5.32 (BLT-parity M2) — heir queue foundation.
            // HeroComesOfAgeEvent fires когда engine продвигает child через 18-летний
            // порог. Если parent — adopted [BLink]-hero, мы пушим heir.came_of_age
            // event на backend → INSERT в bannerlord_heirs. Frontend получает список
            // через GET /api/bannerlord/heirs. Это foundation: на death героя backend
            // в будущем (M2.1) может pick first alive heir вместо random wanderer.
            CampaignEvents.HeroComesOfAgeEvent.AddNonSerializedListener(this, OnHeroComesOfAge);
            // Heir died ДО succession — UPDATE alive=0 в backend.
            CampaignEvents.HeroKilledEvent.AddNonSerializedListener(this, OnHeirMaybeDied);
        }

        private void OnHeroComesOfAge(Hero hero)
        {
            try
            {
                if (hero == null || hero.Father == null && hero.Mother == null) return;
                // Find parent who is [BLink]-hero.
                Hero parent = null;
                if (hero.Father != null && hero.Father.Name != null
                    && BannerlordLink.Util.HeroNaming.IsAdopted(hero.Father.Name.ToString()))
                {
                    parent = hero.Father;
                }
                else if (hero.Mother != null && hero.Mother.Name != null
                    && BannerlordLink.Util.HeroNaming.IsAdopted(hero.Mother.Name.ToString()))
                {
                    parent = hero.Mother;
                }
                if (parent == null) return;
                string parentName = parent.Name.ToString();
                string parentUsername = BannerlordLink.Util.HeroNaming.ExtractUsername(parentName);
                if (string.IsNullOrEmpty(parentUsername)) return;

                string heirName = hero.Name?.ToString() ?? hero.StringId;
                BannerlordLinkModule.Log(
                    $"[heir M2] @{parentUsername}: child '{heirName}' came of age " +
                    $"(heir_id={hero.StringId})");

                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    parent_username = parentUsername,
                    heir_hero_id    = hero.StringId,
                    heir_name       = heirName,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.heir_came_of_age", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[heir M2] OnHeroComesOfAge warn: {ex.Message}");
            }
        }

        private void OnHeirMaybeDied(Hero victim, Hero killer,
            KillCharacterAction.KillCharacterActionDetail detail,
            bool showNotification)
        {
            // M2 heir.died — push event только если victim — heir одного из adopted
            // heroes. Backend проверит UNIQUE constraint, если heir_id не в bannerlord_heirs
            // — silent no-op (это обычный NPC death).
            try
            {
                if (victim == null) return;
                // Если у victim сам [BLink] — это primary hero death, отдельный flow.
                if (victim.Name != null
                    && BannerlordLink.Util.HeroNaming.IsAdopted(victim.Name.ToString()))
                    return;
                // Check если родитель [BLink].
                bool parentIsAdopted =
                    (victim.Father?.Name != null
                     && BannerlordLink.Util.HeroNaming.IsAdopted(victim.Father.Name.ToString()))
                    || (victim.Mother?.Name != null
                        && BannerlordLink.Util.HeroNaming.IsAdopted(victim.Mother.Name.ToString()));
                if (!parentIsAdopted) return;

                BannerlordLinkModule.Log(
                    $"[heir M2] heir died: heir_id={victim.StringId} " +
                    $"({victim.Name?.ToString() ?? "?"}) detail={detail}");
                string evtData = Newtonsoft.Json.JsonConvert.SerializeObject(new
                {
                    heir_hero_id = victim.StringId,
                });
                System.Threading.Tasks.Task.Run(async () =>
                    await BannerlordLinkModule.Backend.PostEventAsync(
                        "bannerlord", "hero.heir_died", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[heir M2] OnHeirMaybeDied warn: {ex.Message}");
            }
        }

        // Sprint 5.32 (BLT-parity H5) — track последнее pushed IsWounded
        // состояние per hero чтобы push'ить ТОЛЬКО при изменении. Без
        // этого был бы daily POST для каждого viewer'а каждый день
        // (ненужный шум в backend log + 0 информации).
        private static readonly System.Collections.Generic.Dictionary<string, bool>
            _lastPushedWoundedState = new System.Collections.Generic.Dictionary<string, bool>();

        private void OnDailyTickHero(Hero hero)
        {
            try
            {
                if (hero == null || !hero.IsAlive) return;
                // Только BLink-герои.
                if (hero.Name == null) return;
                string name = hero.Name.ToString();
                if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) return;

                bool currentWounded;
                try { currentWounded = hero.IsWounded; }
                catch { return; }  // старая версия игры без IsWounded — skip

                string key = hero.StringId;
                bool needPush = false;
                if (!_lastPushedWoundedState.TryGetValue(key, out bool last))
                {
                    needPush = true;  // first observation
                }
                else if (last != currentWounded)
                {
                    needPush = true;
                    BannerlordLinkModule.Log(
                        $"[DailyTickHero H5] @{name}: wounded transition " +
                        $"{last} → {currentWounded}");
                }
                if (needPush)
                {
                    _lastPushedWoundedState[key] = currentWounded;
                    BannerlordLink.Util.HeroStateSync.Push(hero);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[DailyTickHero H5] @{hero?.Name?.ToString() ?? "?"}: warn {ex.Message}");
            }
        }

        public override void SyncData(IDataStore dataStore)
        {
            // Stateless — нечего сохранять между сессиями save game.
        }

        private void OnHeroKilled(Hero victim, Hero killer, KillCharacterAction.KillCharacterActionDetail detail, bool showNotification)
        {
            if (victim?.Name == null) return;

            try
            {
                // Sprint 5.31 #45e (audit MED-3) — раньше отправляли username =
                // raw Name.ToString() для ВСЕХ умерших heroes. Для не-adopted
                // это были localised vanilla имена ("Raganvad" и т.п.) — backend
                // не находил matching row в bannerlord_heroes, event тратился
                // впустую. Plus для adopted: full "[BLink] viewer" вместо
                // чистого username. Теперь ExtractUsername + skip non-adopted.
                string username = BannerlordLink.Util.HeroNaming
                    .ExtractUsername(victim.Name.ToString());
                if (string.IsNullOrEmpty(username))
                {
                    // Non-adopted hero — не наш viewer, событие не пушим.
                    return;
                }
                username = username.ToLowerInvariant();
                string killerName = killer?.Name?.ToString() ?? "unknown";
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    hero_id = victim.StringId,
                    killer_name = killerName,
                    detail = detail.ToString(),
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "player.died", evtData));
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] HeroKilled: @{username} by {killerName} ({detail})");
                // Sprint 5.32 — force-push HeroStateSync чтобы is_alive=0 пришёл
                // в backend сразу (без ожидания следующего periodic sync).
                // Иначе viewer мог видеть "жив" до 8s polling tick.
                try { BannerlordLink.Util.HeroStateSync.Push(victim); }
                catch (Exception syncEx)
                {
                    BannerlordLinkModule.Log(
                        $"[CampaignEvent] HeroKilled HeroStateSync push failed: {syncEx.Message}");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[CampaignEvent] HeroKilled handler error: {ex.Message}");
            }
        }

        private void OnHeroLevelledUp(Hero hero, bool shouldNotify)
        {
            // Sprint M19: вместо inline {username, level} пушим полный snapshot —
            // backend получит level + случайно изменившийся clan/kingdom/gold/etc.
            HeroStateSync.Push(hero);
            BannerlordLinkModule.Log(
                $"[CampaignEvent] HeroLevelledUp: {hero?.Name?.ToString()} → " +
                $"level {hero?.Level} (full state pushed)");
        }

        /// <summary>Sprint 5.27l: cleanup viewer-героев из MainParty после
        /// КАЖДОГО боя (CampaignEvents.MapEventEnded — fires после battle/raid/
        /// siege с campaign-уровня, независимо от того сработал MissionLogic.
        /// OnEndMission или нет).
        ///
        /// BLT pattern: AddToCounts(-curCount) + EnterSettlementAction в
        /// HomeSettlement → нет phantom-reference → MainParty инварианты
        /// сохранены.</summary>
        private void OnMapEventEnded(TaleWorlds.CampaignSystem.MapEvents.MapEvent ev)
        {
            try
            {
                // Skip если в активном Mission — engine ещё разбирается с
                // post-battle UI (loot, party screen). Защита от race condition.
                if (TaleWorlds.MountAndBlade.Mission.Current != null) return;

                var mainParty = TaleWorlds.CampaignSystem.Party.MobileParty.MainParty;
                var roster = mainParty?.MemberRoster;
                if (roster == null || roster.Count == 0) return;

                var playerClan = Clan.PlayerClan;
                int evicted = 0;

                // Snapshot перед modification (избежать collection-modified).
                var snapshot = new System.Collections.Generic.List<TaleWorlds.CampaignSystem.Roster.TroopRosterElement>();
                for (int i = 0; i < roster.Count; i++)
                {
                    snapshot.Add(roster.GetElementCopyAtIndex(i));
                }

                foreach (var slot in snapshot)
                {
                    var ch = slot.Character;
                    if (ch == null || !ch.IsHero) continue;
                    var hero = ch.HeroObject;
                    if (hero == null) continue;
                    // Гард #1: never touch MainHero.
                    if (hero == Hero.MainHero) continue;
                    // Гард #2: only [BLink] viewer-heroes.
                    if (hero.Name == null) continue;
                    string name = hero.Name.ToString();
                    if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) continue;
                    // Гард #3: companion / spouse в PlayerClan — оставляем.
                    if (hero.Clan == playerClan) continue;

                    // Safe eviction (BLT pattern):
                    //   1) Check current count, skip if already 0.
                    //   2) AddToCounts(-curCount) — атомарно в roster.
                    //   3) EnterSettlementAction → дать hero legit home.
                    int curCount = 0;
                    try { curCount = roster.GetTroopCount(ch); } catch { }
                    if (curCount <= 0) continue;

                    try
                    {
                        roster.AddToCounts(ch, -curCount);

                        var home = hero.HomeSettlement;
                        if (home == null)
                        {
                            // Fallback: any town in map.
                            try
                            {
                                home = TaleWorlds.CampaignSystem.Settlements.Settlement.All
                                    ?.Where(s => s != null && s.IsTown)
                                    .FirstOrDefault();
                            }
                            catch { }
                        }
                        if (home != null)
                        {
                            try
                            {
                                EnterSettlementAction.ApplyForCharacterOnly(hero, home);
                            }
                            catch { }
                        }
                        evicted++;
                        BannerlordLinkModule.Log(
                            $"[MapEventEnded] evicted @{name} from MainParty " +
                            $"(clan={hero.Clan?.Name?.ToString() ?? "?"}, " +
                            $"home={home?.Name?.ToString() ?? "—"})");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[MapEventEnded] evict {name} failed: {ex.Message}");
                    }
                }

                if (evicted > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[MapEventEnded] cleaned {evicted} viewer-heroes из MainParty " +
                        $"after battle ({ev?.EventType.ToString() ?? "?"})");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[MapEventEnded] CRASHED: {ex.Message}");
            }
        }

        // M22: push session_start с real save_id (Campaign.UniqueGameId)
        // на КАЖДЫЙ save load. Backend сравнивает с last known save_id для
        // канала и reset'ит heroes если save_id изменился.
        // Sprint 5.28: + repair MainParty roster если негативный count.
        private void OnGameLoadFinished()
        {
            RepairNegativeRoster();
            PushSessionStart("game_load_finished");
        }
        private void OnSessionLaunched(CampaignGameStarter starter)
        {
            RepairNegativeRoster();
            PushSessionStart("session_launched");
        }

        /// <summary>Sprint 5.28: repair MainParty roster от последствий старых багов:
        ///
        /// 1) NEGATIVE counts — `RestorePartyMembership` делал безусловный
        ///    AddMember(-1) для уже-ушедших героев, уводя count ниже 0.
        ///    Юзер: «Войны готовые к битве -36/101».
        ///
        /// 2) DUPLICATE hero counts — `SummonHero` делал безусловный +1 при
        ///    каждом призыве, даже если hero уже в MainParty. После N summon'ов
        ///    одного viewer'а его count = N. Юзер: «17 дублей kuro_gothic».
        ///
        /// Heroes (NOT regular troops!) с count > 1 схлопываем в 1 (если в
        /// PlayerClan) или в 0 (если adopted-but-not-clan).
        /// Regular troops с positive count — не трогаем, нормальное состояние.
        ///
        /// Запускается раз на сессию (load / session launch).</summary>
        private static void RepairNegativeRoster()
        {
            try
            {
                var mainParty = TaleWorlds.CampaignSystem.Party.MobileParty.MainParty;
                var roster = mainParty?.MemberRoster;
                if (roster == null || roster.Count == 0) return;

                int fixedNegatives = 0;
                int totalDeficit = 0;
                int fixedDupes = 0;
                int totalExcess = 0;

                // Snapshot перед modification (избежать collection-modified).
                var snapshot = new System.Collections.Generic.List<TaleWorlds.CampaignSystem.Roster.TroopRosterElement>();
                for (int i = 0; i < roster.Count; i++)
                {
                    snapshot.Add(roster.GetElementCopyAtIndex(i));
                }

                var playerClan = Clan.PlayerClan;

                foreach (var slot in snapshot)
                {
                    var ch = slot.Character;
                    if (ch == null) continue;

                    // === Case 1: negative count (применимо ко всем) ===
                    if (slot.Number < 0)
                    {
                        int deficit = slot.Number;
                        try
                        {
                            roster.AddToCounts(ch, -deficit);
                            fixedNegatives++;
                            totalDeficit += deficit;
                            BannerlordLinkModule.Log(
                                $"[RosterRepair] cleared negative '{ch.StringId}' ({deficit} → 0)");
                        }
                        catch (Exception ex)
                        {
                            BannerlordLinkModule.Log(
                                $"[RosterRepair] negative fix {ch.StringId} failed: {ex.Message}");
                        }
                        continue;
                    }

                    // === Case 2: hero dupes (только для heroes!) ===
                    // Heroes должны быть count=1 в clan party, count=0 иначе.
                    // Troops с count > 1 — нормальные виды войск, не трогаем.
                    if (!ch.IsHero || ch.HeroObject == null) continue;
                    if (slot.Number <= 1) continue;

                    int targetCount = (ch.HeroObject.Clan == playerClan) ? 1 : 0;
                    int excess = slot.Number - targetCount;
                    if (excess <= 0) continue;

                    try
                    {
                        roster.AddToCounts(ch, -excess);
                        fixedDupes++;
                        totalExcess += excess;
                        BannerlordLinkModule.Log(
                            $"[RosterRepair] collapsed hero '{ch.HeroObject.Name?.ToString() ?? ch.StringId}' " +
                            $"({slot.Number} → {targetCount}, removed {excess} dupes)");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[RosterRepair] dupe fix {ch.StringId} failed: {ex.Message}");
                    }
                }

                if (fixedNegatives > 0 || fixedDupes > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[RosterRepair] done — negatives:{fixedNegatives} (deficit={totalDeficit}), " +
                        $"hero-dupes:{fixedDupes} (excess={totalExcess})");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[RosterRepair] CRASHED: {ex.Message}");
            }
        }

        private void PushSessionStart(string trigger)
        {
            try
            {
                string saveId = Campaign.Current?.UniqueGameId ?? "unknown";
                if (string.Equals(saveId, _lastPushedSaveId, StringComparison.Ordinal))
                {
                    // Тот же save повторно — пропускаем чтобы не спамить backend.
                    return;
                }
                _lastPushedSaveId = saveId;

                string evtData = JsonConvert.SerializeObject(new
                {
                    save_id = saveId,
                    trigger = trigger,
                    mod_version = "0.1.0",
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "module.session_start", evtData));
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] {trigger}: session_start pushed save_id={saveId}");

                // Sprint M22+: heroes_snapshot после ОПЦИОНАЛЬНОЙ миграции
                // legacy hero names → [BLink] prefix (для backwards-compat).
                MigrateLegacyHeroNames();
                IntroduceAdoptedHeroes();
                PushHeroesSnapshot(saveId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] PushSessionStart({trigger}) error: {ex.Message}");
            }
        }

        private void PushHeroesSnapshot(string saveId)
        {
            try
            {
                if (Campaign.Current == null) return;
                // Filter ТОЛЬКО adopted heroes ([BLink] prefix). 2000 vanilla
                // heroes → ~5-50 adopted. Backend ожидает lowercase logins
                // (без [BLink] prefix) — HeroNaming.ExtractUsername делает это.
                var usernames = Campaign.Current.AliveHeroes
                    ?.Where(h => h?.Name != null
                        && BannerlordLink.Util.HeroNaming.IsAdopted(h.Name.ToString()))
                    .Select(h => BannerlordLink.Util.HeroNaming.ExtractUsername(h.Name.ToString()))
                    .Where(n => !string.IsNullOrEmpty(n))
                    .Distinct()
                    .ToArray() ?? new string[0];

                string evtData = JsonConvert.SerializeObject(new
                {
                    save_id = saveId,
                    usernames = usernames,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "module.heroes_snapshot", evtData));
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] heroes_snapshot pushed: {usernames.Length} adopted heroes " +
                    $"(filter: [BLink] prefix only)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] PushHeroesSnapshot error: {ex.Message}");
            }
        }

        /// <summary>
        /// One-time migration: existing adopted heroes (имя совпадает с
        /// known viewer username из PowerCache) получают [BLink] prefix
        /// если они без него. Это нужно для smooth transition после
        /// deploy этого fix'а — heroes в старых save'ах не имеют префикса.
        /// </summary>
        private void MigrateLegacyHeroNames()
        {
            try
            {
                if (Campaign.Current?.AliveHeroes == null) return;
                var known = BannerlordLink.Net.PowerCache.GetAllUsernames();
                if (known == null || known.Length == 0) return;

                int migrated = 0;
                foreach (var username in known)
                {
                    // Match exactly old name = username (без prefix).
                    var hero = Campaign.Current.AliveHeroes.FirstOrDefault(h =>
                        h?.Name != null
                        && !BannerlordLink.Util.HeroNaming.IsAdopted(h.Name.ToString())
                        && string.Equals(h.Name.ToString(), username,
                            StringComparison.OrdinalIgnoreCase));
                    if (hero == null) continue;

                    var (full, first) = BannerlordLink.Util.HeroNaming.Format(username);
                    hero.SetName(full, first);
                    migrated++;
                    BannerlordLinkModule.Log(
                        $"[NameMigration] @{username} → {BannerlordLink.Util.HeroNaming.PREFIX}{username}");
                }
                if (migrated > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[NameMigration] {migrated} legacy hero(es) renamed with [BLink] prefix");
                }

                // Cleanup orphan opaque IDs ([BLink] u_xxx, [BLink] u7sm4o...) —
                // creats до фикса JWT auth. Strip [BLink] prefix → они становятся
                // обычными wanderers, выпадают из heroes_snapshot filter.
                CleanupOpaqueHeroes();
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[NameMigration] error: {ex.Message}");
            }
        }

        /// <summary>
        /// Sprint 5.16: retroactive introduction. Все alive [BLink] heroes,
        /// созданные до фикса 5.16, не имеют HasMet=true → отображаются как
        /// "Unknown wanderer" у стримера. На каждом session_start вызываем
        /// SetHasMet() для всех adopted heroes — idempotent (engine просто
        /// re-set'ит boolean, безболезненно).
        /// </summary>
        private void IntroduceAdoptedHeroes()
        {
            try
            {
                if (Campaign.Current?.AliveHeroes == null) return;
                int introduced = 0;
                foreach (var hero in Campaign.Current.AliveHeroes.ToList())
                {
                    if (hero?.Name == null) continue;
                    if (!BannerlordLink.Util.HeroNaming.IsAdopted(hero.Name.ToString())) continue;
                    if (hero.HasMet) continue;   // skip — уже introduced
                    try
                    {
                        hero.SetHasMet();
                        introduced++;
                    }
                    catch { }
                }
                if (introduced > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[Introduce] {introduced} adopted hero(es) marked HasMet=true " +
                        "(retroactive)");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[Introduce] error: {ex.Message}");
            }
        }

        /// <summary>
        /// Sprint 5.3c: detect и развенчать (un-adopt) opaque-ID героев —
        /// `[BLink] u7sm4o56sut9pgnkuobvh`, `[BLink] u_tehzvsseaya8blbpepk` и т.п.
        /// Они появились из-за JWT auth бага (fixed 2026-05-17). Strip prefix
        /// → герой становится обычным wanderer, не светится в extension.
        /// </summary>
        private static readonly System.Text.RegularExpressions.Regex _opaqueRx =
            new System.Text.RegularExpressions.Regex(
                @"^u[a-z0-9_-]{15,}$",
                System.Text.RegularExpressions.RegexOptions.Compiled);

        private void CleanupOpaqueHeroes()
        {
            try
            {
                if (Campaign.Current?.AliveHeroes == null) return;

                int cleaned = 0;
                foreach (var hero in Campaign.Current.AliveHeroes.ToList())
                {
                    if (hero?.Name == null) continue;
                    string name = hero.Name.ToString();
                    if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) continue;
                    string viewerLogin = BannerlordLink.Util.HeroNaming
                        .ExtractUsername(name);
                    if (string.IsNullOrEmpty(viewerLogin)) continue;
                    // длинный + начинается с 'u' + base64url chars → opaque
                    if (!_opaqueRx.IsMatch(viewerLogin)) continue;

                    // Развенчать: убрать [BLink] prefix чтобы выпал из snapshot
                    // filter. Имя оставляем (game world references invariant).
                    var newFirst = new TaleWorlds.Localization.TextObject(
                        $"Orphan_{viewerLogin.Substring(0, System.Math.Min(8, viewerLogin.Length))}");
                    hero.SetName(newFirst, newFirst);
                    cleaned++;
                    BannerlordLinkModule.Log(
                        $"[CleanupOpaque] un-adopted orphan: {name} → {newFirst}");
                }
                if (cleaned > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[CleanupOpaque] {cleaned} opaque hero(es) un-adopted");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[CleanupOpaque] error: {ex.Message}");
            }
        }
    }
}
