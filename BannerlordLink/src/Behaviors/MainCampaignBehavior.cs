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
            // Sprint 5.27h: hourly safety net — выкидывает [BLink] viewer-героев
            // которые залипли в MainParty после battle (fallback на случай если
            // KillRewardBehavior.OnEndMission не отработал — retreat / abort).
            CampaignEvents.HourlyTickEvent.AddNonSerializedListener(this, OnHourlyTick);
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
                string username = victim.Name.ToString().ToLowerInvariant();
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
                    $"[CampaignEvent] HeroKilled: {username} by {killerName} ({detail})");
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

        /// <summary>Sprint 5.27h: safety net для PartyRestore.
        /// Каждый час сканит MainParty.MemberRoster и выкидывает [BLink]
        /// viewer-героев, которые не принадлежат PlayerClan. Срабатывает
        /// когда KillRewardBehavior.OnEndMission пропустил restore
        /// (retreat, abort, crash mid-mission).</summary>
        private void OnHourlyTick()
        {
            try
            {
                // Skip если в активном Mission — не лезем в roster в бою.
                if (TaleWorlds.MountAndBlade.Mission.Current != null) return;

                var mainParty = TaleWorlds.CampaignSystem.Party.MobileParty.MainParty;
                var roster = mainParty?.MemberRoster;
                if (roster == null || roster.Count == 0) return;

                var playerClan = Clan.PlayerClan;
                int evicted = 0;

                // Iterate по copy чтобы не модифицировать во время enumeration.
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
                    // Только viewer-героев ([BLink] prefix).
                    if (hero.Name == null) continue;
                    string name = hero.Name.ToString();
                    if (!BannerlordLink.Util.HeroNaming.IsAdopted(name)) continue;
                    // Если hero реально принадлежит PlayerClan (companion / spouse
                    // стримера) — оставляем. Иначе выкидываем.
                    if (hero.Clan == playerClan) continue;

                    try
                    {
                        mainParty.Party.AddMember(ch, -1);
                        evicted++;
                        BannerlordLinkModule.Log(
                            $"[HourlyTick] evicted stuck @{name} from MainParty " +
                            $"(clan={hero.Clan?.Name?.ToString() ?? "?"})");
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[HourlyTick] evict {name} failed: {ex.Message}");
                    }
                }

                if (evicted > 0)
                {
                    BannerlordLinkModule.Log(
                        $"[HourlyTick] evicted {evicted} stuck viewer-heroes из MainParty");
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[HourlyTick] CRASHED: {ex.Message}");
            }
        }

        // M22: push session_start с real save_id (Campaign.UniqueGameId)
        // на КАЖДЫЙ save load. Backend сравнивает с last known save_id для
        // канала и reset'ит heroes если save_id изменился.
        private void OnGameLoadFinished() => PushSessionStart("game_load_finished");
        private void OnSessionLaunched(CampaignGameStarter starter)
            => PushSessionStart("session_launched");

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
