using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Election;   // vanilla KingdomDecision (DeclareWar/MakePeace)
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity DIPLO) — Kingdom politics + ransom (Lait fork inspired).
    ///
    /// 3 handlers:
    ///   EnactPolicyHandler   — king/clan-leader propose policy → Kingdom.AddPolicy
    ///                          (direct apply: viewer заплатил, gets immediate effect)
    ///   MakePeaceHandler     — king-only: MakePeaceAction.Apply(myKingdom, targetKingdom)
    ///   PayRansomHandler     — backend pool достиг cost → EndCaptivityAction.ApplyByRansom
    ///
    /// Pragmatic choice: direct Apply (skip lord-voting dance) — viewer купил effect,
    /// должен получить result. Иначе frustration: 1500⦷ за policy которую lord vote rejected.
    /// </summary>
    public class EnactPolicyHandler : IActionHandler
    {
        public string ActionType => "hero.enact_policy";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string kingdomId = (data["kingdom_id"]?.ToString() ?? "").Trim();
            string policyId = (data["policy_id"]?.ToString() ?? "").Trim();
            string policyName = data["policy_name"]?.ToString() ?? policyId;
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[diplo-policy ENTRY] @{username} kingdom={kingdomId} policy={policyId} " +
                $"name='{policyName}' action_id={actionId}");

            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(policyId))
            {
                BannerlordLinkModule.Log("[diplo-policy REFUSE] missing username or policy_id");
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            }

            MainThreadDispatcher.Enqueue(() =>
                Apply(username, kingdomId, policyId, policyName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string kingdomId,
            string policyId, string policyName, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }

                var kingdom = hero.Clan?.Kingdom;
                if (kingdom == null)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-policy] REFUSE @{username}: не в kingdom'е");
                    ActionFeedback.PostFailed(actionId, "no_kingdom");
                    return;
                }
                // Optional defensive: backend already checked, но guard.
                if (kingdom.Leader != hero && hero.Clan?.Leader != hero)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-policy] REFUSE @{username}: не king/clan-leader");
                    ActionFeedback.PostFailed(actionId, "not_authorized");
                    return;
                }

                // Resolve PolicyObject by StringId.
                PolicyObject policy = null;
                try { policy = MBObjectManager.Instance.GetObject<PolicyObject>(policyId); }
                catch { }
                if (policy == null)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-policy] REFUSE @{username}: policy '{policyId}' not found");
                    ActionFeedback.PostFailed(actionId, "policy_not_found");
                    return;
                }

                // Toggle: HasPolicy → Remove, else Add. Viewer пает crustics за
                // "enact" — backend marks status='enacted'. Toggle semantics
                // даёт viewer'у возможность откатить плохую policy за тот же
                // прайс. UI можно дальше показать diff состояния.
                bool wantEnact = !kingdom.HasPolicy(policy);
                if (wantEnact) kingdom.AddPolicy(policy);
                else           kingdom.RemovePolicy(policy);

                // 2026-07-22 — проверяем ПО ФАКТУ, а не по факту вызова: движковые
                // «сделай X» умеют молча ничего не делать. Действие платное (1500💎),
                // поэтому тихий no-op обязан стать провалом → авторефанд.
                bool nowHas = kingdom.HasPolicy(policy);
                if (nowHas != wantEnact)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-policy] @{username} NO-OP: '{policyName}' в {kingdom.Name} " +
                        $"остался {(nowHas ? "принятым" : "непринятым")} — рефанд");
                    ActionFeedback.PostFailed(actionId, "policy_no_effect");
                    return;
                }

                BannerlordLinkModule.Log(
                    $"[diplo-policy] @{username} {(wantEnact ? "ENACTED" : "REMOVED")} " +
                    $"policy '{policyName}' {(wantEnact ? "for" : "from")} {kingdom.Name}");
                // Итог наверх: ACK от ActionPoller приходит ДО этой работы и ничего
                // не доказывает — без этого события заявка вечно висит 'pending'.
                ActionFeedback.PostPolicyResult(actionId, policyId, wantEnact);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[diplo-policy] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── MakePeaceHandler — direct peace via MakePeaceAction ────────────────────
    public class MakePeaceHandler : IActionHandler
    {
        public string ActionType => "hero.make_peace";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string targetKingdomId = (data["target_kingdom_id"]?.ToString() ?? "").Trim();
            string targetKingdomName = data["target_kingdom_name"]?.ToString() ?? targetKingdomId;
            int tribute = 0;
            try { tribute = (int)(data["offered_tribute"]?.ToObject<int>() ?? 0); } catch { }
            // AUDIT 2026-05-29 (fix #4): clamp backend-supplied tribute к разумному
            // диапазону. Мод не должен слепо доверять payload — malformed/большое
            // значение могло бы сломать дипломатию/экономику.
            const int MAX_TRIBUTE = 5_000_000;
            if (tribute > MAX_TRIBUTE) tribute = MAX_TRIBUTE;
            else if (tribute < -MAX_TRIBUTE) tribute = -MAX_TRIBUTE;
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[diplo-peace ENTRY] @{username} → target='{targetKingdomName}' " +
                $"(id={targetKingdomId}) tribute={tribute} action_id={actionId}");

            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(targetKingdomId))
            {
                BannerlordLinkModule.Log("[diplo-peace REFUSE] missing username or target_kingdom_id");
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            }

            MainThreadDispatcher.Enqueue(() =>
                Apply(username, targetKingdomId, targetKingdomName, tribute, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string targetKingdomId,
            string targetKingdomName, int tribute, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }

                var myKingdom = hero.Clan?.Kingdom;
                if (myKingdom == null)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-peace] REFUSE @{username}: не в kingdom'е");
                    ActionFeedback.PostFailed(actionId, "no_kingdom");
                    return;
                }
                if (myKingdom.Leader != hero)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-peace] REFUSE @{username}: не король");
                    ActionFeedback.PostFailed(actionId, "not_king");
                    return;
                }

                Kingdom target = null;
                try { target = MBObjectManager.Instance.GetObject<Kingdom>(targetKingdomId); }
                catch { }
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-peace] REFUSE @{username}: target kingdom '{targetKingdomId}' not found");
                    ActionFeedback.PostFailed(actionId, "target_not_found");
                    return;
                }
                if (target == myKingdom)
                {
                    ActionFeedback.PostFailed(actionId, "self_target");
                    return;
                }

                // Peace requires that we ARE at war. Otherwise no-op.
                if (!myKingdom.IsAtWarWith(target))
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-peace] REFUSE @{username}: уже мир с {target.Name}");
                    ActionFeedback.PostFailed(actionId, "not_at_war");
                    return;
                }

                // Direct apply — viewer заплатил crustics, hard peace.
                // Tribute can be positive (we pay) or negative (they pay us);
                // engine clamps internally.
                if (tribute != 0)
                {
                    MakePeaceAction.ApplyByKingdomDecision(myKingdom, target, tribute, 0);
                }
                else
                {
                    MakePeaceAction.Apply(myKingdom, target);
                }
                BannerlordLinkModule.Log(
                    $"[diplo-peace] @{username} PEACE: {myKingdom.Name} ↔ {target.Name} (tribute={tribute})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[diplo-peace] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // 2026-06-14 — общий резолвер королевства по StringId/имени. GetObject<Kingdom>
    // часто возвращает null (kingdoms — campaign-объекты, не в MBObjectManager) →
    // надёжный путь: Kingdom.All. Был баг «target_not_found» на валидных vlandia/empire.
    internal static class DiploUtil
    {
        public static Kingdom ResolveKingdom(string id, string name)
        {
            Kingdom k = null;
            try { k = MBObjectManager.Instance.GetObject<Kingdom>(id); } catch { }
            if (k != null) return k;
            try
            {
                foreach (var kk in Kingdom.All)
                    if (kk != null && (kk.StringId == id ||
                        string.Equals(kk.Name?.ToString(), name, StringComparison.OrdinalIgnoreCase)))
                        return kk;
            }
            catch { }
            return null;
        }

        // 2026-07-20 (#38) — предложение войны/мира «сразу становится неактуальным».
        // Декомпайл KingdomDecision.ShouldBeCancelled: решение от НЕ-игрока движок
        // отменяет тем же тиком, если у клана-предлагающего не хватает ВЛИЯНИЯ
        // спонсировать своё предложение (Influence < 1.5×стоимости → flag=true).
        // А vanilla AddDecision ещё и СПИСЫВАЕТ влияние (GetInfluenceCost) → у мелкого
        // viewer-клана оно уходит в минус → мгновенная отмена. Зритель платит крустиками,
        // влиянием платить не должен.
        // Фикс: (1) AddDecision(ignoreInfluenceCost:true) — не списываем; (2) даём клану
        // влияние-буфер, чтобы flag=false и решение дошло до реального голосования (а не
        // выкидывалось до него). Дальше исход честно решают кланы/король.
        public static void SubmitDecisionToVote(Kingdom kingdom, Clan proposerClan,
            TaleWorlds.CampaignSystem.Election.KingdomDecision decision)
        {
            try
            {
                if (proposerClan != null && proposerClan.Influence < 300f)
                {
                    try { proposerClan.Influence = 300f; } catch { }
                }
            }
            catch { }
            kingdom.AddDecision(decision, ignoreInfluenceCost: true);
        }
    }

    // ── ProposeWarHandler — предложить войну ЧЕРЕЗ ГОЛОСОВАНИЕ кланов ──────────
    // 2026-06-14. Vanilla DeclareWarDecision → Kingdom.AddDecision → движок собирает
    // голоса кланов королевства и резолвит сам. Зритель платит за ПРЕДЛОЖЕНИЕ, не за
    // результат (может не пройти). Любой лидер клана в королевстве.
    public class ProposeWarHandler : IActionHandler
    {
        public string ActionType => "kingdom.propose_war";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string targetKingdomId = (data["target_kingdom_id"]?.ToString() ?? "").Trim();
            string targetKingdomName = data["target_kingdom_name"]?.ToString() ?? targetKingdomId;
            string actionId = ActionFeedback.GetActionId(data);
            BannerlordLinkModule.Log($"[diplo-war ENTRY] @{username} → '{targetKingdomName}' (id={targetKingdomId}) action_id={actionId}");
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(targetKingdomId))
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            MainThreadDispatcher.Enqueue(() => Apply(username, targetKingdomId, targetKingdomName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string targetKingdomId, string targetKingdomName, string actionId)
        {
            try
            {
                if (Campaign.Current == null) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: no campaign"); ActionFeedback.PostFailed(actionId, "no_campaign"); return; }
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: hero не найден/мёртв"); ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
                var myKingdom = hero.Clan?.Kingdom;
                if (myKingdom == null) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: не в kingdom'е"); ActionFeedback.PostFailed(actionId, "no_kingdom"); return; }
                if (hero.Clan?.Leader != hero) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: не лидер клана"); ActionFeedback.PostFailed(actionId, "not_clan_leader"); return; }

                // Резолв целевого королевства. GetObject<Kingdom> ненадёжен (kingdoms —
                // campaign-объекты, не всегда в MBObjectManager) → fallback на Kingdom.All.
                Kingdom target = DiploUtil.ResolveKingdom(targetKingdomId, targetKingdomName);
                if (target == null) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: target '{targetKingdomId}'/'{targetKingdomName}' не найден"); ActionFeedback.PostFailed(actionId, "target_not_found"); return; }
                if (target == myKingdom) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: self-target"); ActionFeedback.PostFailed(actionId, "self_target"); return; }
                if (target.IsEliminated) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: target eliminated"); ActionFeedback.PostFailed(actionId, "target_eliminated"); return; }
                if (myKingdom.IsAtWarWith(target)) { BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: уже воюем с {target.Name}"); ActionFeedback.PostFailed(actionId, "already_at_war"); return; }

                // Дубль: предложение войны против этого таргета уже на голосовании?
                try
                {
                    foreach (var d in myKingdom.UnresolvedDecisions)
                        if (d is DeclareWarDecision w && w.FactionToDeclareWarOn == target)
                        {
                            BannerlordLinkModule.Log($"[diplo-war] REFUSE @{username}: война с {target.Name} уже на голосовании");
                            ActionFeedback.PostFailed(actionId, "duplicate_decision"); return;
                        }
                }
                catch { }

                var decision = new DeclareWarDecision(hero.Clan, target);
                DiploUtil.SubmitDecisionToVote(myKingdom, hero.Clan, decision);
                BannerlordLinkModule.Log($"[diplo-war OK] @{username} предложил войну: {myKingdom.Name} → {target.Name} (на голосование кланов)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[diplo-war] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── ProposePeaceHandler — предложить мир ЧЕРЕЗ ГОЛОСОВАНИЕ кланов ──────────
    public class ProposePeaceHandler : IActionHandler
    {
        public string ActionType => "kingdom.propose_peace";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? "").Trim().ToLowerInvariant();
            string targetKingdomId = (data["target_kingdom_id"]?.ToString() ?? "").Trim();
            string targetKingdomName = data["target_kingdom_name"]?.ToString() ?? targetKingdomId;
            string actionId = ActionFeedback.GetActionId(data);
            BannerlordLinkModule.Log($"[diplo-ppeace ENTRY] @{username} → '{targetKingdomName}' (id={targetKingdomId}) action_id={actionId}");
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(targetKingdomId))
                return Task.FromResult<(bool, string)>((false, "missing fields"));
            MainThreadDispatcher.Enqueue(() => Apply(username, targetKingdomId, targetKingdomName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string targetKingdomId, string targetKingdomName, string actionId)
        {
            try
            {
                if (Campaign.Current == null) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: no campaign"); ActionFeedback.PostFailed(actionId, "no_campaign"); return; }
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: hero не найден/мёртв"); ActionFeedback.PostFailed(actionId, "hero_not_found"); return; }
                var myKingdom = hero.Clan?.Kingdom;
                if (myKingdom == null) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: не в kingdom'е"); ActionFeedback.PostFailed(actionId, "no_kingdom"); return; }
                if (hero.Clan?.Leader != hero) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: не лидер клана"); ActionFeedback.PostFailed(actionId, "not_clan_leader"); return; }

                Kingdom target = DiploUtil.ResolveKingdom(targetKingdomId, targetKingdomName);
                if (target == null) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: target '{targetKingdomId}'/'{targetKingdomName}' не найден"); ActionFeedback.PostFailed(actionId, "target_not_found"); return; }
                if (target == myKingdom) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: self-target"); ActionFeedback.PostFailed(actionId, "self_target"); return; }
                if (!myKingdom.IsAtWarWith(target)) { BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: не воюем с {target.Name}"); ActionFeedback.PostFailed(actionId, "not_at_war"); return; }

                // Дубль
                try
                {
                    foreach (var d in myKingdom.UnresolvedDecisions)
                        if (d is MakePeaceKingdomDecision p && p.FactionToMakePeaceWith == target)
                        {
                            BannerlordLinkModule.Log($"[diplo-ppeace] REFUSE @{username}: мир с {target.Name} уже на голосовании");
                            ActionFeedback.PostFailed(actionId, "duplicate_decision"); return;
                        }
                }
                catch { }

                // 0 tribute — движок + голосование решают остальное.
                var decision = new MakePeaceKingdomDecision(hero.Clan, target, 0, 0);
                DiploUtil.SubmitDecisionToVote(myKingdom, hero.Clan, decision);
                BannerlordLinkModule.Log($"[diplo-ppeace OK] @{username} предложил мир: {myKingdom.Name} ↔ {target.Name} (на голосование кланов)");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[diplo-ppeace] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── PayRansomHandler — pool full → release prisoner ────────────────────────
    public class PayRansomHandler : IActionHandler
    {
        public string ActionType => "hero.pay_ransom";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string capturedUser = (data["captured_hero"]?.ToString()
                                   ?? data["target"]?.ToString() ?? "")
                                  .Trim().ToLowerInvariant();
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[diplo-ransom ENTRY] release captured @{capturedUser} action_id={actionId}");

            if (string.IsNullOrEmpty(capturedUser))
            {
                BannerlordLinkModule.Log("[diplo-ransom REFUSE] no captured_hero");
                return Task.FromResult<(bool, string)>((false, "no captured_hero"));
            }

            MainThreadDispatcher.Enqueue(() => Apply(capturedUser, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string capturedUser, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                var hero = BannerlordLink.Actions.HeroLookup.FindByUsername(capturedUser);
                if (hero == null)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }
                if (!hero.IsPrisoner)
                {
                    BannerlordLinkModule.Log(
                        $"[diplo-ransom] @{capturedUser} не в плену (уже освобождён?)");
                    // Not a failure — pool was paid before mod synced.
                    return;
                }

                // ApplyByRansom requires (prisoner, payer). Payer = main hero
                // (стример conceptually платит, реально crustics from chat pool).
                var payer = Hero.MainHero;
                EndCaptivityAction.ApplyByRansom(hero, payer);
                BannerlordLinkModule.Log(
                    $"[diplo-ransom] RELEASED @{capturedUser} by ransom (payer={payer?.Name})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[diplo-ransom] @{capturedUser} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── SetKingdomTaxHandler — king sets kingdom tax rate (Backlog #1, BLT C.5) ──
    public class SetKingdomTaxHandler : IActionHandler
    {
        public string ActionType => "kingdom.set_tax_rate";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["initiated_by"]?.ToString() ?? data["target"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            int ratePct = 0;
            try { ratePct = (int)(data["tax_rate_pct"]?.ToObject<int>() ?? 0); } catch { }
            // Clamp 0..100 (mod-side defense; backend тоже валидирует).
            if (ratePct < 0) ratePct = 0;
            else if (ratePct > 100) ratePct = 100;
            string actionId = ActionFeedback.GetActionId(data);

            BannerlordLinkModule.Log(
                $"[kingdom-tax ENTRY] @{username} rate={ratePct}% action_id={actionId}");

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            MainThreadDispatcher.Enqueue(() => Apply(username, ratePct, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, int ratePct, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }
                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    ActionFeedback.PostFailed(actionId, "hero_not_found");
                    return;
                }
                var kingdom = hero.Clan?.Kingdom;
                if (kingdom == null)
                {
                    BannerlordLinkModule.Log($"[kingdom-tax] REFUSE @{username}: не в kingdom'е");
                    ActionFeedback.PostFailed(actionId, "no_kingdom");
                    return;
                }
                // King-only: только правитель королевства задаёт налог.
                if (kingdom.Leader != hero)
                {
                    BannerlordLinkModule.Log($"[kingdom-tax] REFUSE @{username}: не король");
                    ActionFeedback.PostFailed(actionId, "not_king");
                    return;
                }
                var beh = BannerlordLink.Behaviors.KingdomTaxBehavior.Current;
                if (beh == null)
                {
                    ActionFeedback.PostFailed(actionId, "behavior_missing");
                    return;
                }
                beh.SetKingdomTaxRate(kingdom, ratePct / 100f);
                BannerlordLinkModule.Log(
                    $"[kingdom-tax] @{username} set {kingdom.Name} tax → {ratePct}%");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[kingdom-tax] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
