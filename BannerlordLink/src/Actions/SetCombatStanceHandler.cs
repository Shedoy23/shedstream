using System;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// 2026-06-10 — `hero.set_combat_stance`. Зритель выбирает боевую стойку
    /// СВОЕГО бойца: defensive / balanced / aggressive. Сдвигает баланс
    /// блок/парри vs атака в боевом ИИ (см. PowersMissionBehavior.ApplyCombatAiTick).
    ///
    /// Бесплатно, мгновенно: обновляем PowerCache (применится на ближайшем
    /// 2с-тике) + эхо-пушим `combat_stance` в backend через player.state_update
    /// (для UI + перезагрузки стойки на рестарте игры через /class-state).
    ///
    /// data: { target, stance }
    /// </summary>
    public class SetCombatStanceHandler : IActionHandler
    {
        public string ActionType => "hero.set_combat_stance";

        private static bool IsValid(string s) =>
            s == "defensive" || s == "balanced" || s == "aggressive";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string stance = (data["stance"]?.ToString() ?? "").Trim().ToLowerInvariant();

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));
            if (!IsValid(stance))
                return Task.FromResult<(bool, string)>((false, "bad stance"));

            MainThreadDispatcher.Enqueue(() =>
            {
                PowerCache.UpdateHeroStance(username, stance);
                // HeroProfileBehavior owns a normal Dictionary read by SyncData;
                // keep all profile writes on the game thread.
                BannerlordLink.Behaviors.HeroProfileBehavior.Instance
                    ?.SetStance(username, stance);

                string json = JsonConvert.SerializeObject(new
                {
                    username = username,
                    combat_stance = stance,
                });
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
                            $"[set_combat_stance] echo @{username} failed: {ex.Message}");
                    }
                });

                BannerlordLinkModule.Log($"[set_combat_stance] @{username} → {stance}");
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
