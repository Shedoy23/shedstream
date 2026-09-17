using System;
using BannerlordLink.Util;
using BannerlordLink.Actions;
using BannerlordLink.Behaviors;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

class Program
{
    static int count;
    static void Check(bool pass, string message) { count++; if (!pass) throw new Exception(message); }
    static void Act(string type, JObject data)
    {
        ActionFeedback.Applied = false; ActionFeedback.Error = null;
        new EquipmentShopHandler(type).ExecuteAsync(data).GetAwaiter().GetResult();
    }
    static void TestHandlers()
    {
        var hero = HeroLookup.Hero = new Hero();
        var behavior = EquipmentShopBehavior.Instance = new EquipmentShopBehavior();
        var item = new ItemObject { StringId = "armor", Value = 400, Tier = 3 };
        MBObjectManager.Instance.Objects["armor"] = item;
        var request = new JObject { ["target"] = "alice", ["save_id"] = "save1", ["hero_id"] = "hero1", ["item_id"] = "armor", ["price_gold"] = 400 };
        request["equipment_session_id"] = behavior.SessionId;
        hero.Level = 24;
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "equipment_level_locked" && hero.Gold == 1000 && behavior.Saved.Items.Count == 0, "Low-level hostile purchase must not charge or grant");
        hero.Level = 25; request["price_gold"] = 1;
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "equipment_price_changed" && hero.Gold == 1000, "Client cheap price must not be trusted");
        request["price_gold"] = 2000; hero.Gold = 4500;
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "equipment_price_changed" && hero.Gold == 4500 && behavior.Saved.Items.Count == 0, "Previous fivefold price cannot buy after the tenfold increase");
        request["price_gold"] = 4000; hero.Gold = 3999;
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "not_enough_gold" && hero.Gold == 3999, "Authoritative live gold check at multiplied price");
        hero.Gold = 4500; request["save_id"] = "old_save";
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "stale_hero_session" && hero.Gold == 4500, "Queued purchase may not cross saves");
        request["save_id"] = "save1"; request["hero_id"] = "old_hero";
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "stale_hero_session", "Queued purchase may not cross hero generations");
        request["hero_id"] = "hero1"; request["equipment_session_id"] = "previous_runtime_same_save";
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "stale_equipment_session" && hero.Gold == 4500 && behavior.Saved.Items.Count == 0, "Reloading older same-save rejects previous-runtime action");
        request.Remove("equipment_session_id");
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "stale_equipment_session", "Missing equipment session fails closed");
        request["equipment_session_id"] = behavior.SessionId; Mission.Current = new Mission();
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Error == "in_mission" && hero.Gold == 4500, "No equipment changes in missions");
        Mission.Current = null; behavior.StoreFails = true;
        Act("hero.buy_equipment", request);
        Check(!ActionFeedback.Applied && hero.Gold == 4500 && behavior.Saved.Items.Count == 0, "Persistence failure must compensate actual gold charge");
        behavior.StoreFails = false; behavior.PushFails = true;
        Act("hero.buy_equipment", request);
        Check(ActionFeedback.Applied && hero.Gold == 500 && behavior.Saved.Items.Count == 1, "Successful purchase charges ten times native value and survives mirror network failure");
        var owned = behavior.Saved.Items[0];
        Check(owned.Slot == null && hero.BattleEquipment[EquipmentIndex.Body].IsEmpty, "Purchase enters storage without equipping");
        request["owned_id"] = owned.OwnedId; request["slot"] = "head";
        Act("hero.equip_owned", request);
        Check(ActionFeedback.Error == "incompatible_equipment_slot", "Armor cannot be put in wrong slot");
        request["slot"] = "body"; request["owned_id"] = "another_viewer_owned_id";
        Act("hero.equip_owned", request);
        Check(ActionFeedback.Error == "equipment_not_owned", "Owned ID is scoped to hero ledger");
        request["owned_id"] = owned.OwnedId;
        var old = new ItemObject { StringId = "old_armor" }; var mod = new ItemModifier { StringId = "lordly" };
        hero.BattleEquipment[EquipmentIndex.Body] = new EquipmentElement(old, mod);
        behavior.StoreFails = true;
        Act("hero.equip_owned", request);
        Check(!ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].Item == old && hero.BattleEquipment[EquipmentIndex.Body].ItemModifier == mod, "Failed inventory commit rolls back exact native equipment");
        behavior.StoreFails = false;
        Act("hero.equip_owned", request);
        Check(ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].Item == item && hero.Gold == 500, "Owned equip is free and applies selected object");
        Check(behavior.Saved.Items.Exists(x => x.ItemId == "old_armor" && x.ModifierId == "lordly" && x.Slot == null), "Native modifier gear retained in storage");
        Act("hero.unequip_owned", request);
        Check(ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].IsEmpty && behavior.Saved.Items.TrueForAll(x => x.Slot == null), "Unequip preserves ownership");
        request["owned_id"] = owned.OwnedId;
        Act("hero.discard_owned", request);
        Check(ActionFeedback.Applied && !behavior.Saved.Items.Exists(x => x.OwnedId == owned.OwnedId) && hero.Gold == 500, "Discard removes the exact stored instance without a refund");
        Act("hero.discard_owned", request);
        Check(ActionFeedback.Error == "equipment_not_owned", "Discard cannot remove the same instance twice");
        var imported = behavior.Saved.Items.Find(x => x.ItemId == "old_armor");
        MBObjectManager.Instance.Objects["old_armor"] = old;
        MBObjectManager.Instance.Objects["lordly"] = mod;
        request["owned_id"] = imported.OwnedId;
        Act("hero.equip_owned", request);
        Check(ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].Item == old, "Stored native item can be equipped before discard");
        behavior.StoreFails = true;
        Act("hero.discard_owned", request);
        Check(!ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].Item == old && behavior.Saved.Items.Exists(x => x.OwnedId == imported.OwnedId), "Failed equipped discard restores game gear and ownership");
        behavior.StoreFails = false;
        Act("hero.discard_owned", request);
        Check(ActionFeedback.Applied && hero.BattleEquipment[EquipmentIndex.Body].IsEmpty && !behavior.Saved.Items.Exists(x => x.OwnedId == imported.OwnedId), "Equipped discard removes the matching game item and owned instance");
    }
    static void TestSessionRetry()
    {
        var handshake = new EquipmentSessionHandshake("original-nonce-and-save", 12345);
        int attempts = 0;
        Func<string, long, System.Threading.Tasks.Task<bool>> send = (json, timestamp) => {
            attempts++;
            Check(json == "original-nonce-and-save" && timestamp == 12345, "Session retry preserves original payload and epoch timestamp");
            return System.Threading.Tasks.Task.FromResult(attempts > 1);
        };
        Check(!handshake.EnsureAsync(send).GetAwaiter().GetResult(), "Lost session start cannot allow catalog publication");
        Check(handshake.EnsureAsync(send).GetAwaiter().GetResult(), "Failed session handshake retries until ACK");
        Check(handshake.EnsureAsync(send).GetAwaiter().GetResult() && attempts == 2, "Acknowledged handshake does not resend or clear ready inventory");
    }
    static int Main()
    {
        try
        {
            Check(EquipmentShopPolicy.RequiredLevel(4) == 25, "Tier IV must require hero level 25");
            Check(EquipmentShopPolicy.RequiredLevel(5) == 30, "Tier V must require hero level 30");
            Check(EquipmentShopPolicy.RequiredLevel(6) == 35, "Tier VI must require hero level 35");
            Check(EquipmentShopPolicy.PublicTier(3) == 4, "Native Tier4 zero-based maps to public IV");
            Check(EquipmentShopPolicy.PublicTier(-1) == 1 && EquipmentShopPolicy.PublicTier(8) == 6, "Tier bounds");
            Check(EquipmentShopPolicy.Price(0) == 10 && EquipmentShopPolicy.Price(900) == 9000, "Native game value is multiplied by ten with a ten-dinar floor");
            Check(EquipmentShopPolicy.Price(int.MaxValue) == int.MaxValue, "Price multiplier cannot overflow gold and become cheap");
            var ledger = new EquipmentLedger();
            ledger.Observe("body", "old_armor", "lordly");
            var old = ledger.Items[0];
            ledger.Observe("body", "old_armor", "lordly");
            Check(ledger.Items.Count == 1, "Snapshot refresh must not duplicate owned items");
            var bought = ledger.Add("new_armor");
            ledger.Equip(bought, "body");
            Check(old.Slot == null && old.ModifierId == "lordly", "Displaced modifier armor remains owned");
            Check(bought.Slot == "body", "Selected item is equipped");
            ledger.Equip(old, "body");
            Check(bought.Slot == null && old.Slot == "body", "Switch back preserves purchased item");
            ledger.Unequip("body");
            Check(old.Slot == null && ledger.Items.Count == 2, "Unequip returns to storage");
            Check(old.OwnedId != bought.OwnedId, "Instances have unique IDs");
            var duplicate = ledger.Add("new_armor");
            Check(duplicate.OwnedId != bought.OwnedId, "Two identical purchases remain distinct instances");
            var observed = new EquipmentLedger();
            observed.Observe("body", "armor", null);
            string nativeId = observed.Items[0].OwnedId;
            observed.Observe("body", "armor", "lordly");
            observed.Observe("body", "armor", "legendary");
            Check(observed.Items.Count == 1 && observed.Items[0].OwnedId == nativeId && observed.Items[0].ModifierId == "legendary", "Repeated forge modifies one instance without creating free old copies");
            observed.Observe("body", null, null);
            Check(observed.Items.Count == 0, "External discard must not resurrect destroyed equipment");
            observed.Observe("body", "old", null);
            observed.Observe("body", "new", null);
            Check(observed.Items.Count == 1 && observed.Items[0].ItemId == "new", "External replacement imports only current native equipment");
            var removedContent = new EquipmentLedger();
            removedContent.Observe("body", "modded_armor", "modded_quality");
            string missingId = removedContent.Items[0].OwnedId;
            removedContent.Observe("body", null, null, previousContentAvailable: false);
            Check(removedContent.Items.Count == 1 && removedContent.Items[0].OwnedId == missingId && removedContent.Items[0].Slot == null && removedContent.Items[0].ModifierId == "modded_quality", "Removing content mod preserves unavailable item and original modifier ownership");
            removedContent.Observe("body", null, null);
            Check(removedContent.Items.Count == 1, "Repeated empty native snapshot does not erase unavailable stored item");
            var removedModifier = new EquipmentLedger();
            removedModifier.Observe("body", "armor", "modded_quality");
            removedModifier.Observe("body", "armor", null, previousContentAvailable: false);
            removedModifier.Observe("body", "armor", null);
            Check(removedModifier.Items.Count == 2 && removedModifier.Items.Exists(x => x.ModifierId == "modded_quality" && x.Slot == null), "Missing modifier remains unavailable, native plain replacement imported once");
            TestHandlers();
            TestSessionRetry();
            Console.WriteLine($"PASS {count} equipment shop checks"); return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine("FAIL: " + ex.Message); return 1; }
    }
}
