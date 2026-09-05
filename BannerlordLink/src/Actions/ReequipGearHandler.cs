using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// `hero.reequip_gear` — «переформировать снаряжение» (BLT
    /// ReequipInsteadOfUpgrade). Ре-ролл ВСЕЙ снаряги на ТЕКУЩЕМ тире (без
    /// повышения) — фикс-утилита, когда экипировка «залипла»/кривая (пустые
    /// слоты, неподходящие предметы и т.п.). Работает в т.ч. на T6 ★MAX, где
    /// апгрейд уже недоступен.
    ///
    /// data: { target, class_key, gear_tier }  (gear_tier — user-facing 0..6,
    /// backend передаёт текущий из bannerlord_heroes, как в set_class).
    ///
    /// БЕСПЛАТНО (utility/fix, не повышает мощь — тот же тир). Переиспользует
    /// UpgradeGearHandler.ApplyGearLoadout: анти-дубль оружия + сохранение
    /// крафта/призов (ShouldReplaceSlot). Кампания-only (Mission guard).
    /// </summary>
    public class ReequipGearHandler : IActionHandler
    {
        public string ActionType => "hero.reequip_gear";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string classKey = (data["class_key"]?.ToString() ?? "").Trim().ToLowerInvariant();
            int gearTier = (int?)data["gear_tier"] ?? 0;
            if (gearTier < 0) gearTier = 0;
            if (gearTier > 6) gearTier = 6;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(classKey))
                return Task.FromResult<(bool, string)>((false, "no class_key"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Reequip(username, classKey, gearTier, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Reequip(string username, string classKey, int gearTier, string actionId)
        {
            try
            {
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[reequip_gear] REFUSE @{username}: нельзя менять snar во время Mission");
                    ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[reequip_gear] REFUSE @{username}: hero не найден / мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                int engineTier = Math.Max(0, gearTier - 1);   // 0..6 user → 0..5 engine
                int slotsFilled = UpgradeGearHandler.ApplyGearLoadout(hero, classKey, engineTier);

                BannerlordLinkModule.Log(
                    $"[reequip_gear] @{username} re-rolled at T{gearTier} ({classKey}): " +
                    $"{slotsFilled} slots (FREE — fix utility)");

                // Push equipment snapshot + state sync (UI refresh). Золото НЕ
                // трогаем — бесплатно.
                EquipmentSync.PushAll(hero);
                HeroStateSync.Push(hero);
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[reequip_gear] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
