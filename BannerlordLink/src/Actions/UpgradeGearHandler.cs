using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// `hero.upgrade_gear` — прокачка снаряжения по 6-tier системе.
    ///
    /// data: { target, class_key, target_tier }
    ///   class_key — текущий class viewer'а (передаётся backend'ом из БД).
    ///   target_tier — 1..6 (user-facing). Engine tier = target_tier - 1.
    ///
    /// Class spec + item picker живут в ClassLoadout (общие с SetClassHandler/
    /// ReequipGearHandler) — single source of truth, mirror M15 seed.
    ///
    /// Flow:
    ///   1. Skip если Mission.Current != null (battle equipment locked).
    ///   2. Resolve Hero, validate alive + достаточно Hero.Gold.
    ///   3. ApplyGearLoadout — weapons (WeaponClass-aware) + armor (вес-band +
    ///      skip-слоты) + mount по class config на target tier.
    ///   4. Списать Hero.Gold, push gear_tier_changed + state/equipment sync.
    ///
    /// BLT inspired (EquipHero.cs UpgradeEquipment) — clean-room re-impl.
    /// </summary>
    public class UpgradeGearHandler : IActionHandler
    {
        public string ActionType => "hero.upgrade_gear";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string classKey = (data["class_key"]?.ToString() ?? "").Trim().ToLowerInvariant();
            int targetTier = (int?)data["target_tier"] ?? 0;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(classKey) || !ClassLoadout.Classes.ContainsKey(classKey))
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

                // 2026-07-29 (багрепорт #42) — ТИХИЙ ПЛАТНЫЙ NO-OP.
                // Раньше `slotsFilled` считался, но использовался только в логе:
                // золото списывалось, `hero.gear_tier_changed` уходил на бэкенд и
                // тир рос ДАЖЕ ЕСЛИ не заменился ни один слот. Зритель платил до
                // 1 500 000 динаров и не получал ничего, а тир в базе «убегал»
                // вперёд — следующая покупка целилась ещё выше и повторяла то же.
                // Правило CLAUDE.md: платное действие обязано детектить тихий
                // no-op ДО ack-true, и детект — по НАБЛЮДАЕМОМУ эффекту.
                // Здесь наблюдаемый эффект и есть число заменённых слотов.
                if (slotsFilled <= 0)
                {
                    BannerlordLinkModule.Log(
                        $"[upgrade_gear] REFUSE @{username} → T{targetTier} ({classKey}): " +
                        $"0 слотов заменено — снаряжение не изменилось, деньги НЕ списаны");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "gear_no_change");
                    return;
                }

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

                // 2026-06-15 — per-save профиль (восстановится на backend при загрузке сейва).
                BannerlordLink.Behaviors.HeroProfileBehavior.Instance?.SetGearTier(username, targetTier);

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
        // 2026-06-18 — теперь читает ClassLoadout (WeaponClass-фильтр оружия +
        // armor weight band + skip-слоты), чтобы upgrade/reequip давали тот же
        // class-aware результат, что и set_class.
        internal static int ApplyGearLoadout(Hero hero, string classKey, int engineTier,
            bool stripArmorModifiers = false)
        {
            if (hero == null || classKey == null || !ClassLoadout.Classes.TryGetValue(classKey, out var cfg))
                return 0;
            var rng = new Random();
            var equipment = hero.BattleEquipment;
            int slotsFilled = 0;

            // ── 1. Weapon slots по class config (WeaponClass-aware, анти-дубль) ──
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
                var slot = cfg.Slots[i];
                var slotType = slot.Type;
                if (slotType == ClassLoadout.Invalid)
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

                var item = ClassLoadout.FindTieredItem(slotType, engineTier, rng, null, usedWeaponIds, hero, slot.Wc);
                if (item != null && ShouldReplaceSlot(equipment, (EquipmentIndex)i, engineTier))
                {
                    equipment[(EquipmentIndex)i] = new EquipmentElement(item);
                    usedWeaponIds.Add(item.StringId ?? "");
                    slotsFilled++;
                }
            }

            // ── 2. Armor slots — вес-band из cfg + skip-слоты (частичная броня) ──
            foreach (var (idx, type) in ClassLoadout.ArmorSlots)
            {
                // partial-armor (berserk = no helmet) — skip: чистим non-modifier stale.
                if (cfg.SkipArmorSlots != null && Array.IndexOf(cfg.SkipArmorSlots, idx) >= 0)
                {
                    try
                    {
                        var cur = equipment[idx];
                        if (cur.IsEmpty || cur.ItemModifier == null)
                            equipment[idx] = EquipmentElement.Invalid;
                    }
                    catch { }
                    continue;
                }
                var item = ClassLoadout.FindTieredItem(type, engineTier, rng, null, null, hero, null, cfg.Armor, cfg.CultureId);
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
                var horse = ClassLoadout.FindTieredItem(ClassLoadout.HorseType, engineTier, rng, mountFilter, null, hero);
                if (horse != null && ShouldReplaceSlot(equipment, EquipmentIndex.Horse, engineTier))
                {
                    equipment[EquipmentIndex.Horse] = new EquipmentElement(horse);
                    slotsFilled++;
                }
                var harness = ClassLoadout.FindTieredItem(ClassLoadout.HorseHarnessType, engineTier, rng, mountFilter, null, hero);
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
    }
}
