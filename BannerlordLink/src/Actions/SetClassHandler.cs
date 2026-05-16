using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Net;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `hero.set_class` — применяет equipment template
    /// к hero на основе выбранного класса.
    ///
    /// Backend сам уже UPSERT'ил выбор в bannerlord_hero_class. Mod
    /// здесь только PHYSICAL apply — find random items нужного типа из
    /// ItemObject pool и equip их в slots.
    ///
    /// data: { target, class_key }
    /// class_key mapping → (slots[4] item types, use_horse, use_camel)
    /// — hardcoded ниже, mirror M15 seed.
    /// </summary>
    public class SetClassHandler : IActionHandler
    {
        public string ActionType => "hero.set_class";

        /// <summary>Class config — параллель M15 seed на C# стороне.</summary>
        private class ClassConfig
        {
            public ItemObject.ItemTypeEnum[] Slots;
            public bool UseHorse;
            public bool UseCamel;
        }

        // Mapping class_key → ClassConfig. Должен матчиться с M15.
        private static readonly Dictionary<string, ClassConfig> _classes =
            new Dictionary<string, ClassConfig>
        {
            ["tank"]            = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Shield, T.Invalid, T.Invalid } },
            ["archer"]          = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.Invalid, T.Invalid } },
            ["heavy_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.Shield, T.OneHandedWeapon } },
            ["crossbow"]        = new ClassConfig { Slots = new[] { T.Crossbow, T.Bolts, T.Invalid, T.Invalid } },
            ["heavy_crossbow"]  = new ClassConfig { Slots = new[] { T.Crossbow, T.Bolts, T.Shield, T.OneHandedWeapon } },
            ["cavalry"]         = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseHorse = true },
            ["camel_cavalry"]   = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Polearm, T.Shield, T.Invalid }, UseCamel = true },
            ["horse_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Invalid }, UseHorse = true },
            ["camel_archer"]    = new ClassConfig { Slots = new[] { T.Bow, T.Arrows, T.OneHandedWeapon, T.Invalid }, UseCamel = true },
            ["psycho"]          = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.Invalid, T.Invalid, T.Invalid } },
            ["berserk"]         = new ClassConfig { Slots = new[] { T.TwoHandedWeapon, T.TwoHandedWeapon, T.Invalid, T.Invalid } },
            ["assassin"]        = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.OneHandedWeapon, T.Thrown, T.Invalid } },
            ["knight"]          = new ClassConfig { Slots = new[] { T.OneHandedWeapon, T.Shield, T.Polearm, T.Invalid }, UseHorse = true },
        };

        // Alias чтобы код был читаемее
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

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string classKey = (data["class_key"]?.ToString() ?? "").Trim().ToLowerInvariant();

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(classKey) || !_classes.ContainsKey(classKey))
                return Task.FromResult<(bool, string)>((false, $"unknown class '{classKey}'"));

            MainThreadDispatcher.Enqueue(() => ApplyClass(username, classKey));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void ApplyClass(string username, string classKey)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[set_class] @{username}: hero не найден или мёртв");
                    return;
                }
                var cfg = _classes[classKey];

                // Pool вещей по типу — vanilla items.
                // Cache по типу чтобы не сканить ItemObject.All на каждом slot.
                var rng = new Random();
                var equipment = hero.BattleEquipment;

                // 4 weapon slots
                for (int i = 0; i < 4 && i < cfg.Slots.Length; i++)
                {
                    var slotType = cfg.Slots[i];
                    if (slotType == T.Invalid) continue;

                    var item = FindRandomItem(slotType, rng);
                    if (item == null)
                    {
                        BannerlordLinkModule.Log($"[set_class] @{username}: no item для {slotType} (slot {i})");
                        continue;
                    }
                    equipment[(EquipmentIndex)i] = new EquipmentElement(item);
                }

                // Mount slot (Horse / Camel)
                ItemObject mount = null;
                if (cfg.UseHorse)
                    mount = FindRandomItem(T.Horse, rng, name => !name.Contains("camel"));
                else if (cfg.UseCamel)
                    mount = FindRandomItem(T.Horse, rng, name => name.Contains("camel"));
                // (T.Horse покрывает оба — Camel это subtype в vanilla 1.3.x)

                if (mount != null)
                {
                    equipment[EquipmentIndex.Horse] = new EquipmentElement(mount);
                }

                BannerlordLinkModule.Log(
                    $"[set_class] @{username} → {classKey} (mount={mount?.StringId ?? "—"})");

                // Sprint 4.2: update PowerCache immediately + refresh from backend
                // (на случай если class_level изменился). Skill boosts применяем
                // здесь (persistent на hero), HP/scale — в MissionLogic.
                PowerCache.UpdateHero(username, classKey, 1);
                ApplyClassSkillBoosts(hero, classKey);

                // Async refresh full cache (для других viewers тоже)
                _ = Task.Run(async () =>
                    await PowerCache.RefreshAsync(BannerlordLinkModule.Backend));

                // Push equipment snapshot — backend bannerlord_equipment +
                // frontend hero card обновятся.
                EquipmentSync.PushAll(hero);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[set_class] @{username} CRASHED: {ex.Message}");
            }
        }

        /// <summary>Apply *_skill_boost powers как persistent skill levels.
        /// HP/scale остаются для MissionLogic (per-spawn). Skills — на hero
        /// permanently т.к. это в campaign view тоже отображается.</summary>
        private static void ApplyClassSkillBoosts(Hero hero, string classKey)
        {
            // Mapping our power_key suffix → DefaultSkills property name
            var skillMap = new Dictionary<string, string>
            {
                ["one_handed_skill_boost"]  = "OneHanded",
                ["two_handed_skill_boost"]  = "TwoHanded",
                ["polearm_skill_boost"]     = "Polearm",
                ["bow_skill_boost"]         = "Bow",
                ["crossbow_skill_boost"]    = "Crossbow",
                ["throwing_skill_boost"]    = "Throwing",
                ["riding_skill_boost"]      = "Riding",
                ["athletic_skill_boost"]    = "Athletics",
            };

            string username = hero.Name?.ToString()?.ToLowerInvariant();
            if (string.IsNullOrEmpty(username)) return;

            foreach (var pair in skillMap)
            {
                var val = PowerCache.GetPowerValue(username, pair.Key);
                if (!val.HasValue || val.Value <= 0) continue;

                try
                {
                    var prop = typeof(TaleWorlds.Core.DefaultSkills).GetProperty(pair.Value);
                    var skill = prop?.GetValue(null) as TaleWorlds.Core.SkillObject;
                    if (skill == null) continue;
                    int targetLvl = (int)val.Value;
                    int current = hero.GetSkillValue(skill);
                    if (targetLvl > current)
                    {
                        hero.HeroDeveloper.SetInitialSkillLevel(skill, targetLvl);
                        BannerlordLinkModule.Log(
                            $"[set_class] @{username} {pair.Value} boosted {current} → {targetLvl}");
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[set_class] skill {pair.Key} apply error: {ex.Message}");
                }
            }
        }

        private static ItemObject FindRandomItem(
            ItemObject.ItemTypeEnum type,
            Random rng,
            Func<string, bool> nameFilter = null)
        {
            var pool = MBObjectManager.Instance
                .GetObjectTypeList<ItemObject>()
                ?.Where(i => i != null && i.ItemType == type)
                ?.Where(i => !i.NotMerchandise)  // skip quest-only items
                ?.ToList();
            if (pool == null || pool.Count == 0) return null;

            if (nameFilter != null)
            {
                var filtered = pool
                    .Where(i => nameFilter(i.StringId?.ToLowerInvariant() ?? ""))
                    .ToList();
                if (filtered.Count > 0) pool = filtered;
            }

            return pool[rng.Next(pool.Count)];
        }
    }
}
