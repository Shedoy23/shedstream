using System;
using System.Linq;
using System.Collections.Generic;
using BannerlordLink.Behaviors;
using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;
using TaleWorlds.ObjectSystem;
namespace BannerlordLink.Util
{
    // All methods read game objects: call only from the campaign/main thread.
    internal static class HeroProgressionRuntime
    {
        internal static string ActorReason(Hero hero, bool? mission = null)
            => hero == null || !hero.IsAlive ? "hero_not_found_or_dead"
                : (mission ?? (TaleWorlds.MountAndBlade.Mission.Current != null)) ? "in_mission" : null;
        internal static string ValidateContext(Hero hero, JObject data, bool daily = false)
        {
            bool hasContext = data["save_id"] != null || data["equipment_session_id"] != null || data["hero_id"] != null;
            if (daily && !hasContext) return null;
            if (string.IsNullOrEmpty((string)data["save_id"]) || string.IsNullOrEmpty((string)data["equipment_session_id"]) || string.IsNullOrEmpty((string)data["hero_id"])) return "progression_context_required";
            if (!string.Equals((string)data["save_id"], Campaign.Current?.UniqueGameId, StringComparison.Ordinal)) return "stale_hero_session";
            if (!string.Equals((string)data["equipment_session_id"], EquipmentShopBehavior.Instance?.SessionId, StringComparison.Ordinal)) return "stale_equipment_session";
            if (!string.Equals((string)data["hero_id"], hero?.StringId, StringComparison.Ordinal)) return "stale_hero_identity";
            return null;
        }
        internal static ProgressionPolicy.Quote Focus(Hero hero, SkillObject skill, int amount)
        {
            if (hero == null || skill == null) return new ProgressionPolicy.Quote { Reason = "hero_not_found_or_dead" };
            var q = ProgressionPolicy.Focus(hero.HeroDeveloper.GetFocus(skill), amount, Campaign.Current.Models.CharacterDevelopmentModel.MaxFocusPerSkill, hero.Gold);
            q.Reason = ActorReason(hero) ?? q.Reason;
            return q;
        }
        internal static ProgressionPolicy.Quote Attribute(Hero hero, CharacterAttribute attr, int amount)
        {
            if (hero == null || attr == null) return new ProgressionPolicy.Quote { Reason = "hero_not_found_or_dead" };
            var q = ProgressionPolicy.Attribute(hero.GetAttributeValue(attr), amount, Campaign.Current.Models.CharacterDevelopmentModel.MaxAttribute, hero.Gold);
            q.Reason = ActorReason(hero) ?? q.Reason;
            return q;
        }
        internal static string XpReason(Hero hero, SkillObject skill, bool? mission = null)
            => (hero == null || !hero.IsAlive ? "hero_not_found_or_dead" : null) ?? ProgressionPolicy.XpReason(hero.GetSkillValue(skill),
                hero.HeroDeveloper.GetFocusFactor(skill), Campaign.Current.Models.GenericXpModel.GetXpMultiplier(hero));
        internal static List<SkillObject> XpCandidates(Hero hero)
            => MBObjectManager.Instance.GetObjectTypeList<SkillObject>().Where(s => s != null && !string.IsNullOrEmpty(s.StringId) && XpReason(hero, s) == null).ToList();
        private static JObject Option(int amount, ProgressionPolicy.Quote q, string actorReason)
            => new JObject { ["amount"] = amount, ["cost_gold"] = q.CostGold,
                ["available"] = actorReason == null && q.Available, ["reason"] = actorReason ?? q.Reason };
        internal static JObject Snapshot(Hero hero, bool? mission = null)
        {
            var model = Campaign.Current.Models.CharacterDevelopmentModel;
            string actor = ActorReason(hero, mission);
            var skills = new JArray(); var attributes = new JArray(); bool random = false;
            foreach (var s in MBObjectManager.Instance.GetObjectTypeList<SkillObject>().Where(s => s != null && !string.IsNullOrEmpty(s.StringId)))
            {
                int focus = hero.HeroDeveloper.GetFocus(s);
                string xpReason = XpReason(hero, s, mission); random |= xpReason == null;
                skills.Add(new JObject { ["id"] = s.StringId, ["level"] = hero.GetSkillValue(s), ["focus"] = focus,
                    ["native_focus_limit"] = model.MaxFocusPerSkill, ["focus_limit"] = Math.Min(model.MaxFocusPerSkill, ProgressionPolicy.FocusPurchaseLimit),
                    ["focus_options"] = new JArray(Option(1, ProgressionPolicy.Focus(focus, 1, model.MaxFocusPerSkill, hero.Gold), actor)),
                    ["xp_available"] = xpReason == null, ["xp_reason"] = xpReason });
            }
            foreach (var a in MBObjectManager.Instance.GetObjectTypeList<CharacterAttribute>().Where(a => a != null && !string.IsNullOrEmpty(a.StringId)))
            {
                int value = hero.GetAttributeValue(a);
                attributes.Add(new JObject { ["id"] = a.StringId, ["value"] = value, ["native_limit"] = model.MaxAttribute,
                    ["limit"] = Math.Min(model.MaxAttribute, ProgressionPolicy.AttributePurchaseLimit),
                    ["options"] = new JArray(Option(1, ProgressionPolicy.Attribute(value, 1, model.MaxAttribute, hero.Gold), actor)) });
            }
            return new JObject { ["version"] = 1, ["skills"] = skills, ["attributes"] = attributes,
                ["random_xp_available"] = random, ["random_xp_reason"] = random ? null : (hero == null || !hero.IsAlive ? "hero_not_found_or_dead" : "no_available_skills") };
        }
        internal static void Push(Hero hero)
        {
            HeroStateSync.Push(hero);
            var shop = EquipmentShopBehavior.Instance;
            if (shop != null) { var ledger = shop.Read(hero); shop.Store(hero, ledger); shop.Push(hero, ledger); }
        }
    }
}
