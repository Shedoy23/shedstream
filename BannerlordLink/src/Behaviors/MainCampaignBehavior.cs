using System;
using System.Threading.Tasks;
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
            if (hero?.Name == null) return;

            try
            {
                string username = hero.Name.ToString().ToLowerInvariant();
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    hero_id = hero.StringId,
                    level = hero.Level,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "player.state_update", evtData));
                BannerlordLinkModule.Log(
                    $"[CampaignEvent] HeroLevelledUp: {username} → level {hero.Level}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[CampaignEvent] HeroLevelledUp handler error: {ex.Message}");
            }
        }
    }
}
