using System;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Push'ит full equipment snapshot hero'я на backend через
    /// `hero.equipment_changed` event per-slot. Backend handler делает
    /// UPSERT в bannerlord_equipment / DELETE если item_id=null.
    ///
    /// Payload per item (M21):
    ///   • item_id, item_name — basic identification
    ///   • tier (0-5 → UI T1-T6)
    ///   • item_value — base game price
    ///   • weight
    ///   • stats_json — per-type stats:
    ///     • weapon: {swing_dmg, swing_spd, thrust_dmg, thrust_spd, length,
    ///                swing_type, thrust_type, accuracy, missile_spd, stack}
    ///     • armor:  {head, body, leg, arm}
    ///     • horse:  {speed, charge, maneuver, hp}
    ///     • other:  {} (shield, ammo display только name+tier)
    ///
    /// Iter'ит 11 slots: Weapon0..3 + Head/Body/Leg/Gloves/Cape + Horse + Harness.
    /// Empty slot → item_id=null → backend DELETE (важно при class change).
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

        /// <summary>Explicit slot → clean name. НЕ полагаемся на idx.ToString()
        /// т.к. EquipmentIndex имеет enum-алиасы с общими int-значениями
        /// (Head==NumAllWeaponSlots==ArmorItemBeginSlot, Weapon0==WeaponItemBeginSlot,
        /// Horse==ArmorItemEndSlot) → ToString() даёт неверное имя слота.</summary>
        private static string SlotName(EquipmentIndex idx)
        {
            switch (idx)
            {
                case EquipmentIndex.Weapon0:      return "weapon0";
                case EquipmentIndex.Weapon1:      return "weapon1";
                case EquipmentIndex.Weapon2:      return "weapon2";
                case EquipmentIndex.Weapon3:      return "weapon3";
                case EquipmentIndex.Head:         return "head";
                case EquipmentIndex.Body:         return "body";
                case EquipmentIndex.Leg:          return "leg";
                case EquipmentIndex.Gloves:       return "gloves";
                case EquipmentIndex.Cape:         return "cape";
                case EquipmentIndex.Horse:        return "horse";
                case EquipmentIndex.HorseHarness: return "horseharness";
                default:                          return idx.ToString().ToLowerInvariant();
            }
        }

        public static void PushAll(Hero hero)
        {
            if (hero == null || hero.Name == null) return;
            try
            {
                string username = HeroNaming.ExtractUsername(hero.Name.ToString());
                if (string.IsNullOrEmpty(username)) return;

                var eq = hero.BattleEquipment;
                int filled = 0;
                foreach (var idx in SLOTS_TO_SYNC)
                {
                    var el = eq[idx];
                    // 2026-05-29 FIX (статы шлема/оружия всегда 0): НЕ используем
                    // idx.ToString() — у EquipmentIndex enum-алиасы делят int-
                    // значения: Head(5)=NumAllWeaponSlots=ArmorItemBeginSlot,
                    // Weapon0(0)=WeaponItemBeginSlot, Horse(10)=ArmorItemEndSlot.
                    // ToString() возвращал первый алиас ("numallweaponslots" и
                    // т.п.) → фронт не узнавал slot → иконка '·', статы 0.
                    // Явный маппинг даёт правильные имена.
                    string slotName = SlotName(idx);

                    if (el.IsEmpty || el.Item == null)
                    {
                        PostEquipmentEvent(username, slotName, null, null,
                            -1, 0, 0f, null);
                        continue;
                    }

                    var item = el.Item;
                    int tier = (int)item.Tier;
                    int value = item.Value;
                    float weight = item.Weight;
                    string statsJson = BuildStatsJson(item);

                    PostEquipmentEvent(username, slotName,
                        item.StringId, item.Name?.ToString() ?? item.StringId,
                        tier, value, weight, statsJson);
                    filled++;
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

        /// <summary>
        /// Build stats JSON по типу item'а. Compact dict — backend
        /// сохраняет как-is, frontend парсит и рендерит badges.
        /// </summary>
        private static string BuildStatsJson(ItemObject item)
        {
            try
            {
                switch (item.ItemType)
                {
                    case ItemObject.ItemTypeEnum.OneHandedWeapon:
                    case ItemObject.ItemTypeEnum.TwoHandedWeapon:
                    case ItemObject.ItemTypeEnum.Polearm:
                    case ItemObject.ItemTypeEnum.Bow:
                    case ItemObject.ItemTypeEnum.Crossbow:
                    case ItemObject.ItemTypeEnum.Thrown:
                        return BuildWeaponStats(item);

                    case ItemObject.ItemTypeEnum.Arrows:
                    case ItemObject.ItemTypeEnum.Bolts:
                        return BuildAmmoStats(item);

                    case ItemObject.ItemTypeEnum.Shield:
                        return BuildShieldStats(item);

                    case ItemObject.ItemTypeEnum.HeadArmor:
                    case ItemObject.ItemTypeEnum.BodyArmor:
                    case ItemObject.ItemTypeEnum.LegArmor:
                    case ItemObject.ItemTypeEnum.HandArmor:
                    case ItemObject.ItemTypeEnum.Cape:
                        return BuildArmorStats(item);

                    case ItemObject.ItemTypeEnum.Horse:
                        return BuildHorseStats(item);

                    case ItemObject.ItemTypeEnum.HorseHarness:
                        return BuildArmorStats(item);  // harness тоже armor

                    default:
                        return "{}";
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[EquipmentSync] stats build failed for {item.StringId}: {ex.Message}");
                return "{}";
            }
        }

        private static string BuildWeaponStats(ItemObject item)
        {
            var w = item.PrimaryWeapon;
            if (w == null) return "{}";
            var sb = new StringBuilder("{");
            sb.AppendFormat("\"swing_dmg\":{0},", w.SwingDamage);
            sb.AppendFormat("\"swing_spd\":{0},", w.SwingSpeed);
            sb.AppendFormat("\"swing_type\":\"{0}\",", w.SwingDamageType);
            sb.AppendFormat("\"thrust_dmg\":{0},", w.ThrustDamage);
            sb.AppendFormat("\"thrust_spd\":{0},", w.ThrustSpeed);
            sb.AppendFormat("\"thrust_type\":\"{0}\",", w.ThrustDamageType);
            sb.AppendFormat("\"length\":{0},", w.WeaponLength);
            sb.AppendFormat("\"accuracy\":{0},", w.Accuracy);
            sb.AppendFormat("\"missile_spd\":{0}", w.MissileSpeed);
            sb.Append("}");
            return sb.ToString();
        }

        private static string BuildAmmoStats(ItemObject item)
        {
            var w = item.PrimaryWeapon;
            if (w == null) return "{}";
            return string.Format(
                "{{\"dmg\":{0},\"stack\":{1}}}",
                w.MissileDamage, w.MaxDataValue);
        }

        private static string BuildShieldStats(ItemObject item)
        {
            var w = item.PrimaryWeapon;
            if (w == null) return "{}";
            // Shield-specific: HitPoints (durability), BodyArmor (block coverage)
            return string.Format(
                "{{\"hp\":{0},\"body\":{1}}}",
                w.MaxDataValue, w.BodyArmor);
        }

        private static string BuildArmorStats(ItemObject item)
        {
            var a = item.ArmorComponent;
            if (a == null) return "{}";
            var sb = new StringBuilder("{");
            sb.AppendFormat("\"head\":{0},", a.HeadArmor);
            sb.AppendFormat("\"body\":{0},", a.BodyArmor);
            sb.AppendFormat("\"leg\":{0},", a.LegArmor);
            sb.AppendFormat("\"arm\":{0}", a.ArmArmor);
            sb.Append("}");
            return sb.ToString();
        }

        private static string BuildHorseStats(ItemObject item)
        {
            var h = item.HorseComponent;
            if (h == null) return "{}";
            return string.Format(
                "{{\"speed\":{0},\"charge\":{1},\"maneuver\":{2},\"hp\":{3}}}",
                h.Speed, h.ChargeDamage, h.Maneuver, h.HitPoints);
        }

        private static void PostEquipmentEvent(string username, string slotName,
            string itemId, string itemName,
            int tier, int value, float weight, string statsJson)
        {
            var backend = BannerlordLinkModule.Backend;
            if (backend == null) return;

            // item_id=null → backend DELETE row. Передаём null literal для cleanup.
            string idJson = itemId == null ? "null" : "\"" + EscapeJson(itemId) + "\"";
            string nameJson = itemName == null ? "null" : "\"" + EscapeJson(itemName) + "\"";
            string tierJson = tier < 0 ? "null" : tier.ToString();
            string statsField = statsJson ?? "null";

            string json = string.Format(
                System.Globalization.CultureInfo.InvariantCulture,
                "{{\"username\":\"{0}\",\"slot\":\"{1}\",\"item_id\":{2},\"item_name\":{3}," +
                "\"tier\":{4},\"item_value\":{5},\"weight\":{6:F2},\"stats\":{7}}}",
                EscapeJson(username), EscapeJson(slotName),
                idJson, nameJson, tierJson, value, weight, statsField);

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
