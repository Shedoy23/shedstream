using System;
using System.Threading.Tasks;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Helper для push'а full hero state на backend как `player.state_update` event.
    ///
    /// Sprint M19: расширяет state fields — gold + level + clan_name +
    /// kingdom_name + location + is_alive + is_prisoner. Дёргается из:
    ///   • AdoptHeroHandler — после adoption (initial state)
    ///   • SetClassHandler  — после class change (level/clan/kingdom могут
    ///     не меняться, но re-sync дешёвый, держит UI свежим)
    ///   • MainCampaignBehavior.OnHeroLevelledUp — level changed
    ///
    /// Backend whitelist (см. _adapter._on_player_state_update) принимает
    /// эти поля и UPDATE'ит bannerlord_heroes. Дополнительные поля игнорируются.
    ///
    /// Fire-and-forget — не блокирует main thread, ошибки log only.
    /// </summary>
    public static class HeroStateSync
    {
        public static void Push(Hero hero)
        {
            if (hero == null || hero.Name == null) return;
            try
            {
                string username = hero.Name.ToString()?.ToLowerInvariant();
                if (string.IsNullOrEmpty(username)) return;

                // Clan / Kingdom могут быть null (wanderer без клана / клан вне
                // королевства). Передаём явно null чтобы backend стёр поле
                // (e.g. heir после смерти лидера клана).
                string clanName = hero.Clan?.Name?.ToString();
                string kingdomName = hero.Clan?.Kingdom?.Name?.ToString();

                var payload = new
                {
                    username      = username,
                    hero_id       = hero.StringId,
                    gold          = hero.Gold,
                    level         = hero.Level,
                    is_alive      = hero.IsAlive ? 1 : 0,
                    is_prisoner   = hero.IsPrisoner ? 1 : 0,
                    location      = hero.CurrentSettlement?.Name?.ToString(),
                    clan_name     = clanName,
                    kingdom_name  = kingdomName,
                };
                string json = JsonConvert.SerializeObject(payload);

                Task.Run(async () =>
                {
                    try
                    {
                        await BannerlordLinkModule.Backend
                            .PostEventAsync("bannerlord", "player.state_update", json);
                    }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[HeroStateSync] push @{username} failed: {ex.Message}");
                    }
                });

                BannerlordLinkModule.Log(
                    $"[HeroStateSync] @{username} L{hero.Level} " +
                    $"gold={hero.Gold} clan={clanName ?? "—"} kingdom={kingdomName ?? "—"}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[HeroStateSync] CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
