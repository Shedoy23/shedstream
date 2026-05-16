using System;
using System.Threading.Tasks;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Push'ит full equipment snapshot hero'я на backend как серию событий
    /// `hero.equipment_changed`. Адаптер уже обрабатывает per-slot event —
    /// UPSERT в bannerlord_equipment / DELETE если item_id=null.
    ///
    /// Вызывается после mass-equipment changes:
    ///   • AdoptHeroHandler — после создания wanderer'а (template имеет
    ///     starting equipment, нужно sync)
    ///   • SetClassHandler — после apply class slots + armor + horse
    ///   • UpgradeGearHandler — после tier upgrade (replaces всё)
    ///
    /// Iter'ит 11 slots: Weapon0..3 + Head/Body/Leg/Gloves/Cape +
    /// Horse + HorseHarness. ExtraWeaponSlot опускаем (rarely used).
    /// Для пустых слотов пушим item_id=null → backend удалит старый row
    /// (важно после class change — старое armor могло остаться от
    /// предыдущего класса).
    /// </summary>
    public static class EquipmentSync
    {
        private static readonly EquipmentIndex[] SLOTS_TO_SYNC =
        {
            EquipmentIndex.Weapon0,
            EquipmentIndex.Weapon1,
            EquipmentIndex.Weapon2,
            EquipmentIndex.Weapon3,
            EquipmentIndex.Head,
            EquipmentIndex.Body,
            EquipmentIndex.Leg,
            EquipmentIndex.Gloves,
            EquipmentIndex.Cape,
            EquipmentIndex.Horse,
            EquipmentIndex.HorseHarness,
        };

        public static void PushAll(Hero hero)
        {
            if (hero == null || hero.Name == null) return;
            try
            {
                string username = hero.Name.ToString()?.ToLowerInvariant();
                if (string.IsNullOrEmpty(username)) return;

                var eq = hero.BattleEquipment;
                int filled = 0;
                foreach (var idx in SLOTS_TO_SYNC)
                {
                    var el = eq[idx];
                    string slotName = idx.ToString().ToLowerInvariant();

                    string itemId = null;
                    string itemName = null;
                    if (!el.IsEmpty && el.Item != null)
                    {
                        itemId = el.Item.StringId;
                        itemName = el.Item.Name?.ToString() ?? itemId;
                        filled++;
                    }

                    PostEquipmentEvent(username, slotName, itemId, itemName);
                }

                BannerlordLinkModule.Log(
                    $"[EquipmentSync] @{username}: pushed snapshot, {filled}/{SLOTS_TO_SYNC.Length} slots filled");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[EquipmentSync] PushAll @{hero?.Name} CRASHED: {ex.Message}");
            }
        }

        private static void PostEquipmentEvent(string username, string slotName,
            string itemId, string itemName)
        {
            var backend = BannerlordLinkModule.Backend;
            if (backend == null) return;

            // item_id=null → backend DELETE row (slot now empty).
            // JSON literal null для C# string null — пишем "null" без quotes.
            string idJson = itemId == null ? "null" : $"\"{EscapeJson(itemId)}\"";
            string nameJson = itemName == null ? "null" : $"\"{EscapeJson(itemName)}\"";

            string json = string.Format(
                "{{\"username\":\"{0}\",\"slot\":\"{1}\",\"item_id\":{2},\"item_name\":{3}}}",
                EscapeJson(username), EscapeJson(slotName), idJson, nameJson);

            Task.Run(async () =>
            {
                try
                {
                    await backend.PostEventAsync("bannerlord", "hero.equipment_changed", json);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[EquipmentSync] push @{username} slot={slotName} failed: {ex.Message}");
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
