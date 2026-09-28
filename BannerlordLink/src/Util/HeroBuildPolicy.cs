using System;
using System.Collections.Generic;

namespace BannerlordLink.Util
{
    // Save-owned choices, deliberately absent on existing heroes. New campaigns
    // initialize this on adoption; reading an old save never migrates it.
    internal sealed class HeroBuildState
    {
        public int Version = 1;
        public string Specialization = "guardian";
        public string SelectedWeaponType;
        public string StarterKit;
        public long WeaponPowerCooldownUntil;
    }

    internal sealed class WeaponPowerDefinition
    {
        internal readonly string Weapon, Power, Label, Description, Skill;
        internal readonly double[] Values;
        internal WeaponPowerDefinition(string weapon, string power, string label,
            string description, string skill, params double[] values)
        { Weapon = weapon; Power = power; Label = label; Description = description; Skill = skill; Values = values; }
    }

    internal static class HeroBuildPolicy
    {
        internal const int CooldownSeconds = 90;
        internal const int DurationSeconds = 45;
        internal static readonly string[] Specializations = { "guardian", "assault", "marksman", "mobility" };
        internal static readonly WeaponPowerDefinition[] Powers = {
            new WeaponPowerDefinition("one_handed", "rage", "Натиск", "Усиливает удары одноручным оружием на 45 секунд.", "OneHanded", 1.15, 1.25, 1.4),
            new WeaponPowerDefinition("two_handed", "cleave", "Рассечение", "Удары двуручным оружием задевают соседних врагов на 45 секунд.", "TwoHanded", .2, .35, .5),
            new WeaponPowerDefinition("polearm", "shield_break_burst", "Разрушитель щитов", "Удары древковым оружием могут разбить щит на 45 секунд; шанс растёт с навыком.", "Polearm", 25, 50, 75),
            new WeaponPowerDefinition("bow", "explosive_arrows", "Взрывные стрелы", "Попадания из лука наносят урон соседним врагам на 45 секунд.", "Bow", 10, 20, 30),
            new WeaponPowerDefinition("crossbow", "explosive_arrows", "Взрывные болты", "Попадания из арбалета наносят урон соседним врагам на 45 секунд.", "Crossbow", 10, 20, 30),
            new WeaponPowerDefinition("thrown", "poison_dot", "Отравленные снаряды", "Попадания метательным оружием отравляют врага на 45 секунд.", "Throwing", 2, 4, 6),
            new WeaponPowerDefinition("shield", "ironskin_toggle", "Стойкая защита", "Снижает входящий урон, пока щит в руке, на 45 секунд.", "OneHanded", 15, 25, 35),
        };
        internal static int Rank(int skill) => skill >= 150 ? 3 : skill >= 50 ? 2 : 1;
        internal static WeaponPowerDefinition Power(string weapon)
        {
            foreach (var p in Powers) if (p.Weapon == weapon) return p;
            return null;
        }
        internal static bool ValidSpecialization(string value) => Array.IndexOf(Specializations, value) >= 0;
        internal static double? Passive(HeroBuildState build, string key)
        {
            if (build == null) return null;
            if (build.Specialization == "guardian" && key == "hp_multiplier") return 1.15;
            if (build.Specialization == "mobility" && key == "move_speed_pct") return 10;
            return null; // never fall through to the old class bonus table
        }
        internal static double DamageMultiplier(HeroBuildState build, bool missile)
            => build != null && ((build.Specialization == "assault" && !missile)
                || (build.Specialization == "marksman" && missile)) ? 1.1 : 1;
        internal static string Select(HeroBuildState build, string weapon, bool equipped, bool mission)
        {
            if (mission) return "in_mission";
            if (Power(weapon) == null) return "unknown_weapon_power";
            if (!equipped) return "required_weapon_not_equipped";
            if (build.SelectedWeaponType == weapon) return "already_selected";
            build.SelectedWeaponType = weapon;
            return null;
        }
        internal static string CanActivate(HeroBuildState build, string power, bool wielded, long now)
        {
            var selected = Power(build?.SelectedWeaponType);
            if (selected == null || selected.Power != power) return "weapon_power_not_selected";
            if (!wielded) return "required_weapon_not_wielded";
            if (build.WeaponPowerCooldownUntil > now) return "weapon_power_cooldown";
            return null;
        }
        internal static bool AllowsHit(HeroBuildState build, string power, string actualWeapon, bool missile)
        {
            if (build == null) return true;
            var selected = Power(build.SelectedWeaponType);
            if (selected == null || selected.Power != power || selected.Weapon != actualWeapon) return false;
            bool ranged = actualWeapon == "bow" || actualWeapon == "crossbow" || actualWeapon == "thrown";
            return ranged == missile;
        }
    }
}
