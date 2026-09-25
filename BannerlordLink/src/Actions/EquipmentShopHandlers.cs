using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    public sealed class EquipmentShopHandler : IActionHandler
    {
        public string ActionType { get; }
        public EquipmentShopHandler(string type) { ActionType = type; }

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            MainThreadDispatcher.Enqueue(() => Apply(data));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private void Apply(JObject data)
        {
            string actionId = ActionFeedback.GetActionId(data);
            Hero hero = null;
            int charged = 0;
            int credited = 0;
            Equipment original = null;
            var rosterMutations = new List<Tuple<TaleWorlds.CampaignSystem.Roster.ItemRoster, EquipmentElement, int>>();
            bool committed = false;
            try
            {
                bool equipPurchase = ActionType == "hero.buy_equipment" && (bool?)data["equip_now"] == true;
                // Buying and discarding stored items do not touch battle equipment.
                // Equipping, unequipping, and discarding an equipped item must wait.
                if (Mission.Current != null && (equipPurchase || (ActionType != "hero.buy_equipment" && ActionType != "hero.discard_owned")))
                { ActionFeedback.PostFailed(actionId, "in_mission"); return; }
                string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
                hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
                if (hero.IsPrisoner) { ActionFeedback.PostFailed(actionId, "hero_prisoner"); return; }
                if (equipPurchase && EquipmentShopBehavior.PartyInventory(hero) != null) { ActionFeedback.PostFailed(actionId, "inventory_state_changed"); return; }
                if (Campaign.Current == null || data["save_id"]?.ToString() != Campaign.Current.UniqueGameId
                    || data["hero_id"]?.ToString() != hero.StringId)
                { ActionFeedback.PostFailed(actionId, "stale_hero_session"); return; }
                var behavior = EquipmentShopBehavior.Instance;
                if (behavior == null) { ActionFeedback.PostFailed(actionId, "inventory_unavailable"); return; }
                if (data["equipment_session_id"]?.ToString() != behavior.SessionId)
                { ActionFeedback.PostFailed(actionId, "stale_equipment_session"); return; }
                var ledger = behavior.Read(hero);

                if (ActionType == "hero.buy_equipment")
                {
                    var item = MBObjectManager.Instance.GetObject<ItemObject>(data["item_id"]?.ToString() ?? "");
                    if (!EquipmentShopBehavior.Sellable(item)) { ActionFeedback.PostFailed(actionId, "item_unavailable"); return; }
                    int required = EquipmentShopPolicy.RequiredLevel(EquipmentShopPolicy.PublicTier((int)item.Tier));
                    if (hero.Level < required) { ActionFeedback.PostFailed(actionId, "equipment_level_locked"); return; }
                    int price = EquipmentShopPolicy.Price(item.Value);
                    if ((int?)data["price_gold"] != price) { ActionFeedback.PostFailed(actionId, "equipment_price_changed"); return; }
                    if (equipPurchase)
                    {
                        string slot = data["slot"]?.ToString() ?? "";
                        var index = EquipmentSync.SlotFromName(slot);
                        if (!index.HasValue || !EquipmentShopBehavior.Slots(item).Contains(slot))
                        { ActionFeedback.PostFailed(actionId, "incompatible_equipment_slot"); return; }
                        if (!EquipmentShopBehavior.MountCompatible(hero, item, slot))
                        { ActionFeedback.PostFailed(actionId, "incompatible_mount_harness"); return; }
                        var displaced = hero.BattleEquipment[index.Value];
                        if (data["expected_item_id"]?.ToString() != (displaced.Item?.StringId ?? "")
                            || data["expected_modifier_id"]?.ToString() != (displaced.ItemModifier?.StringId ?? ""))
                        { ActionFeedback.PostFailed(actionId, "equipment_changed"); return; }
                        int tradeIn = displaced.IsEmpty ? 0 : Math.Max(0, displaced.ItemValue);
                        if ((int?)data["trade_in_gold"] != tradeIn)
                        { ActionFeedback.PostFailed(actionId, "equipment_price_changed"); return; }
                        int netPrice = price - tradeIn;
                        int surplus = Math.Max(0, -netPrice);
                        if ((long)hero.Gold + surplus > int.MaxValue)
                        { ActionFeedback.PostFailed(actionId, "gold_limit_reached"); return; }
                        original = new Equipment(hero.BattleEquipment);
                        var charge = new JObject { ["hero_gold_cost"] = Math.Max(0, netPrice) };
                        if (!HeroGoldCharge.TryCharge(hero, charge, actionId, ActionType, out charged)) return;
                        hero.BattleEquipment[index.Value] = new EquipmentElement(item);
                        var applied = hero.BattleEquipment[index.Value];
                        if (applied.Item != item || applied.ItemModifier != null) throw new InvalidOperationException("equipment_apply_failed");
                        if (surplus > 0)
                        {
                            int before = hero.Gold;
                            try { GiveGoldAction.ApplyBetweenCharacters(null, hero, surplus, true); }
                            finally { credited = hero.Gold - before; }
                            if (credited != surplus) throw new InvalidOperationException("trade_in_credit_failed");
                        }
                        ledger.Items.RemoveAll(x => x.Slot == slot);
                        ledger.Observe(slot, item.StringId, null);
                        behavior.Store(hero, ledger);
                        committed = true;
                        BannerlordLinkModule.Log($"[{ActionType}] @{username} item={item.StringId} slot={slot} trade={displaced.Item?.StringId} sale={tradeIn} gold_delta={-netPrice}");
                    }
                    else
                    {
                    // Без своего отряда покупка ложится в личный сундук героя (25.09).
                    var roster = EquipmentShopBehavior.PartyInventory(hero);
                    if (roster == null && ledger.StashCount() >= EquipmentShopPolicy.StashCapacity)
                    { ActionFeedback.PostFailed(actionId, "stash_full"); return; }
                    var charge = new JObject { ["hero_gold_cost"] = price };
                    if (!HeroGoldCharge.TryCharge(hero, charge, actionId, ActionType, out charged)) return;
                    if (roster != null)
                    {
                        roster.AddToCounts(new EquipmentElement(item), 1);
                        rosterMutations.Add(Tuple.Create(roster, new EquipmentElement(item), 1));
                    }
                    else ledger.Add(item.StringId);
                    behavior.Store(hero, ledger);
                    committed = true;
                    BannerlordLinkModule.Log($"[{ActionType}] @{username} item={item.StringId} → {(roster != null ? "party inventory" : "личный сундук")} gold=-{charged}");
                    }
                }
                else if (ActionType == "hero.discard_owned")
                {
                    if (data["source"]?.ToString() == "party")
                    {
                        var item = MBObjectManager.Instance.GetObject<ItemObject>(data["item_id"]?.ToString() ?? "");
                        var modifier = string.IsNullOrEmpty(data["modifier_id"]?.ToString()) ? null
                            : MBObjectManager.Instance.GetObject<ItemModifier>(data["modifier_id"].ToString());
                        var roster = EquipmentShopBehavior.PartyInventory(hero);
                        var element = new EquipmentElement(item, modifier);
                        if (item == null || roster == null || roster.FindIndexOfElement(element) < 0)
                        { ActionFeedback.PostFailed(actionId, "equipment_not_owned"); return; }
                        roster.AddToCounts(element, -1);
                        rosterMutations.Add(Tuple.Create(roster, element, -1));
                        behavior.Store(hero, ledger);
                        committed = true;
                        BannerlordLinkModule.Log($"[{ActionType}] @{username} item={item.StringId} source=party");
                    }
                    else
                    {
                    var owned = ledger.Items.FirstOrDefault(x => x.OwnedId == data["owned_id"]?.ToString());
                    if (owned == null) { ActionFeedback.PostFailed(actionId, "equipment_not_owned"); return; }
                    if (Mission.Current != null && owned.Slot != null)
                    { ActionFeedback.PostFailed(actionId, "in_mission"); return; }
                    if (owned.Slot != null)
                    {
                        var index = EquipmentSync.SlotFromName(owned.Slot);
                        if (!index.HasValue) { ActionFeedback.PostFailed(actionId, "invalid_equipment_slot"); return; }
                        var equipped = hero.BattleEquipment[index.Value];
                        if (equipped.Item?.StringId != owned.ItemId || equipped.ItemModifier?.StringId != owned.ModifierId)
                        { ActionFeedback.PostFailed(actionId, "equipment_changed"); return; }
                        original = new Equipment(hero.BattleEquipment);
                        hero.BattleEquipment[index.Value] = EquipmentElement.Invalid;
                        if (!hero.BattleEquipment[index.Value].IsEmpty) throw new InvalidOperationException("equipment_remove_failed");
                    }
                    ledger.Items.Remove(owned);
                    behavior.Store(hero, ledger);
                    committed = true;
                    BannerlordLinkModule.Log($"[{ActionType}] @{username} item={owned.ItemId} owned={owned.OwnedId} slot={owned.Slot ?? "storage"}");
                    }
                }
                else
                {
                    string slot = (data["slot"]?.ToString() ?? "").Trim().ToLowerInvariant();
                    var index = EquipmentSync.SlotFromName(slot);
                    if (!index.HasValue) { ActionFeedback.PostFailed(actionId, "invalid_equipment_slot"); return; }
                    original = new Equipment(hero.BattleEquipment);
                    if (ActionType == "hero.equip_owned")
                    {
                        if (data["source"]?.ToString() == "party")
                        {
                            var item = MBObjectManager.Instance.GetObject<ItemObject>(data["item_id"]?.ToString() ?? "");
                            var modifier = string.IsNullOrEmpty(data["modifier_id"]?.ToString()) ? null
                                : MBObjectManager.Instance.GetObject<ItemModifier>(data["modifier_id"].ToString());
                            var roster = EquipmentShopBehavior.PartyInventory(hero);
                            var element = new EquipmentElement(item, modifier);
                            if (item == null || roster == null || roster.FindIndexOfElement(element) < 0)
                            { ActionFeedback.PostFailed(actionId, "equipment_not_owned"); return; }
                            if (!EquipmentShopBehavior.Slots(item).Contains(slot))
                            { ActionFeedback.PostFailed(actionId, "incompatible_equipment_slot"); return; }
                            if (!EquipmentShopBehavior.MountCompatible(hero, item, slot))
                            { ActionFeedback.PostFailed(actionId, "incompatible_mount_harness"); return; }
                            var displaced = hero.BattleEquipment[index.Value];
                            roster.AddToCounts(element, -1);
                            rosterMutations.Add(Tuple.Create(roster, element, -1));
                            if (!displaced.IsEmpty) {
                                roster.AddToCounts(displaced, 1);
                                rosterMutations.Add(Tuple.Create(roster, displaced, 1));
                            }
                            hero.BattleEquipment[index.Value] = element;
                            ledger.Items.RemoveAll(x => x.Slot == slot);
                            ledger.Observe(slot, item.StringId, modifier?.StringId);
                        }
                        else
                        {
                        var owned = ledger.Items.FirstOrDefault(x => x.OwnedId == data["owned_id"]?.ToString());
                        if (owned == null) { ActionFeedback.PostFailed(actionId, "equipment_not_owned"); return; }
                        if (owned.Slot == slot) { ActionFeedback.PostFailed(actionId, "already_equipped"); return; }
                        var item = MBObjectManager.Instance.GetObject<ItemObject>(owned.ItemId);
                        if (item == null || !EquipmentShopBehavior.Slots(item).Contains(slot))
                        { ActionFeedback.PostFailed(actionId, "incompatible_equipment_slot"); return; }
                        if (!EquipmentShopBehavior.MountCompatible(hero, item, slot))
                        { ActionFeedback.PostFailed(actionId, "incompatible_mount_harness"); return; }
                        ItemModifier modifier = string.IsNullOrEmpty(owned.ModifierId) ? null
                            : MBObjectManager.Instance.GetObject<ItemModifier>(owned.ModifierId);
                        if (!string.IsNullOrEmpty(owned.ModifierId) && modifier == null)
                        { ActionFeedback.PostFailed(actionId, "item_modifier_unavailable"); return; }
                        // Legacy storage can supply a replacement, but displaced
                        // native equipment must return to the actual party roster.
                        // Без своего отряда снятое остаётся в учёте: ledger.Equip
                        // переносит его в личный сундук вместе с качеством (25.09).
                        var displaced = hero.BattleEquipment[index.Value];
                        var roster = EquipmentShopBehavior.PartyInventory(hero);
                        if (roster == null && !displaced.IsEmpty && owned.Slot != null
                            && ledger.StashCount() >= EquipmentShopPolicy.StashCapacity)
                        { ActionFeedback.PostFailed(actionId, "stash_full"); return; }
                        if (roster != null)
                        {
                            if (!displaced.IsEmpty)
                            {
                                roster.AddToCounts(displaced, 1);
                                rosterMutations.Add(Tuple.Create(roster, displaced, 1));
                            }
                            ledger.Items.RemoveAll(x => x.Slot == slot && x != owned);
                        }
                        if (owned.Slot != null) hero.BattleEquipment[EquipmentSync.SlotFromName(owned.Slot).Value] = EquipmentElement.Invalid;
                        hero.BattleEquipment[index.Value] = new EquipmentElement(item, modifier);
                        var applied = hero.BattleEquipment[index.Value];
                        if (applied.Item != item || applied.ItemModifier != modifier) throw new InvalidOperationException("equipment_apply_failed");
                        ledger.Equip(owned, slot);
                        }
                    }
                    else
                    {
                        if (hero.BattleEquipment[index.Value].IsEmpty) { ActionFeedback.PostFailed(actionId, "equipment_slot_empty"); return; }
                        // Без своего отряда снятое уходит в личный сундук героя (25.09).
                        var roster = EquipmentShopBehavior.PartyInventory(hero);
                        if (roster == null && ledger.StashCount() >= EquipmentShopPolicy.StashCapacity)
                        { ActionFeedback.PostFailed(actionId, "stash_full"); return; }
                        if (roster != null)
                        {
                            roster.AddToCounts(hero.BattleEquipment[index.Value], 1);
                            rosterMutations.Add(Tuple.Create(roster, hero.BattleEquipment[index.Value], 1));
                        }
                        hero.BattleEquipment[index.Value] = EquipmentElement.Invalid;
                        if (!hero.BattleEquipment[index.Value].IsEmpty) throw new InvalidOperationException("equipment_remove_failed");
                        if (roster != null) ledger.Items.RemoveAll(x => x.Slot == slot);
                        else ledger.Unequip(slot);
                    }
                    behavior.Store(hero, ledger);
                    committed = true;
                    BannerlordLinkModule.Log($"[{ActionType}] @{username} slot={slot} owned={data["owned_id"]}");
                }

                // Terminal success reflects committed game state; a networking
                // failure afterwards is repaired by the periodic full snapshot.
                ActionFeedback.PostApplied(actionId);
                try { behavior.Push(hero, ledger); EquipmentSync.PushAll(hero); HeroStateSync.Push(hero); }
                catch (Exception ex) { BannerlordLinkModule.Log("[EquipmentShop] mirror retry pending: " + ex.Message); }
            }
            catch (Exception ex)
            {
                if (!committed)
                {
                    for (int i = rosterMutations.Count - 1; i >= 0; i--)
                    {
                        try { rosterMutations[i].Item1.AddToCounts(rosterMutations[i].Item2, -rosterMutations[i].Item3); }
                        catch (Exception rollback) { BannerlordLinkModule.Log("[EquipmentShop] ROSTER ROLLBACK FAILED: " + rollback); }
                    }
                    if (original != null && hero != null)
                    {
                        try
                        {
                            foreach (string slot in EquipmentShopBehavior.AllSlots)
                            {
                                var index = EquipmentSync.SlotFromName(slot).Value;
                                hero.BattleEquipment[index] = original[index];
                            }
                        }
                        catch (Exception rollback) { BannerlordLinkModule.Log("[EquipmentShop] EQUIPMENT ROLLBACK FAILED: " + rollback); }
                    }
                    if (credited > 0)
                    {
                        try { GiveGoldAction.ApplyBetweenCharacters(hero, null, credited, true); }
                        catch (Exception rollback) { BannerlordLinkModule.Log("[EquipmentShop] CREDIT ROLLBACK FAILED: " + rollback); }
                    }
                    HeroGoldCharge.Refund(hero, charged, ActionType);
                    ActionFeedback.PostFailed(actionId, "equipment_failed:" + ex.GetType().Name);
                }
                BannerlordLinkModule.Log($"[{ActionType}] failed: {ex}");
            }
        }
    }
}
