using System;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.Core;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 5.32 #48 — Harmony finalizer на TaleWorlds.CampaignSystem.
    /// CampaignBehaviors.BannerCampaignBehavior.DailyTickHero(Hero).
    ///
    /// 2026-06-16 ROOT-CAUSE (декомпиль DailyTickHero, см. CLAUDE.md «decompile
    /// to root-cause, don't blind-swallow»): единственный каст в методе —
    /// `(BannerComponent)hero.BannerItem.Item.ItemComponent`. InvalidCast = в
    /// слот баннера героя попал НЕ-баннер (ItemComponent != BannerComponent).
    /// Было у @bapah1_1 / @k0r0b14 (23×/день). Раньше finalizer просто ГЛОТАЛ
    /// → silently broken: баннер не назначался + спам в логе.
    ///
    /// Теперь PREFIX чистит битый BannerItem ДО vanilla → vanilla видит invalid
    /// → переназначит корректный баннер (self-heal). Валидные/пустые баннеры НЕ
    /// трогаем — falls through в vanilla без изменений. Finalizer ОСТАВЛЕН как
    /// backstop, но теперь логирует ПОЛНЫЙ стек любого InvalidCast, который
    /// prefix не поймал (диагностика будущих источников).
    ///
    /// Reflection-based — если type не найден в текущей версии SandBox, patch
    /// gracefully skip'нется без crash'а на init.
    /// </summary>
    public static class BannerCampaignBehaviorPatch
    {
        // Sprint 5.33 COMPAT-1 — guard static cctor против Reflection throws.
        // Раньше `static readonly Type ... = AccessTools.TypeByName(...)` ←
        // если другой мод (особенно armor/equipment overhaul вроде Last Down
        // Armory) ранее load'ит assembly с битыми TypeRef, AccessTools может
        // bubble ReflectionTypeLoadException из cctor → JIT-loader валит
        // наш DLL целиком, OnSubModuleLoad никогда не fire, лог пустой,
        // user видит только native 0xC0000005 access violation. Lazy + guard.
        private static readonly Type _bannerCampaignBehaviorType =
            SafeResolveType("TaleWorlds.CampaignSystem.CampaignBehaviors.BannerCampaignBehavior");

        private static Type SafeResolveType(string fullName)
        {
            try { return AccessTools.TypeByName(fullName); }
            catch (Exception ex)
            {
                // Class load — нельзя trust'ить BannerlordLinkModule.Log
                // (тоже мог не загрузиться), пишем в Console прямо.
                try { System.Console.WriteLine(
                    $"[BannerlordLink/COMPAT] SafeResolveType('{fullName}') threw " +
                    $"{ex.GetType().Name}: {ex.Message} — patch skip"); } catch { }
                return null;
            }
        }

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

            // 2026-06-16 ROOT-CAUSE FIX — чистим битый BannerItem ДО vanilla,
            // чтобы каст (BannerComponent)Item.ItemComponent не падал. Валидные
            // и пустые баннеры не трогаем → fall through в vanilla без изменений.
            [HarmonyPrefix]
            public static void Prefix(Hero hero)
            {
                try
                {
                    if (hero == null) return;
                    var be = hero.BannerItem;
                    if (be.IsInvalid()) return;                 // пусто — vanilla ok
                    var comp = be.Item?.ItemComponent;
                    if (comp is BannerComponent) return;        // настоящий баннер — vanilla ok
                    // Не-BannerComponent (или null) в слоте баннера — именно на
                    // нём падает InvalidCast. Чистим → vanilla переназначит.
                    string who = "?";
                    try { who = hero.Name?.ToString() ?? "?"; } catch { }
                    BannerlordLinkModule.Log(
                        $"[BannerCampaignBehavior] PREFIX: битый BannerItem у hero='{who}' " +
                        $"(component={comp?.GetType().Name ?? "null"}) → clear, vanilla переназначит");
                    hero.BannerItem = new EquipmentElement((ItemObject)null);
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[BannerCampaignBehavior] PREFIX guard error: {ex.Message}");
                }
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
                        $"для hero='{name}' (viewer=@{username}) — prefix-guard НЕ поймал, " +
                        $"полный стек для диагностики:\n{__exception}");
                    return null;   // swallow → process не падает (backstop)
                }
                // Other exceptions re-throw — пусть diagnostics видит.
                return __exception;
            }
        }
    }
}
