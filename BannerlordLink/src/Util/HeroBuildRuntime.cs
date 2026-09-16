using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Behaviors;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Util
{
    internal static class HeroBuildRuntime
    {
        internal static HeroBuildState State(string username)
            => EquipmentShopBehavior.Instance?.GetBuild(username);

        internal static SkillObject Skill(string key)
        {
            switch (key) {
                case "OneHanded": return DefaultSkills.OneHanded;
                case "TwoHanded": return DefaultSkills.TwoHanded;
                case "Polearm": return DefaultSkills.Polearm;
                case "Bow": return DefaultSkills.Bow;
                case "Crossbow": return DefaultSkills.Crossbow;
                case "Throwing": return DefaultSkills.Throwing;
                default: return null;
            }
        }

        internal static string WeaponType(MissionWeapon weapon)
        {
            if (weapon.IsEmpty || weapon.Item == null) return null;
            // CurrentUsageItem distinguishes bastard swords and thrown weapons
            // used as melee. Missile payload is the arrow/bolt, not the launcher.
            var usage = weapon.CurrentUsageItem;
            if (usage == null) return EquipmentShopBehavior.Category(weapon.Item);
            switch (usage.WeaponClass) {
                case WeaponClass.Arrow: return "bow";
                case WeaponClass.Bolt: return "crossbow";
                case WeaponClass.SmallShield: case WeaponClass.LargeShield: return "shield";
            }
            var skill = usage.RelevantSkill;
            if (skill == DefaultSkills.OneHanded) return "one_handed";
            if (skill == DefaultSkills.TwoHanded) return "two_handed";
            if (skill == DefaultSkills.Polearm) return "polearm";
            if (skill == DefaultSkills.Bow) return "bow";
            if (skill == DefaultSkills.Crossbow) return "crossbow";
            if (skill == DefaultSkills.Throwing) return "thrown";
            return null;
        }
        internal static bool Wielded(Agent agent, string weapon)
        {
            if (agent == null || !agent.IsActive()) return false;
            return weapon == "shield" ? WeaponType(agent.WieldedOffhandWeapon) == "shield"
                : WeaponType(agent.WieldedWeapon) == weapon;
        }
        internal static bool Equipped(Hero hero, string weapon)
        {
            var equipment = new List<ItemObject>();
            for (int i = 0; i < 4; i++) {
                var item = hero.BattleEquipment[(EquipmentIndex)i].Item;
                if (item != null) equipment.Add(item);
            }
            return equipment.Any(item => EquipmentShopBehavior.Category(item) == weapon && Usable(hero, item)
                && ((weapon != "bow" && weapon != "crossbow") || equipment.Any(ammo => AmmoCompatible(item, ammo))));
        }
        private static bool AmmoCompatible(ItemObject launcher, ItemObject ammo)
            => launcher.PrimaryWeapon != null && ammo.PrimaryWeapon != null
                && (EquipmentShopBehavior.Category(ammo) == "arrows" || EquipmentShopBehavior.Category(ammo) == "bolts")
                && launcher.PrimaryWeapon.AmmoClass == ammo.PrimaryWeapon.WeaponClass;
        private static bool Usable(Hero hero, ItemObject item)
            => item.Difficulty <= 0 || (item.PrimaryWeapon?.RelevantSkill != null
                && hero.GetSkillValue(item.PrimaryWeapon.RelevantSkill) >= item.Difficulty);

        internal static FormationClass Formation(Hero hero)
        {
            bool mounted = hero.BattleEquipment[EquipmentIndex.Horse].Item != null;
            bool ranged = Equipped(hero, "bow") || Equipped(hero, "crossbow");
            return mounted ? (ranged ? FormationClass.HorseArcher : FormationClass.Cavalry)
                : (ranged ? FormationClass.Ranged : FormationClass.Infantry);
        }
        internal static Dictionary<string, ItemObject> Starter(Hero hero, string key)
            => Starter(key, StarterPool(hero));

        private static List<ItemObject> StarterPool(Hero hero)
            => MBObjectManager.Instance.GetObjectTypeList<ItemObject>()
                .Where(i => EquipmentShopBehavior.Sellable(i) && (int)i.Tier <= 0 && Usable(hero, i))
                .OrderBy(i => (int)i.Tier).ThenBy(i => i.Value).ThenBy(i => i.StringId, StringComparer.Ordinal).ToList();

        private static Dictionary<string, ItemObject> Starter(string key, List<ItemObject> pool)
        {
            string[] categories;
            switch (key) {
                case "infantry": categories = new[] { "one_handed", "shield" }; break;
                case "two_handed": categories = new[] { "two_handed" }; break;
                case "archer": categories = new[] { "bow", "arrows" }; break;
                default: return null;
            }
            var result = new Dictionary<string, ItemObject>();
            for (int i = 0; i < categories.Length; i++) {
                var item = pool.FirstOrDefault(x => EquipmentShopBehavior.Category(x) == categories[i]
                    && (categories[i] != "bow" || pool.Any(ammo => AmmoCompatible(x, ammo)))
                    && (categories[i] != "arrows" || AmmoCompatible(result["weapon0"], x)));
                if (item == null) return null;
                result["weapon" + i] = item;
            }
            // Optional basic clothing is previewed exactly; missing armor never
            // upgrades the free kit to expensive/high-tier modded equipment.
            foreach (string slot in new[] { "body", "leg" }) {
                var item = pool.FirstOrDefault(x => EquipmentShopBehavior.Category(x) == slot);
                if (item != null) result[slot] = item;
            }
            return result;
        }
        internal static JObject Snapshot(Hero hero, HeroBuildState state, bool? missionOverride = null)
        {
            if (state == null) return null;
            var options = new JArray();
            foreach (var p in HeroBuildPolicy.Powers) {
                int skill = hero.GetSkillValue(Skill(p.Skill));
                bool available = Equipped(hero, p.Weapon);
                options.Add(new JObject { ["weapon_type"] = p.Weapon, ["power_key"] = p.Power,
                    ["label"] = p.Label, ["description"] = p.Description, ["skill"] = p.Skill,
                    ["skill_level"] = skill, ["rank"] = HeroBuildPolicy.Rank(skill),
                    ["value"] = p.Values[HeroBuildPolicy.Rank(skill) - 1], ["available"] = available,
                    ["reason"] = available ? null : "required_weapon_not_equipped" });
            }
            var kits = new JArray();
            var starterPool = state.StarterKit == null ? StarterPool(hero) : null;
            foreach (string key in state.StarterKit == null ? new[] { "infantry", "two_handed", "archer" } : new string[0]) {
                var contents = Starter(key, starterPool);
                var rows = new JArray();
                if (contents != null) foreach (var kv in contents) rows.Add(new JObject {
                    ["item_id"] = kv.Value.StringId, ["name"] = kv.Value.Name?.ToString() ?? kv.Value.StringId, ["slot"] = kv.Key });
                kits.Add(new JObject { ["id"] = key,
                    ["label"] = key == "infantry" ? "Одноручное оружие и щит" : key == "archer" ? "Лук и стрелы" : "Двуручное оружие",
                    ["items"] = rows, ["available"] = contents != null && state.StarterKit == null,
                    ["reason"] = state.StarterKit != null ? "starter_already_claimed" : contents == null ? "starter_items_unavailable" : null });
            }
            return new JObject { ["version"] = state.Version, ["specialization"] = state.Specialization,
                ["selected_weapon_type"] = state.SelectedWeaponType, ["selected_power"] = HeroBuildPolicy.Power(state.SelectedWeaponType)?.Power,
                ["starter_kit"] = state.StarterKit, ["starter_claimed"] = state.StarterKit != null,
                ["weapon_power_cooldown_until"] = state.WeaponPowerCooldownUntil,
                ["is_prisoner"] = hero.IsPrisoner,
                ["is_mounted"] = hero.BattleEquipment[EquipmentIndex.Horse].Item != null,
                ["can_manage"] = !(missionOverride ?? Mission.Current != null) && !hero.IsPrisoner,
                ["in_battle"] = missionOverride ?? Mission.Current != null, ["power_options"] = options, ["starter_kits"] = kits,
                ["specializations"] = new JArray {
                    Spec("guardian", "Защитник", "+15% здоровья в полевых боях."),
                    Spec("assault", "Натиск", "+10% урона оружием в ближнем бою."),
                    Spec("marksman", "Стрелок", "+10% урона стрелами, болтами и метательным оружием."),
                    Spec("mobility", "Подвижность", "+10% скорости передвижения пешком.") } };
        }
        private static JObject Spec(string id, string label, string description)
            => new JObject { ["id"] = id, ["label"] = label, ["description"] = description };
    }
}
