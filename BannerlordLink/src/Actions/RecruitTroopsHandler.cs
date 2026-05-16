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
    /// `hero.recruit_troops` — BLT-style retinue recruit/upgrade.
    ///
    /// data: { target }
    /// Логика (BLT pattern, BLTAdoptAHeroCampaignBehavior.UpgradeRetinue):
    ///   1. Skip если Mission.Current != null (snar/retinue locked in battle).
    ///   2. Read retinue snapshot из game ?
    ///      У нас mod-side не хранит state — backend хранит в bannerlord_retinue.
    ///      Mod просто получает существующий retinue через action_data:
    ///        data.retinue = [{slot_index, troop_id, tier}, ...]
    ///      и решает что делать (add/upgrade).
    ///   3. Если len(retinue) < MAX_RETINUE (10):
    ///      • Pick basic troop из hero.Culture (BasicTroop)
    ///      • Hero.Gold cost = TIER_COSTS[0] = 5000
    ///      • Insert new slot
    ///   4. Else: upgrade lowest-tier troop:
    ///      • Find min tier in retinue
    ///      • CharacterObject.UpgradeTargets.SelectRandom() → new troop
    ///      • Cost = TIER_COSTS[tier]
    ///   5. Push event hero.retinue_changed {slots: [...]} → backend syncs.
    ///
    /// Hero.Gold cost (BLT defaults):
    ///   T0→T1: 5000, T1→T2: 10000, T2→T3: 20000, T3→T4: 30000, T4→T5: 50000
    /// </summary>
    public class RecruitTroopsHandler : IActionHandler
    {
        public string ActionType => "hero.recruit_troops";

        private const int MAX_RETINUE = 10;

        private static readonly int[] TIER_COSTS =
        {
            5_000,   // recruit (tier 0)
            10_000,  // upgrade tier 0 → 1
            20_000,  // tier 1 → 2
            30_000,  // tier 2 → 3
            50_000,  // tier 3 → 4
            80_000,  // tier 4 → 5
        };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            // Backend passes current retinue snapshot (из bannerlord_retinue).
            // Mod использует чтобы знать какие slots filled и какие troops upgrade'ить.
            var retinueJson = data["retinue"] as JArray;
            var existingSlots = new List<(int slot, string troopId, int tier)>();
            if (retinueJson != null)
            {
                foreach (var item in retinueJson)
                {
                    int slot = (int?)item["slot_index"] ?? -1;
                    string troopId = item["troop_id"]?.ToString();
                    int tier = (int?)item["tier"] ?? 0;
                    if (slot >= 0 && !string.IsNullOrEmpty(troopId))
                        existingSlots.Add((slot, troopId, tier));
                }
            }

            MainThreadDispatcher.Enqueue(() => Recruit(username, existingSlots));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Recruit(string username, List<(int slot, string troopId, int tier)> existing)
        {
            try
            {
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_troops] @{username}: skip — нельзя нанимать в Mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[recruit_troops] @{username}: hero не найден или мёртв");
                    return;
                }

                // Decide: add new troop OR upgrade existing?
                bool addNew = existing.Count < MAX_RETINUE;
                int tier = addNew ? 0 : existing.OrderBy(s => s.tier).First().tier;
                int cost = tier < TIER_COSTS.Length ? TIER_COSTS[tier] : TIER_COSTS[TIER_COSTS.Length - 1];

                if (hero.Gold < cost)
                {
                    BannerlordLinkModule.Log(
                        $"[recruit_troops] @{username}: not enough gold ({hero.Gold} < {cost}) " +
                        $"для {(addNew ? "recruit" : $"upgrade T{tier}")}");
                    return;
                }

                CharacterObject newTroop = null;
                int newTier = 0;
                int updatedSlot;

                if (addNew)
                {
                    // Basic troop из culture
                    var culture = hero.Culture;
                    if (culture?.BasicTroop == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops] @{username}: no BasicTroop для culture {culture?.StringId ?? "?"}");
                        return;
                    }
                    newTroop = culture.BasicTroop;
                    newTier = (int)newTroop.Tier;
                    updatedSlot = existing.Count;  // append
                }
                else
                {
                    // Upgrade lowest-tier troop. Find slot.
                    var slot = existing.OrderBy(s => s.tier).First();
                    var current = MBObjectManager.Instance.GetObject<CharacterObject>(slot.troopId);
                    if (current?.UpgradeTargets == null || current.UpgradeTargets.Length == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[recruit_troops] @{username}: troop {slot.troopId} has no UpgradeTargets " +
                            "(уже maxed)");
                        return;
                    }
                    var rng = new Random();
                    newTroop = current.UpgradeTargets[rng.Next(current.UpgradeTargets.Length)];
                    newTier = (int)newTroop.Tier;
                    updatedSlot = slot.slot;
                }

                // Deduct gold + push event
                GiveGoldAction.ApplyBetweenCharacters(hero, null, cost, true);
                BannerlordLinkModule.Log(
                    $"[recruit_troops] @{username}: {(addNew ? "recruited" : "upgraded")} " +
                    $"slot {updatedSlot} → {newTroop.StringId} T{newTier + 1} " +
                    $"(-{cost} dinars, gold={hero.Gold})");

                // Push event for backend update
                var payload = new
                {
                    username = username,
                    slot_index = updatedSlot,
                    troop_id = newTroop.StringId,
                    troop_name = newTroop.Name?.ToString() ?? newTroop.StringId,
                    tier = newTier,
                    action = addNew ? "recruit" : "upgrade",
                };
                string json = JsonConvert.SerializeObject(payload);
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.retinue_changed", json));

                // Full state sync — gold updated
                HeroStateSync.Push(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[recruit_troops] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }
    }
}
