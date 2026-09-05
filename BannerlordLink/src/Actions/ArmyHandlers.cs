using System;
using System.Linq;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// 2026-06-14 — «Армия» MVP (спека: docs/ARMY_MVP_SPEC.md). Вариант A:
    /// армия КОРОЛЕВСТВА на vanilla Kingdom.CreateArmy — движок держит армию сам,
    /// низкий LGPL-риск (НЕ BLT-независимая армия с патчами рассеивания).
    /// Приказы армии = существующие party orders (партия-лидер тащит армию за собой,
    /// отдельных army-команд не делаем). Clean-room: только vanilla TaleWorlds API.
    /// Первый срез: создание/роспуск + cohesion=100 разово; ежечасный долив cohesion
    /// — fast-follow после проверки в игре.
    /// </summary>
    public class CreateArmyHandler : IActionHandler
    {
        public string ActionType => "hero.army_create";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));
            MainThreadDispatcher.Enqueue(() => Apply(username, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string actionId)
        {
            bool applied = false;
            try
            {
                if (Campaign.Current == null) { ActionFeedback.PostFailed(actionId, "no_campaign"); return; }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log($"[army_create] REFUSE @{username}: hero не найден/мёртв");
                    ActionFeedback.PostFailed(actionId, "hero_not_found"); return;
                }
                var mp = hero.PartyBelongedTo;
                if (mp == null) { ActionFeedback.PostFailed(actionId, "no_party"); return; }
                if (mp.LeaderHero != hero)
                {
                    BannerlordLinkModule.Log($"[army_create] REFUSE @{username}: не лидер своей партии");
                    ActionFeedback.PostFailed(actionId, "not_party_leader"); return;
                }
                var clan = hero.Clan;
                if (clan == null || clan.Kingdom == null)
                {
                    BannerlordLinkModule.Log($"[army_create] REFUSE @{username}: не в королевстве");
                    ActionFeedback.PostFailed(actionId, "not_in_kingdom"); return;
                }
                if (clan.Leader != hero)
                {
                    BannerlordLinkModule.Log($"[army_create] REFUSE @{username}: не лидер клана");
                    ActionFeedback.PostFailed(actionId, "not_clan_leader"); return;
                }
                if (mp.Army != null) { ActionFeedback.PostFailed(actionId, "already_in_army"); return; }
                if (mp.MapEvent != null) { ActionFeedback.PostFailed(actionId, "in_battle"); return; }
                if (mp.IsDisbanding) { ActionFeedback.PostFailed(actionId, "party_disbanding"); return; }
                if (clan.IsUnderMercenaryService) { ActionFeedback.PostFailed(actionId, "mercenary"); return; }

                // 2026-07-20 FIX — «армия качается: садится в осаду и уходит».
                // Раньше AI размораживался БЕЗУСЛОВНО: если у героя был активный
                // party-order (осада), приказ терял замок, движковый AI уводил партию,
                // а наш hourly-reissue возвращал → бесконечные качели. Теперь: если
                // активный приказ ЕСТЬ — замок не снимаем (его вернём после создания
                // армии), если приказа нет — прежнее поведение.
                var activeOrder = BannerlordLink.Behaviors.PartyOrderBehavior.GetOrder(username);
                if (activeOrder == null)
                {
                    try { mp.Ai.SetDoNotMakeNewDecisions(false); } catch { }
                }

                // Точка сбора: фьеф клана → дом героя → текущее поселение партии.
                Settlement gather = null;
                try
                {
                    gather = clan.Settlements?.FirstOrDefault()
                             ?? hero.HomeSettlement
                             ?? mp.CurrentSettlement;
                }
                catch { }
                if (gather == null)
                {
                    BannerlordLinkModule.Log($"[army_create] REFUSE @{username}: нет точки сбора (нет фьефа/дома)");
                    ActionFeedback.PostFailed(actionId, "no_gather_point"); return;
                }

                // Созвать партии королевства в армию — иначе армия = только лидер
                // (баг 2026-06-14: партий=1). Vanilla-модель даёт кандидатов; передаём
                // в CreateArmy → движок шлёт им призыв (идут к точке сбора, join со временем).
                var toCall = new TaleWorlds.Library.MBList<MobileParty>();
                int callCount = 0;
                try
                {
                    // 2026-09-02 (1.4.8): GetMobilePartiesToCallToArmy из модели
                    // исчез. Кандидатов теперь отдаёт CanLordCreateArmy через out —
                    // тот же список, только за булевым ответом «а может ли вообще».
                    // Проверено по декомпиляции ArmyManagementCalculationModel.
                    TaleWorlds.Library.MBList<MobileParty> candidates;
                    if (Campaign.Current.Models.ArmyManagementCalculationModel
                            .CanLordCreateArmy(mp, out candidates) && candidates != null)
                    { toCall.AddRange(candidates); callCount = toCall.Count; }
                }
                catch (Exception mEx)
                {
                    BannerlordLinkModule.Log($"[army_create] CanLordCreateArmy warn @{username}: {mEx.Message}");
                }

                // Влияние — естественная in-game цена созыва партий. Зритель платит
                // криптиками, НЕ влиянием: даём большой буфер на время создания, потом
                // возвращаем влияние клана как было (и на успехе, и на неудаче).
                float influenceBefore = clan.Influence;
                try { clan.Influence = influenceBefore + 5000f; } catch { }

                // 2026-07-20 FIX — тип армии по активному приказу. Patrolling = «патрулируй»,
                // и ИИ армии тащил её ПРОЧЬ с осады (вторая половина качелей). Логика движка
                // (Army.cs) сама учитывает BesiegeSettlement у лидера — даём ей верный тип.
                var armyType = Army.ArmyTypes.Patrolling;
                if (activeOrder != null)
                {
                    switch (activeOrder.Value.orderType)
                    {
                        case "siege":  armyType = Army.ArmyTypes.Besieger; break;
                        case "raid":   armyType = Army.ArmyTypes.Raider;   break;
                        case "defend": armyType = Army.ArmyTypes.Defender; break;
                    }
                }

                try
                {
                    clan.Kingdom.CreateArmy(hero, gather, armyType, toCall);
                }
                catch (Exception cEx)
                {
                    try { clan.Influence = influenceBefore; } catch { }
                    BannerlordLinkModule.Log($"[army_create] CreateArmy threw @{username}: {cEx.Message}");
                    ActionFeedback.PostFailed(actionId, "create_threw"); return;
                }

                if (mp.Army == null)
                {
                    try { clan.Influence = influenceBefore; } catch { }
                    BannerlordLinkModule.Log($"[army_create] @{username}: армия не создалась (Army==null) — влияние вернул");
                    ActionFeedback.PostFailed(actionId, "army_creation_failed"); return;
                }

                // Влияние клана возвращаем как было (платили криптиками) + max cohesion.
                try { clan.Influence = influenceBefore; } catch { }
                try { mp.Army.Cohesion = 100f; } catch { }
                applied = true;
                ActionFeedback.PostApplied(actionId);

                // 2026-07-20 FIX — вернуть приказ в силу СРАЗУ. CreateArmy перетирает
                // цель партии (сбор у gather-точки), а наш hourly-reissue троттлится до
                // 4 игровых часов → в этом окне партия «уходила с осады». Переотдаём
                // приказ и возвращаем замок AI немедленно, не дожидаясь тика.
                if (activeOrder != null)
                {
                    try
                    {
                        BannerlordLink.Behaviors.PartyOrderBehavior.ReissueNow(username);
                        BannerlordLinkModule.Log(
                            $"[army_create] @{username}: приказ '{activeOrder.Value.orderType}' "
                            + $"переотдан армии (тип={armyType})");
                    }
                    catch (Exception rEx)
                    {
                        BannerlordLinkModule.Log($"[army_create] reissue warn @{username}: {rEx.Message}");
                    }
                }

                BannerlordLinkModule.Log(
                    $"[army_create OK] @{username} армия собрана у '{gather.Name}' " +
                    $"(созвано партий={callCount}, в армии сейчас={mp.Army.Parties?.Count ?? 1}; " +
                    $"остальные подойдут к точке сбора)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[army_create] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                // Созданную армию нельзя совместить с возвратом: поздний сбой
                // переотдачи приказа или логирования не отменяет основной эффект.
                if (!applied)
                    ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── DisbandArmyHandler — распустить армию зрителя ──────────────────────────
    public class DisbandArmyHandler : IActionHandler
    {
        public string ActionType => "hero.army_disband";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));
            MainThreadDispatcher.Enqueue(() => Apply(username, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string actionId)
        {
            try
            {
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null) { ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
                var mp = hero.PartyBelongedTo;
                if (mp == null || mp.Army == null) { ActionFeedback.PostFailed(actionId, "no_army"); return; }
                if (mp.Army.LeaderParty != mp)
                {
                    BannerlordLinkModule.Log($"[army_disband] REFUSE @{username}: не лидер армии");
                    ActionFeedback.PostFailed(actionId, "not_army_leader"); return;
                }
                DisbandArmyAction.ApplyByUnknownReason(mp.Army);
                BannerlordLinkModule.Log($"[army_disband OK] @{username} армия распущена");
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[army_disband] @{username} CRASHED: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
