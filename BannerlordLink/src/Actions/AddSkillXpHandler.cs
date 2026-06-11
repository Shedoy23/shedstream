using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
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
    /// есть class (PowerCache) — skills этого класса × 15 weight, остальные × 1.
    /// Cavalry-viewer прокачивает Riding/Polearm в 15× чаще чем Crossbow.
    /// BLT pattern (ImproveAdoptedHero.cs SkillCategoryWeights).
    /// </summary>
    public class AddSkillXpHandler : IActionHandler
    {
        // Sprint 5.29: classKey → primary skill StringId list (mirror BLT weights).
        // Lowercase StringIds (matches DefaultSkills property names lower).
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
            string skillKey = (data["skill_key"]?.ToString() ?? "").Trim();
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
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null || !hero.IsAlive)
                    {
                        // Sprint 5.31 #45c — REFUSE prefix + refund (Sprint 5.30 audit
                        // missed this file). Без refund viewer теряет крустики.
                        BannerlordLinkModule.Log($"[hero.add_skill] REFUSE @{username}: hero не найден или мёртв");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                        return;
                    }

                    // Skill resolution:
                    //   skillKey пуст → random pick из all DefaultSkills properties
                    //   skillKey задан → lookup по name (case-insensitive)
                    SkillObject skill = null;
                    var t = typeof(DefaultSkills);
                    var allSkillProps = t.GetProperties(BindingFlags.Public | BindingFlags.Static)
                        .Where(p => p.PropertyType == typeof(SkillObject))
                        .ToList();

                    if (string.IsNullOrEmpty(skillKey))
                    {
                        // Sprint 5.29: class-weighted random pick.
                        // Если у hero есть class в PowerCache → его skills × 15.
                        // Без class — uniform random (как раньше).
                        var rng = new Random();
                        var allSkills = allSkillProps
                            .Select(p => p.GetValue(null) as SkillObject)
                            .Where(s => s != null)
                            .ToList();
                        if (allSkills.Count == 0)
                        {
                            // Sprint 5.31 #45c — reflection broke (новая версия игры?).
                            // Was: silent return. Теперь REFUSE + refund.
                            BannerlordLinkModule.Log(
                                $"[hero.add_skill] REFUSE @{username}: DefaultSkills reflection " +
                                "вернула 0 — версия игры изменилась?");
                            BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "no_skills_via_reflection");
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
                            // Build weighted pool: primary × 15, others × 1.
                            // total = primary.Length × 15 + (all - primary) × 1.
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
                        foreach (var p in allSkillProps)
                        {
                            if (!string.Equals(p.Name, skillKey, StringComparison.OrdinalIgnoreCase))
                                continue;
                            skill = p.GetValue(null) as SkillObject;
                            break;
                        }
                        if (skill == null)
                        {
                            foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Static))
                            {
                                if (f.FieldType != typeof(SkillObject)) continue;
                                if (!string.Equals(f.Name, skillKey, StringComparison.OrdinalIgnoreCase))
                                    continue;
                                skill = f.GetValue(null) as SkillObject;
                                break;
                            }
                        }
                    }
                    if (skill == null)
                    {
                        // Sprint 5.31 #45c — было silent return без refund.
                        // Теперь REFUSE + refund: viewer ошибся в skill_key,
                        // вернём ему крустики.
                        BannerlordLinkModule.Log(
                            $"[hero.add_skill] REFUSE @{username}: skill '{skillKey}' не найден " +
                            "(пробуй: Bow / OneHanded / TwoHanded / Polearm / Crossbow / " +
                            "Throwing / Riding / Athletics / Crafting / Tactics / Scouting / " +
                            "Roguery / Charm / Leadership / Trade / Steward / Medicine / Engineering)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "unknown_skill:" + skillKey);
                        return;
                    }

                    // Sprint 5.29 BLT-parity #9: apply reward_boost (role-based).
                    // Backend пушит data["reward_boost"]: viewer=1.0, mod=1.5,
                    // broadcaster=2.0. Subscriber detection TODO (Helix scope).
                    double rewardBoost = 1.0;
                    try { rewardBoost = (double?)data["reward_boost"] ?? 1.0; }
                    catch { }
                    int boostedXp = (int)Math.Round(xp * rewardBoost);

                    int before = hero.GetSkillValue(skill);

                    // Sprint 5.32 (BLT-parity M6) — skill cap 330.
                    // BLT default (BLTAdoptAHero MaxSkillLevel = 330). Без cap'а
                    // viewer мог раскачать одну skill до 1023 (engine maximum),
                    // что ломает баланс — perfect aim archer / one-shot Polearm.
                    // Cap 330 = ~T6 champion-level, оставляет потолок для
                    // дальнейшего progression через levels/attributes, но
                    // блокирует абсурдные значения. Refund крустики при отказе.
                    const int SKILL_CAP = 330;
                    if (before >= SKILL_CAP)
                    {
                        BannerlordLinkModule.Log(
                            $"[hero.add_skill] REFUSE @{username}: {skill.StringId} " +
                            $"уже на cap'е ({before} >= {SKILL_CAP}). " +
                            $"Прокачка остановлена — выбирай другой skill.");
                        BannerlordLink.Util.ActionFeedback.PostFailed(
                            actionId, "skill_cap_reached:" + skill.StringId);
                        return;
                    }

                    // Sprint 5.32 (BLT-parity LOW-2) — isAffectedByFocusFactor: true.
                    // Natural-balance: XP получаемый × focus-multiplier (1.0–2.0 по focus
                    // points в skill'е). Без флага — все viewers получают одинаковый
                    // фиксированный XP, что обесценивает focus-purchases. Теперь focus
                    // = реальный эффект на XP-throughput. BLT default (BLTAdoptAHero
                    // AddSkillXpAction calls with affected=true).
                    hero.HeroDeveloper.AddSkillXp(skill, boostedXp, isAffectedByFocusFactor: true);
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
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
