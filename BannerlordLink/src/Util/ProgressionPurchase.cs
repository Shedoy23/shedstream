using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Actions;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;
namespace BannerlordLink.Util
{
    internal static class ProgressionPurchase
    {
        internal static void Apply(string username, JObject data, bool focus)
        {
            string actionId = ActionFeedback.GetActionId(data);
            Hero hero = null;
            bool effect = false;
            int charged = 0, before = 0, goldBefore = 0;
            bool debitStarted = false, mutationStarted = false;
            Func<int> read = null;
            string chosenId = null, chosenName = null;
            try
            {
                hero = HeroLookup.FindByUsername(username);
                string reason = HeroProgressionRuntime.ValidateContext(hero, data) ?? HeroProgressionRuntime.ActorReason(hero);
                if (reason != null) { ActionFeedback.PostFailed(actionId, reason); return; }
                if (data["expected_value"]?.Type != JTokenType.Integer || data["expected_cost_gold"]?.Type != JTokenType.Integer)
                { ActionFeedback.PostFailed(actionId, "progression_quote_required"); return; }
                int amount = (int?)data["amount"] ?? 1;
                // Snapshot currently offers exactly +1. Never silently clamp a requested quantity.
                if (amount != 1) { ActionFeedback.PostFailed(actionId, "invalid_amount"); return; }
                string key = (string)data[focus ? "skill_key" : "attribute_key"] ?? "";
                Action mutate;
                ProgressionPolicy.Quote quote;
                if (focus)
                {
                    var skill = MBObjectManager.Instance.GetObjectTypeList<SkillObject>().FirstOrDefault(s => s != null && !string.IsNullOrEmpty(s.StringId) && string.Equals(s.StringId, key, StringComparison.Ordinal));
                    if (skill == null) { ActionFeedback.PostFailed(actionId, "unknown_skill"); return; }
                    chosenId = skill.StringId; chosenName = skill.Name?.ToString() ?? chosenId;
                    read = () => hero.HeroDeveloper.GetFocus(skill);
                    mutate = () => hero.HeroDeveloper.AddFocus(skill, amount, checkUnspentFocusPoints: false);
                    quote = HeroProgressionRuntime.Focus(hero, skill, amount);
                }
                else
                {
                    var attr = MBObjectManager.Instance.GetObjectTypeList<CharacterAttribute>().FirstOrDefault(a => a != null && !string.IsNullOrEmpty(a.StringId) && string.Equals(a.StringId, key, StringComparison.Ordinal));
                    if (attr == null) { ActionFeedback.PostFailed(actionId, "unknown_attribute"); return; }
                    chosenId = attr.StringId; chosenName = attr.Name?.ToString() ?? chosenId;
                    read = () => hero.GetAttributeValue(attr);
                    mutate = () => hero.HeroDeveloper.AddAttribute(attr, amount, checkUnspentPoints: false);
                    quote = HeroProgressionRuntime.Attribute(hero, attr, amount);
                }
                before = read();
                reason = ProgressionPolicy.ValidateExpected(before, quote.CostGold, (int)data["expected_value"], (int)data["expected_cost_gold"]);
                if (reason == null) reason = quote.Reason;
                if (reason != null) { ActionFeedback.PostFailed(actionId, reason); return; }
                goldBefore = hero.Gold; debitStarted = true;
                GiveGoldAction.ApplyBetweenCharacters(hero, null, quote.CostGold, true);
                charged = Math.Max(0, goldBefore - hero.Gold);
                if (charged != quote.CostGold)
                {
                    bool refunded = RefundCharge(hero, ref charged, actionId); debitStarted = false;
                    ActionFeedback.PostFailed(actionId, refunded ? "progression_charge_failed" : "progression_compensation_failed"); return;
                }
                mutationStarted = true;
                mutate();
                effect = read() > before;
                if (!effect)
                {
                    bool refunded = RefundCharge(hero, ref charged, actionId); debitStarted = false;
                    ActionFeedback.PostFailed(actionId, refunded ? "progression_postcondition_failed" : "progression_compensation_failed"); return;
                }
                // Confirm the observed effect before best-effort display synchronization.
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                // A patched engine method may throw AFTER changing the attribute/focus.
                if (debitStarted && charged == 0)
                {
                    try { charged = Math.Max(0, goldBefore - hero.Gold); }
                    catch { ActionFeedback.PostFailed(actionId, "progression_outcome_unknown"); return; }
                }
                if (!effect && mutationStarted && read != null)
                {
                    try { effect = read() > before; }
                    catch { BannerlordLinkModule.Log("[progression] mutation outcome unknown; no automatic game-gold refund"); ActionFeedback.PostFailed(actionId, "progression_outcome_unknown"); return; }
                }
                if (effect) ActionFeedback.PostApplied(actionId);
                else
                {
                    bool refunded = RefundCharge(hero, ref charged, actionId); debitStarted = false;
                    ActionFeedback.PostFailed(actionId, refunded ? "progression_apply_failed" : "progression_compensation_failed");
                }
                BannerlordLinkModule.Log("[progression] " + ex);
            }
            finally
            {
                if (effect && chosenId != null) try
                {
                    int value = read();
                    var payload = new JObject { ["username"] = username, [focus ? "skill_key" : "attribute_key"] = chosenId,
                        [focus ? "skill_name" : "attribute_name"] = chosenName, ["amount"] = value - before,
                        [focus ? "new_focus" : "new_value"] = value, ["cost"] = charged };
                    string json = payload.ToString(Newtonsoft.Json.Formatting.None);
                    Task.Run(() => BannerlordLinkModule.Backend.PostEventAsync("bannerlord", focus ? "hero.focus_changed" : "hero.attribute_changed", json));
                }
                catch (Exception ex) { BannerlordLinkModule.Log("[progression] display event failed: " + ex.Message); }
                if (hero != null) try { HeroProgressionRuntime.Push(hero); }
                    catch (Exception ex) { BannerlordLinkModule.Log("[progression] snapshot retry on tick: " + ex.Message); }
            }
        }
        private static bool RefundCharge(Hero hero, ref int charged, string actionId)
        {
            int amount = charged; charged = 0; // Compensation is attempted at most once, even if observation fails.
            if (amount <= 0) return true;
            try
            {
                int before = hero.Gold;
                bool reported = HeroGoldCharge.Refund(hero, amount, "progression");
                if (reported && (long)hero.Gold - before == amount) return true;
            }
            catch (Exception ex) { BannerlordLinkModule.Log("[progression] compensation observation: " + ex.Message); }
            BannerlordLinkModule.Log("[progression] compensation NOT CONFIRMED action=" + actionId + " hero=" + hero.StringId + " amount=" + amount);
            return false;
        }

    }
}
