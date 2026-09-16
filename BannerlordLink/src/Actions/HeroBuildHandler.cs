using System;
using System.Threading.Tasks;
using BannerlordLink.Behaviors;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    public sealed class HeroBuildHandler : IActionHandler
    {
        public string ActionType { get; }
        public HeroBuildHandler(string action) { ActionType = action; }
        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            MainThreadDispatcher.Enqueue(() => Apply(data));
            return Task.FromResult<(bool, string)>((true, null));
        }
        private void Apply(JObject data)
        {
            string actionId = ActionFeedback.GetActionId(data);
            Hero hero = null;
            Equipment before = null;
            bool committed = false;
            try {
                if (Mission.Current != null) { ActionFeedback.PostFailed(actionId, "in_mission"); return; }
                string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
                hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
                if (hero.IsPrisoner) { ActionFeedback.PostFailed(actionId, "prisoner"); return; }
                var behavior = EquipmentShopBehavior.Instance;
                if (behavior == null) { ActionFeedback.PostFailed(actionId, "inventory_unavailable"); return; }
                if (Campaign.Current == null || data["save_id"]?.ToString() != Campaign.Current.UniqueGameId
                    || data["hero_id"]?.ToString() != hero.StringId)
                { ActionFeedback.PostFailed(actionId, "stale_hero_session"); return; }
                if (data["equipment_session_id"]?.ToString() != behavior.SessionId)
                { ActionFeedback.PostFailed(actionId, "stale_equipment_session"); return; }
                var ledger = behavior.Read(hero);
                var build = ledger.Build;
                if (build == null || build.Version != 1) { ActionFeedback.PostFailed(actionId, "build_unavailable"); return; }
                switch (ActionType) {
                    case "hero.set_specialization":
                        string specialization = data["specialization"]?.ToString();
                        if (!HeroBuildPolicy.ValidSpecialization(specialization)) { ActionFeedback.PostFailed(actionId, "unknown_specialization"); return; }
                        if (build.Specialization == specialization) { ActionFeedback.PostFailed(actionId, "already_selected"); return; }
                        build.Specialization = specialization;
                        break;
                    case "hero.select_weapon_power":
                        string weapon = data["weapon_type"]?.ToString();
                        string refusal = HeroBuildPolicy.Select(build, weapon, HeroBuildRuntime.Equipped(hero, weapon), false);
                        if (refusal != null) { ActionFeedback.PostFailed(actionId, refusal); return; }
                        break;
                    case "hero.claim_starter":
                        if (build.StarterKit != null) { ActionFeedback.PostFailed(actionId, "starter_already_claimed"); return; }
                        string key = data["starter_kit"]?.ToString();
                        var contents = HeroBuildRuntime.Starter(hero, key);
                        if (contents == null) { ActionFeedback.PostFailed(actionId, "starter_items_unavailable"); return; }
                        before = new Equipment(hero.BattleEquipment);
                        foreach (var kv in contents) {
                            var slot = EquipmentSync.SlotFromName(kv.Key).Value;
                            var owned = ledger.Add(kv.Value.StringId);
                            hero.BattleEquipment[slot] = new EquipmentElement(kv.Value);
                            if (hero.BattleEquipment[slot].Item != kv.Value) throw new InvalidOperationException("starter_equip_failed");
                            ledger.Equip(owned, kv.Key);
                        }
                        build.StarterKit = key;
                        build.SelectedWeaponType = key == "infantry" ? "one_handed" : key == "archer" ? "bow" : "two_handed";
                        break;
                    default: ActionFeedback.PostFailed(actionId, "unknown_build_action"); return;
                }
                behavior.Store(hero, ledger);
                // Re-read the save-owned state, not just the requested value.
                if (behavior.Read(hero).Build == null) throw new InvalidOperationException("build_store_failed");
                committed = true;
                ActionFeedback.PostApplied(actionId);
                try { behavior.Push(hero, ledger); EquipmentSync.PushAll(hero); HeroStateSync.Push(hero); }
                catch (Exception ex) { BannerlordLinkModule.Log("[HeroBuild] mirror retry pending: " + ex.Message); }
            }
            catch (Exception ex) {
                if (!committed) {
                    if (before != null && hero != null) {
                        try {
                            foreach (string slot in EquipmentShopBehavior.AllSlots) {
                                var index = EquipmentSync.SlotFromName(slot).Value;
                                hero.BattleEquipment[index] = before[index];
                            }
                        } catch (Exception rollback) { BannerlordLinkModule.Log("[HeroBuild] equipment rollback failed: " + rollback); }
                    }
                    ActionFeedback.PostFailed(actionId, "build_failed:" + ex.GetType().Name);
                }
                BannerlordLinkModule.Log("[HeroBuild] " + ex);
            }
        }
    }
}
