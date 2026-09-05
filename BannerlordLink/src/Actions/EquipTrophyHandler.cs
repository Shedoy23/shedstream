using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.29 / BLT-parity #6 Phase A — equip custom trophy into hero
    /// inventory как real vanilla ItemObject.
    ///
    /// Trophy метаданные приходят от backend (base_type / subtype / rarity / tier).
    /// Mod находит matching vanilla ItemObject из MBObjectManager pool'а:
    ///   1. Filter по ItemType (weapon → OneHandedWeapon/Bow/etc., armor → HeadArmor/etc.)
    ///   2. Filter по subtype (weapon: WeaponClass; armor/horse: same ItemType)
    ///   3. Filter по tier (rarity → ItemTier mapping)
    ///   4. Random pick из подходящих → AddToCounts в hero inventory
    ///
    /// Если фильтр пустой — fallback на random любой ItemType match.
    ///
    /// Custom name НЕ применяется к ItemObject (Bannerlord не поддерживает
    /// per-instance renaming без CustomItem registration). Custom_name виден
    /// только в нашем backend inventory UI как "trophy label". Future iteration
    /// добавит ItemModifier prefix (Balanced/Masterwork) для визуального buff'а.
    ///
    /// Data: {target, base_type, base_subtype, rarity, tier, custom_name}
    /// </summary>
    public class EquipTrophyHandler : IActionHandler
    {
        public string ActionType => "hero.equip_trophy";

        // ── base_subtype → WeaponClass mapping (для weapon trophy) ─────────
        private static readonly Dictionary<string, WeaponClass> WEAPON_SUBTYPE_MAP =
            new Dictionary<string, WeaponClass>(StringComparer.OrdinalIgnoreCase)
            {
                ["Меч"]      = WeaponClass.OneHandedSword,
                ["Топор"]    = WeaponClass.OneHandedAxe,
                ["Копьё"]    = WeaponClass.OneHandedPolearm,
                ["Молот"]    = WeaponClass.Mace,
                ["Лук"]      = WeaponClass.Bow,
                ["Арбалет"]  = WeaponClass.Crossbow,
                ["Кинжал"]   = WeaponClass.Dagger,
                ["Глефа"]    = WeaponClass.TwoHandedPolearm,
            };

        // ── base_subtype → ItemTypeEnum mapping (для armor) ─────────────────
        private static readonly Dictionary<string, ItemObject.ItemTypeEnum> ARMOR_SUBTYPE_MAP =
            new Dictionary<string, ItemObject.ItemTypeEnum>(StringComparer.OrdinalIgnoreCase)
            {
                ["Шлем"]      = ItemObject.ItemTypeEnum.HeadArmor,
                ["Кираса"]    = ItemObject.ItemTypeEnum.BodyArmor,
                ["Поножи"]    = ItemObject.ItemTypeEnum.LegArmor,
                ["Перчатки"]  = ItemObject.ItemTypeEnum.HandArmor,
                ["Плащ"]      = ItemObject.ItemTypeEnum.Cape,
            };

        // ── rarity → ItemObject.ItemTiers mapping ──────────────────────────
        private static readonly Dictionary<string, ItemObject.ItemTiers[]> RARITY_TIER_MAP =
            new Dictionary<string, ItemObject.ItemTiers[]>(StringComparer.OrdinalIgnoreCase)
            {
                ["common"]    = new[] { ItemObject.ItemTiers.Tier1, ItemObject.ItemTiers.Tier2 },
                ["uncommon"]  = new[] { ItemObject.ItemTiers.Tier2, ItemObject.ItemTiers.Tier3 },
                ["rare"]      = new[] { ItemObject.ItemTiers.Tier3, ItemObject.ItemTiers.Tier4 },
                ["epic"]      = new[] { ItemObject.ItemTiers.Tier4, ItemObject.ItemTiers.Tier5 },
                ["legendary"] = new[] { ItemObject.ItemTiers.Tier5, ItemObject.ItemTiers.Tier6 },
            };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();

            // Sprint 5.33 (BLT-parity ITEM) — register trophy bonuses в
            // ActiveTrophyState. DamageHookPatch.Prefix будет читать на каждом
            // blow для apply'а damage_bonus / armor_bonus.
            try
            {
                int dmgBonus = (int?)data["damage_bonus"] ?? 0;
                int armBonus = (int?)data["armor_bonus"] ?? 0;
                float weightF = (float?)data["weight_factor"] ?? 1.0f;
                float speedF = (float?)data["speed_factor"] ?? 1.0f;
                string regName = data["custom_name"]?.ToString() ?? "?";
                string regBaseType = (data["base_type"]?.ToString() ?? "").ToLowerInvariant();

                if (!string.IsNullOrEmpty(username) &&
                    (dmgBonus > 0 || armBonus > 0 ||
                     Math.Abs(weightF - 1.0f) > 0.001f || Math.Abs(speedF - 1.0f) > 0.001f))
                {
                    BannerlordLink.Net.ActiveTrophyState.Register(username,
                        new BannerlordLink.Net.ActiveTrophyState.TrophyStats
                        {
                            DamageBonus = dmgBonus,
                            ArmorBonus = armBonus,
                            WeightFactor = weightF,
                            SpeedFactor = speedF,
                            CustomName = regName,
                            BaseType = regBaseType,
                        });
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[hero.equip_trophy] @{username} trophy register warn: {ex.Message}");
            }

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target"));

            string baseType    = (data["base_type"]?.ToString()    ?? "").Trim().ToLowerInvariant();
            string baseSubtype = (data["base_subtype"]?.ToString() ?? "").Trim();
            string rarity      = (data["rarity"]?.ToString()       ?? "common").Trim().ToLowerInvariant();
            string customName  = (data["custom_name"]?.ToString()  ?? "Trophy").Trim();

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
                Equip(username, baseType, baseSubtype, rarity, customName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Equip(string username, string baseType, string baseSubtype,
            string rarity, string customName, string actionId)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[equip_trophy] REFUSE @{username}: hero не найден / мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                // 2026-05-31 (audit) — off-mission гард: нельзя писать BattleEquipment
                // на живом Agent во время Mission (stale equipment → null-deref на
                // следующей атаке). Как в прочих equip-хендлерах.
                if (TaleWorlds.MountAndBlade.Mission.Current != null)
                {
                    BannerlordLinkModule.Log($"[equip_trophy] REFUSE @{username}: нельзя надеть во время Mission");
                    ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                // Get target party — viewer's hero PartyBelongedTo или MainParty.
                ItemRoster roster = null;
                var party = hero.PartyBelongedTo;
                if (party != null) roster = party.ItemRoster;
                if (roster == null)
                {
                    // Fallback: hero без party (notable в settlement) → отдаём в MainParty
                    roster = MobileParty.MainParty?.ItemRoster;
                }
                if (roster == null)
                {
                    BannerlordLinkModule.Log(
                        $"[equip_trophy] REFUSE @{username}: no item roster (party=null, MainParty=null)");
                    ActionFeedback.PostFailed(actionId, "no_inventory");
                    return;
                }

                // Find matching item.
                ItemObject picked = FindMatchingItem(baseType, baseSubtype, rarity);
                if (picked == null)
                {
                    BannerlordLinkModule.Log(
                        $"[equip_trophy] REFUSE @{username}: no matching ItemObject " +
                        $"(base={baseType} subtype={baseSubtype} rarity={rarity})");
                    ActionFeedback.PostFailed(actionId, "no_matching_item");
                    return;
                }

                // 2026-05-29 FIX («одеть не работало»): раньше делали
                // roster.AddToCounts → предмет падал в инвентарь party (а для
                // party-less adopted hero — в MainParty стримера), на героя НЕ
                // надевался → "ничего не произошло". Теперь НАДЕВАЕМ на тело
                // героя через BattleEquipment[slot] (reuse EquipItemHandler.ResolveSlot).
                EquipmentIndex idx = EquipItemHandler.ResolveSlot(picked, null, hero);
                if (idx == EquipmentIndex.None)
                {
                    // Fallback: слот не определён (редко) → в inventory как раньше.
                    roster.AddToCounts(picked, 1);
                    BannerlordLinkModule.Log(
                        $"[equip_trophy] @{username} slot undeterminable для " +
                        $"{picked.StringId} → AddToCounts fallback");
                }
                else
                {
                    // Modifier-guard: не затираем именную/смитованную шмотку.
                    bool blocked = false;
                    try
                    {
                        var cur = hero.BattleEquipment[idx];
                        if (!cur.IsEmpty && cur.ItemModifier != null) blocked = true;
                    }
                    catch { }
                    if (blocked)
                    {
                        roster.AddToCounts(picked, 1);
                        BannerlordLinkModule.Log(
                            $"[equip_trophy] @{username}: slot {idx} занят модифицированным " +
                            $"предметом → трофей в inventory (не затираем)");
                    }
                    else
                    {
                        hero.BattleEquipment[idx] = new EquipmentElement(picked);
                        BannerlordLinkModule.Log(
                            $"[equip_trophy] @{username} НАДЕЛ {picked.Name?.ToString() ?? picked.StringId} " +
                            $"(трофей «{customName}» {rarity} T{picked.Tier}) → slot {idx}");
                    }
                }

                // Sprint 5.31 #45g (codegraph audit MED-4) — push equipment_changed.
                // Раньше success path не пушил event → backend cache stale до
                // следующего HeroStateSync. Sync через unified hero state push.
                try { BannerlordLink.Util.HeroStateSync.Push(hero); }
                catch (Exception syncEx)
                {
                    BannerlordLinkModule.Log(
                        $"[equip_trophy] @{username} HeroStateSync push failed: {syncEx.Message}");
                }
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[equip_trophy] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "exception:" + ex.GetType().Name);
            }
        }

        /// <summary>Find ItemObject matching trophy spec. Returns null если pool пуст.</summary>
        private static ItemObject FindMatchingItem(string baseType, string baseSubtype, string rarity)
        {
            var allItems = MBObjectManager.Instance.GetObjectTypeList<ItemObject>();
            if (allItems == null || allItems.Count == 0) return null;

            IEnumerable<ItemObject> pool = allItems.Where(i =>
                i != null && i.StringId != null
                && !i.NotMerchandise   // filter quest/special items
                && i.Type != ItemObject.ItemTypeEnum.Banner);

            // 1) Filter по base_type.
            if (baseType == "weapon")
            {
                if (WEAPON_SUBTYPE_MAP.TryGetValue(baseSubtype, out var wc))
                {
                    pool = pool.Where(i =>
                        i.Weapons != null
                        && i.Weapons.Any(w => w != null && w.WeaponClass == wc));
                }
                else
                {
                    pool = pool.Where(i =>
                        i.Type == ItemObject.ItemTypeEnum.OneHandedWeapon
                        || i.Type == ItemObject.ItemTypeEnum.TwoHandedWeapon
                        || i.Type == ItemObject.ItemTypeEnum.Polearm
                        || i.Type == ItemObject.ItemTypeEnum.Bow
                        || i.Type == ItemObject.ItemTypeEnum.Crossbow
                        || i.Type == ItemObject.ItemTypeEnum.Thrown);
                }
            }
            else if (baseType == "armor")
            {
                if (ARMOR_SUBTYPE_MAP.TryGetValue(baseSubtype, out var atype))
                {
                    pool = pool.Where(i => i.Type == atype);
                }
                else
                {
                    pool = pool.Where(i =>
                        i.Type == ItemObject.ItemTypeEnum.HeadArmor
                        || i.Type == ItemObject.ItemTypeEnum.BodyArmor
                        || i.Type == ItemObject.ItemTypeEnum.LegArmor
                        || i.Type == ItemObject.ItemTypeEnum.HandArmor
                        || i.Type == ItemObject.ItemTypeEnum.Cape);
                }
            }
            else if (baseType == "horse")
            {
                pool = pool.Where(i => i.Type == ItemObject.ItemTypeEnum.Horse);
            }

            var byType = pool.ToList();
            if (byType.Count == 0) return null;

            // 2) Filter по tier (rarity → tier range). Если пусто — fallback к any.
            if (RARITY_TIER_MAP.TryGetValue(rarity, out var tiers))
            {
                var byTier = byType.Where(i => tiers.Contains(i.Tier)).ToList();
                if (byTier.Count > 0)
                    return byTier[new Random().Next(byTier.Count)];
            }

            // Fallback: any matching item (rarity tier filter был too strict).
            return byType[new Random().Next(byType.Count)];
        }
    }
}
