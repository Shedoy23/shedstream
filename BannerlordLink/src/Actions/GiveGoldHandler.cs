using System;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `player.give_item` (когда item type=="gold") — выдаёт
    /// динары hero'ю. Для real items (weapon, armor) — TODO Sprint 3.3.
    ///
    /// API: GiveGoldAction.ApplyBetweenCharacters(null, hero, amount, disableNotification).
    /// </summary>
    public class GiveGoldHandler : IActionHandler
    {
        public string ActionType => "player.give_item";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string itemType = data["item_type"]?.ToString() ?? "gold";
            int amount = (int?)data["amount"] ?? 0;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));

            // Sprint 3.2: только gold support. Real items в 3.3.
            if (itemType != "gold")
                return Task.FromResult<(bool, string)>((false, $"item_type={itemType} not implemented (only 'gold' пока)"));

            if (amount <= 0)
                return Task.FromResult<(bool, string)>((false, "amount must be > 0"));

            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[give_item:gold] @{username}: hero не найден");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[give_item:gold] @{username}: dead, skip");
                        return;
                    }
                    int before = hero.Gold;
                    // ApplyBetweenCharacters(giver, receiver, amount, disableNotification)
                    // — positional т.к. parameter names различаются по версиям 1.x.
                    GiveGoldAction.ApplyBetweenCharacters(null, hero, amount, true);
                    BannerlordLinkModule.Log(
                        $"[give_item:gold] @{username} gold {before} → {hero.Gold} (+{amount})");

                    // Push state update event так backend знает о gold change.
                    string evtData = JsonConvert.SerializeObject(new
                    {
                        username = username,
                        gold = hero.Gold,
                    });
                    Task.Run(async () => await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "player.state_update", evtData));
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[give_item:gold] @{username} CRASHED: {ex.Message}");
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
