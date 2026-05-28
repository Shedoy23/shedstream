using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
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
                if (kingdom.HasPolicy(policy))
                {
                    kingdom.RemovePolicy(policy);
                    BannerlordLinkModule.Log(
                        $"[diplo-policy] @{username} REMOVED policy '{policyName}' from {kingdom.Name}");
                }
                else
                {
                    kingdom.AddPolicy(policy);
                    BannerlordLinkModule.Log(
                        $"[diplo-policy] @{username} ENACTED policy '{policyName}' for {kingdom.Name}");
                }
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
}
