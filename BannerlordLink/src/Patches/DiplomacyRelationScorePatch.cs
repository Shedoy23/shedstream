using System;
using System.Reflection;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.GameComponents;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-09-22 — БЭКСТОП против ванильного NRE, уронившего игру 22.09 в 13:10
    /// (разбор: `docs/BANNERLORD_CRASH_2026-09-22.md`).
    ///
    /// Ванильный `DefaultDiplomacyModel.GetRelationScore` первой же строкой делает
    ///     factionDeclaresWar.Leader.Clan.GetRelationWithClan(...)
    /// без единой проверки. Достаточно одного клана, который числится в
    /// королевстве и указывает на лидера без клана — и суточный тик роняет игру
    /// целиком (голосование королевства о мире).
    ///
    /// ПРИЧИНУ чинит не этот патч, а `Util/ClanIntegrity`: `hero.leave_clan`
    /// больше не создаёт такую связку, а `RepairAll()` на загрузке лечит уже
    /// сохранённые кампании. Патч — страховка на случай, если битую связку
    /// создаст путь, которого мы ещё не знаем: он НАЗЫВАЕТ виноватый клан в логе
    /// и возвращает нейтральный 0 вместо падения.
    ///
    /// Мутировать мир отсюда нельзя: вызов идёт изнутри `KingdomElection.Setup`,
    /// который в этот момент перебирает кланы королевства. Ремонт делает
    /// следующая загрузка.
    ///
    /// Kill-switch: имя класса в `SKIP_PATCH_NAMES` (`BannerlordLinkModule.cs`).
    /// </summary>
    [HarmonyPatch]
    public static class DiplomacyRelationScorePatch
    {
        private static MethodBase TargetMethod() =>
            AccessTools.Method(typeof(DefaultDiplomacyModel), "GetRelationScore");

        // Метод приватный: если TaleWorlds его переименуют, патч молча
        // пропускается, а не валит инициализацию мода.
        private static bool Prepare() => TargetMethod() != null;

        private static bool Prefix(
            IFaction factionDeclaresWar,
            IFaction factionDeclaredWar,
            IFaction evaluatingFaction,
            ref float __result)
        {
            string broken = FirstBroken(factionDeclaresWar)
                         ?? FirstBroken(factionDeclaredWar)
                         ?? FirstBroken(evaluatingFaction);
            if (broken == null) return true;   // всё цело — в ваниль

            BannerlordLinkModule.Log(
                $"[diplo-guard] GetRelationScore пропущен: {broken}. " +
                "Связка «клан ↔ лидер» битая — ремонт сработает на следующей загрузке " +
                "(ClanIntegrity.RepairAll).");
            __result = 0f;
            return false;
        }

        /// <summary>Описание поломки фракции, либо null если она цела.</summary>
        private static string FirstBroken(IFaction faction)
        {
            try
            {
                if (faction == null) return "фракция == null";
                var leader = faction.Leader;
                if (leader == null)
                    return $"'{Describe(faction)}' без лидера";
                if (leader.Clan == null)
                    return $"'{Describe(faction)}': лидер '{leader.Name}' не состоит ни в каком клане";
                return null;
            }
            catch (Exception ex)
            {
                return $"проверка фракции упала: {ex.GetType().Name}";
            }
        }

        private static string Describe(IFaction faction)
        {
            try { return faction.Name?.ToString() ?? faction.StringId ?? "?"; }
            catch { return "?"; }
        }
    }
}
