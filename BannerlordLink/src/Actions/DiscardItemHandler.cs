using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.MountAndBlade;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// `hero.discard_item` — зритель выбрасывает вещь из слота СВОЕГО героя
    /// (освобождает слот, в т.ч. перекованную/«залоченную» вещь). Бесплатно,
    /// без возврата валюты. Нужно когда оплаченная вещь мешает — напр.
    /// перекованный меч не даёт «топорному» классу надеть топор: ручной opt-out
    /// из M8-preservation (раньше такую вещь нельзя было снять иначе как форжем).
    ///
    /// data: { initiated_by (бэк форсит = JWT-юзер), slot }
    /// slot ∈ weapon0..3 / head / body / leg / gloves / cape / horse / horseharness.
    ///
    /// Гейт: действуем по initiated_by (бэк проставляет = запросивший по JWT,
    /// клиент это НЕ контролирует), НЕ по клиентскому target → чужой слот не сбросить.
    /// </summary>
    public class DiscardItemHandler : IActionHandler
    {
        public string ActionType => "hero.discard_item";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string slot = (data["slot"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));
            if (string.IsNullOrEmpty(slot))
                return Task.FromResult<(bool, string)>((false, "no slot"));

            MainThreadDispatcher.Enqueue(() => Discard(username, slot, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Discard(string username, string slotName, string actionId)
        {
            try
            {
                // Off-mission guard (как в прочих equip-хендлерах): нельзя писать
                // BattleEquipment на живом Agent во время Mission.
                if (Mission.Current != null)
                {
                    BannerlordLinkModule.Log($"[discard_item] REFUSE @{username}: нельзя во время Mission");
                    ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[discard_item] REFUSE @{username}: hero не найден / мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                var idx = EquipmentSync.SlotFromName(slotName);
                if (idx == null)
                {
                    BannerlordLinkModule.Log($"[discard_item] @{username}: неизвестный слот '{slotName}'");
                    ActionFeedback.PostFailed(actionId, "bad_slot");
                    return;
                }

                var equipment = hero.BattleEquipment;
                var cur = equipment[idx.Value];
                string dropped = (!cur.IsEmpty && cur.Item != null)
                    ? (cur.Item.Name?.ToString() ?? cur.Item.StringId) : "(пусто)";
                equipment[idx.Value] = EquipmentElement.Invalid;

                BannerlordLinkModule.Log(
                    $"[discard_item] @{username}: slot {slotName} → выброшено «{dropped}»");

                // Re-sync: пустой слот → backend DELETE row → фронт показывает «пусто».
                EquipmentSync.PushAll(hero);
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[discard_item] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "exception:" + ex.GetType().Name);
            }
        }
    }
}
