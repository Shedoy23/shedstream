using System;
using System.Collections.Generic;
using System.Linq;
using BannerlordLink.Util;
using TaleWorlds.ObjectSystem;
using System.Threading.Tasks;
using BannerlordLink.Net;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `hero.add_skill` — добавляет XP в указанный skill hero'я.
    ///
    /// data: { target, skill_key (e.g. "Bow"), xp (int) }
    /// API: hero.HeroDeveloper.AddSkillXp(skillObject, xp).
    ///
    /// Sprint 5.29: class-weighted random pick. Если skill_key пуст и у hero
    /// есть class (PowerCache) — skills этого класса × 12 weight, остальные × 1.
    /// Cavalry-viewer прокачивает Riding/Polearm в 12× чаще чем Crossbow.
    /// BLT pattern (ImproveAdoptedHero.cs SkillCategoryWeights).
    /// </summary>
    public class AddSkillXpHandler : IActionHandler
    {
        // Sprint 5.29: classKey → primary skill StringId list (mirror BLT weights).
        // Intentional class weights; registry discovery is independent of these labels.
        private static readonly Dictionary<string, string[]> CLASS_PRIMARY_SKILLS =
            new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
            {
                ["archer"]        = new[] { "Bow", "Throwing", "Athletics", "Tactics", "OneHanded" },
                ["horse_archer"]  = new[] { "Bow", "Riding", "OneHanded", "Throwing" },
                ["camel_archer"]  = new[] { "Bow", "Riding", "OneHanded", "Throwing" },
                ["cavalry"]       = new[] { "Riding", "Polearm", "OneHanded", "Athletics" },
                ["camel_cavalry"] = new[] { "Riding", "Polearm", "OneHanded", "Athletics" },
                ["knight"]        = new[] { "Riding", "OneHanded", "Polearm", "Athletics", "Leadership" },
                ["infantry"]      = new[] { "OneHanded", "TwoHanded", "Polearm", "Athletics" },
                ["tank"]          = new[] { "OneHanded", "Polearm", "Athletics", "Engineering" },
                ["berserk"]       = new[] { "TwoHanded", "OneHanded", "Athletics", "Polearm" },
                ["psycho"]        = new[] { "Athletics", "OneHanded", "TwoHanded" },
            };
        private const int CLASS_SKILL_WEIGHT = 12;   // классовые навыки качаются чаще
        private const int OTHER_SKILL_WEIGHT = 1;

        public string ActionType => "hero.add_skill";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string skillKey = (data["skill_key"]?.ToString() ?? "");
            int xp = (int?)data["xp"] ?? 0;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (xp <= 0)
                return Task.FromResult<(bool, string)>((false, "xp must be > 0"));
            // AUDIT 2026-05-29 (fix #4): cap backend-supplied xp. Outcome уже
            // ограничен SKILL_CAP=330, но без input-cap большой xp × reward_boost
            // мог переполнить (int)Math.Round(...) → отрицательный xp. Clamp.
            const int MAX_XP_GRANT = 1_000_000;
            if (xp > MAX_XP_GRANT) xp = MAX_XP_GRANT;
            // Если skill_key пуст — mod выберет random skill (server-side option
            // для simple UI с одной кнопкой "+XP в случайный skill").

            // Sprint 5.31 #45c — extract actionId один раз для refund'ов.
            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);

            MainThreadDispatcher.Enqueue(() =>
            {
                bool applied = false;
                Hero hero = null;
                SkillObject observedSkill = null;
                int observedLevel = 0, observedTotalXp = 0;
                float observedSkillXp = 0;
                bool mutationStarted = false;
                try
                {
                    hero = HeroLookup.FindByUsername(username);
                    if (hero == null || !hero.IsAlive)
                    {
                        // Sprint 5.31 #45c — REFUSE prefix + refund (Sprint 5.30 audit
                        // missed this file). Без refund viewer теряет крустики.
                        BannerlordLinkModule.Log($"[hero.add_skill] REFUSE @{username}: hero не найден или мёртв");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                        return;
                    }

                    string contextReason = HeroProgressionRuntime.ValidateContext(hero, data, (bool?)data["_daily"] == true);
                    if (contextReason != null) { ActionFeedback.PostFailed(actionId, contextReason); return; }
                    SkillObject skill = null;
                    if (string.IsNullOrEmpty(skillKey))
                    {
                        // Sprint 5.29: class-weighted random pick.
                        // Если у hero есть class в PowerCache → его skills × 12.
                        // Без class — uniform random (как раньше).
                        var rng = new Random();
                        var allSkills = HeroProgressionRuntime.XpCandidates(hero);
                        if (allSkills.Count == 0)
                        {
                            BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_available_skills");
                            return;
                        }

                        var hc = PowerCache.GetHeroClass(username);
                        string[] primary = null;
                        if (hc != null && !string.IsNullOrEmpty(hc.Value.classKey))
                        {
                            CLASS_PRIMARY_SKILLS.TryGetValue(hc.Value.classKey, out primary);
                        }

                        if (primary == null || primary.Length == 0)
                        {
                            // No class info → uniform pick (legacy behavior).
                            skill = allSkills[rng.Next(allSkills.Count)];
                        }
                        else
                        {
                            // Build weighted pool: primary × 12, others × 1.
                            // total = primary.Length × 12 + (all - primary) × 1.
                            var primarySet = new HashSet<string>(primary,
                                StringComparer.OrdinalIgnoreCase);
                            int totalWeight = 0;
                            foreach (var s in allSkills)
                            {
                                bool isPrimary = primarySet.Contains(s.StringId);
                                totalWeight += isPrimary ? CLASS_SKILL_WEIGHT : OTHER_SKILL_WEIGHT;
                            }
                            int roll = rng.Next(totalWeight);
                            int accum = 0;
                            foreach (var s in allSkills)
                            {
                                bool isPrimary = primarySet.Contains(s.StringId);
                                accum += isPrimary ? CLASS_SKILL_WEIGHT : OTHER_SKILL_WEIGHT;
                                if (roll < accum) { skill = s; break; }
                            }
                            if (skill == null) skill = allSkills[allSkills.Count - 1];
                            BannerlordLinkModule.Log(
                                $"[hero.add_skill] @{username} class={hc.Value.classKey} → " +
                                $"weighted pick: {skill.StringId} " +
                                $"({(primarySet.Contains(skill.StringId) ? "primary" : "other")})");
                        }
                        skillKey = skill.StringId;  // для log
                    }
                    else
                    {
                        skill = MBObjectManager.Instance.GetObjectTypeList<SkillObject>()
                            .FirstOrDefault(s => s != null && string.Equals(s.StringId, skillKey, StringComparison.Ordinal));
                    }
                    if (skill == null)
                    {
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "unknown_skill:" + skillKey);
                        return;
                    }

                    // Sprint 5.29 BLT-parity #9: apply reward_boost (role-based).
                    // Backend пушит data["reward_boost"]: viewer=1.0, mod=1.5,
                    // broadcaster=2.0. Subscriber detection TODO (Helix scope).
                    double rewardBoost = 1.0;
                    try { rewardBoost = (double?)data["reward_boost"] ?? 1.0; }
                    catch { }
                    if (double.IsNaN(rewardBoost) || double.IsInfinity(rewardBoost) || rewardBoost <= 0 || xp * rewardBoost > int.MaxValue)
                    { ActionFeedback.PostFailed(actionId, "invalid_reward_boost"); return; }
                    int boostedXp = (int)Math.Round(xp * rewardBoost);
                    if (boostedXp <= 0) { ActionFeedback.PostFailed(actionId, "invalid_xp"); return; }
                    string xpReason = HeroProgressionRuntime.XpReason(hero, skill);
                    if (xpReason != null) { ActionFeedback.PostFailed(actionId, xpReason); return; }

                    int before = hero.GetSkillValue(skill);
                    float xpBefore = hero.HeroDeveloper.GetSkillXpProgress(skill);

                    // Purchase ceiling is ShedLink policy. Native learning factors remain enabled.
                    const int SKILL_CAP = ProgressionPolicy.SkillPurchaseLimit;
                    observedSkill = skill; observedLevel = before; observedSkillXp = xpBefore;
                    observedTotalXp = hero.HeroDeveloper.TotalXp; mutationStarted = true;
                    hero.HeroDeveloper.AddSkillXp(skill, boostedXp, isAffectedByFocusFactor: true);
                    int levelAfterMutation = hero.GetSkillValue(skill);
                    float xpAfterMutation = hero.HeroDeveloper.GetSkillXpProgress(skill);
                    if (levelAfterMutation == before && xpAfterMutation == xpBefore && hero.HeroDeveloper.TotalXp == observedTotalXp)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.add_skill] REFUSE @{username}: {skill.StringId} " +
                            $"XP не изменился (level={before}, xp={xpBefore})");
                        BannerlordLink.Util.ActionFeedback.PostFailed(
                            actionId, "skill_xp_not_applied:" + skill.StringId);
                        return;
                    }
                    applied = true;
                    BannerlordLink.Util.ActionFeedback.PostApplied(actionId);
                    // 2026-05-31 (audit) — применяем level/derived-статы СРАЗУ, не ждём
                    // daily-tick (BLT SkillXP делает так же). Иначе level лагает день.
                    hero.HeroDeveloper.DevelopCharacterStats();
                    int after = hero.GetSkillValue(skill);
                    // Soft-cap clamp: если AddSkillXp перепрыгнул cap (большой
                    // boostedXp за раз), сжимаем до cap'а через SetInitialSkillLevel.
                    if (after > SKILL_CAP)
                    {
                        try
                        {
                            hero.HeroDeveloper.SetInitialSkillLevel(skill, SKILL_CAP);
                            after = SKILL_CAP;
                            BannerlordLinkModule.Log(
                                $"[hero.add_skill M6] @{username} {skill.StringId} clamped " +
                                $"to cap {SKILL_CAP} (overshoot from boostedXp)");
                        }
                        catch (Exception cex)
                        {
                            BannerlordLinkModule.Log(
                                $"[hero.add_skill M6] @{username} clamp warn: {cex.Message}");
                        }
                    }
                    if (rewardBoost > 1.0)
                        BannerlordLinkModule.Log(
                            $"[hero.add_skill] @{username} {skill.StringId} " +
                            $"+{boostedXp}xp (×{rewardBoost:F1} boost from {xp}xp) " +
                            $"({before} → {after})");
                    else
                        BannerlordLinkModule.Log(
                            $"[hero.add_skill] @{username} {skill.StringId} " +
                            $"+{boostedXp}xp ({before} → {after})");

                    // Push skill state update.
                    string evtData = JsonConvert.SerializeObject(new
                    {
                        username = username,
                        skill_key = skill.StringId,
                        level = after,
                        xp = (int)hero.HeroDeveloper.GetSkillXpProgress(skill),
                    });
                    Task.Run(async () => await BannerlordLinkModule.Backend
                        .PostEventAsync("bannerlord", "hero.skill_changed", evtData));
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log($"[hero.add_skill] @{username} CRASHED: {ex.Message}");
                    // После AddSkillXp эффект уже выдан: возврат создал бы двойную
                    // выгоду. До этой точки любой сбой обязан вернуть крустики.
                    if (!applied && mutationStarted)
                    {
                        bool unknown;
                        applied = ObserveXpEffect(hero, observedSkill, observedLevel, observedSkillXp, observedTotalXp, out unknown);
                        if (applied) ActionFeedback.PostApplied(actionId);
                        else if (unknown)
                        {
                            BannerlordLinkModule.Log("[hero.add_skill] cannot confirm mutation outcome action=" + actionId + " hero=" + hero.StringId);
                            ActionFeedback.PostFailed(actionId, "skill_xp_outcome_unknown");
                            return;
                        }
                    }
                    if (!applied)
                        BannerlordLink.Util.ActionFeedback.PostFailed(
                            actionId, "exception:" + ex.GetType().Name);
                }
                finally
                {
                    if (hero != null) try { HeroProgressionRuntime.Push(hero); }
                        catch (Exception syncEx) { BannerlordLinkModule.Log("[progression] snapshot retry on tick: " + syncEx.Message); }
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
        private static bool ObserveXpEffect(Hero hero, SkillObject skill, int level, float xp, int totalXp, out bool unknown)
        {
            bool effect = false; unknown = false;
            try { effect |= hero.GetSkillValue(skill) > level; } catch { unknown = true; }
            try { effect |= hero.HeroDeveloper.GetSkillXpProgress(skill) > xp; } catch { unknown = true; }
            try { effect |= hero.HeroDeveloper.TotalXp > totalXp; } catch { unknown = true; }
            return effect;
        }

    }
}
