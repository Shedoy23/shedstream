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
            // 2026-07-20 (classes v2) — культурный скин класса: вся броня одной культуры
            // → узнаваемый силуэт/палитра с одного кадра стрима (Стургия=меха,
            // Империя=ламелляр, Вландия=латы, Баттания=капюшоны, Асераи=пустыня,
            // Кузаиты=степь). null = без ограничения. Оружие/кони культурой НЕ фильтруем.
            public string CultureId = null;
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
            // 2026-06-18 (Phase 1) — 12-class overhaul roster. Weapon by WeaponClass +
            // armor weight band + skip-slots + mount. Mirror m80 catalog reseed.
            // ── INFANTRY ──
            ["tank"]        = new Config { Slots = new Slot[] {
                                  new Slot(T.OneHandedWeapon, WeaponClass.Mace),
                                  new Slot(T.Shield, WeaponClass.LargeShield),
                                  T.Invalid, T.Invalid },
                                  Armor = ArmorBand.Heavy, CultureId = "empire" },
            // 2026-07-20 (v2) — броня теперь у ВСЕХ: SkipArmorSlots убран (был Head+Body).
            // «Стеклянную пушку» держат ЧИСЛА (hp_mult/dmg_reduction/lifesteal), а не голый
            // торс — иначе зритель платит за класс и умирает за 2 секунды.
            ["berserk"]     = new Config { Slots = new Slot[] {       // northern two-axe cleaver
                                  new Slot(T.TwoHandedWeapon, WeaponClass.TwoHandedAxe),
                                  new Slot(T.TwoHandedWeapon, WeaponClass.TwoHandedAxe),
                                  T.Invalid, T.Invalid },
                                  Armor = ArmorBand.Light, CultureId = "sturgia" },
            ["legionnaire"] = new Config { Slots = new Slot[] {       // sword + shield + javelin
                                  new Slot(T.OneHandedWeapon, WeaponClass.OneHandedSword),
                                  T.Shield,
                                  new Slot(T.Thrown, WeaponClass.Javelin),
                                  T.Invalid },
                                  Armor = ArmorBand.Medium },
            // 2026-07-21 (v2 return) — ассасин вернулся в ростер с «Невидимостью».
            // Культура: все 6 королевских скинов заняты шестёркой, поэтому берём
            // разбойничью — тёмные капюшоны/кожа, силуэт «не из армии», узнаётся с кадра.
            // Фильтр культуры мягкий (пусто → отпускаем культуру), так что риск только
            // косметический: если ассортимент бандитской брони окажется бедным, часть
            // слотов возьмётся любой культурой → проверить вид в игре.
            ["assassin"]    = new Config { Slots = new Slot[] {       // dagger + throwing knives
                                  new Slot(T.OneHandedWeapon, WeaponClass.Dagger),
                                  new Slot(T.Thrown, WeaponClass.ThrowingKnife),
                                  T.Invalid, T.Invalid },
                                  Armor = ArmorBand.Light, CultureId = "forest_bandits" },
            ["spearman"]    = new Config { Slots = new Slot[] {       // 2H spear + shield (anti-cav)
                                  new Slot(T.Polearm, WeaponClass.TwoHandedPolearm),
                                  T.Shield, T.Invalid, T.Invalid },
                                  Armor = ArmorBand.Medium },
            ["maul"]        = new Config { Slots = new Slot[] {       // 2H mace (anti-armor crusher)
                                  new Slot(T.TwoHandedWeapon, WeaponClass.TwoHandedMace),
                                  T.Invalid, T.Invalid, T.Invalid },
                                  Armor = ArmorBand.Medium },
            // ── RANGED (foot) ──
            ["archer"]      = new Config { Slots = new Slot[] {       // bow + arrows + dagger
                                  T.Bow, T.Arrows, T.Arrows,
                                  new Slot(T.OneHandedWeapon, WeaponClass.Dagger) },
                                  Armor = ArmorBand.Light, CultureId = "battania" },
            ["crossbow"]    = new Config { Slots = new Slot[] {       // crossbow + bolts + 1H
                                  T.Crossbow, T.Bolts, T.Bolts, T.OneHandedWeapon },
                                  Armor = ArmorBand.Medium, CultureId = "aserai" },
            ["skirmisher"]  = new Config { Slots = new Slot[] {       // 2× javelin + small shield + 1H
                                  new Slot(T.Thrown, WeaponClass.Javelin),
                                  new Slot(T.Thrown, WeaponClass.Javelin),
                                  new Slot(T.Shield, WeaponClass.SmallShield),
                                  T.OneHandedWeapon },
                                  Armor = ArmorBand.Light },
            // ── CAVALRY ──
            ["knight"]      = new Config { Slots = new Slot[] {       // heavy: lance + 1H + large shield
                                  new Slot(T.Polearm, WeaponClass.OneHandedPolearm),
                                  T.OneHandedWeapon,
                                  new Slot(T.Shield, WeaponClass.LargeShield),
                                  T.Invalid },
                                  Armor = ArmorBand.Heavy, UseHorse = true, CultureId = "vlandia" },
            ["lancer"]      = new Config { Slots = new Slot[] {       // light: lance + javelin + 1H
                                  new Slot(T.Polearm, WeaponClass.OneHandedPolearm),
                                  new Slot(T.Thrown, WeaponClass.Javelin),
                                  T.OneHandedWeapon, T.Invalid },
                                  Armor = ArmorBand.Medium, UseHorse = true },
            ["horse_archer"] = new Config { Slots = new Slot[] {      // mounted bow harasser
                                  T.Bow, T.Arrows, T.OneHandedWeapon, T.Arrows },
                                  Armor = ArmorBand.Light, UseHorse = true, CultureId = "khuzait" },
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
            ArmorBand armorBand = ArmorBand.Any,
            string cultureId = null)
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

            // 2026-07-20 (v2) — культурный скин класса. Фильтр по культуре предмета, чтобы
            // весь комплект читался одним стилем. Фолбэк: пусто → отпускаем культуру (тир и
            // материал важнее «правильного» стиля; у тонких слотов вроде асерайских поножей
            // предметов просто нет — см. SPEC_CLASSES_V2 §3.3).
            if (!string.IsNullOrEmpty(cultureId))
            {
                var culPool = pool.Where(i =>
                {
                    try
                    {
                        return i.Culture != null
                               && string.Equals(i.Culture.StringId, cultureId, StringComparison.OrdinalIgnoreCase);
                    }
                    catch { return false; }
                }).ToList();
                if (culPool.Count > 0) pool = culPool;
            }

            // Gender-lock (BLT CanUseItem gender part). Fallback to full pool if empties.
            if (hero != null)
            {
                var usable = pool.Where(i => GearGenderOk(i, hero)).ToList();
                if (usable.Count > 0) pool = usable;
            }

            // Броня — свои квантильные ступени вместо движкового тира (см. PickQuantileArmor).
            // Оружие/кони остаются на движковых тирах: там прогрессия честная.
            if (IsArmorType(type)) return PickQuantileArmor(pool, engineTier, rng);

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

        private static bool IsArmorType(ItemObject.ItemTypeEnum t)
        {
            return t == ItemObject.ItemTypeEnum.HeadArmor
                || t == ItemObject.ItemTypeEnum.BodyArmor
                || t == ItemObject.ItemTypeEnum.LegArmor
                || t == ItemObject.ItemTypeEnum.HandArmor
                || t == ItemObject.ItemTypeEnum.Cape;
        }

        // Очки защиты предмета — тот же вес, что у движковой формулы
        // (DefaultItemValueModel.CalculateArmorTier: 1.2×head + body + leg + arm).
        // Слот-множитель и линейный сдвиг движка ПОРЯДОК не меняют → для ранжирования
        // внутри одного слота достаточно суммы.
        private static float ArmorScore(ItemObject item)
        {
            try
            {
                var a = item?.ArmorComponent;
                if (a == null) return 0f;
                return 1.2f * a.HeadArmor + a.BodyArmor + a.LegArmor + a.ArmArmor;
            }
            catch { return 0f; }
        }

        /// <summary>
        /// 2026-07-20 (v2) — броня: 6 СВОИХ ступеней по очкам защиты внутри пула класса
        /// (культура+материал), вместо движкового Tier.
        ///
        /// Зачем: движковый тир брони = сумма очков защиты, поэтому ЛЁГКАЯ броня физически
        /// кэпится на T1–T3 — у берсерка/лучника «ближайший тир» к 5-6 упирался в ту же
        /// кожанку, и зритель платил за upgrade_gear T4→T6, не видя разницы (латентный
        /// платный no-op). Квантили дают каждому классу 6 РЕАЛЬНЫХ шагов «обноски → лучший
        /// доспех своей культуры», и апгрейд всегда виден глазами.
        ///
        /// engineTier здесь 0..5 (вызывающие: gearTier 0..6 → engineTier = max(0, gearTier-1)).
        /// </summary>
        private static ItemObject PickQuantileArmor(List<ItemObject> pool, int engineTier, Random rng)
        {
            if (pool == null || pool.Count == 0) return null;
            const int STEPS = 6;
            int step = engineTier;
            if (step < 0) step = 0;
            if (step > STEPS - 1) step = STEPS - 1;

            var ranked = pool.OrderBy(ArmorScore).ToList();
            int lo = (int)((long)step * ranked.Count / STEPS);
            int hi = (int)((long)(step + 1) * ranked.Count / STEPS);
            if (lo >= ranked.Count) lo = ranked.Count - 1;
            if (hi <= lo) hi = Math.Min(lo + 1, ranked.Count);

            var bandItems = ranked.GetRange(lo, hi - lo);
            // Внутри ступени отсекаем самые невзрачные (Appearance), но оставляем разброс —
            // reequip_gear это платный re-roll, он должен давать разные вещи.
            if (bandItems.Count >= 4)
            {
                var byLook = bandItems.OrderByDescending(i => { try { return i.Appearance; } catch { return 0f; } }).ToList();
                bandItems = byLook.GetRange(0, Math.Max(2, byLook.Count / 2));
            }
            return bandItems[rng.Next(bandItems.Count)];
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
