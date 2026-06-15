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
            ["archer"]          = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Arrows, T.Arrows, T.Bow } },
            ["heavy_archer"]    = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.Arrows, T.Arrows, T.Bow } },
            ["crossbow"]        = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Bolts, T.Bolts, T.Crossbow } },
            ["heavy_crossbow"]  = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.Bolts, T.Bolts, T.Crossbow } },
            ["cavalry"]         = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseHorse = true },
            ["camel_cavalry"]   = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseCamel = true },
            ["horse_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Arrows }, UseHorse = true },
            ["camel_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Arrows }, UseCamel = true },
            ["psycho"]          = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.Thrown, T.Thrown, T.Invalid } },
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

                int engineTier = targetTier - 1;   // 1-6 → 0-5
                // 2026-05-29 — slot-fill вынесен в ApplyGearLoadout (общий с
                // ReequipGearHandler). Анти-дубль оружия + ShouldReplaceSlot
                // (не затираем призы/крафт) внутри.
                // Вариант A: апгрейд тира → строго базовая броня (сброс модификатора
                // равно-/ниже-тирной брони). Качество даёт только форж.
                int slotsFilled = ApplyGearLoadout(hero, classKey, engineTier,
                    stripArmorModifiers: true);

                // Списать Hero.Gold ПОСЛЕ apply equipment (atomic в-game).
                // GiveGoldAction.ApplyBetweenCharacters(giver, receiver, amount):
                // если первый аргумент null — взять gold из nowhere, отрицательный
                // amount = deduct из hero.
                int goldBefore = hero.Gold;
                GiveGoldAction.ApplyBetweenCharacters(hero, null, cost, true);
                BannerlordLinkModule.Log(
                    $"[upgrade_gear] @{username} → T{targetTier} ({classKey}): " +
                    $"{slotsFilled} slots filled, " +
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

        // 2026-05-29 — общий slot-fill для upgrade_gear И reequip_gear. Набивает
        // weapon/armor/horse слоты под класс на заданном engineTier (0-5).
        // Анти-дубль оружия (seed уже надетыми + добавляем каждый выбранный) +
        // ShouldReplaceSlot (не затираем призы/крафт). Возвращает кол-во
        // заполненных слотов. Списание золота/синк делает caller.
        // stripArmorModifiers (2026-06-15, вариант A): на АПГРЕЙДЕ тира сбрасываем
        // модификатор равно-/ниже-тирной БРОНИ → строго базовая броня нового тира.
        // Тир = базовая мощь (мод), качество = только форж. Пересбор и оружие зовут
        // с false (бережём крафт/призы/перековку). Higher-tier приз НЕ даунгрейдим.
        internal static int ApplyGearLoadout(Hero hero, string classKey, int engineTier,
            bool stripArmorModifiers = false)
        {
            if (hero == null || classKey == null || !_classes.TryGetValue(classKey, out var cfg))
                return 0;
            var rng = new Random();
            var equipment = hero.BattleEquipment;
            int slotsFilled = 0;

            // ── 1. Weapon slots по class config (анти-дубль) ──
            var usedWeaponIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int s = 0; s < 4; s++)
            {
                try
                {
                    var cur = equipment[(EquipmentIndex)s];
                    if (!cur.IsEmpty && cur.Item != null)
                        usedWeaponIds.Add(cur.Item.StringId ?? "");
                }
                catch { }
            }
            for (int i = 0; i < 4 && i < cfg.Slots.Length; i++)
            {
                var slotType = cfg.Slots[i];
                if (slotType == T.Invalid)
                {
                    // 2026-05-31 FIX — чистим неиспользуемый слот (как в
                    // SetClassHandler). «Пересбор» заодно убирает stale-оружие
                    // от прошлого класса. Legendary (modifier'нутый) сохраняем.
                    try
                    {
                        var stale = equipment[(EquipmentIndex)i];
                        if (!stale.IsEmpty && stale.ItemModifier == null)
                            equipment[(EquipmentIndex)i] = EquipmentElement.Invalid;
                    }
                    catch { }
                    continue;
                }

                var item = FindTieredItem(slotType, engineTier, rng, null, usedWeaponIds, hero);
                if (item != null && ShouldReplaceSlot(equipment, (EquipmentIndex)i, engineTier))
                {
                    equipment[(EquipmentIndex)i] = new EquipmentElement(item);
                    usedWeaponIds.Add(item.StringId ?? "");
                    slotsFilled++;
                }
            }

            // ── 2. Armor slots — всегда заполняем все 5 ──
            foreach (var (idx, type) in ArmorSlots)
            {
                var item = FindTieredItem(type, engineTier, rng, null, null, hero);
                if (item != null && ShouldReplaceSlot(equipment, idx, engineTier, stripArmorModifiers))
                {
                    equipment[idx] = new EquipmentElement(item);
                    slotsFilled++;
                }
            }

            // ── 3. Horse + Harness для mounted classes (family-type matching) ──
            if (cfg.UseHorse || cfg.UseCamel)
            {
                bool wantCamel = cfg.UseCamel;
                System.Func<string, bool> mountFilter = wantCamel
                    ? (System.Func<string, bool>)(name => name.IndexOf("camel", StringComparison.OrdinalIgnoreCase) >= 0)
                    : (name => name.IndexOf("camel", StringComparison.OrdinalIgnoreCase) < 0);
                var horse = FindTieredItem(T.Horse, engineTier, rng, mountFilter, null, hero);
                if (horse != null && ShouldReplaceSlot(equipment, EquipmentIndex.Horse, engineTier))
                {
                    equipment[EquipmentIndex.Horse] = new EquipmentElement(horse);
                    slotsFilled++;
                }
                var harness = FindTieredItem(T.HorseHarness, engineTier, rng, mountFilter, null, hero);
                if (harness != null && ShouldReplaceSlot(equipment, EquipmentIndex.HorseHarness, engineTier))
                {
                    equipment[EquipmentIndex.HorseHarness] = new EquipmentElement(harness);
                    slotsFilled++;
                }
            }
            else
            {
                // Пеший класс — снять коня + барду (фикс «остаётся в кавалерийской
                // формации» при reequip/upgrade пешим классом, 2026-05-29).
                try
                {
                    equipment[EquipmentIndex.Horse] = EquipmentElement.Invalid;
                    equipment[EquipmentIndex.HorseHarness] = EquipmentElement.Invalid;
                }
                catch { }
            }

            return slotsFilled;
        }

        // 2026-05-29 — адаптация BLT (EquipHero.cs:253 "Never replace stuff that
        // is higher tier (in practice it can only be tournament prize)"). НЕ
        // затираем слот если текущий предмет ВЫШЕ target tier'а (турнирный приз)
        // ИЛИ именной/смитованный (ItemModifier — крафтовый трофей, надетый
        // через «одеть»). Пустой слот — всегда заполняем.
        private static bool ShouldReplaceSlot(Equipment eq, EquipmentIndex idx, int engineTier,
            bool stripModifier = false)
        {
            try
            {
                var cur = eq[idx];
                if (cur.IsEmpty || cur.Item == null) return true;
                if ((int)cur.Item.Tier > engineTier) return false;     // higher-tier prize — keep (не даунгрейдим)
                // stripModifier=true (апгрейд брони, вариант A): сбрасываем модификатор
                // равно-/ниже-тирного предмета → строго базовая броня. false (пересбор/
                // оружие/конь): бережём крафт/призы/перековку.
                if (!stripModifier && cur.ItemModifier != null) return false;  // crafted/named — keep
            }
            catch { /* defensive — на сомнении заменяем */ }
            return true;
        }

        // Tier-aware item lookup — адаптация BLT SelectRandomItemNearestTier:
        // группируем по tier, берём ближайшую к target группу (см. ниже).
        //
        // Sprint 5.32 (BLT-parity M4) — optional nameFilter predicate для
        // family-type matching (camel vs horse mount/harness).
        //
        // 2026-05-29 (anti-duplicate, BLT EquipHero.cs:241/273): optional
        // excludeIds — StringId'ы предметов уже надетых в этом проходе. Сначала
        // пытаемся выбрать вне excludeIds (чтобы berserk/assassin не получили 2
        // одинаковых молота), и только если deduped-пул пуст — fallback на full
        // pool (BLT тоже допускает дубль как last-resort).
        private static ItemObject FindTieredItem(
            ItemObject.ItemTypeEnum type, int engineTier, Random rng,
            System.Func<string, bool> nameFilter = null,
            HashSet<string> excludeIds = null,
            Hero hero = null)
        {
            var pool = MBObjectManager.Instance
                .GetObjectTypeList<ItemObject>()
                ?.Where(i => i != null && i.ItemType == type)
                ?.Where(i => !i.NotMerchandise)
                ?.ToList();
            if (pool == null || pool.Count == 0) return null;

            // 2026-05-31 (Finding A) — для маунтов оставляем только верховых боевых
            // животных: исключаем мулов/вьючных (HorseComponent.IsPackAnimal) и
            // не-верховых. Раньше пул T.Horse тащил мулов → mounted-класс мог
            // выехать на муле без charge'а. Паттерн из CreatePartyHandler.
            if (type == T.Horse)
            {
                var mounts = pool
                    .Where(i => i.HorseComponent != null
                                && i.HorseComponent.IsRideable
                                && !i.HorseComponent.IsPackAnimal)
                    .ToList();
                if (mounts.Count > 0) pool = mounts;
            }

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

            // 2026-05-31 (BLT CanUseItem, гендер-часть) — не выдаём гендерно-
            // залоченный гир не тому полу. Fallback на полный пул если фильтр
            // опустошает. Skill-гейт НЕ делаем: у свежего героя skill <
            // Difficulty высокотировой шмотки → отфильтровал бы нужный гир.
            if (hero != null)
            {
                var usable = pool.Where(i => GearGenderOk(i, hero)).ToList();
                if (usable.Count > 0) pool = usable;
            }

            // Anti-duplicate first pass: исключаем уже надетое в этом проходе.
            if (excludeIds != null && excludeIds.Count > 0)
            {
                var deduped = pool.Where(i => !excludeIds.Contains(i.StringId ?? "")).ToList();
                var pick = PickNearestTier(deduped, engineTier, rng);
                if (pick != null) return pick;
                // deduped пуст (весь пул уже занят) → fall through на full pool.
            }
            return PickNearestTier(pool, engineTier, rng);
        }

        // 2026-05-31 — гендер-флаги предмета (BLT EquipHero.CanUseItem gender-часть).
        // true = пол героя может носить предмет.
        private static bool GearGenderOk(ItemObject item, Hero hero)
        {
            try
            {
                if (hero.IsFemale && item.ItemFlags.HasFlag(ItemFlags.NotUsableByFemale)) return false;
                if (!hero.IsFemale && item.ItemFlags.HasFlag(ItemFlags.NotUsableByMale)) return false;
            }
            catch { }
            return true;
        }

        // 2026-05-29 — адаптация BLT SelectRandomItemNearestTier
        // (EquipHero.cs:579). Группируем по tier, сортируем по близости к
        // target (ключ 100*|target-t| + t — при равной дистанции предпочитаем
        // НИЖНИЙ tier), берём random из ближайшей группы. Раньше last-resort был
        // random из всего пула → для T6-стрел (vanilla макс ~T4) выпадал
        // случайный T1. Теперь — ближайшая группа (T4).
        private static ItemObject PickNearestTier(List<ItemObject> pool, int engineTier, Random rng)
        {
            if (pool == null || pool.Count == 0) return null;
            var nearest = pool.GroupBy(i => (int)i.Tier)
                .OrderBy(g => Math.Abs(engineTier - g.Key))   // ближайший тир
                .ThenBy(g => g.Key)                            // при равенстве — ниже
                .FirstOrDefault();
            if (nearest == null) return null;
            var nearestList = nearest.ToList();
            return nearestList[rng.Next(nearestList.Count)];
        }
    }
}
