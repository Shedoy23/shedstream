using System;
using HarmonyLib;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 5.32 #48 — Harmony finalizer на TaleWorlds.CampaignSystem.
    /// CampaignBehaviors.BannerCampaignBehavior.DailyTickHero(Hero).
    ///
    /// Crash dump (TaleWorlds.MountAndBlade.Launcher.exe.24004.dmp) показал
    /// System.InvalidCastException в этом методе при daily-tick'е adopted
    /// viewer-героя. Очередной TaleWorlds vanilla bug — пытается cast'нуть
    /// hero state в конкретный type (вероятно Clan.Banner или PartyBelongedTo
    /// в SiegeEvent), runtime type не совпадает → process die.
    ///
    /// BLT решает то же самое для всех problematic vanilla campaign behaviors
    /// — оборачивает в try/catch через Harmony finalizer.
    ///
    /// Finalizer runs ПОСЛЕ original, может swallow exception возвратом null.
    /// Других exceptions не глотаем — пусть всплывают для diagnostics.
    ///
    /// Reflection-based — если type не найден в текущей версии SandBox, patch
    /// gracefully skip'нется без crash'а на init.
    /// </summary>
    public static class BannerCampaignBehaviorPatch
    {
        private static readonly Type _bannerCampaignBehaviorType =
            AccessTools.TypeByName(
                "TaleWorlds.CampaignSystem.CampaignBehaviors.BannerCampaignBehavior");

        [HarmonyPatch]
        public static class DailyTickHeroFinalizer
        {
            // Sprint 5.32 ROBUST FIX — TargetMethods (plural) yield pattern.
            // Return null из TargetMethod() bubbles HarmonyException через PatchAll.
            // Empty yield — gracefully skip без exception.
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
            {
                if (_bannerCampaignBehaviorType == null)
                {
                    BannerlordLinkModule.Log(
                        "[BannerCampaignBehavior] type не найден — finalizer skip " +
                        "(version mismatch?)");
                    yield break;
                }
                var m = AccessTools.Method(_bannerCampaignBehaviorType, "DailyTickHero",
                    new[] { typeof(Hero) });
                if (m == null)
                {
                    BannerlordLinkModule.Log(
                        "[BannerCampaignBehavior] DailyTickHero method не найден — skip");
                    yield break;
                }
                BannerlordLinkModule.Log(
                    "[BannerCampaignBehavior] DailyTickHero finalizer registered " +
                    "(swallows InvalidCastException для defensive crash protection)");
                yield return m;
            }

            // Sprint 5.32 #48 — Finalizer signature: (Exception __exception, Hero hero)
            // returns Exception. Возврат null = swallow; возврат __exception = re-throw.
            [HarmonyFinalizer]
            public static Exception Finalizer(Exception __exception, Hero hero)
            {
                if (__exception == null) return null;
                if (__exception is InvalidCastException)
                {
                    // Это специфический crash dump которому отслеживается этот патч.
                    // Логируем кто из героев тиггерит и пропускаем — TaleWorlds
                    // engine сам разрулит (skip tick on this hero для today).
                    string name = "?";
                    string username = "?";
                    try
                    {
                        name = hero?.Name?.ToString() ?? "?";
                        username = BannerlordLink.Util.HeroNaming
                            .ExtractUsername(name) ?? "?";
                    }
                    catch { }
                    BannerlordLinkModule.Log(
                        $"[BannerCampaignBehavior] SWALLOWED InvalidCastException " +
                        $"для hero='{name}' (viewer=@{username}). " +
                        $"TaleWorlds vanilla bug; daily tick для этого hero сегодня skip'нется.");
                    return null;   // swallow → process не падает
                }
                // Other exceptions re-throw — пусть diagnostics видит.
                return __exception;
            }
        }
    }
}
