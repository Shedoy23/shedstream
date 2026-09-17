using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
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
            Equipment original = null;
            bool committed = false;
            try
            {
                // Buying and discarding stored items do not touch battle equipment.
                // Equipping, unequipping, and discarding an equipped item must wait.
                if (Mission.Current != null && ActionType != "hero.buy_equipment" && ActionType != "hero.discard_owned")
                { ActionFeedback.PostFailed(actionId, "in_mission"); return; }
                string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
                hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
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
                    var charge = new JObject { ["hero_gold_cost"] = price };
                    if (!HeroGoldCharge.TryCharge(hero, charge, actionId, ActionType, out charged)) return;
                    var bought = ledger.Add(item.StringId);
                    behavior.Store(hero, ledger);
                    committed = true;
                    BannerlordLinkModule.Log($"[{ActionType}] @{username} item={item.StringId} owned={bought.OwnedId} gold=-{charged}");
                }
                else if (ActionType == "hero.discard_owned")
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
                else
                {
                    string slot = (data["slot"]?.ToString() ?? "").Trim().ToLowerInvariant();
                    var index = EquipmentSync.SlotFromName(slot);
                    if (!index.HasValue) { ActionFeedback.PostFailed(actionId, "invalid_equipment_slot"); return; }
                    original = new Equipment(hero.BattleEquipment);
                    if (ActionType == "hero.equip_owned")
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
                        if (owned.Slot != null) hero.BattleEquipment[EquipmentSync.SlotFromName(owned.Slot).Value] = EquipmentElement.Invalid;
                        hero.BattleEquipment[index.Value] = new EquipmentElement(item, modifier);
                        var applied = hero.BattleEquipment[index.Value];
                        if (applied.Item != item || applied.ItemModifier != modifier) throw new InvalidOperationException("equipment_apply_failed");
                        ledger.Equip(owned, slot);
                    }
                    else
                    {
                        if (hero.BattleEquipment[index.Value].IsEmpty) { ActionFeedback.PostFailed(actionId, "equipment_slot_empty"); return; }
                        hero.BattleEquipment[index.Value] = EquipmentElement.Invalid;
                        if (!hero.BattleEquipment[index.Value].IsEmpty) throw new InvalidOperationException("equipment_remove_failed");
                        ledger.Unequip(slot);
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
                    HeroGoldCharge.Refund(hero, charged, ActionType);
                    ActionFeedback.PostFailed(actionId, "equipment_failed:" + ex.GetType().Name);
                }
                BannerlordLinkModule.Log($"[{ActionType}] failed: {ex}");
            }
        }
    }
}
