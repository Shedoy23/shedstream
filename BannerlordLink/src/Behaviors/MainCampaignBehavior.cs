using System;
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
        public override void RegisterEvents()
        {
            CampaignEvents.HeroKilledEvent.AddNonSerializedListener(this, OnHeroKilled);
            CampaignEvents.HeroLevelledUp.AddNonSerializedListener(this, OnHeroLevelledUp);
            // M22: detect save switch — push session_start с real save_id
            // (Campaign.UniqueGameId per save).
            CampaignEvents.OnGameLoadFinishedEvent.AddNonSerializedListener(this, OnGameLoadFinished);
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

        // M22: при load campaign push session_start с real save_id
        // (Campaign.UniqueGameId — guid per save). Backend сравнивает с
        // last known для канала и reset'ит heroes если save_id изменился.
        private void OnGameLoadFinished()
        {
            try
            {
                string saveId = Campaign.Current?.UniqueGameId ?? "unknown";
                string evtData = JsonConvert.SerializeObject(new
                {
                    save_id = saveId,
                    mod_version = "0.1.0",
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "module.session_start", evtData));
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] OnGameLoadFinished: session_start pushed save_id={saveId}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] OnGameLoadFinished handler error: {ex.Message}");
            }
        }
    }
}
