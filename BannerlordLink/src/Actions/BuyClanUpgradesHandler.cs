using System;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using BannerlordLink.Util;

namespace BannerlordLink.Actions
{
    public sealed class BuyClanUpgradesHandler : IActionHandler
    {
        public string ActionType => "hero.buy_clan_upgrades";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString()
                               ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            MainThreadDispatcher.Enqueue(() =>
            {
                TaleWorlds.CampaignSystem.Hero chargedHero = null;
                int chargedAmount = 0;
                bool committed = false;
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
                    if (!hero.IsAlive) { ActionFeedback.PostFailed(actionId, "hero_dead"); return; }
                    if (!HeroGoldCharge.TryCharge(hero, data, actionId,
                            "buy_clan_upgrades", out chargedAmount)) return;
                    chargedHero = hero;
                    if (chargedAmount <= 0) { ActionFeedback.PostFailed(actionId, "invalid_gold_cost"); return; }

                    var evt = JsonConvert.SerializeObject(new {
                        action_id = actionId, username,
                        gold_charged = chargedAmount, gold_after = hero.Gold,
                    });
                    if (BannerlordLinkModule.Backend == null
                        || !BannerlordLinkModule.Backend.EnqueueDurableEvent(
                            "bannerlord", "hero.clan_upgrades_purchased", evt))
                    {
                        HeroGoldCharge.Refund(hero, chargedAmount, "buy_clan_upgrades");
                        chargedAmount = 0;
                        ActionFeedback.PostFailed(actionId, "confirmation_enqueue_failed");
                        return;
                    }
                    committed = true;
                    try { HeroStateSync.Push(hero); } catch { }
                    ActionFeedback.PostApplied(actionId);
                    BannerlordLinkModule.Log($"[buy_clan_upgrades] @{username}: committed -{chargedAmount} gold={hero.Gold}");
                }
                catch (Exception ex)
                {
                    if (!committed && chargedAmount > 0)
                        HeroGoldCharge.Refund(chargedHero, chargedAmount, "buy_clan_upgrades");
                    BannerlordLinkModule.Log($"[buy_clan_upgrades] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                    ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
                }
            });
            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
