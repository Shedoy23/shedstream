using System;
using System.Collections.Generic;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// 2026-06-15 — «Кузница»: ПЕРЕКОВКА КАЧЕСТВА. Зритель выбирает свой НАДЕТЫЙ
    /// предмет в слоте → ему присваивается лучшее доступное качество (модификатор
    /// Legendary→Masterwork из группы предмета). НЕ создаёт новых предметов
    /// (никакого Crafting / раздувания сейва) — апгрейдит реальную экипировку,
    /// поэтому прокачка базового тира шмота не обесценивается.
    ///
    /// Лимит ИНТРИНСИК: довести предмет до лучшего качества можно один раз —
    /// повтор на уже-топовом → refuse+refund (нечего улучшать).
    ///
    /// Clean-room: публичный API (BattleEquipment[slot], ItemComponent.
    /// ItemModifierGroup.GetModifiersBasedOnQuality, EquipmentElement). Код BLT не
    /// копируется — это не их «craft + custom modifier», а апгрейд качества надетого.
    ///
    /// Data: {target, slot}  slot = weapon0..weapon3 / head/body/leg/gloves/cape/horse
    /// </summary>
    public class ReforgeQualityHandler : IActionHandler
    {
        public string ActionType => "hero.reforge_quality";

        private static readonly Dictionary<string, EquipmentIndex> SLOT_MAP =
            new Dictionary<string, EquipmentIndex>(StringComparer.OrdinalIgnoreCase)
            {
                ["weapon0"] = EquipmentIndex.Weapon0,
                ["weapon1"] = EquipmentIndex.Weapon1,
                ["weapon2"] = EquipmentIndex.Weapon2,
                ["weapon3"] = EquipmentIndex.Weapon3,
                ["head"]    = EquipmentIndex.Head,
                ["body"]    = EquipmentIndex.Body,
                ["leg"]     = EquipmentIndex.Leg,
                ["gloves"]  = EquipmentIndex.Gloves,
                ["cape"]    = EquipmentIndex.Cape,
                ["horse"]   = EquipmentIndex.Horse,
            };

        // Шкала качества по ВОЗРАСТАНИЮ (enum: Poor<Inferior<Common<Fine<Masterwork<Legendary).
        // Перековка поднимает на ОДНУ ступень вверх от текущей: Базовое→Хорошее(Fine)→
        // Шикарное(Masterwork)→Легендарное(Legendary). 20000💎 за шаг.
        private static readonly ItemQuality[] QUALITY_ASC =
            { ItemQuality.Fine, ItemQuality.Masterwork, ItemQuality.Legendary };

        public System.Threading.Tasks.Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string slot = (data["slot"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(slot))
                return System.Threading.Tasks.Task.FromResult<(bool, string)>((false, "missing fields"));
            MainThreadDispatcher.Enqueue(() => Reforge(username, slot, actionId));
            return System.Threading.Tasks.Task.FromResult<(bool, string)>((true, null));
        }

        private static void Reforge(string username, string slot, string actionId)
        {
            try
            {
                if (Campaign.Current == null) { Refuse(username, actionId, "no_campaign"); return; }
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) { Refuse(username, actionId, "hero_not_found_or_dead"); return; }
                // Менять BattleEquipment на живом Agent во время Mission опасно (stale equipment
                // → null-deref на следующей атаке) — как в прочих equip-хендлерах.
                if (TaleWorlds.MountAndBlade.Mission.Current != null) { Refuse(username, actionId, "in_mission"); return; }
                if (!SLOT_MAP.TryGetValue(slot, out var idx)) { Refuse(username, actionId, "unknown_slot"); return; }

                var cur = hero.BattleEquipment[idx];
                if (cur.IsEmpty || cur.Item == null) { Refuse(username, actionId, "slot_empty"); return; }
                var item = cur.Item;

                var group = item.ItemComponent?.ItemModifierGroup;
                if (group == null) { Refuse(username, actionId, "no_quality_group"); return; }

                ItemQuality curQ = cur.ItemModifier != null ? cur.ItemModifier.ItemQuality : ItemQuality.Common;
                string itemName = item.Name?.ToString() ?? item.StringId;
                string curModId = cur.ItemModifier != null ? cur.ItemModifier.StringId : "(none)";

                // Следующая ступень СТРОГО выше текущей, у которой есть модификатор в
                // группе (+1 шаг). Базовое(Common)→Хорошее→Шикарное→Легендарное.
                ItemModifier nextMod = null;
                ItemQuality nextQ = ItemQuality.Common;
                foreach (var q in QUALITY_ASC)
                {
                    if ((int)q <= (int)curQ) continue;       // пропускаем ступени на уровне/ниже текущей
                    var mods = group.GetModifiersBasedOnQuality(q);
                    if (mods != null && mods.Count > 0) { nextMod = mods[0]; nextQ = q; break; }
                }
                if (nextMod == null)
                {
                    // Ступеней выше нет: либо предмет уже на потолке (>=Fine), либо у
                    // группы вообще нет качественных модификаторов. Оба → refund.
                    string reason = (int)curQ >= (int)ItemQuality.Fine ? "already_best" : "no_modifier";
                    BannerlordLinkModule.Log(
                        $"[reforge_quality] @{username} {slot}: '{itemName}' нет ступени выше — " +
                        $"curQ={curQ}(mod={curModId}) reason={reason}");
                    Refuse(username, actionId, reason);
                    return;
                }

                hero.BattleEquipment[idx] = new EquipmentElement(item, nextMod);
                BannerlordLinkModule.Log(
                    $"[reforge_quality] @{username} {slot}: '{itemName}' " +
                    $"качество {curQ}(mod={curModId}) -> {nextQ}(mod={nextMod.StringId})");
                // PushAll — чтобы новое качество (M77 quality) сразу попало в
                // bannerlord_equipment и бейдж в расширении обновился. HeroStateSync
                // шлёт hero-stats, но НЕ экипировку — нужны оба.
                try { EquipmentSync.PushAll(hero); } catch { }
                try { HeroStateSync.Push(hero); } catch { }
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[reforge_quality] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "exception:" + ex.GetType().Name);
            }
        }

        private static void Refuse(string username, string actionId, string reason)
        {
            BannerlordLinkModule.Log($"[reforge_quality] REFUSE @{username}: {reason}");
            ActionFeedback.PostFailed(actionId, reason);
        }
    }
}
