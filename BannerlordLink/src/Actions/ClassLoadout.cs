using System;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Single source of truth for class → equipment loadout + the tier-aware
    /// item picker. Shared by SetClassHandler (set_class) AND UpgradeGearHandler/
    /// ReequipGearHandler (upgrade_gear / reequip_gear) so the class spec lives in
    /// ONE place — mirror the M15 backend seed.
    ///
    /// 2026-06-18 (class overhaul Phase 0) — extracted from two duplicate copies.
    /// A slot is ItemType + optional WeaponClass (axe/mace/javelin/dagger…); a
    /// class also carries an armor weight band + optional skipped armor slots
    /// (partial-armor identities, e.g. berserk = no helmet).
    /// </summary>
    internal static class ClassLoadout
    {
        // Armor weight band — Light picks the lightest item in the nearest tier,
        // Heavy the heaviest. Any/Medium → random (current behavior). gear_tier
        // still chooses the tier first, so the band keeps heavy/light identity at
        // every tier WITHOUT killing tier progression.
        public enum ArmorBand { Any, Light, Medium, Heavy }

        // Per-slot weapon: ItemType + optional WeaponClass. Implicit
        // ItemTypeEnum→Slot keeps class lines readable (wc = null).
        public struct Slot
        {
            public readonly ItemObject.ItemTypeEnum Type;
            public readonly WeaponClass? Wc;
            public Slot(ItemObject.ItemTypeEnum type, WeaponClass? wc = null) { Type = type; Wc = wc; }
            public static implicit operator Slot(ItemObject.ItemTypeEnum t) => new Slot(t, null);
        }

        public class Config
        {
            public Slot[] Slots;
            public bool UseHorse;
            public bool UseCamel;
            public ArmorBand Armor = ArmorBand.Any;          // Any = current behavior
            public EquipmentIndex[] SkipArmorSlots = null;   // null/empty = fill all 5
        }

        // Alias чтобы класс-лоадауты читались.
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
            public const ItemObject.ItemTypeEnum Invalid = ItemObject.ItemTypeEnum.Invalid;
        }

        // Convenience: the Invalid sentinel for slot checks by callers.
        public const ItemObject.ItemTypeEnum Invalid = ItemObject.ItemTypeEnum.Invalid;
        public const ItemObject.ItemTypeEnum HorseType = ItemObject.ItemTypeEnum.Horse;
        public const ItemObject.ItemTypeEnum HorseHarnessType = ItemObject.ItemTypeEnum.HorseHarness;

        // Class spec — mirror M15 seed. Must match the backend bannerlord_classes.
        public static readonly Dictionary<string, Config> Classes =
            new Dictionary<string, Config>(StringComparer.OrdinalIgnoreCase)
        {
            ["tank"]            = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.Shield, T.Invalid, T.Invalid } },
            ["archer"]          = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.Arrows, T.Arrows, T.Bow } },
            ["heavy_archer"]    = new Config { Slots = new Slot[] { T.TwoHandedWeapon, T.Arrows, T.Arrows, T.Bow } },
            ["crossbow"]        = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.Bolts, T.Bolts, T.Crossbow } },
            ["heavy_crossbow"]  = new Config { Slots = new Slot[] { T.TwoHandedWeapon, T.Bolts, T.Bolts, T.Crossbow } },
            ["cavalry"]         = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseHorse = true },
            ["camel_cavalry"]   = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseCamel = true },
            ["horse_archer"]    = new Config { Slots = new Slot[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Arrows }, UseHorse = true },
            ["camel_archer"]    = new Config { Slots = new Slot[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Arrows }, UseCamel = true },
            ["psycho"]          = new Config { Slots = new Slot[] { T.TwoHandedWeapon, T.Thrown, T.Thrown, T.Invalid } },
            // 2026-06-18 (Phase 0 PROOF) — berserk = 2×2H-axe (cleave), barechested:
            // skip Head + Body (no helmet, no chest/нагрудник), light legs/gloves/cape.
            // Other 12 unchanged this phase.
            ["berserk"]         = new Config {
                                      Slots = new Slot[] {
                                          new Slot(T.TwoHandedWeapon, WeaponClass.TwoHandedAxe),
                                          new Slot(T.TwoHandedWeapon, WeaponClass.TwoHandedAxe),
                                          T.Invalid, T.Invalid },
                                      Armor = ArmorBand.Light,
                                      SkipArmorSlots = new[] { EquipmentIndex.Head, EquipmentIndex.Body } },
            ["assassin"]        = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.OneHandedWeapon, T.Thrown, T.Invalid } },
            ["knight"]          = new Config { Slots = new Slot[] { T.OneHandedWeapon, T.Shield, T.Polearm, T.Invalid }, UseHorse = true },
        };

        // Armor coverage order (BLT pattern). Head first so partial-armor classes
        // can skip it cleanly.
        public static readonly (EquipmentIndex idx, ItemObject.ItemTypeEnum type)[] ArmorSlots =
        {
            (EquipmentIndex.Head,   ItemObject.ItemTypeEnum.HeadArmor),
            (EquipmentIndex.Body,   ItemObject.ItemTypeEnum.BodyArmor),
            (EquipmentIndex.Leg,    ItemObject.ItemTypeEnum.LegArmor),
            (EquipmentIndex.Gloves, ItemObject.ItemTypeEnum.HandArmor),
            (EquipmentIndex.Cape,   ItemObject.ItemTypeEnum.Cape),
        };

        // Tier-aware item lookup (BLT SelectRandomItemNearestTier, EquipHero.cs:579):
        // group by tier, take nearest group to target (ties prefer lower tier).
        // weaponClass narrows the weapon pool to a specific class (axe/mace/javelin);
        // armorBand picks lightest/heaviest within the tier for armor.
        // excludeIds = StringId's already equipped this pass (anti-duplicate); falls
        // back to the full pool if dedup empties it (BLT allows dupes as last resort).
        public static ItemObject FindTieredItem(
            ItemObject.ItemTypeEnum type,
            int engineTier,
            Random rng,
            Func<string, bool> nameFilter = null,
            HashSet<string> excludeIds = null,
            Hero hero = null,
            WeaponClass? weaponClass = null,
            ArmorBand armorBand = ArmorBand.Any)
        {
            var pool = MBObjectManager.Instance
                .GetObjectTypeList<ItemObject>()
                ?.Where(i => i != null && i.ItemType == type)
                ?.Where(i => !i.NotMerchandise)
                ?.ToList();
            if (pool == null || pool.Count == 0) return null;

            // Маунты: только верховые боевые животные (не мулы/вьючные).
            if (type == ItemObject.ItemTypeEnum.Horse)
            {
                var mounts = pool
                    .Where(i => i.HorseComponent != null
                                && i.HorseComponent.IsRideable
                                && !i.HorseComponent.IsPackAnimal)
                    .ToList();
                if (mounts.Count > 0) pool = mounts;
            }

            // nameFilter получает lowercased StringId (camel/non-camel).
            if (nameFilter != null)
            {
                var filtered = pool
                    .Where(i => nameFilter(i.StringId?.ToLowerInvariant() ?? ""))
                    .ToList();
                if (filtered.Count > 0) pool = filtered;
            }

            // Narrow to a specific WeaponClass (axe/mace/javelin/dagger…). Fallback
            // to unfiltered if empty (better wrong-class weapon than a bare hand) —
            // but log so we notice a gap.
            if (weaponClass.HasValue)
            {
                var wcPool = pool.Where(i =>
                {
                    try { return i.PrimaryWeapon != null && i.PrimaryWeapon.WeaponClass == weaponClass.Value; }
                    catch { return false; }
                }).ToList();
                if (wcPool.Count > 0) pool = wcPool;
                else BannerlordLinkModule.Log(
                    $"[ClassLoadout] no item of WeaponClass {weaponClass.Value} for {type} — fallback to any {type}");
            }

            // 2026-06-18 — armor weight band → filter by MaterialType so Light classes
            // get genuinely light gear (cloth/leather), NOT "lightest heavy item in the
            // tier" (bug: berserk got a T6 chainmail hauberk). Fallback to unfiltered if
            // the material filter empties the pool. Weapons pass armorBand=Any → no-op.
            if (armorBand != ArmorBand.Any)
            {
                var mats = ArmorMaterialsFor(armorBand);
                if (mats != null)
                {
                    var matPool = pool.Where(i =>
                    {
                        try
                        {
                            return i.ArmorComponent != null
                                   && Array.IndexOf(mats, i.ArmorComponent.MaterialType) >= 0;
                        }
                        catch { return false; }
                    }).ToList();
                    if (matPool.Count > 0) pool = matPool;
                }
            }

            // Gender-lock (BLT CanUseItem gender part). Fallback to full pool if empties.
            if (hero != null)
            {
                var usable = pool.Where(i => GearGenderOk(i, hero)).ToList();
                if (usable.Count > 0) pool = usable;
            }

            // Anti-duplicate first pass.
            if (excludeIds != null && excludeIds.Count > 0)
            {
                var deduped = pool.Where(i => !excludeIds.Contains(i.StringId ?? "")).ToList();
                var pick = PickNearestTier(deduped, engineTier, rng, armorBand);
                if (pick != null) return pick;
            }
            return PickNearestTier(pool, engineTier, rng, armorBand);
        }

        // Гендер-флаги предмета (BLT EquipHero.CanUseItem gender-часть).
        public static bool GearGenderOk(ItemObject item, Hero hero)
        {
            try
            {
                if (hero.IsFemale && item.ItemFlags.HasFlag(ItemFlags.NotUsableByFemale)) return false;
                if (!hero.IsFemale && item.ItemFlags.HasFlag(ItemFlags.NotUsableByMale)) return false;
            }
            catch { }
            return true;
        }

        // 2026-06-18 — armor materials allowed per weight band. Light = cloth/leather
        // (genuinely light, no mail/plate); Medium = chainmail/leather; Heavy = plate/
        // chainmail. null = no material constraint (Any).
        private static ArmorComponent.ArmorMaterialTypes[] ArmorMaterialsFor(ArmorBand band)
        {
            switch (band)
            {
                case ArmorBand.Light:
                    return new[] { ArmorComponent.ArmorMaterialTypes.Cloth,
                                   ArmorComponent.ArmorMaterialTypes.Leather,
                                   ArmorComponent.ArmorMaterialTypes.None };
                case ArmorBand.Medium:
                    return new[] { ArmorComponent.ArmorMaterialTypes.Chainmail,
                                   ArmorComponent.ArmorMaterialTypes.Leather };
                case ArmorBand.Heavy:
                    return new[] { ArmorComponent.ArmorMaterialTypes.Plate,
                                   ArmorComponent.ArmorMaterialTypes.Chainmail };
                default:
                    return null;
            }
        }

        private static ItemObject PickNearestTier(List<ItemObject> pool, int engineTier, Random rng, ArmorBand band = ArmorBand.Any)
        {
            if (pool == null || pool.Count == 0) return null;
            var nearest = pool.GroupBy(i => (int)i.Tier)
                .OrderBy(g => Math.Abs(engineTier - g.Key))   // ближайший тир
                .ThenBy(g => g.Key)                            // при равенстве — ниже
                .FirstOrDefault();
            if (nearest == null) return null;
            var nearestList = nearest.ToList();
            // Weight band within the chosen tier (Light/Heavy). Preserves gear_tier
            // progression (tier chosen first) while giving heavy/light identity.
            if (band == ArmorBand.Light)
                return nearestList.OrderBy(i => i.Weight).First();
            if (band == ArmorBand.Heavy)
                return nearestList.OrderByDescending(i => i.Weight).First();
            return nearestList[rng.Next(nearestList.Count)];
        }
    }
}
