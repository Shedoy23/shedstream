using System;
using System.Threading.Tasks;
using BannerlordLink.Util;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Sprint 5.33 (BLT-parity FAM) — mod handlers for viewer↔viewer family интеракции.
    ///
    /// Все handlers принимают `child_hero_id` (engine Hero.StringId) и resolve через
    /// MBObjectManager напрямую — дети могут быть не в HeroIdentityBehavior dict
    /// (M9 регистрирует только adopted [BLink], а дети — engine-created via marriage).
    /// Backend authorize'ит ownership через bannerlord_heirs.parent_username — mod
    /// просто верит payload (it's not user-supplied JWT, а pre-validated backend payload).
    ///
    /// 4 handlers:
    ///   - ActivateMarriageHandler — hero.activate_marriage (proposal accepted)
    ///   - ChildRenameHandler — hero.rename_child
    ///   - ChildLooksHandler — hero.change_child_looks (BodyProperties from body_code)
    ///   - ChildRespecSkillsHandler — hero.respec_child_skills (ClearHero + re-init)
    ///
    /// All 4 share resolver helper FindHeroByStringId + validation.
    /// </summary>
    internal static class FamilyHelper
    {
        public static Hero FindHeroByStringId(string heroStringId, out string reason)
        {
            reason = null;
            if (string.IsNullOrEmpty(heroStringId))
            {
                reason = "no_hero_id";
                return null;
            }
            Hero hero;
            try { hero = MBObjectManager.Instance.GetObject<Hero>(heroStringId); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[FAM helper] GetObject<Hero>('{heroStringId}') crashed: {ex.Message}");
                reason = "lookup_crash";
                return null;
            }
            if (hero == null)
            {
                reason = "hero_not_found";
                return null;
            }
            if (!hero.IsAlive)
            {
                reason = "hero_dead";
                return null;
            }
            return hero;
        }
    }

    // ── 1. ActivateMarriageHandler ─────────────────────────────────────────────
    public class ActivateMarriageHandler : IActionHandler
    {
        public string ActionType => "hero.activate_marriage";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string childAId = (data["child_a_hero_id"]?.ToString() ?? "").Trim();
            string childBId = (data["child_b_hero_id"]?.ToString() ?? "").Trim();
            string childAName = data["child_a_name"]?.ToString() ?? childAId;
            string childBName = data["child_b_name"]?.ToString() ?? childBId;
            string proposerUser = (data["proposer_username"]?.ToString() ?? "").ToLowerInvariant();
            string targetUser = (data["target_username"]?.ToString() ?? "").ToLowerInvariant();

            if (string.IsNullOrEmpty(childAId) || string.IsNullOrEmpty(childBId))
                return Task.FromResult<(bool, string)>((false, "no child hero_ids"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
                Activate(childAId, childBId, childAName, childBName,
                         proposerUser, targetUser, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Activate(string aId, string bId, string aName, string bName,
            string proposerUser, string targetUser, string actionId)
        {
            try
            {
                if (Campaign.Current == null)
                {
                    BannerlordLinkModule.Log("[FAM-marriage] no Campaign, skip");
                    ActionFeedback.PostFailed(actionId, "no_campaign");
                    return;
                }

                var heroA = FamilyHelper.FindHeroByStringId(aId, out string rA);
                if (heroA == null)
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-marriage] REFUSE: childA '{aName}' ({aId}) — {rA}");
                    ActionFeedback.PostFailed(actionId, "child_a_" + rA);
                    return;
                }
                var heroB = FamilyHelper.FindHeroByStringId(bId, out string rB);
                if (heroB == null)
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-marriage] REFUSE: childB '{bName}' ({bId}) — {rB}");
                    ActionFeedback.PostFailed(actionId, "child_b_" + rB);
                    return;
                }

                // Already married?
                if (heroA.Spouse != null || heroB.Spouse != null)
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-marriage] REFUSE: одна из сторон уже замужем " +
                        $"({heroA.Spouse?.Name?.ToString() ?? "—"} / {heroB.Spouse?.Name?.ToString() ?? "—"})");
                    ActionFeedback.PostFailed(actionId, "already_married");
                    return;
                }
                // Age check
                if (heroA.Age < 18f || heroB.Age < 18f)
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-marriage] REFUSE: too young (A={heroA.Age}, B={heroB.Age})");
                    ActionFeedback.PostFailed(actionId, "too_young");
                    return;
                }

                // BLT pattern + vanilla MarryAction: set Spouse mutual + handle clan.
                // Engine MarriageHelper делает additional housekeeping (banner-share,
                // clan-join), но прямой Spouse setter — minimal viable path.
                heroA.Spouse = heroB;
                heroB.Spouse = heroA;

                BannerlordLinkModule.Log(
                    $"[FAM-marriage] OK: '{heroA.Name}' (@{proposerUser}'s) ❤ " +
                    $"'{heroB.Name}' (@{targetUser}'s)");

                // Push event для backend log + UI notify.
                string evtData = JsonConvert.SerializeObject(new
                {
                    child_a_hero_id = aId,
                    child_b_hero_id = bId,
                    child_a_name = heroA.Name?.ToString() ?? aName,
                    child_b_name = heroB.Name?.ToString() ?? bName,
                    proposer_username = proposerUser,
                    target_username = targetUser,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.marriage_activated", evtData));
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[FAM-marriage] CRASHED: {ex.GetType().Name}: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed:" + ex.Message);
            }
        }
    }

    // ── 2. ChildRenameHandler ──────────────────────────────────────────────────
    public class ChildRenameHandler : IActionHandler
    {
        public string ActionType => "hero.rename_child";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string childId = (data["child_hero_id"]?.ToString() ?? "").Trim();
            string newName = (data["new_name"]?.ToString() ?? "").Trim();
            if (string.IsNullOrEmpty(childId))
                return Task.FromResult<(bool, string)>((false, "no child_hero_id"));
            if (string.IsNullOrEmpty(newName))
                return Task.FromResult<(bool, string)>((false, "no new_name"));
            if (newName.Length > 40) newName = newName.Substring(0, 40);

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(childId, newName, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string childId, string newName, string actionId)
        {
            try
            {
                var hero = FamilyHelper.FindHeroByStringId(childId, out string reason);
                if (hero == null) { ActionFeedback.PostFailed(actionId, reason); return; }

                string oldName = hero.Name?.ToString() ?? "?";
                hero.SetName(new TaleWorlds.Localization.TextObject(newName),
                             new TaleWorlds.Localization.TextObject(newName));
                BannerlordLinkModule.Log(
                    $"[FAM-rename] '{oldName}' → '{newName}' ({childId})");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[FAM-rename] CRASHED: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── 3. ChildLooksHandler — body_code change ────────────────────────────────
    public class ChildLooksHandler : IActionHandler
    {
        public string ActionType => "hero.change_child_looks";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string childId = (data["child_hero_id"]?.ToString() ?? "").Trim();
            string bodyCode = (data["body_code"]?.ToString() ?? "").Trim();
            if (string.IsNullOrEmpty(childId))
                return Task.FromResult<(bool, string)>((false, "no child_hero_id"));
            if (string.IsNullOrEmpty(bodyCode))
                return Task.FromResult<(bool, string)>((false, "no body_code"));

            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(childId, bodyCode, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string childId, string bodyCode, string actionId)
        {
            try
            {
                var hero = FamilyHelper.FindHeroByStringId(childId, out string reason);
                if (hero == null) { ActionFeedback.PostFailed(actionId, reason); return; }

                // Parse body_code → BodyProperties. TaleWorlds expects 256-hex
                // string или TextObject-encoded value. FromString — engine helper.
                BodyProperties bp;
                if (!BodyProperties.FromString(bodyCode, out bp))
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-looks] REFUSE: bad body_code '{bodyCode.Substring(0, Math.Min(32, bodyCode.Length))}...'");
                    ActionFeedback.PostFailed(actionId, "bad_body_code");
                    return;
                }
                // TaleWorlds 1.3.x не имеет public Hero.UpdatePlayerCharacterBodyProperties
                // (он есть в campaign player flow, но не exposed для arbitrary heroes).
                // Используем reflection на private field `_staticBodyProperties` /
                // `_dynamicBodyProperties` чтобы mutate body. Fallback — fail gracefully.
                bool applied = false;
                try
                {
                    // Hero has `StaticBodyProperties` (set in ctor) + dynamic (BodyProperties).
                    // BLT pattern: set both через reflection backing fields.
                    var staticField = HarmonyLib.AccessTools.Field(
                        typeof(Hero), "_staticBodyProperties");
                    if (staticField != null)
                    {
                        staticField.SetValue(hero, bp.StaticProperties);
                        applied = true;
                    }
                    // Dynamic body (age/build/weight) — separate field.
                    var dynamicField = HarmonyLib.AccessTools.Field(
                        typeof(Hero), "_bodyProperties");
                    if (dynamicField != null)
                    {
                        dynamicField.SetValue(hero, bp);
                        applied = true;
                    }
                }
                catch (Exception rEx)
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-looks] reflection warn: {rEx.Message}");
                }

                if (applied)
                {
                    BannerlordLinkModule.Log($"[FAM-looks] OK: '{hero.Name}' body updated");
                }
                else
                {
                    BannerlordLinkModule.Log(
                        $"[FAM-looks] WARN: BodyProperties fields not found — no-op для hero={hero.Name}");
                    ActionFeedback.PostFailed(actionId, "body_field_not_found");
                    return;
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[FAM-looks] CRASHED: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }

    // ── 4. ChildRespecSkillsHandler ────────────────────────────────────────────
    public class ChildRespecSkillsHandler : IActionHandler
    {
        public string ActionType => "hero.respec_child_skills";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string childId = (data["child_hero_id"]?.ToString() ?? "").Trim();
            if (string.IsNullOrEmpty(childId))
                return Task.FromResult<(bool, string)>((false, "no child_hero_id"));
            string actionId = ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(childId, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string childId, string actionId)
        {
            try
            {
                var hero = FamilyHelper.FindHeroByStringId(childId, out string reason);
                if (hero == null) { ActionFeedback.PostFailed(actionId, reason); return; }

                if (hero.HeroDeveloper == null)
                {
                    BannerlordLinkModule.Log("[FAM-respec] no HeroDeveloper");
                    ActionFeedback.PostFailed(actionId, "no_developer");
                    return;
                }

                // Clear все skills + attributes + focuses → fresh slate.
                // AdoptHeroHandler pattern: ClearHero + 1 baseline skill point чтобы
                // engine не считал hero "0-points orphan" (BLT discovery, save reload crash).
                hero.HeroDeveloper.ClearHero();
                hero.HeroDeveloper.SetInitialSkillLevel(DefaultSkills.OneHanded, 1);
                hero.HeroDeveloper.InitializeHeroDeveloper();

                BannerlordLinkModule.Log($"[FAM-respec] OK: '{hero.Name}' skills reset");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[FAM-respec] CRASHED: {ex.Message}");
                ActionFeedback.PostFailed(actionId, "crashed");
            }
        }
    }
}
