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

                // Sprint M22+: ALSO push heroes_snapshot — список имён всех
                // alive heroes в save (lowercase). Backend diff'ит с
                // bannerlord_heroes.username и удаляет rows которых нет
                // в snapshot. Точный per-hero existence check — лучше чем
                // save_id matching (UniqueGameId per-campaign, не per-save).
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
                var usernames = Campaign.Current.AliveHeroes
                    ?.Where(h => h?.Name != null)
                    .Select(h => h.Name.ToString()?.ToLowerInvariant())
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
                    $"[CampaignEvent] heroes_snapshot pushed: {usernames.Length} alive heroes");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] PushHeroesSnapshot error: {ex.Message}");
            }
        }
    }
}
