using System;
using System.Linq;
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
    /// Sprint 5.8 — `hero.add_focus` action. Viewer тратит Hero.Gold чтобы
    /// добавить focus point в конкретный skill (или random).
    ///
    /// BLT pattern (FocusPoints.cs): tier-based cost per current focus level:
    ///   F1=30K, F2=40K, F3=50K, F4=60K, F5=75K динаров.
    ///   Max 5 focus per skill.
    ///
    /// data: {target, skill_key (optional), amount (default 1)}
    ///   skill_key empty/null → random improvable skill
    ///
    /// Skills: OneHanded, TwoHanded, Polearm, Bow, Crossbow, Throwing,
    ///         Athletics, Riding, Smithing, Scouting, Tactics, Roguery,
    ///         Charm, Leadership, Trade, Steward, Medicine, Engineering
    /// </summary>
    public class AddFocusHandler : IActionHandler
    {
        public string ActionType => "hero.add_focus";

        // BLT default focus tier costs (соответствует FocusPointsSettings)
        private static readonly int[] FOCUS_TIER_COSTS =
        {
            30_000,  // F0 → F1
            40_000,  // F1 → F2
            50_000,  // F2 → F3
            60_000,  // F3 → F4
            75_000,  // F4 → F5
        };

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no username"));

            string skillKey = (data["skill_key"]?.ToString() ?? "").Trim();
            int amount = (int?)data["amount"] ?? 1;
            if (amount < 1) amount = 1;
            if (amount > 5) amount = 5;

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() => Apply(username, skillKey, amount, actionId));
            return Task.FromResult<(bool, string)>((true, null));
        }

        private static void Apply(string username, string skillKey, int amount, string actionId)
        {
            bool committed = false;
            try
            {
                if (TaleWorlds.MountAndBlade.Mission.Current != null)
                {
                    BannerlordLinkModule.Log(
                        $"[add_focus] REFUSE @{username}: нельзя во время Mission (engine crash risk)");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_mission");
                    return;
                }

                var hero = HeroLookup.FindByUsername(username);
                if (hero == null || !hero.IsAlive)
                {
                    BannerlordLinkModule.Log(
                        $"[add_focus] REFUSE @{username}: hero не найден / мёртв");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                    return;
                }

                SkillObject skill = null;
                var allSkills = MBObjectManager.Instance.GetObjectTypeList<SkillObject>();
                if (allSkills == null || allSkills.Count == 0)
                {
                    BannerlordLinkModule.Log($"[add_focus] REFUSE @{username}: no skills available");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_skills_object");
                    return;
                }

                if (!string.IsNullOrEmpty(skillKey))
                {
                    skill = allSkills.FirstOrDefault(s =>
                        string.Equals(s.StringId, skillKey, StringComparison.OrdinalIgnoreCase)
                        || string.Equals(s.Name?.ToString(), skillKey, StringComparison.OrdinalIgnoreCase));
                    if (skill == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[add_focus] REFUSE @{username}: skill '{skillKey}' не найден");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "unknown_skill:" + skillKey);
                        return;
                    }
                    if (hero.HeroDeveloper.GetFocus(skill) >= 5)
                    {
                        BannerlordLinkModule.Log(
                            $"[add_focus] REFUSE @{username}: {skill.StringId} уже F5 (max)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "skill_focus_maxed");
                        return;
                    }
                }
                else
                {
                    var improvable = allSkills.Where(s => hero.HeroDeveloper.GetFocus(s) < 5).ToList();
                    if (improvable.Count == 0)
                    {
                        BannerlordLinkModule.Log(
                            $"[add_focus] REFUSE @{username}: все skills уже F5 (max)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "all_skills_focus_maxed");
                        return;
                    }
                    // Sprint 5.32 (BLT-parity LOW-5) — engine-grade MBRandom.
                    skill = improvable[TaleWorlds.Core.MBRandom.RandomInt(improvable.Count)];
                }

                int currentFocus = hero.HeroDeveloper.GetFocus(skill);
                int maxAdd = 5 - currentFocus;
                if (amount > maxAdd) amount = maxAdd;

                int totalCost = 0;
                for (int i = 0; i < amount; i++)
                {
                    int idx = currentFocus + i;
                    if (idx < FOCUS_TIER_COSTS.Length)
                        totalCost += FOCUS_TIER_COSTS[idx];
                    else
                        totalCost += FOCUS_TIER_COSTS[FOCUS_TIER_COSTS.Length - 1];
                }

                if (hero.Gold < totalCost)
                {
                    BannerlordLinkModule.Log(
                        $"[add_focus] REFUSE @{username}: not enough hero gold " +
                        $"({hero.Gold} < {totalCost}) для +{amount} focus в {skill.StringId}");
                    BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "not_enough_hero_gold");
                    return;
                }

                // Charge first, but compensate if the engine mutation fails or
                // does not satisfy its postcondition.
                GiveGoldAction.ApplyBetweenCharacters(hero, null, totalCost, true);
                try
                {
                    hero.HeroDeveloper.AddFocus(skill, amount, checkUnspentFocusPoints: false);
                }
                catch (Exception mutationEx)
                {
                    HeroGoldCharge.Refund(hero, totalCost, "add_focus");
                    ActionFeedback.PostFailed(actionId, "focus_apply_failed");
                    BannerlordLinkModule.Log(
                        $"[add_focus] @{username} mutation failed: {mutationEx.Message}");
                    return;
                }
                int newFocus = hero.HeroDeveloper.GetFocus(skill);
                if (newFocus <= currentFocus)
                {
                    HeroGoldCharge.Refund(hero, totalCost, "add_focus");
                    ActionFeedback.PostFailed(actionId, "focus_postcondition_failed");
                    return;
                }
                committed = true;

                BannerlordLinkModule.Log(
                    $"[add_focus] @{username}: +{amount} focus в {skill.StringId} " +
                    $"({currentFocus} → {newFocus}), -{totalCost}💰 gold={hero.Gold}");

                // Push event для backend display
                string evtData = JsonConvert.SerializeObject(new
                {
                    username = username,
                    skill_key = skill.StringId,
                    skill_name = skill.Name?.ToString() ?? skill.StringId,
                    amount = amount,
                    new_focus = newFocus,
                    cost = totalCost,
                });
                Task.Run(async () => await BannerlordLinkModule.Backend
                    .PostEventAsync("bannerlord", "hero.focus_changed", evtData));

                HeroStateSync.Push(hero);
                ActionFeedback.PostApplied(actionId);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[add_focus] @{username} CRASHED: {ex.GetType().Name}: {ex.Message}");
                if (!committed)
                    ActionFeedback.PostFailed(actionId, "crashed:" + ex.GetType().Name);
            }
        }
    }
}
