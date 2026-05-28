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
            // 1. Try known fast-path full names first (cheaper than scan).
            string[] candidates = new[]
            {
                "SandBox.ViewModelCollection.Missions.NameMarker.MissionNameMarkerTargetVM",
                "SandBox.ViewModelCollection.Missions.NameMarker.Targets.MissionNameMarkerTargetVM",
                "TaleWorlds.MountAndBlade.View.MissionViews.MissionNameMarkerTargetVM",
            };
            foreach (var fn in candidates)
            {
                Type t = null;
                try { t = AccessTools.TypeByName(fn); }
                catch { /* armor/equipment overhauls могут sabotage'нуть TypeByName */ }
                if (t != null)
                {
                    BannerlordLinkModule.Log(
                        $"[NameMarker] resolved type via known name: {t.FullName}");
                    return t;
                }
            }
            // 2. Fallback — scan all loaded assemblies for matching simple name.
            //    Sprint 5.33 COMPAT-2 — было `catch { continue; }` (Exception
            //    swallow), но `ReflectionTypeLoadException` всё равно содержит
            //    partial results через `ex.Types` — другие моды могут иметь
            //    broken TypeRef но валидные типы рядом. Используем partial.
            //    Самый robust способ — выживает в любой namespace shuffle.
            foreach (var asm in System.AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try { types = asm.GetTypes(); }
                catch (System.Reflection.ReflectionTypeLoadException rtl)
                {
                    // Partial — берём только non-null entries.
                    types = rtl.Types ?? Array.Empty<Type>();
                }
                catch { continue; }
                foreach (var t in types)
                {
                    if (t == null || t.Name == null) continue;
                    if (t.Name == "MissionNameMarkerTargetVM")
                    {
                        BannerlordLinkModule.Log(
                            $"[NameMarker] resolved type via assembly scan: {t.FullName}");
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
