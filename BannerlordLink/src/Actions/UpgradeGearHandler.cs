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
    /// `hero.upgrade_gear` — прокачка снаряжения по 6-tier системе.
    ///
    /// data: { target, class_key, target_tier }
    ///   class_key — текущий class viewer'а (передаётся backend'ом из БД).
    ///   target_tier — 1..6 (user-facing). Engine tier = target_tier - 1.
    ///
    /// Flow:
    ///   1. Skip если Mission.Current != null (battle equipment locked).
    ///   2. Resolve Hero, validate alive.
    ///   3. Для class.Slots[0..3] (weapons/shield/ammo) — replace на random
    ///      item типа slot[i] с Tier == engineTier (fallback на lower-tier
    ///      если пусто на target).
    ///   4. Armor slots (Head/Body/Leg/Gloves/Cape) — replace на random
    ///      ItemTypeEnum.*Armor с Tier == engineTier.
    ///   5. Horse + Harness если class.UseHorse/UseCamel.
    ///   6. HeroStateSync.Push — backend синкает новое equipment_changed.
    ///
    /// BLT inspired (EquipHero.cs UpgradeEquipment) — clean-room re-impl,
    /// наша class config + tier mapping отдельные.
    /// </summary>
    public class UpgradeGearHandler : IActionHandler
    {
        public string ActionType => "hero.upgrade_gear";

        // Slot config — параллель SetClassHandler._classes + M15 seed.
        // Дублирование оправдано — оба handler'а должны знать class spec.
        private class ClassConfig
        {
            public ItemObject.ItemTypeEnum[] Slots;
            public bool UseHorse;
            public bool UseCamel;
        }

        private static readonly Dictionary<string, ClassConfig> _classes =
            new Dictionary<string, ClassConfig>(StringComparer.OrdinalIgnoreCase)
        {
            ["tank"]            = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Shield, T.Invalid, T.Invalid } },
            ["archer"]          = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.Invalid, T.Invalid } },
            ["heavy_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.Shield, T.OneHandedWeapon } },
            ["crossbow"]        = new ClassConfig { Slots = new[] { T.Crossbow, T.Bolts, T.Invalid, T.Invalid } },
            ["heavy_crossbow"]  = new ClassConfig { Slots = new[] { T.Crossbow, T.Bolts, T.Shield, T.OneHandedWeapon } },
            ["cavalry"]         = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseHorse = true },
            ["camel_cavalry"]   = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseCamel = true },
            ["horse_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Invalid }, UseHorse = true },
            ["camel_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Invalid }, UseCamel = true },
            ["psycho"]          = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.Invalid, T.Invalid, T.Invalid } },
            ["berserk"]         = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.TwoHandedWeapon, T.Invalid, T.Invalid } },
            ["assassin"]        = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.OneHandedWeapon, T.Thrown, T.Invalid } },
            ["knight"]          = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Shield, T.Polearm, T.Invalid }, UseHorse = true },
        };

        private static class T
        {
            public const ItemObject.ItemTypeEnum OneHandedWeapon = ItemObject.ItemTypeEnum.OneHandedWeapon;
            public const ItemObject.ItemTypeEnum TwoHandedWeapon = ItemObject.ItemTypeEnum.TwoHandedWeapon;
            public const ItemObject.ItemTypeEnum Polearm = ItemObject.ItemTypeEnum.Polearm;
            public const ItemObject.ItemTypeEnum Bow = ItemObject.ItemTypeEnum.Bow;
            public const ItemObject.ItemTypeEnum Crossbow = ItemObject.ItemTypeEnum.Crossbow;
            public const ItemObject.ItemTypeEnum Arrows = ItemObject.ItemTypeEnum.Arrows;
            public const ItemObject.ItemTypeEnum Bolts = ItemObject.ItemTypeEnum.Bolts;
            public const ItemObject.ItemTypeEnum Thrown = ItemObject.ItemTypeEnum.Thrown;
            public const ItemObject.ItemTypeEnum Shield = ItemObject.ItemTypeEnum.Shield;
            public const ItemObject.ItemTypeEnum Horse = ItemObject.ItemTypeEnum.Horse;
            public const ItemObject.ItemTypeEnum HorseHarness = ItemObject.ItemTypeEnum.HorseHarness;
            public const ItemObject.ItemTypeEnum BodyArmor = ItemObject.ItemTypeEnum.BodyArmor;
            public const ItemObject.ItemTypeEnum HeadArmor = ItemObject.ItemTypeEnum.HeadArmor;
            public const ItemObject.ItemTypeEnum LegArmor = ItemObject.ItemTypeEnum.LegArmor;
            public const ItemObject.ItemTypeEnum HandArmor = ItemObject.ItemTypeEnum.HandArmor;
            public const ItemObject.ItemTypeEnum Cape = ItemObject.ItemTypeEnum.Cape;
            public const ItemObject.ItemTypeEnum Invalid = ItemObject.ItemTypeEnum.Invalid;
        }

        // EquipmentIndex'ы броневых слотов — порядок armor coverage (BLT pattern).
        private static readonly (EquipmentIndex idx, ItemObject.ItemTypeEnum type)[] ArmorSlots =
        {
            (EquipmentIndex.Head,   T.HeadArmor),
            (EquipmentIndex.Body,   T.BodyArmor),
            (EquipmentIndex.Leg,    T.LegArmor),
            (EquipmentIndex.Gloves, T.HandArmor),
            (EquipmentIndex.Cape,   T.Cape),
        };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string classKey = (data["class_key"]?.ToString() ?? "").Trim().ToLowerInvariant();
            int targetTier = (int?)data["target_tier"] ?? 0;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(classKey) || !_classes.ContainsKey(classKey))
                return Task.FromResult<(bool, string)>((false, $"unknown class '{classKey}'"));
            if (targetTier < 1 || targetTier > 6)
                return Task.FromResult<(bool, string)>((false, $"invalid target_tier {targetTier}"));

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => ApplyUpgrade(username, classKey, targetTier, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        // Tier costs in Hero.Gold (in-game динары). Source of truth — mod-side
        // экономика. Backend получает hero.gear_tier_changed event после
        // successful upgrade и обновляет DB cache.
        private static readonly Dictionary<int, int> HERO_GOLD_TIER_COSTS =
            new Dictionary<int, int>
        {
            [1] =    50_000,
            [2] =   100_000,
            [3] =   200_000,
            [4] =   400_000,
            [5] =   800_000,
            [6] = 1_500_000,
        };

        private static void ApplyUpgrade(string username, string classKey, int targetTier, string actionId)
        {
            try
            {
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[upgrade_gear] REFUSE @{username}: нельзя менять snar во время Mission");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[upgrade_gear] REFUSE @{username}: hero не найден или мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                int cost = HERO_GOLD_TIER_COSTS.TryGetValue(targetTier, out var c) ? c : 0;
                if (hero.Gold < cost)
                {
                    BannerlordLinkModule.Log(
                        $"[upgrade_gear] REFUSE @{username}: not enough hero gold ({hero.Gold} < {cost} для T{targetTier})");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                var cfg = _classes[classKey];
                int engineTier = targetTier - 1;   // 1-6 → 0-5
                var rng = new Random();
                var equipment = hero.BattleEquipment;
                int slotsFilled = 0, slotsSkipped = 0;

                // ── 1. Weapon slots по class config ──
                for (int i = 0; i < 4 && i < cfg.Slots.Length; i++)
                {
                    var slotType = cfg.Slots[i];
                    if (slotType == T.Invalid) continue;

                    var item = FindTieredItem(slotType, engineTier, rng);
                    if (item != null)
                    {
                        equipment[(EquipmentIndex)i] = new EquipmentElement(item);
                        slotsFilled++;
                    }
                    else slotsSkipped++;
                }

                // ── 2. Armor slots — всегда заполняем все 5 ──
                foreach (var (idx, type) in ArmorSlots)
                {
                    var item = FindTieredItem(type, engineTier, rng);
                    if (item != null)
                    {
                        equipment[idx] = new EquipmentElement(item);
                        slotsFilled++;
                    }
                    else slotsSkipped++;
                }

                // ── 3. Horse + Harness для mounted classes ──
                if (cfg.UseHorse || cfg.UseCamel)
                {
                    // Sprint 5.32 (BLT-parity M4) — family-type matching.
                    // Camel и Horse — разные mounts в TaleWorlds (Horse.ItemType,
                    // но с разными HorseComponent.Monster). Раньше FindTieredItem
                    // мог выбрать camel mount для horse-class или наоборот.
                    // Аналогично harness — camel harness не подходит к horse mount.
                    // Теперь: используем `name.Contains("camel")` matcher как в
                    // SetClassHandler (надёжнее чем HorseComponent.Monster lookup
                    // который иногда null для DLC mounts).
                    bool wantCamel = cfg.UseCamel;
                    System.Func<string, bool> mountFilter = wantCamel
                        ? (System.Func<string, bool>)(name => name.IndexOf("camel", StringComparison.OrdinalIgnoreCase) >= 0)
                        : (name => name.IndexOf("camel", StringComparison.OrdinalIgnoreCase) < 0);
                    var horse = FindTieredItem(T.Horse, engineTier, rng, mountFilter);
                    if (horse != null)
                    {
                        equipment[EquipmentIndex.Horse] = new EquipmentElement(horse);
                        slotsFilled++;
                    }
                    var harness = FindTieredItem(T.HorseHarness, engineTier, rng, mountFilter);
                    if (harness != null)
                    {
                        equipment[EquipmentIndex.HorseHarness] = new EquipmentElement(harness);
                        slotsFilled++;
                    }
                }

                // Списать Hero.Gold ПОСЛЕ apply equipment (atomic в-game).
                // GiveGoldAction.ApplyBetweenCharacters(giver, receiver, amount):
                // если первый аргумент null — взять gold из nowhere, отрицательный
                // amount = deduct из hero.
                int goldBefore = hero.Gold;
                GiveGoldAction.ApplyBetweenCharacters(hero, null, cost, true);
                BannerlordLinkModule.Log(
                    $"[upgrade_gear] @{username} → T{targetTier} ({classKey}): " +
                    $"{slotsFilled} slots filled, {slotsSkipped} not found, " +
                    $"gold {goldBefore} → {hero.Gold} (-{cost})");

                // Push hero.gear_tier_changed event — backend update'ит row.
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    gear_tier = targetTier,
                    cost_gold = cost,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.gear_tier_changed", evtData));

                // Full state sync — gold/level/etc. UI refresh.
                HeroStateSync.Push(hero);
                // Push equipment snapshot — 11 slots → backend bannerlord_equipment.
                EquipmentSync.PushAll(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[upgrade_gear] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        // Tier-aware item lookup. Сначала exact-tier match, потом fallback на
        // (tier-1), потом любой merchandise-item типа. Это страхует случаи
        // где pool sparse (e.g. T6 Bolts может не существовать).
        //
        // Sprint 5.32 (BLT-parity M4) — optional nameFilter predicate для
        // family-type matching (camel vs horse mount/harness).
        private static ItemObject FindTieredItem(
            ItemObject.ItemTypeEnum type, int engineTier, Random rng,
            System.Func<string, bool> nameFilter = null)
        {
            var pool = MBObjectManager.Instance
                .GetObjectTypeList<ItemObject>()
                ?.Where(i => i != null && i.ItemType == type)
                ?.Where(i => !i.NotMerchandise)
                ?.ToList();
            if (pool == null || pool.Count == 0) return null;

            // Apply name filter (camel/non-camel) если задан.
            if (nameFilter != null)
            {
                var filtered = pool
                    .Where(i => nameFilter(i.StringId ?? ""))
                    .ToList();
                if (filtered.Count > 0) pool = filtered;
                // если filter дал empty pool — fall through к unfiltered
                // (lieber camel-harness-on-horse чем пустой slot).
            }

            // exact tier
            var atTier = pool.Where(i => (int)i.Tier == engineTier).ToList();
            if (atTier.Count > 0) return atTier[rng.Next(atTier.Count)];

            // fallback: one tier below (BLT pattern, EquipHero.cs:279)
            var lower = pool.Where(i => (int)i.Tier == Math.Max(0, engineTier - 1)).ToList();
            if (lower.Count > 0) return lower[rng.Next(lower.Count)];

            // last resort: random из всего пула
            return pool[rng.Next(pool.Count)];
        }
    }
}
