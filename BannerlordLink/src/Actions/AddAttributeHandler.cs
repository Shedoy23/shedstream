using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.CharacterDevelopment;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.8 — `hero.add_attribute` action. Viewer тратит Hero.Gold чтобы
    /// добавить attribute point в конкретный attribute (или random).
    ///
    /// BLT pattern (AttributePoints.cs): max 10 per attribute.
    /// Наш cost: flat 50K динаров per point (BLT использует ImproveAdoptedHero
    /// default cost которое настраивается; мы фиксируем 50K).
    ///
    /// data: {target, attribute_key (optional), amount (default 1)}
    ///   attribute_key empty/null → random improvable
    ///
    /// Attributes (6): Vigor, Control, Endurance, Cunning, Social, Intelligence
    /// </summary>
    public class AddAttributeHandler : IActionHandler
    {
        public string ActionType => "hero.add_attribute";

        private const int ATTRIBUTE_COST = 50_000;  // динаров per point

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string attrKey = (data["attribute_key"]?.ToString() ?? "").Trim();
            int amount = (int?)data["amount"] ?? 1;
            if (amount < 1) amount = 1;
            if (amount > 10) amount = 10;

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, attrKey, amount, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string attrKey, int amount, string actionId)
        {
            bool committed = false;
            try
            {
                if (TaleWorlds.MountAndBlade.Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[add_attribute] REFUSE @{username}: нельзя во время Mission (engine crash risk)");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[add_attribute] REFUSE @{username}: hero не найден / мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                var allAttributes = MBObjectManager.Instance
                    .GetObjectTypeList<CharacterAttribute>();
                if (allAttributes == null || allAttributes.Count == 0)
                {
                    BannerlordLinkModule.Log($"[add_attribute] REFUSE @{username}: no attributes available");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_attributes_object");
                    return;
                }

                CharacterAttribute attribute = null;
                if (!string.IsNullOrEmpty(attrKey))
                {
                    attribute = allAttributes.FirstOrDefault(a =>
                        string.Equals(a.StringId, attrKey, StringComparison.OrdinalIgnoreCase)
                        || string.Equals(a.Name?.ToString(), attrKey, StringComparison.OrdinalIgnoreCase));
                    if (attribute == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[add_attribute] REFUSE @{username}: attribute '{attrKey}' не найден");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "unknown_attribute:" + attrKey);
                        return;
                    }
                    if (hero.GetAttributeValue(attribute) >= 10)
                    {
                        BannerlordLinkModule.Log(
                            $"[add_attribute] REFUSE @{username}: {attribute.StringId} уже 10 (max)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "attribute_maxed");
                        return;
                    }
                }
                else
                {
                    var improvable = allAttributes
                        .Where(a => hero.GetAttributeValue(a) < 10).ToList();
                    if (improvable.Count == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[add_attribute] REFUSE @{username}: все attributes уже 10 (max)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "all_attributes_maxed");
                        return;
                    }
                    // Sprint 5.32 (BLT-parity LOW-5) — engine-grade MBRandom.
                    attribute = improvable[TaleWorlds.Core.MBRandom.RandomInt(improvable.Count)];
                }

                // Cap amount to remaining capacity
                int currentVal = hero.GetAttributeValue(attribute);
                int maxAdd = 10 - currentVal;
                if (amount > maxAdd) amount = maxAdd;

                int totalCost = ATTRIBUTE_COST * amount;

                if (hero.Gold < totalCost)
                {
                    BannerlordLinkModule.Log(
                        $"[add_attribute] REFUSE @{username}: not enough hero gold " +
                        $"({hero.Gold} < {totalCost}) для +{amount} в {attribute.StringId}");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                // Charge first, but compensate if the engine mutation fails or
                // does not satisfy its postcondition.
                GiveGoldAction.ApplyBetweenCharacters(hero, null, totalCost, true);
                try
                {
                    hero.HeroDeveloper.AddAttribute(attribute, amount, checkUnspentPoints: false);
                }
                catch (Exception mutationEx)
                {
                    HeroGoldCharge.Refund(hero, totalCost, "add_attribute");
                    ActionFeedback.PostFailed(actionId, "attribute_apply_failed");
                    BannerlordLinkModule.Log(
                        $"[add_attribute] @{username} mutation failed: {mutationEx.Message}");
                    return;
                }
                int newVal = hero.GetAttributeValue(attribute);
                if (newVal <= currentVal)
                {
                    HeroGoldCharge.Refund(hero, totalCost, "add_attribute");
                    ActionFeedback.PostFailed(actionId, "attribute_postcondition_failed");
                    return;
                }
                committed = true;

                BannerlordLinkModule.Log(
                    $"[add_attribute] @{username}: +{amount} в {attribute.StringId} " +
                    $"({currentVal} → {newVal}), -{totalCost}💰 gold={hero.Gold}");

                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    attribute_key = attribute.StringId,
                    attribute_name = attribute.Name?.ToString() ?? attribute.StringId,
                    amount = amount,
                    new_value = newVal,
                    cost = totalCost,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.attribute_changed", evtData));

                HeroStateSync.Push(hero);
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[add_attribute] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                if (!committed)
                    ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
            }
        }
    }
}
