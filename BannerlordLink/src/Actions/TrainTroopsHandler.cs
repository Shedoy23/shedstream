using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// `hero.train_troops` — BLT-parity TrainingBehavior, адаптированная под нашу
    /// backend-свиту (bannerlord_retinue), а не MobileParty (у адоптнутого героя
    /// её обычно нет).
    ///
    /// «Тренировать свиту» = bulk-upgrade: ВСЕ слоты свиты, у которых есть
    /// UpgradeTargets, апаются на один тир за раз. All-or-nothing по золоту —
    /// если у героя хватает динаров на сумму апгрейдов всех апгрейдабельных
    /// слотов, апаем все и списываем сумму; иначе отказ (frontend показывает
    /// смету). Maxed-слоты (без UpgradeTargets) пропускаются.
    ///
    /// data: { target, retinue: [{slot_index, troop_id, tier, is_elite}, ...] }
    /// Per-slot цена — TIER_COSTS[tier] (×3 elite), как в RecruitTroopsHandler.
    /// Пушит hero.retinue_changed per upgraded slot → backend синкает.
    ///
    /// Логика апгрейда (UpgradeTargets, same-culture pref) зеркалит recruit_troops.
    /// </summary>
    public class TrainTroopsHandler : IActionHandler
    {
        public string ActionType => "hero.train_troops";

        // Mirror RecruitTroopsHandler.TIER_COSTS — цена апгрейда tier T → T+1.
        private static readonly int[] TIER_COSTS =
        {
            5_000, 10_000, 20_000, 30_000, 50_000, 80_000,
        };
        private const float ELITE_COST_MULTIPLIER = 3f;

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            var retinueJson = data["retinue"] as JArray;
            var slots = new List<(int slot, string troopId, int tier, bool isElite)>();
            if (retinueJson != null)
            {
                foreach (var item in retinueJson)
                {
                    int slot = (int?)item["slot_index"] ?? -1;
                    string troopId = item["troop_id"]?.ToString();
                    int tier = (int?)item["tier"] ?? 0;
                    bool slotElite = (bool?)item["is_elite"] ?? false;
                    if (slot >= 0 && !string.IsNullOrEmpty(troopId))
                        slots.Add((slot, troopId, tier, slotElite));
                }
            }

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Train(username, slots, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Train(string username,
            List<(int slot, string troopId, int tier, bool isElite)> slots, string actionId)
        {
            try
            {
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[train_troops] @{username}: skip — нельзя тренировать в Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[train_troops] @{username}: hero не найден / мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                if (slots.Count == 0)
                {
                    BannerlordLinkModule.Log($"[train_troops] @{username}: свита пуста");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "empty_retinue");
                    return;
                }

                var rng = new Random();
                // Plan: апгрейдабельные слоты + target + цена.
                var planned = new List<(int slot, CharacterObject target, int newTier, bool isElite, int cost)>();
                int totalCost = 0;
                foreach (var s in slots)
                {
                    var current = MBObjectManager.Instance.GetObject<CharacterObject>(s.troopId);
                    if (current?.UpgradeTargets == null || current.UpgradeTargets.Length == 0)
                        continue;   // maxed — пропускаем

                    // Same-culture pref (как в recruit) — апгрейд держит линейку героя.
                    var sameCulture = current.UpgradeTargets
                        .Where(t => t != null && t.Culture == hero.Culture).ToList();
                    var pool = sameCulture.Count > 0 ? sameCulture : current.UpgradeTargets.ToList();
                    if (pool.Count == 0) continue;
                    var target = pool[rng.Next(pool.Count)];
                    if (target == null) continue;

                    int baseCost = s.tier < TIER_COSTS.Length
                        ? TIER_COSTS[s.tier] : TIER_COSTS[TIER_COSTS.Length - 1];
                    int cost = s.isElite ? (int)(baseCost * ELITE_COST_MULTIPLIER) : baseCost;
                    planned.Add((s.slot, target, (int)target.Tier, s.isElite, cost));
                    totalCost += cost;
                }

                if (planned.Count == 0)
                {
                    BannerlordLinkModule.Log($"[train_troops] @{username}: вся свита уже maxed");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "all_maxed");
                    return;
                }
                if (hero.Gold < totalCost)
                {
                    BannerlordLinkModule.Log(
                        $"[train_troops] @{username}: not enough gold ({hero.Gold} < {totalCost}) " +
                        $"для тренировки {planned.Count} слотов");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                // Списать сумму одним списанием + апнуть все слоты.
                GiveGoldAction.ApplyBetweenCharacters(hero, null, totalCost, true);
                foreach (var p in planned)
                {
                    var payload = new
                    {
                        username = username,
                        slot_index = p.slot,
                        troop_id = p.target.StringId,
                        troop_name = p.target.Name?.ToString() ?? p.target.StringId,
                        tier = p.newTier,
                        is_elite = p.isElite,
                        action = "upgrade",
                    };
                    string json = JsonConvert.SerializeObject(payload);
                    Task.Run(async () => await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "hero.retinue_changed", json));
                }

                BannerlordLinkModule.Log(
                    $"[train_troops] @{username}: trained {planned.Count} slot(s) " +
                    $"(-{totalCost} dinars, gold={hero.Gold})");
                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[train_troops] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
