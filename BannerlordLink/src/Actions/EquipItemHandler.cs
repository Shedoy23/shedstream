using System;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.1b — `player.equip_item` real handler (MVP).
    ///
    /// data: { target, item_id, slot? }
    ///   item_id — ItemObject.StringId (e.g. "imperial_long_sword_t3").
    ///   slot    — optional EquipmentIndex name; иначе авторезолв по ItemType.
    ///
    /// Логика:
    ///   1. Resolve hero через HeroLookup.FindByUsername
    ///   2. Resolve ItemObject через MBObjectManager (string ID lookup)
    ///   3. Determine target slot (infer from item.ItemType если не задан)
    ///   4. Apply: hero.BattleEquipment[idx] = new EquipmentElement(item)
    ///   5. Fire-and-forget hero.equipment_changed event на backend
    ///      (adapter уже обрабатывает — синкает bannerlord_equipment table)
    ///
    /// Out of scope (5.1c+):
    ///   • Item modifiers (lordly/masterwork) — BLT использует EquipmentElement(item, modifier)
    ///   • Auto-add компаньонные boots/gloves если изменили body armor
    ///   • Shop catalog auto-seeding (mod не пушит initial item list пока)
    ///   • Currency validation на сервере item.Value (backend сейчас принимает любой price)
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

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(itemId))
                return Task.FromResult<(bool, string)>((false, "no item_id"));

            MainThreadDispatcher.Enqueue(() => Equip(username, itemId, slotName));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Equip(string username, string itemId, string slotName)
        {
            try
            {
                Hero hero = HeroLookup.FindByUsername(username);
                if (hero == null)
                {
                    BannerlordLinkModule.Log($"[player.equip_item] @{username}: hero not found");
                    return;
                }

                ItemObject item = MBObjectManager.Instance.GetObject<ItemObject>(itemId);
                if (item == null)
                {
                    BannerlordLinkModule.Log(
                        $"[player.equip_item] @{username}: item_id '{itemId}' not in ObjectManager");
                    return;
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

                BannerlordLinkModule.Log(
                    $"[player.equip_item] @{username}: {item.Name} → slot {idx} (type={item.ItemType})");

                // Sync event на backend → bannerlord_equipment table обновится.
                PostEquipmentEventAsync(username, idx, item);
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
