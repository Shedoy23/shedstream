using System;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
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
    /// </summary>
    public class AddSkillXpHandler : IActionHandler
    {
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
            // Если skill_key пуст — mod выберет random skill (server-side option
            // для simple UI с одной кнопкой "+XP в случайный skill").

            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null || !hero.IsAlive)
                    {
                        BannerlordLinkModule.Log($"[hero.add_skill] @{username}: hero не найден или мёртв");
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
                        // Random skill — простой подход для "1000⦷ → +100 XP в случайный skill"
                        var rng = new Random();
                        var allSkills = allSkillProps
                            .Select(p => p.GetValue(null) as SkillObject)
                            .Where(s => s != null)
                            .ToList();
                        if (allSkills.Count > 0)
                        {
                            skill = allSkills[rng.Next(allSkills.Count)];
                            skillKey = skill.StringId;  // для log
                        }
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
                        BannerlordLinkModule.Log(
                            $"[hero.add_skill] @{username}: skill '{skillKey}' не найден " +
                            "(пробуй: Bow / OneHanded / TwoHanded / Polearm / Crossbow / " +
                            "Throwing / Riding / Athletics / Crafting / Tactics / Scouting / " +
                            "Roguery / Charm / Leadership / Trade / Steward / Medicine / Engineering)");
                        return;
                    }

                    int before = hero.GetSkillValue(skill);
                    hero.HeroDeveloper.AddSkillXp(skill, xp);
                    int after = hero.GetSkillValue(skill);
                    BannerlordLinkModule.Log(
                        $"[hero.add_skill] @{username} {skill.StringId} +{xp}xp ({before} → {after})");

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
