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
        internal static string SlotName(EquipmentIndex idx)
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
                            -1, 0, 0f, null, null);
                        continue;
                    }

                    var item = el.Item;
                    int tier = (int)item.Tier;
                    int value = item.Value;
                    float weight = item.Weight;
                    // M77: статы С учётом модификатора (легендарка бустит броню/урон/
                    // скорость) — иначе расширение показывало базовые цифры, не
                    // совпадающие с тултипом в игре.
                    string statsJson = BuildStatsJson(item, el.ItemModifier);
                    // M77 «Кузница»: качество модификатора (poor..legendary). Без
                    // модификатора → null (базовое качество, фронт не рисует бейдж).
                    string quality = el.ItemModifier != null
                        ? el.ItemModifier.ItemQuality.ToString().ToLowerInvariant()
                        : null;

                    PostEquipmentEvent(username, slotName,
                        item.StringId, item.Name?.ToString() ?? item.StringId,
                        tier, value, weight, statsJson, quality);
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
        /// Build stats JSON по типу item'а. mod (nullable) — ItemModifier: легендарка/
        /// мастерворк бустят броню/урон/скорость. Передаём, чтобы расширение показывало
        /// те же цифры, что тултип в игре (а не базовые без модификатора). Compact dict —
        /// backend сохраняет как-is, frontend парсит и рендерит badges.
        /// </summary>
        private static string BuildStatsJson(ItemObject item, ItemModifier mod)
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
                        return BuildWeaponStats(item, mod);

                    case ItemObject.ItemTypeEnum.Arrows:
                    case ItemObject.ItemTypeEnum.Bolts:
                        return BuildAmmoStats(item, mod);

                    case ItemObject.ItemTypeEnum.Shield:
                        return BuildShieldStats(item, mod);

                    case ItemObject.ItemTypeEnum.HeadArmor:
                    case ItemObject.ItemTypeEnum.BodyArmor:
                    case ItemObject.ItemTypeEnum.LegArmor:
                    case ItemObject.ItemTypeEnum.HandArmor:
                    case ItemObject.ItemTypeEnum.Cape:
                        return BuildArmorStats(item, mod);

                    case ItemObject.ItemTypeEnum.Horse:
                        return BuildHorseStats(item, mod);

                    case ItemObject.ItemTypeEnum.HorseHarness:
                        return BuildArmorStats(item, mod);  // harness тоже armor

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

        // Null-safe применение модификатора к базовому стату (mod==null → база без изменений).
        private static int ModDmg(ItemModifier m, int v)    => m != null ? m.ModifyDamage(v) : v;
        private static int ModSpd(ItemModifier m, int v)    => m != null ? m.ModifySpeed(v) : v;
        private static int ModMisSpd(ItemModifier m, int v) => m != null ? m.ModifyMissileSpeed(v) : v;
        private static int ModArmor(ItemModifier m, int v)  => m != null ? m.ModifyArmor(v) : v;
        private static int ModHp(ItemModifier m, int v)     => m != null ? m.ModifyHitPoints((short)v) : v;
        private static int ModStack(ItemModifier m, int v)  => m != null ? m.ModifyStackCount((short)v) : v;

        private static string BuildWeaponStats(ItemObject item, ItemModifier mod)
        {
            var w = item.PrimaryWeapon;
            if (w == null) return "{}";
            var sb = new StringBuilder("{");
            sb.AppendFormat("\"swing_dmg\":{0},", ModDmg(mod, w.SwingDamage));
            sb.AppendFormat("\"swing_spd\":{0},", ModSpd(mod, w.SwingSpeed));
            sb.AppendFormat("\"swing_type\":\"{0}\",", w.SwingDamageType);
            sb.AppendFormat("\"thrust_dmg\":{0},", ModDmg(mod, w.ThrustDamage));
            sb.AppendFormat("\"thrust_spd\":{0},", ModSpd(mod, w.ThrustSpeed));
            sb.AppendFormat("\"thrust_type\":\"{0}\",", w.ThrustDamageType);
            sb.AppendFormat("\"length\":{0},", w.WeaponLength);
            sb.AppendFormat("\"accuracy\":{0},", w.Accuracy);
            sb.AppendFormat("\"missile_spd\":{0}", ModMisSpd(mod, w.MissileSpeed));
            sb.Append("}");
            return sb.ToString();
        }

        private static string BuildAmmoStats(ItemObject item, ItemModifier mod)
        {
            var w = item.PrimaryWeapon;
            if (w == null) return "{}";
            return string.Format(
                "{{\"dmg\":{0},\"stack\":{1}}}",
                ModDmg(mod, w.MissileDamage), ModStack(mod, w.MaxDataValue));
        }

        private static string BuildShieldStats(ItemObject item, ItemModifier mod)
        {
            var w = item.PrimaryWeapon;
            if (w == null) return "{}";
            // Shield-specific: HitPoints (durability), BodyArmor (block coverage)
            return string.Format(
                "{{\"hp\":{0},\"body\":{1}}}",
                ModHp(mod, w.MaxDataValue), w.BodyArmor);
        }

        private static string BuildArmorStats(ItemObject item, ItemModifier mod)
        {
            var a = item.ArmorComponent;
            if (a == null) return "{}";
            var sb = new StringBuilder("{");
            sb.AppendFormat("\"head\":{0},", ModArmor(mod, a.HeadArmor));
            sb.AppendFormat("\"body\":{0},", ModArmor(mod, a.BodyArmor));
            sb.AppendFormat("\"leg\":{0},", ModArmor(mod, a.LegArmor));
            sb.AppendFormat("\"arm\":{0}", ModArmor(mod, a.ArmArmor));
            sb.Append("}");
            return sb.ToString();
        }

        private static string BuildHorseStats(ItemObject item, ItemModifier mod)
        {
            var h = item.HorseComponent;
            if (h == null) return "{}";
            int speed    = mod != null ? mod.ModifyMountSpeed(h.Speed)        : h.Speed;
            int charge   = mod != null ? mod.ModifyMountCharge(h.ChargeDamage) : h.ChargeDamage;
            int maneuver = mod != null ? mod.ModifyMountManeuver(h.Maneuver)   : h.Maneuver;
            int hp       = mod != null ? mod.ModifyMountHitPoints(h.HitPoints) : h.HitPoints;
            return string.Format(
                "{{\"speed\":{0},\"charge\":{1},\"maneuver\":{2},\"hp\":{3}}}",
                speed, charge, maneuver, hp);
        }

        private static void PostEquipmentEvent(string username, string slotName,
            string itemId, string itemName,
            int tier, int value, float weight, string statsJson, string quality)
        {
            var backend = BannerlordLinkModule.Backend;
            if (backend == null) return;

            // item_id=null → backend DELETE row. Передаём null literal для cleanup.
            string idJson = itemId == null ? "null" : "\"" + EscapeJson(itemId) + "\"";
            string nameJson = itemName == null ? "null" : "\"" + EscapeJson(itemName) + "\"";
            string tierJson = tier < 0 ? "null" : tier.ToString();
            string statsField = statsJson ?? "null";
            string qualityJson = quality == null ? "null" : "\"" + EscapeJson(quality) + "\"";

            string json = string.Format(
                System.Globalization.CultureInfo.InvariantCulture,
                "{{\"username\":\"{0}\",\"slot\":\"{1}\",\"item_id\":{2},\"item_name\":{3}," +
                "\"tier\":{4},\"item_value\":{5},\"weight\":{6:F2},\"stats\":{7},\"quality\":{8}}}",
                EscapeJson(username), EscapeJson(slotName),
                idJson, nameJson, tierJson, value, weight, statsField, qualityJson);

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
