using System;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CharacterDevelopment;
using TaleWorlds.Core;

namespace BannerlordLink.Actions
{
    /// <summary>
    /// Real handler для `player.modify_attribute` — добавляет attribute points hero'ю.
    ///
    /// data: { target, attribute (e.g. "Vigor"), points (int) }
    /// Vanilla attributes (6): Vigor, Control, Endurance, Cunning, Social, Intelligence.
    /// API: hero.HeroDeveloper.AddAttribute(charAttribute, points) — Bannerlord 1.3.x.
    /// </summary>
    public class ModifyAttributeHandler : IActionHandler
    {
        public string ActionType => "player.modify_attribute";

        public Task<(bool success, string error)> ExecuteAsync(JObject data)
        {
            string username = (data["target"]?.ToString() ?? data["initiated_by"]?.ToString() ?? "")
                              .Trim().ToLowerInvariant();
            string attrKey = (data["attribute"]?.ToString() ?? "").Trim();
            int points = (int?)data["points"] ?? 0;

            if (string.IsNullOrEmpty(username))
                return Task.FromResult<(bool, string)>((false, "no target username"));
            if (string.IsNullOrEmpty(attrKey))
                return Task.FromResult<(bool, string)>((false, "attribute required"));
            if (points == 0)
                return Task.FromResult<(bool, string)>((false, "points must be non-zero"));

            string actionId = BannerlordLink.Util.ActionFeedback.GetActionId(data);
            MainThreadDispatcher.Enqueue(() =>
            {
                try
                {
                    // Sprint 5.28: nельзя менять attribute во время Mission
                    // (engine native crash). См. AddAttributeHandler comment.
                    if (TaleWorlds.MountAndBlade.Mission.Current != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[modify_attribute] @{username}: skip — нельзя во " +
                            "время Mission (engine crash risk)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "in_mission");
                        return;
                    }

                    var hero = HeroLookup.FindByUsername(username);
                    if (hero == null || !hero.IsAlive)
                    {
                        BannerlordLinkModule.Log(
                            $"[modify_attribute] @{username}: hero не найден или мёртв");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "hero_not_found_or_dead");
                        return;
                    }

                    // Resolve attribute через reflection (как Skills — properties в 1.3.x).
                    CharacterAttribute attr = null;
                    var t = typeof(DefaultCharacterAttributes);
                    foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Static))
                    {
                        if (p.PropertyType != typeof(CharacterAttribute)) continue;
                        if (!string.Equals(p.Name, attrKey, StringComparison.OrdinalIgnoreCase))
                            continue;
                        attr = p.GetValue(null) as CharacterAttribute;
                        break;
                    }
                    if (attr == null)
                    {
                        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Static))
                        {
                            if (f.FieldType != typeof(CharacterAttribute)) continue;
                            if (!string.Equals(f.Name, attrKey, StringComparison.OrdinalIgnoreCase))
                                continue;
                            attr = f.GetValue(null) as CharacterAttribute;
                            break;
                        }
                    }
                    if (attr == null)
                    {
                        BannerlordLinkModule.Log(
                            $"[modify_attribute] @{username}: attribute '{attrKey}' не найден " +
                            "(пробуй: Vigor / Control / Endurance / Cunning / Social / Intelligence)");
                        BannerlordLink.Util.ActionFeedback.PostFailed(actionId, "attribute_not_found");
                        return;
                    }

                    int before = hero.GetAttributeValue(attr);
                    hero.HeroDeveloper.AddAttribute(attr, points, checkUnspentPoints: false);
                    int after = hero.GetAttributeValue(attr);
                    BannerlordLinkModule.Log(
                        $"[modify_attribute] @{username} {attr.StringId} {before} → {after} (+{points})");
                    BannerlordLink.Util.HeroStateSync.Push(hero);
                    BannerlordLink.Util.ActionFeedback.PostApplied(actionId);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[modify_attribute] @{username} CRASHED: {ex.Message}");
                    BannerlordLink.Util.ActionFeedback.PostFailed(
                        actionId, "crashed:" + ex.GetType().Name);
                }
            });

            return Task.FromResult<(bool, string)>((true, null));
        }
    }
}
