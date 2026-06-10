using System;
using HarmonyLib;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-06-10 — defensive finalizer на
    /// TaleWorlds.CampaignSystem.ViewModelCollection.Map.MapNotificationTypes.
    /// KingdomVoteNotificationItemVM.ExecuteAction.
    ///
    /// Лог 2026-06-09 (default20260609.log, ~20:00): FTL NullReferenceException
    /// внутри ExecuteAction этого VM (клик по колокольчику голосования
    /// королевства) → процесс упал, игра перезапустилась. Чисто ванильный баг
    /// (нет наших фреймов в стеке); мод повышает объём kingdom-vote'ов (много
    /// viewer-кланов в королевствах) → выше шанс словить.
    ///
    /// Finalizer swallow'ит ТОЛЬКО NRE из этого метода (попап не откроется, но
    /// процесс не падает). Другие exceptions пропускаем — пусть всплывают для
    /// diagnostics. Reflection-based: если type/метод не найдены в текущей
    /// версии — graceful skip без crash'а на init (паттерн BannerCampaignBehaviorPatch).
    /// </summary>
    public static class KingdomVoteNotificationPatch
    {
        private static readonly Type _vmType = SafeResolveType(
            "TaleWorlds.CampaignSystem.ViewModelCollection.Map.MapNotificationTypes.KingdomVoteNotificationItemVM");

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
        public static class ExecuteActionFinalizer
        {
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
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
                    "(swallows NullReferenceException для defensive crash protection)");
                yield return m;
            }

            [HarmonyFinalizer]
            public static Exception Finalizer(Exception __exception)
            {
                if (__exception == null) return null;
                if (__exception is NullReferenceException)
                {
                    BannerlordLinkModule.Log(
                        "[KingdomVoteNotification] SWALLOWED NullReferenceException в " +
                        "ExecuteAction (ванильный баг клика по уведомлению голосования " +
                        "королевства). Попап не открылся, но процесс не упал.");
                    return null;   // swallow → process не падает
                }
                return __exception;   // прочее — re-throw для diagnostics
            }
        }
    }
}
