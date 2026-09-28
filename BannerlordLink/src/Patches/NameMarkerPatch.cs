using HarmonyLib;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 5.33 NAMETAG (2026-05-28) — DEPRECATED STUB.
    ///
    /// Раньше patch'ил engine `MissionNameMarkerTargetVM` (constructor postfix)
    /// чтобы добавить @username display над adopted-hero agent'ами. В
    /// Bannerlord 1.3.x этот тип стал generic (`1) + non-generic base
    /// class — multiple attempts по type resolution (force-load Assembly +
    /// AppDomain scan + direct asm.GetType) failed across game versions.
    ///
    /// REPLACED BY: <see cref="BannerlordLink.Behaviors.HeroNametagMissionView"/>
    /// — autonomous MissionView с собственным Gauntlet UI layer (pattern из
    /// Lait96/Bannerlord-Twitch-lait/.../BLTHeroWidgetBehavior.cs). НЕ
    /// зависит от engine VM internals → survives любые TaleWorlds renames.
    ///
    /// Stub оставлен чтобы:
    ///   1. Сохранить commit history (грабли + final fix трассируются)
    ///   2. Harmony PatchAll грейсфул-скипнет это (TargetMethods → yield break)
    /// </summary>
    [HarmonyPatch]
    public static class NameMarkerPatch
    {
        [HarmonyPatch]
        public static class MissionNameMarkerTargetVMCtorHook
        {
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
            {
                BannerlordLinkModule.Log(
                    "[NameMarker] DEPRECATED — заменено на HeroNametagMissionView " +
                    "(MissionView + Gauntlet UI, BLT-Lait pattern)");
                yield break;
            }
        }
    }
}
