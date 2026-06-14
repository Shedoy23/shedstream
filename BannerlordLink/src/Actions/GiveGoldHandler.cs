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

            // AUDIT 2026-05-29 (fix #4): cap backend-supplied amount. Мод не
            // должен слепо доверять payload — защита от malformed/compromised
            // backend, который мог бы выдать int.MaxValue золота и сломать econ.
            const int MAX_GOLD_GRANT = 10_000_000;
            if (amount > MAX_GOLD_GRANT)
            {
                BannerlordLinkModule.Log(
                    $"[give_item:gold] @{username}: amount {amount} > cap, clamp → {MAX_GOLD_GRANT}");
                amount = MAX_GOLD_GRANT;
            }

            // 2026-06-14 audit: give_item ACK'ает success СИНХРОННО (ниже), а
            // выдаёт async. Если async-применение отказывает после списания
            // крустиков — без PostFailed зритель теряет деньги (нет рефанда).
            // PostFailed только на до-применения отказах (флаг applied), иначе
            // рефанд + уже выданное золото = двойная выгода.
            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                bool applied = false;
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null)
                    {
                        BannerlordLinkModule.Log($"[give_item:gold] @{username}: hero не найден");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found");
                        return;
                    }
                    if (!hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[give_item:gold] @{username}: dead, skip");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_dead");
                        return;
                    }
                    int before = hero.Gold;
                    // ApplyBetweenCharacters(giver, receiver, amount, disableNotification)
                    // — positional т.к. parameter names различаются по версиям 1.x.
                    GiveGoldAction.ApplyBetweenCharacters(null, hero, amount, true);
                    applied = true;
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
                    // Рефанд только если золото НЕ было выдано (иначе двойная выгода).
                    if (!applied)
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "exception");
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
