using System;
using System.Linq;
using BannerlordLink.Actions;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;
using TaleWorlds.ObjectSystem;

class Program
{
    static int count;
    static void Check(bool value, string name) { count++; if (!value) throw new Exception(name + ": " + ActionFeedback.Error); }
    static void Buy(JObject data) {
        ActionFeedback.Applied = false; ActionFeedback.Error = null;
        new EquipmentShopHandler("hero.buy_equipment").ExecuteAsync(data).GetAwaiter().GetResult();
    }
    static int Main() {
        try {
            var hero = HeroLookup.Hero = new Hero { Gold = 5000 };
            var behavior = EquipmentShopBehavior.Instance = new EquipmentShopBehavior();
            EquipmentShopBehavior.Inventory = null;
            var armor = new ItemObject { StringId = "armor", Value = 400, Tier = 3 };
            var old = new ItemObject { StringId = "old", Value = 500 };
            MBObjectManager.Instance.Objects["armor"] = armor;
            var data = new JObject { ["target"] = "alice", ["save_id"] = "save1", ["hero_id"] = "hero1",
                ["equipment_session_id"] = behavior.SessionId, ["item_id"] = "armor", ["price_gold"] = 4000,
                ["equip_now"] = true, ["slot"] = "body", ["expected_item_id"] = "", ["expected_modifier_id"] = "", ["trade_in_gold"] = 0 };
            Buy(data);
            Check(ActionFeedback.Applied && hero.Gold == 1000 && hero.BattleEquipment[EquipmentIndex.Body].Item == armor,
                "No-party purchase must equip native armor and debit gold");
            hero.BattleEquipment[EquipmentIndex.Body] = new EquipmentElement(old); hero.Gold = 3500;
            Buy(data);
            Check(ActionFeedback.Error == "equipment_changed" && hero.Gold == 3500 && hero.BattleEquipment[EquipmentIndex.Body].Item == old, "Changed slot cannot silently sell new gear");
            data["expected_item_id"] = "old"; data["trade_in_gold"] = 500;
            behavior.StoreFails = true; Buy(data);
            Check(!ActionFeedback.Applied && hero.Gold == 3500 && hero.BattleEquipment[EquipmentIndex.Body].Item == old, "Failed commit restores gear and net payment");
            behavior.StoreFails = false; Buy(data);
            Check(ActionFeedback.Applied && hero.Gold == 0 && hero.BattleEquipment[EquipmentIndex.Body].Item == armor, "Trade-in funds the purchase without full price up front");
            hero.BattleEquipment[EquipmentIndex.Body] = new EquipmentElement(old); hero.Gold = 3500;
            data["trade_in_gold"] = 99999; Buy(data);
            Check(ActionFeedback.Error == "equipment_price_changed" && hero.Gold == 3500, "Forged trade-in amount rejected");
            data["trade_in_gold"] = 500; data["expected_modifier_id"] = "fake"; Buy(data);
            Check(ActionFeedback.Error == "equipment_changed" && hero.Gold == 3500, "Exact modifier fenced");
            data["expected_modifier_id"] = "";
            Mission.Current = new Mission(); Buy(data);
            Check(ActionFeedback.Error == "in_mission" && hero.Gold == 3500, "Buy-and-equip blocked in mission"); Mission.Current = null;
            hero.IsPrisoner = true; Buy(data);
            Check(ActionFeedback.Error == "hero_prisoner" && hero.Gold == 3500, "Captive blocked"); hero.IsPrisoner = false;
            data["slot"] = "head"; Buy(data);
            Check(ActionFeedback.Error == "incompatible_equipment_slot", "Incompatible slot blocked"); data["slot"] = "body";
            hero.Gold = 3499; Buy(data);
            Check(ActionFeedback.Error == "not_enough_gold" && hero.Gold == 3499 && hero.BattleEquipment[EquipmentIndex.Body].Item == old, "Insufficient net payment preserves old item");
            hero.Gold = 0; old.Value = 5000; data["trade_in_gold"] = 5000;
            behavior.StoreFails = true; Buy(data);
            Check(!ActionFeedback.Applied && hero.Gold == 0 && hero.BattleEquipment[EquipmentIndex.Body].Item == old, "Failed commit reverses trade-in surplus");
            behavior.StoreFails = false; Buy(data);
            Check(ActionFeedback.Applied && hero.Gold == 1000, "Trade-in surplus credited once");
            Buy(data); Check(!ActionFeedback.Applied && hero.Gold == 1000, "Replayed old quote cannot sell another item");
            // 25.09 (владелец): без своего отряда обычная покупка ложится в личный сундук.
            data["equip_now"] = false; hero.Gold = 5000; Buy(data);
            Check(ActionFeedback.Applied && hero.Gold == 1000 && behavior.Saved.StashCount() == 1
                && behavior.Saved.Items.Any(x => x.Slot == null && x.ItemId == "armor"), "Ordinary purchase without baggage goes to personal stash");
            behavior.Saved.Items.RemoveAll(x => x.Slot == null); hero.Gold = 1000;
            data["equip_now"] = true; EquipmentShopBehavior.Inventory = new TaleWorlds.CampaignSystem.Roster.ItemRoster(); Buy(data);
            Check(ActionFeedback.Error == "inventory_state_changed", "Party transition cannot change confirmed delivery mode");
            EquipmentShopBehavior.Inventory = null; old.Value = 500;
            var fine = new ItemModifier { StringId = "fine", ValueMultiplier = 2 };
            hero.BattleEquipment[EquipmentIndex.Body] = new EquipmentElement(old, fine); hero.Gold = 3000;
            data["expected_modifier_id"] = "fine"; data["trade_in_gold"] = 1000;
            behavior.StoreFails = true; Buy(data);
            Check(!ActionFeedback.Applied && hero.Gold == 3000 && hero.BattleEquipment[EquipmentIndex.Body].ItemModifier == fine, "Rollback preserves exact quality");
            behavior.StoreFails = false; Buy(data);
            Check(ActionFeedback.Applied && hero.Gold == 0, "Quality-adjusted native value funds replacement");
            old.Value = 5000; hero.Gold = int.MaxValue; hero.BattleEquipment[EquipmentIndex.Body] = new EquipmentElement(old);
            data["expected_modifier_id"] = ""; data["trade_in_gold"] = 5000; Buy(data);
            Check(ActionFeedback.Error == "gold_limit_reached" && hero.Gold == int.MaxValue && hero.BattleEquipment[EquipmentIndex.Body].Item == old, "Trade-in surplus cannot overflow balance");
            data["save_id"] = "old-save"; Buy(data);
            Check(ActionFeedback.Error == "stale_hero_session", "Direct delivery cannot cross saves"); data["save_id"] = "save1";
            data["equipment_session_id"] = "old-session"; Buy(data);
            Check(ActionFeedback.Error == "stale_equipment_session", "Direct delivery cannot cross reloads");
            Console.WriteLine($"PASS no-party equipment: {count} checks"); return 0;
        } catch (Exception e) { Console.Error.WriteLine(e); return 1; }
    }
}
