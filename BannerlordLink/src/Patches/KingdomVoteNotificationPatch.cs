using System;
using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// KingdomVoteNotificationItemVM — попап-«колокольчик» голосования королевства
    /// (война/мир/политики, которые зрители предлагают через дипломатию).
    ///
    /// 2026-06-15 — РУТ-causе бага #10 («окно голосования мелькает и исчезает»):
    /// декомпиляция ванильного VM показала, что клик идёт через
    /// MapNotificationItemBaseVM.ExecuteAction() → _onInspect?.Invoke() →
    /// KingdomVoteNotificationItemVM.OnInspect(). А OnInspect содержит ДВА
    /// незащищённых разыменования:
    ///   • `_decision.ShouldBeCancelled()`   → NRE если _decision == null (устаревшее/
    ///                                          снятое решение, а уведомление осталось)
    ///   • `Clan.PlayerClan.Kingdom`         → NRE если у игрока нет клана
    /// Мод плодит viewer-кланы и kingdom-решения → выше шанс наткнуться на null →
    /// NRE → раньше финализатор просто ГЛОТАЛ его, и попап не открывался (=«мелькает
    /// и исчезает»).
    ///
    /// Лечение: prefix на OnInspect ловит именно эти два null'а и аккуратно убирает
    /// залипшее уведомление (ExecuteRemove — ровно то, что ваниль делает на ветке
    /// «не актуально»), вместо NRE. Если решение валидное (оба не-null) — пропускаем
    /// в ваниль, и голосование открывается штатно. Финализатор на ExecuteAction
    /// остаётся backstop'ом на ЛЮБОЙ другой непредвиденный NRE и теперь логирует
    /// ПОЛНЫЙ стек — если null окажется не в _decision/PlayerClan, следующий репро
    /// покажет точную точку.
    ///
    /// Reflection-based: type/метод не найдены в текущей версии игры → graceful skip
    /// без crash'а на init (паттерн BannerCampaignBehaviorPatch).
    /// </summary>
    public static class KingdomVoteNotificationPatch
    {
        private static readonly Type _vmType = SafeResolveType(
            "TaleWorlds.CampaignSystem.ViewModelCollection.Map.MapNotificationTypes.KingdomVoteNotificationItemVM");

        // _decision приватное поле VM (источник NRE); ExecuteRemove публичный метод базы.
        private static readonly FieldInfo _decisionField =
            _vmType != null ? AccessTools.Field(_vmType, "_decision") : null;
        private static readonly MethodInfo _executeRemove =
            _vmType != null ? AccessTools.Method(_vmType, "ExecuteRemove") : null;

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

        // ── Prefix на OnInspect — ловит null ДО ванильного разыменования ──────────
        [HarmonyPatch]
        public static class OnInspectPrefix
        {
            public static System.Collections.Generic.IEnumerable<MethodBase> TargetMethods()
            {
                if (_vmType == null)
                {
                    BannerlordLinkModule.Log(
                        "[KingdomVoteNotification] type не найден — OnInspect prefix skip");
                    yield break;
                }
                var m = AccessTools.Method(_vmType, "OnInspect");
                if (m == null || _decisionField == null)
                {
                    BannerlordLinkModule.Log(
                        "[KingdomVoteNotification] OnInspect/_decision не найдены — prefix skip " +
                        "(финализатор остаётся backstop'ом)");
                    yield break;
                }
                BannerlordLinkModule.Log(
                    "[KingdomVoteNotification] OnInspect prefix registered (null-guard для " +
                    "_decision/PlayerClan → graceful remove вместо NRE #10)");
                yield return m;
            }

            // return false = пропустить ванильный OnInspect (мы уже обработали),
            // return true  = выполнить ванильный OnInspect (решение валидное).
            public static bool Prefix(object __instance)
            {
                try
                {
                    object decision = _decisionField.GetValue(__instance);
                    bool noClan = Clan.PlayerClan == null;
                    if (decision == null || noClan)
                    {
                        BannerlordLinkModule.Log(
                            $"[KingdomVoteNotification] OnInspect guard: _decision null={decision == null}, " +
                            $"PlayerClan null={noClan} → graceful ExecuteRemove (был бы ванильный NRE #10)");
                        try { _executeRemove?.Invoke(__instance, null); } catch { }
                        return false;   // не пускаем в ваниль — она бы упала
                    }
                }
                catch (Exception ex)
                {
                    BannerlordLinkModule.Log(
                        $"[KingdomVoteNotification] OnInspect prefix guard threw " +
                        $"{ex.GetType().Name}: {ex.Message} — пропускаю в ваниль");
                }
                return true;   // валидное решение → ванильный OnInspect открывает голосование
            }
        }

        // ── Финализатор на ExecuteAction — backstop на любой ДРУГОЙ NRE ───────────
        [HarmonyPatch]
        public static class ExecuteActionFinalizer
        {
            public static System.Collections.Generic.IEnumerable<MethodBase> TargetMethods()
            {
                if (_vmType == null)
                {
                    BannerlordLinkModule.Log(
                        "[KingdomVoteNotification] type не найден — finalizer skip (version mismatch?)");
                    yield break;
                }
                var m = AccessTools.Method(_vmType, "ExecuteAction");
                if (m == null)
                {
                    BannerlordLinkModule.Log(
                        "[KingdomVoteNotification] ExecuteAction method не найден — skip");
                    yield break;
                }
                BannerlordLinkModule.Log(
                    "[KingdomVoteNotification] ExecuteAction finalizer registered " +
                    "(backstop: swallow NRE + лог полного стека для диагностики)");
                yield return m;
            }

            [HarmonyFinalizer]
            public static Exception Finalizer(Exception __exception)
            {
                if (__exception == null) return null;
                if (__exception is NullReferenceException)
                {
                    BannerlordLinkModule.Log(
                        "[KingdomVoteNotification] SWALLOWED NRE в ExecuteAction ПОСЛЕ prefix-guard " +
                        "— значит null НЕ в _decision/PlayerClan. Попап не открылся, процесс жив. " +
                        "Полный стек для следующего фикса:\n" + __exception);
                    return null;   // swallow → process не падает
                }
                return __exception;   // прочее — re-throw для diagnostics
            }
        }
    }
}
