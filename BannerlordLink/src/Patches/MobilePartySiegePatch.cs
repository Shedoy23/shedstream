using System;
using HarmonyLib;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-06-10 — defensive finalizer на
    /// TaleWorlds.CampaignSystem.Party.MobileParty.OnPartyJoinedSiegeInternal.
    ///
    /// Краш-дамп 2026-06-10 ~20:12 (dotnet-dump, символизированный managed-стек):
    ///   System.NullReferenceException
    ///     MobileParty.OnPartyJoinedSiegeInternal()+0x4d
    ///     ← set_BesiegerCamp ← SiegeEvent..ctor ← SiegeEventManager.StartSiegeEvent
    ///     ← EncounterManager.StartSettlementEncounter ← Campaign.Tick()
    /// Чисто ванильный краш старта осады в тике карты (стрим с Diplomacy + SiegeFix
    /// — много AI-осад; edge-case → NRE в осадном bookkeeping'е). НИ ОДНОГО нашего
    /// фрейма в стеке. NRE ловится managed-финализатором.
    ///
    /// Swallow'им ТОЛЬКО NRE из этого метода → партия присоединяется к осаде с
    /// неполным bookkeeping'ом, НО процесс не падает (стрим выживает). Это
    /// band-aid: «настоящий» фикс — на стороне Diplomacy/SiegeFix. Прочие
    /// exceptions пропускаем. Reflection-based: type/метод не найдены → graceful
    /// skip без crash'а на init (паттерн KingdomVoteNotificationPatch).
    /// </summary>
    public static class MobilePartySiegePatch
    {
        private static readonly Type _mpType = SafeResolveType(
            "TaleWorlds.CampaignSystem.Party.MobileParty");

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
        public static class OnPartyJoinedSiegeFinalizer
        {
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
            {
                if (_mpType == null)
                {
                    BannerlordLinkModule.Log(
                        "[MobilePartySiege] MobileParty type не найден — finalizer skip");
                    yield break;
                }
                var m = AccessTools.Method(_mpType, "OnPartyJoinedSiegeInternal");
                if (m == null)
                {
                    BannerlordLinkModule.Log(
                        "[MobilePartySiege] OnPartyJoinedSiegeInternal method не найден — skip");
                    yield break;
                }
                BannerlordLinkModule.Log(
                    "[MobilePartySiege] OnPartyJoinedSiegeInternal finalizer registered " +
                    "(swallows NullReferenceException — vanilla siege-start crash protection)");
                yield return m;
            }

            [HarmonyFinalizer]
            public static Exception Finalizer(Exception __exception)
            {
                if (__exception == null) return null;
                if (__exception is NullReferenceException)
                {
                    BannerlordLinkModule.Log(
                        "[MobilePartySiege] SWALLOWED NullReferenceException в " +
                        "OnPartyJoinedSiegeInternal (ванильный краш старта осады, " +
                        "Diplomacy/SiegeFix edge-case). Процесс не упал.");
                    return null;   // swallow → процесс не падает
                }
                return __exception;   // прочее — re-throw для diagnostics
            }
        }
    }
}
