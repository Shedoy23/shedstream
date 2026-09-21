using System;
using System.Collections.Generic;
using System.Reflection;
using BannerlordLink.Util;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.CampaignBehaviors.BarterBehaviors;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Viewer-led clans choose allegiance through manual commands, not the daily
    /// diplomatic AI. Patch only AI decisions: native kingdom actions must remain
    /// available for viewer commands, kingdom destruction and other game rules.
    /// </summary>
    [HarmonyPatch]
    public static class ViewerKingdomAiPatch
    {
        public static IEnumerable<MethodBase> TargetMethods()
        {
            var type = typeof(DiplomaticBartersBehavior);
            foreach (var name in new[]
            {
                "ConsiderClanJoin", "ConsiderClanJoinAsMercenary",
                "ConsiderClanLeaveKingdom", "ConsiderClanLeaveAsMercenary",
                "ConsiderDefection"
            })
            {
                var signature = name == "ConsiderClanLeaveKingdom" || name == "ConsiderClanLeaveAsMercenary"
                    ? new[] { typeof(Clan) } : new[] { typeof(Clan), typeof(Kingdom) };
                var method = AccessTools.DeclaredMethod(type, name, signature);
                if (method == null) throw new MissingMethodException(type.FullName, name);
                yield return method;
            }
        }

        // __0 also covers ConsiderDefection's differently named clan1 parameter.
        public static bool Prefix(Clan __0)
        {
            return !HeroNaming.IsAdopted(__0?.Leader);
        }
    }
}
