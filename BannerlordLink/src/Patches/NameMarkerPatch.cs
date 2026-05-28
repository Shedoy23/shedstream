using System;
using HarmonyLib;
using TaleWorlds.MountAndBlade;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// Sprint 5.29 — name markers @username над adopted-hero agents.
    ///
    /// Раньше стример играл в slop-mode — не видел чей agent кто. BLT решает
    /// двумя Harmony postfix'ами на vanilla NameMarker VM. Мы делаем то же
    /// + фильтр по нашему [BLink] prefix'у (BLT тэгает всех).
    ///
    /// Vanilla MissionNameMarkerUIHandler сам создаёт VM для каждого agent'а
    /// и обновляет per-frame. Нам нужно лишь:
    ///   1. Force IsTracked=true на VM нашего viewer'а (иначе fades по дистанции).
    ///   2. Установить team-based NameType (enemy/friend color).
    ///
    /// Text marker'а берётся из agent.Name (_name field). У нас уже override
    /// через SummonHeroHandler.SetAgentDisplayName → "@username".
    ///
    /// Filter: agent.Character.HeroObject.Name → IsAdopted? (НЕ agent.Name —
    /// он уже переименован в "@username", IsAdopted check провалится).
    ///
    /// Reflection-based (через AccessTools.TypeByName) — namespace
    /// SandBox.ViewModelCollection.Missions.NameMarker может отсутствовать
    /// в build'е, тогда patch fails gracefully на init.
    /// </summary>
    public static class NameMarkerPatch
    {
        // Sprint 5.32 #47 fix — resolve via assembly scan (resilient to TaleWorlds
        // namespace changes). Раньше hard-coded full name "SandBox.ViewModelCollection
        // .Missions.NameMarker.MissionNameMarkerTargetVM" — TaleWorlds перенесли в
        // ".NameMarker.Targets.MissionNameMarkerTargetVM" → AccessTools.TypeByName
        // вернул null → patch silently degraded → @username markers пропали.
        // Теперь scan'им все loaded assemblies на тип whose simple name matches.
        // Sprint 5.33 COMPAT-1 — guard cctor (см. BannerCampaignBehaviorPatch
        // комментарий). Если ResolveVMType throw'нет в class load → весь
        // DLL не JIT'ится → silent native crash. Ловим всё.
        private static readonly Type _vmType = SafeResolveVMType();

        private static Type SafeResolveVMType()
        {
            try { return ResolveVMType(); }
            catch (Exception ex)
            {
                try { System.Console.WriteLine(
                    $"[BannerlordLink/COMPAT] ResolveVMType threw " +
                    $"{ex.GetType().Name}: {ex.Message} — markers fallback на vanilla"); } catch { }
                return null;
            }
        }

        private static Type ResolveVMType()
        {
            // 2026-05-28: Bannerlord 1.3.x — type стал GENERIC (`1 suffix
            // в metadata) + base class non-generic. Patch base — он работает
            // для ВСЕХ derivative-classes автоматом, и его легче резолвить.
            // Hierarchy:
            //   MissionNameMarkerTargetBaseVM  ← non-generic, наш target
            //   MissionNameMarkerTargetVM<T>   ← generic derived (`1)
            //
            // 1. Try direct assembly load (most reliable).
            try
            {
                string asmPath = System.IO.Path.Combine(
                    TaleWorlds.Library.BasePath.Name,
                    "Modules", "SandBox", "bin", "Win64_Shipping_Client",
                    "SandBox.ViewModelCollection.dll");
                if (System.IO.File.Exists(asmPath))
                {
                    var asm = System.Reflection.Assembly.LoadFrom(asmPath);
                    // Try BASE first (non-generic, патчит всю иерархию).
                    Type tBase = asm.GetType(
                        "SandBox.ViewModelCollection.Missions.NameMarker.Targets.MissionNameMarkerTargetBaseVM",
                        throwOnError: false);
                    if (tBase != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[NameMarker] resolved BASE type via direct asm.GetType: {tBase.FullName}");
                        return tBase;
                    }
                    // Fallback: открытый generic (`1).
                    Type tGen = asm.GetType(
                        "SandBox.ViewModelCollection.Missions.NameMarker.Targets.MissionNameMarkerTargetVM`1",
                        throwOnError: false);
                    if (tGen != null)
                    {
                        BannerlordLinkModule.Log(
                            $"[NameMarker] resolved GENERIC type via direct asm.GetType: {tGen.FullName}");
                        return tGen;
                    }
                    // Last resort — scan все типы в этой конкретной asm.
                    Type[] types;
                    try { types = asm.GetTypes(); }
                    catch (System.Reflection.ReflectionTypeLoadException rtl)
                    { types = rtl.Types ?? Array.Empty<Type>(); }
                    foreach (var t in types)
                    {
                        if (t == null || t.Name == null) continue;
                        // Name returns "MissionNameMarkerTargetVM`1" для generic, проверяем оба.
                        if (t.Name == "MissionNameMarkerTargetBaseVM")
                        {
                            BannerlordLinkModule.Log(
                                $"[NameMarker] resolved via SandBox.VM scan: {t.FullName}");
                            return t;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[NameMarker] direct asm load failed: {ex.GetType().Name}: {ex.Message}");
            }

            // 2. Final fallback — AppDomain wide scan (старый код, ищет base + generic).
            foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try { types = asm.GetTypes(); }
                catch (System.Reflection.ReflectionTypeLoadException rtl)
                { types = rtl.Types ?? Array.Empty<Type>(); }
                catch { continue; }
                foreach (var t in types)
                {
                    if (t == null || t.Name == null) continue;
                    // 2026-05-28: type стал generic → Name == "MissionNameMarkerTargetVM`1".
                    // Patch BaseVM (non-generic, работает универсально).
                    if (t.Name == "MissionNameMarkerTargetBaseVM"
                        || t.Name == "MissionNameMarkerTargetVM`1"
                        || t.Name == "MissionNameMarkerTargetVM")
                    {
                        BannerlordLinkModule.Log(
                            $"[NameMarker] resolved via AppDomain scan: {t.FullName} " +
                            $"(asm={asm.GetName().Name})");
                        return t;
                    }
                }
            }
            return null;
        }

        /// <summary>Used by Harmony PatchAll auto-discovery via target attribute.
        /// Sprint 5.32 ROBUST FIX — `TargetMethod()` возвращавший null **бросал**
        /// HarmonyException в нашей версии HarmonyLib (PatchAll crash на load,
        /// рубит ВСЕ остальные Harmony patches). `TargetMethods()` (plural)
        /// yield-pattern — empty enumerable обрабатывается gracefully.</summary>
        [HarmonyPatch]
        public static class MissionNameMarkerTargetVMCtorHook
        {
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
            {
                if (_vmType == null)
                {
                    BannerlordLinkModule.Log(
                        "[NameMarker] MissionNameMarkerTargetVM type не найден — " +
                        "patch skip (SandBox версия не та?). Markers fallback на vanilla.");
                    yield break;
                }
                // Try (Agent, bool) ctor (old signature).
                var ctor = AccessTools.Constructor(_vmType,
                    new[] { typeof(Agent), typeof(bool) });
                if (ctor != null)
                {
                    BannerlordLinkModule.Log(
                        "[NameMarker] using ctor(Agent, bool)");
                    yield return ctor;
                    yield break;
                }
                // Sprint 5.32 #47 fix — try (Agent, ...) с любой arity.
                foreach (var c in _vmType.GetConstructors())
                {
                    var pars = c.GetParameters();
                    if (pars.Length >= 1 && pars[0].ParameterType == typeof(Agent))
                    {
                        BannerlordLinkModule.Log(
                            $"[NameMarker] using ctor with {pars.Length} args " +
                            $"(first=Agent, fallback resolver)");
                        yield return c;
                        yield break;
                    }
                }
                BannerlordLinkModule.Log(
                    "[NameMarker] не найден ctor(Agent, ...) — patch skip.");
                yield break;
            }

            [HarmonyPostfix]
            public static void Postfix(object __instance, Agent agent)
            {
                try
                {
                    if (__instance == null || agent == null) return;

                    // Filter: только наши adopted viewers получают persistent
                    // markers. Vanilla heroes / troops fade по дистанции
                    // как обычно (BLT'у пофиг — они тэгают всех, у нас более
                    // консервативно чтобы не засорять экран в large battles).
                    var hero = (agent.Character as CharacterObject)?.HeroObject;
                    if (hero?.Name == null) return;
                    if (!BannerlordLink.Util.HeroNaming.IsAdopted(hero.Name.ToString())) return;

                    // Set IsTracked=true чтобы marker не fade'ил по дистанции.
                    // Set NameType + IsEnemy/IsFriendly для team-based color.
                    var t = __instance.GetType();

                    // Resolve team relative to streamer (Agent.Main).
                    bool isEnemy = false, isFriend = false;
                    try
                    {
                        var main = Agent.Main;
                        if (main != null && main != agent)
                        {
                            isEnemy = agent.IsEnemyOf(main);
                            isFriend = !isEnemy && agent.IsFriendOf(main);
                        }
                        else if (main == null)
                        {
                            // Watching mode (стример вне Mission) — fallback
                            // на PlayerTeam check.
                            var pt = Mission.Current?.PlayerTeam;
                            if (pt != null && agent.Team != null)
                            {
                                isFriend = agent.Team == pt;
                                isEnemy = !isFriend && agent.Team.IsEnemyOf(pt);
                            }
                        }
                    }
                    catch { }

                    // Set properties через reflection (без hard ref на VM type).
                    SetBoolProp(t, __instance, "IsTracked", true);
                    if (isEnemy)
                    {
                        SetBoolProp(t, __instance, "IsEnemy", true);
                        // NameTypeEnemy = const на VM type (обычно int 1 или 2)
                        TrySetNameType(t, __instance, "NameTypeEnemy");
                    }
                    else if (isFriend)
                    {
                        SetBoolProp(t, __instance, "IsFriendly", true);
                        TrySetNameType(t, __instance, "NameTypeFriendly");
                    }
                }
                catch (Exception ex)
                {
                    // Silent — не валим VM ctor если что-то пошло не так.
                    // Marker просто отрендерится default.
                    BannerlordLinkModule.Log(
                        $"[NameMarker] ctor postfix error: {ex.Message}");
                }
            }

            private static void SetBoolProp(Type t, object inst, string name, bool value)
            {
                try
                {
                    var prop = AccessTools.Property(t, name);
                    if (prop != null && prop.CanWrite)
                    {
                        prop.SetValue(inst, value);
                        return;
                    }
                    var field = AccessTools.Field(t, name);
                    field?.SetValue(inst, value);
                }
                catch { }
            }

            private static void TrySetNameType(Type t, object inst, string constName)
            {
                try
                {
                    var c = AccessTools.Field(t, constName);
                    if (c == null) return;
                    object val = c.GetValue(null);
                    var prop = AccessTools.Property(t, "NameType");
                    if (prop != null && prop.CanWrite) prop.SetValue(inst, val);
                    else
                    {
                        var field = AccessTools.Field(t, "NameType");
                        field?.SetValue(inst, val);
                    }
                }
                catch { }
            }
        }
    }
}
