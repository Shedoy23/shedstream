using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using BannerlordLink.Net;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

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
    /// Class spec + item picker живут в ClassLoadout (общие с UpgradeGearHandler/
    /// ReequipGearHandler) — single source of truth, mirror M15 seed.
    /// </summary>
    public class SetClassHandler : IActionHandler
    {
        public string ActionType => "hero.set_class";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string classKey = (data["class_key"]?.ToString() ?? "").Trim().ToLowerInvariant();
            // Sprint 5.10c: gear_tier passed from backend — preserve прогрессию
            // при class change. user-facing tier (1..6), 0 = базовое.
            int gearTier = (int?)data["gear_tier"] ?? 0;
            if (gearTier < 0) gearTier = 0;
            if (gearTier > 6) gearTier = 6;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(classKey) || !ClassLoadout.Classes.ContainsKey(classKey))
                return Task.FromResult<(bool, string)>((false, $"unknown class '{classKey}'"));

            // Sprint 5.32 (BLT-parity H7) — pass actionId для refund-on-refuse.
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => ApplyClass(username, classKey, gearTier, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void ApplyClass(string username, string classKey, int gearTier, string actionId)
        {
            try
            {
                // Sprint 5.32 (BLT-parity H7) — Mission guard. BLT pattern
                // (SetHeroClass.cs:68-72) — `You cannot change class, as a
                // mission is active!`. Без guard'а равно equipment swap
                // на active Agent → engine использует stale equipment до
                // respawn'а, на следующем attack'е может null-deref.
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[set_class] REFUSE @{username}: нельзя сменить класс во время Mission " +
                        $"(mode={Mission.Current.Mode})");
                    ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[set_class] @{username}: hero не найден или мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }
                var cfg = ClassLoadout.Classes[classKey];

                // 2026-06-15 — пишем class_key + gear_tier в per-save профиль (SyncData),
                // чтобы на загрузке этого сейва они восстановились на backend (а не
                // показывались из другого playthrough). gear_tier ловим и тут (не только
                // на upgrade_gear): иначе классованный-но-не-апгрейженный герой не имел
                // бы тира в профиле → залипал бы тир другого сейва.
                BannerlordLink.Behaviors.HeroProfileBehavior.Instance?.SetClass(username, classKey);
                BannerlordLink.Behaviors.HeroProfileBehavior.Instance?.SetGearTier(username, gearTier);

                // Sprint 5.10c: engine tier = user-tier - 1 (0..5). Tier=0
                // (user "базовое") → engine tier 0 (cheapest items).
                int engineTier = Math.Max(0, gearTier - 1);
                var rng = new Random();
                var equipment = hero.BattleEquipment;

                // Sprint 5.32 (BLT-parity M8) — preserve tier-5/6 (modifier'нутые)
                // предметы при class change. BLT pattern: если slot занят smithed/
                // Lordly/Masterwork item'ом, viewer вложил много динаров / крустиков —
                // не затирать random T1-T2 шмотом при class change. Старый код
                // безусловно overwrites → теряются legendary item'ы.
                int preservedSlots = 0;

                // Anti-duplicate (BLT EquipHero.cs:241): seed уже надетыми
                // weapon'ами (вкл. preserved modifier-предметы) + добавляем
                // каждый выбранный → классы с двумя слотами одного типа
                // (berserk=2×2H, assassin=2×1H) не получат 2 одинаковых молота.
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

                // 4 weapon slots
                for (int i = 0; i < 4 && i < cfg.Slots.Length; i++)
                {
                    var slot = cfg.Slots[i];
                    var slotType = slot.Type;
                    if (slotType == ClassLoadout.Invalid)
                    {
                        // 2026-05-31 FIX — слот не используется этим классом.
                        // Раньше тут был голый `continue` → старое оружие висело
                        // (archer→berserk: лук/колчан оставались в slot 2-3).
                        // Чистим обычный гир; modifier'нутый (legendary) сохраняем
                        // — вложение зрителя не теряем (M8-консистентно).
                        try
                        {
                            var stale = equipment[(EquipmentIndex)i];
                            if (stale.IsEmpty || stale.ItemModifier == null)
                                equipment[(EquipmentIndex)i] = EquipmentElement.Invalid;
                            else
                                preservedSlots++;
                        }
                        catch { }
                        continue;
                    }

                    // Preserve modifier'нутый slot.
                    try
                    {
                        var current = equipment[(EquipmentIndex)i];
                        if (!current.IsEmpty && current.ItemModifier != null)
                        {
                            preservedSlots++;
                            BannerlordLinkModule.Log(
                                $"[set_class M8] @{username}: slot {i} preserved " +
                                $"({current.Item?.Name?.ToString() ?? "?"} " +
                                $"mod={current.ItemModifier.StringId})");
                            continue;
                        }
                    }
                    catch { }

                    var item = ClassLoadout.FindTieredItem(slotType, engineTier, rng, null, usedWeaponIds, hero, slot.Wc);
                    if (item == null)
                    {
                        BannerlordLinkModule.Log($"[set_class] @{username}: no item для {slotType} (slot {i})");
                        continue;
                    }
                    equipment[(EquipmentIndex)i] = new EquipmentElement(item);
                    usedWeaponIds.Add(item.StringId ?? "");
                }

                // Mount slot — конным классам ставим/сохраняем маунт, пешим —
                // ЯВНО снимаем коня + барду. Без этого при смене конница→пеший
                // класс старый конь оставался в экипировке, и движок по нему
                // держал героя в кавалерийской формации (2026-05-29 fix).
                ItemObject mount = null;
                if (cfg.UseHorse || cfg.UseCamel)
                {
                    bool mountPreserved = false;
                    try
                    {
                        var currMount = equipment[EquipmentIndex.Horse];
                        if (!currMount.IsEmpty && currMount.ItemModifier != null)
                        {
                            mountPreserved = true;
                            preservedSlots++;
                            BannerlordLinkModule.Log(
                                $"[set_class M8] @{username}: mount preserved " +
                                $"({currMount.Item?.Name?.ToString() ?? "?"} " +
                                $"mod={currMount.ItemModifier.StringId})");
                        }
                    }
                    catch { }
                    if (!mountPreserved)
                    {
                        if (cfg.UseHorse)
                            mount = ClassLoadout.FindTieredItem(ClassLoadout.HorseType, engineTier, rng, name => !name.Contains("camel"), null, hero);
                        else if (cfg.UseCamel)
                            mount = ClassLoadout.FindTieredItem(ClassLoadout.HorseType, engineTier, rng, name => name.Contains("camel"), null, hero);
                        // (Horse покрывает оба — Camel это subtype в vanilla 1.3.x)

                        if (mount != null)
                        {
                            equipment[EquipmentIndex.Horse] = new EquipmentElement(mount);
                        }
                    }
                }
                else
                {
                    // Пеший класс — снять коня и барду, иначе формация останется
                    // кавалерийской (см. ResolveFormationClass / GetFormationClass).
                    try
                    {
                        equipment[EquipmentIndex.Horse] = EquipmentElement.Invalid;
                        equipment[EquipmentIndex.HorseHarness] = EquipmentElement.Invalid;
                    }
                    catch { }
                }

                // BLT-PARITY (2026-05-28) — armor slots ARE NOT optional.
                // Sprint 5.10b stripped armor в AdoptHeroHandler, intent был
                // «viewer получит шмот через set_class» — но реализовано было
                // только 4 weapons + mount. Armor (Head/Body/Leg/Gloves/Cape)
                // остался пустым → viewer голый в бою.
                //
                // BLT pattern: SetClass → автоматически UpgradeEquipment(tier).
                // У нас: набиваем armor здесь, чтобы set_class давал complete
                // outfit (как у viewer'а ожидание после "выбрал класс").
                // Modifier preservation работает же по pattern weapon slots.
                // 2026-06-18 — armor band (вес) + skip-слоты (частичная броня)
                // из ClassLoadout.Config; слоты — общий ClassLoadout.ArmorSlots.
                int armorEquipped = 0, armorPreserved = 0;
                foreach (var slot in ClassLoadout.ArmorSlots)
                {
                    try
                    {
                        var current = equipment[slot.idx];
                        // Preserve modifier'нутый armor (M8 pattern).
                        if (!current.IsEmpty && current.ItemModifier != null)
                        {
                            armorPreserved++;
                            continue;
                        }
                        // 2026-06-18 — partial-armor classes (berserk = no helmet) skip
                        // configured slots: clear non-modifier stale → bare slot.
                        if (cfg.SkipArmorSlots != null && Array.IndexOf(cfg.SkipArmorSlots, slot.idx) >= 0)
                        {
                            equipment[slot.idx] = EquipmentElement.Invalid;
                            continue;
                        }
                        var item = ClassLoadout.FindTieredItem(slot.type, engineTier, rng, null, null, hero, null, cfg.Armor);
                        if (item != null)
                        {
                            equipment[slot.idx] = new EquipmentElement(item);
                            armorEquipped++;
                        }
                    }
                    catch (Exception aex)
                    {
                        BannerlordLinkModule.Log(
                            $"[set_class] armor slot {slot.idx} apply error: {aex.Message}");
                    }
                }
                if (armorEquipped > 0 || armorPreserved > 0)
                    BannerlordLinkModule.Log(
                        $"[set_class] @{username}: armor T{gearTier} → " +
                        $"{armorEquipped} equipped, {armorPreserved} preserved (modifier'нутые)");

                if (preservedSlots > 0)
                    BannerlordLinkModule.Log(
                        $"[set_class M8] @{username}: preserved {preservedSlots} " +
                        $"modifier'нутых slot'ов через class change");

                BannerlordLinkModule.Log(
                    $"[set_class] @{username} → {classKey} (T{gearTier}, mount={mount?.StringId ?? "—"})");

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

            string username = BannerlordLink.Util.HeroNaming.ExtractUsername(hero.Name?.ToString());
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
    }
}
