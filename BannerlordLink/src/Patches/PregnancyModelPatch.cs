using System;
using HarmonyLib;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-05-29 — crash dump (crashes/2026-05-29_17.02.47/dump.dmp,
    /// разобран dotnet-dump) показал фатальный System.NullReferenceException
    /// на дейли-тике кампании в ВАНИЛЬНОМ методе:
    ///
    ///   DefaultPregnancyModel.GetDailyChanceOfPregnancyForHero(Hero)   ← NPE
    ///     ← PregnancyCampaignBehavior.RefreshSpouseVisit(Hero)
    ///     ← PregnancyCampaignBehavior.DailyTickHero(Hero) ← Campaign.Tick()
    ///
    /// Проблемный hero (CharacterObject_2929): IsFemale, замужем (_spouse != null),
    /// но _clan == NULL. Ванила дёргает hero.Clan без null-guard'а → процесс падает.
    /// Наши усыновлённые вью-герои бесклановые by design, но их можно поженить
    /// (hero.marry / marriage proposal), и ванильная модель беременности этого
    /// не переживает → серия вылетов (был 3 краша за час).
    ///
    /// Существующий BannerCampaignBehaviorPatch это не ловит: он висит на другом
    /// behavior'е и глотает только InvalidCastException.
    ///
    /// Fix (defensive, как и весь наш crash-protection слой):
    ///   • Prefix — для null hero / null Clan сразу отдаём chance=0 и НЕ заходим
    ///     в original (избегаем багового пути целиком).
    ///   • Finalizer — catch-all на любой другой NullReferenceException внутри
    ///     метода (например hero.Spouse.Clan == null): swallow + chance=0,
    ///     процесс не падает. Прочие исключения пропускаем для диагностики.
    ///
    /// Reflection-based resolve + TargetMethods yield — если type/method не найден
    /// в текущей версии (mismatch / другой мод сломал reflection), patch
    /// gracefully skip'нётся без краша на инициализации (pattern из
    /// BannerCampaignBehaviorPatch, Sprint 5.33 COMPAT-1).
    /// </summary>
    public static class PregnancyModelPatch
    {
        private static readonly Type _pregnancyModelType =
            SafeResolveType("TaleWorlds.CampaignSystem.GameComponents.DefaultPregnancyModel");

        private static Type SafeResolveType(string fullName)
        {
            try { return AccessTools.TypeByName(fullName); }
            catch (Exception ex)
            {
                try { System.Console.WriteLine(
                    $"[BannerlordLink/COMPAT] SafeResolveType('{fullName}') threw " +
                    $"{ex.GetType().Name}: {ex.Message} — patch skip"); } catch { }
                return null;
            }
        }

        [HarmonyPatch]
        public static class GetDailyChanceOfPregnancyForHeroGuard
        {
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
            {
                if (_pregnancyModelType == null)
                {
                    BannerlordLinkModule.Log(
                        "[PregnancyModel] DefaultPregnancyModel type не найден — guard skip " +
                        "(version mismatch?)");
                    yield break;
                }
                var m = AccessTools.Method(_pregnancyModelType, "GetDailyChanceOfPregnancyForHero",
                    new[] { typeof(Hero) });
                if (m == null)
                {
                    BannerlordLinkModule.Log(
                        "[PregnancyModel] GetDailyChanceOfPregnancyForHero method не найден — skip");
                    yield break;
                }
                BannerlordLinkModule.Log(
                    "[PregnancyModel] GetDailyChanceOfPregnancyForHero guard registered " +
                    "(clanless/NRE → chance 0, defensive crash protection)");
                yield return m;
            }

            // Известный кейс краша: бесклановый (или null) hero → ванила дёргает
            // hero.Clan и падает. Отдаём 0 и НЕ заходим в original.
            [HarmonyPrefix]
            public static bool Prefix(Hero hero, ref float __result)
            {
                try
                {
                    if (hero == null || hero.Clan == null)
                    {
                        __result = 0f;
                        return false;   // skip original — избегаем vanilla NPE
                    }
                }
                catch
                {
                    __result = 0f;
                    return false;
                }
                return true;            // hero валиден — обычный путь
            }

            // Catch-all: любой другой NullReferenceException внутри метода
            // (например hero.Spouse.Clan == null) — swallow, chance 0.
            [HarmonyFinalizer]
            public static Exception Finalizer(Exception __exception, Hero hero, ref float __result)
            {
                if (__exception == null) return null;
                if (__exception is NullReferenceException)
                {
                    string name = "?";
                    try { name = hero?.Name?.ToString() ?? "?"; } catch { }
                    BannerlordLinkModule.Log(
                        $"[PregnancyModel] SWALLOWED NullReferenceException для hero='{name}' " +
                        $"(вероятно бесклановый замужний вью-герой); chance=0, дейли-тик не падает.");
                    __result = 0f;
                    return null;        // swallow → процесс не падает
                }
                return __exception;     // прочее — пусть всплывает для диагностики
            }
        }
    }
}
