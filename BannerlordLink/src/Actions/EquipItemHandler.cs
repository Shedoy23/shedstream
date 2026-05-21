using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// `player.equip_item` real handler.
    ///
    /// Sprint 5.1b: targeted equip — data: { target, item_id, slot? }.
    /// Sprint 5.1c: random equip — data: { target, random_category: weapon/armor/horse }.
    ///   Mod выбирает random ItemObject подходящего типа (high-tier filter)
    ///   и equip'ит. Backend gates по mounted-class для horse + price enforce.
    ///
    /// Логика:
    ///   1. Resolve hero через HeroLookup.FindByUsername
    ///   2. Resolve ItemObject:
    ///      • если item_id задан — MBObjectManager.GetObject<ItemObject>(item_id)
    ///      • если random_category задан — PickRandomItemByCategory
    ///   3. Determine target slot (infer from item.ItemType если не задан)
    ///   4. Apply: hero.BattleEquipment[idx] = new EquipmentElement(item)
    ///   5. Fire-and-forget hero.equipment_changed event на backend
    ///
    /// Out of scope (Sprint 5.2+):
    ///   • Item modifiers (lordly/masterwork)
    ///   • Auto-add компаньонные boots/gloves если изменили body armor
    ///   • Random pick по hero's class skill (archer → bow only)
    /// </summary>
    public class EquipItemHandler : IActionHandler
    {
        public string ActionType => "player.equip_item";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string itemId = (data["item_id"]?.ToString() ?? "").Trim();
            string slotName = data["slot"]?.ToString();
            string category = (data["random_category"]?.ToString() ?? "").Trim().ToLowerInvariant();

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(itemId) && string.IsNullOrEmpty(category))
                return Task.FromResult<(bool, string)>((false, "no item_id или random_category"));

            MainThreadDispatcher.Enqueue(() => Equip(username, itemId, slotName, category));
            return Task.FromResult<(bool, string)>((true, null));
        }

        // Hero.Gold prices для random_category (in-game динары, не крустики).
        // Mod-side enforced — backend price=0 в крустиках, fairness через
        // in-game экономику (зритель сначала копит динары через give_gold
        // action или внутри игры, потом тратит на random box).
        // Sprint 5.27o: повышены до T5–T6 уровня — random equip выдаёт
        // high-tier item, baseline должен соответствовать ценности.
        private static readonly System.Collections.Generic.Dictionary<string, int> HERO_GOLD_RANDOM_PRICES =
            new System.Collections.Generic.Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["weapon"] = 1_000_000,
            ["armor"]  =   500_000,
            ["horse"]  = 1_000_000,
        };

        private static void Equip(string username, string itemId, string slotName, string category)
        {
            try
            {
                Hero hero = HeroLookup.FindByUsername(username);
                if (hero == null)
                {
                    BannerlordLinkModule.Log($"[player.equip_item] @{username}: hero not found");
                    return;
                }

                ItemObject item;
                int heroGoldCost = 0;
                if (!string.IsNullOrEmpty(category))
                {
                    // Hero.Gold check — fairness через in-game экономику
                    if (HERO_GOLD_RANDOM_PRICES.TryGetValue(category, out int cost))
                    {
                        heroGoldCost = cost;
                        if (hero.Gold < cost)
                        {
                            BannerlordLinkModule.Log(
                                $"[player.equip_item] @{username}: not enough gold ({hero.Gold} < {cost}) " +
                                $"для random {category}");
                            return;
                        }
                    }

                    item = PickRandomItemByCategory(category);
                    if (item == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.equip_item] @{username}: random category '{category}' no items found");
                        return;
                    }
                    BannerlordLinkModule.Log(
                        $"[player.equip_item] @{username}: random {category} → '{item.StringId}' ({item.Name})");
                }
                else
                {
                    item = MBObjectManager.Instance.GetObject<ItemObject>(itemId);
                    if (item == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[player.equip_item] @{username}: item_id '{itemId}' not in ObjectManager");
                        return;
                    }
                }

                EquipmentIndex idx = ResolveSlot(item, slotName, hero);
                if (idx == EquipmentIndex.None)
                {
                    BannerlordLinkModule.Log(
                        $"[player.equip_item] @{username}: cannot determine slot для item " +
                        $"'{itemId}' (type={item.ItemType})");
                    return;
                }

                hero.BattleEquipment[idx] = new EquipmentElement(item);

                // Deduct Hero.Gold (только для random, не для targeted)
                if (heroGoldCost > 0)
                {
                    int before = hero.Gold;
                    GiveGoldAction.ApplyBetweenCharacters(hero, null, heroGoldCost, true);
                    BannerlordLinkModule.Log(
                        $"[player.equip_item] @{username}: {item.Name} → slot {idx}, " +
                        $"gold {before} → {hero.Gold} (-{heroGoldCost})");
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[player.equip_item] @{username}: {item.Name} → slot {idx} (type={item.ItemType})");
                }

                // Sync event на backend → bannerlord_equipment table обновится.
                PostEquipmentEventAsync(username, idx, item);
                // Hero state — gold update for UI
                if (heroGoldCost > 0)
                {
                    BannerlordLink.Util.HeroStateSync.Push(hero);
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[player.equip_item] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
            }
        }

        // Slot resolution: explicit slotName > infer by ItemType.
        // EquipmentIndex enum: Weapon0..3, Head, Body, Leg, Gloves, Cape,
        // Horse, HorseHarness, ExtraWeaponSlot. NumAllWeaponSlots = 4.
        private static EquipmentIndex ResolveSlot(ItemObject item, string slotName, Hero hero)
        {
            if (!string.IsNullOrEmpty(slotName) &&
                Enum.TryParse<EquipmentIndex>(slotName, ignoreCase: true, out var parsed))
            {
                return parsed;
            }

            switch (item.ItemType)
            {
                case ItemObject.ItemTypeEnum.HeadArmor:    return EquipmentIndex.Head;
                case ItemObject.ItemTypeEnum.BodyArmor:    return EquipmentIndex.Body;
                case ItemObject.ItemTypeEnum.LegArmor:     return EquipmentIndex.Leg;
                case ItemObject.ItemTypeEnum.HandArmor:    return EquipmentIndex.Gloves;
                case ItemObject.ItemTypeEnum.Cape:         return EquipmentIndex.Cape;
                case ItemObject.ItemTypeEnum.Horse:        return EquipmentIndex.Horse;
                case ItemObject.ItemTypeEnum.HorseHarness: return EquipmentIndex.HorseHarness;

                // Weapons & shields & ammo — пытаемся в первый пустой weapon-slot,
                // fallback на Weapon0 (overwrite primary).
                case ItemObject.ItemTypeEnum.OneHandedWeapon:
                case ItemObject.ItemTypeEnum.TwoHandedWeapon:
                case ItemObject.ItemTypeEnum.Polearm:
                case ItemObject.ItemTypeEnum.Bow:
                case ItemObject.ItemTypeEnum.Crossbow:
                case ItemObject.ItemTypeEnum.Thrown:
                case ItemObject.ItemTypeEnum.Shield:
                case ItemObject.ItemTypeEnum.Arrows:
                case ItemObject.ItemTypeEnum.Bolts:
                    return FindEmptyWeaponSlot(hero) ?? EquipmentIndex.Weapon0;

                default: return EquipmentIndex.None;
            }
        }

        private static EquipmentIndex? FindEmptyWeaponSlot(Hero hero)
        {
            for (int i = 0; i < (int)EquipmentIndex.NumAllWeaponSlots; i++)
            {
                var idx = (EquipmentIndex)i;
                if (hero.BattleEquipment[idx].IsEmpty) return idx;
            }
            return null;
        }

        // Sprint 5.1c: random item pick by broad category. High-tier filter
        // чтобы цены 0.5M-1.25M⦷ оправдались. Иначе viewer купил бы за миллион
        // и получил peasant-tier дубинку — нелепо.
        // Категории:
        //   weapon → OneHand/TwoHand/Polearm/Bow/Crossbow/Thrown/Shield
        //   armor  → BodyArmor/HeadArmor/LegArmor/HandArmor/Cape
        //   horse  → Horse
        private static readonly Dictionary<string, ItemObject.ItemTypeEnum[]> CATEGORY_MAP =
            new Dictionary<string, ItemObject.ItemTypeEnum[]>(StringComparer.OrdinalIgnoreCase)
            {
                ["weapon"] = new[]
                {
                    ItemObject.ItemTypeEnum.OneHandedWeapon,
                    ItemObject.ItemTypeEnum.TwoHandedWeapon,
                    ItemObject.ItemTypeEnum.Polearm,
                    ItemObject.ItemTypeEnum.Bow,
                    ItemObject.ItemTypeEnum.Crossbow,
                    ItemObject.ItemTypeEnum.Thrown,
                    ItemObject.ItemTypeEnum.Shield,
                },
                ["armor"] = new[]
                {
                    ItemObject.ItemTypeEnum.BodyArmor,
                    ItemObject.ItemTypeEnum.HeadArmor,
                    ItemObject.ItemTypeEnum.LegArmor,
                    ItemObject.ItemTypeEnum.HandArmor,
                    ItemObject.ItemTypeEnum.Cape,
                },
                ["horse"] = new[]
                {
                    ItemObject.ItemTypeEnum.Horse,
                },
            };

        private static ItemObject PickRandomItemByCategory(string category)
        {
            if (!CATEGORY_MAP.TryGetValue(category, out var allowedTypes)) return null;

            // MBObjectManager.Instance.GetObjectTypeList<ItemObject>() — все items в game. Filter by type + high tier.
            // Tier 4-5 чтобы цена оправдалась. Tier — enum (Tier1..Tier6).
            var candidates = MBObjectManager.Instance.GetObjectTypeList<ItemObject>()
                .Where(it => it != null)
                .Where(it => allowedTypes.Contains(it.ItemType))
                .Where(it => (int)it.Tier >= 4)        // Tier4 = high-tier
                .Where(it => !it.NotMerchandise)       // skip special/quest items
                .ToList();

            if (candidates.Count == 0)
            {
                // Fallback — relax tier filter (некоторые типы могут не иметь Tier4+)
                candidates = MBObjectManager.Instance.GetObjectTypeList<ItemObject>()
                    .Where(it => it != null)
                    .Where(it => allowedTypes.Contains(it.ItemType))
                    .Where(it => !it.NotMerchandise)
                    .ToList();
                if (candidates.Count == 0) return null;
            }

            int idx = MBRandom.RandomInt(0, candidates.Count);
            return candidates[idx];
        }

        // Fire-and-forget — backend's adapter._on_equipment_changed обновит
        // bannerlord_equipment table, frontend увидит при следующем poll'е.
        private static void PostEquipmentEventAsync(string username, EquipmentIndex idx, ItemObject item)
        {
            var backend = BannerlordLinkModule.Backend;
            if (backend == null) return;

            string slotStr = idx.ToString().ToLowerInvariant();
            string itemId = item.StringId;
            string itemName = item.Name?.ToString() ?? itemId;
            string json = string.Format(
                "{{\"username\":\"{0}\",\"slot\":\"{1}\",\"item_id\":\"{2}\",\"item_name\":\"{3}\"}}",
                EscapeJson(username), EscapeJson(slotStr),
                EscapeJson(itemId), EscapeJson(itemName));

            Task.Run(async () =>
            {
                try { await backend.PostEventAsync("bannerlord", "hero.equipment_changed", json); }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[player.equip_item] push event failed: {ex.Message}");
                }
            });
        }

        private static string EscapeJson(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }
}
