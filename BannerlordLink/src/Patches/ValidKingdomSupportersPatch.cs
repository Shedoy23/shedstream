using System;
using System.Collections.Generic;
using HarmonyLib;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Election;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-09-22 — не пускать битый клан в список голосующих королевства.
    ///
    /// Ваниль по голосующим ходит без единой проверки: `Supporter.Name` это
    /// `Clan.Leader.Name`, а `DefaultDiplomacyModel.GetRelationScore` —
    /// `Leader.Clan.GetRelationWithClan(...)`. Клан, который числится в
    /// королевстве и указывает на лидера без клана, роняет суточный тик
    /// целиком (разбор: `docs/BANNERLORD_CRASH_2026-09-22.md`).
    ///
    /// Причину чинит `Util/ClanIntegrity` (действие больше не создаёт такую
    /// связку, загрузка лечит старые сейвы). Этот фильтр — вторая линия: он
    /// срабатывает раньше модели дипломатии и раньше окна голосования, и
    /// НАЗЫВАЕТ выброшенный клан в логе, чтобы следующая поломка не прошла
    /// молча.
    ///
    /// Почему фильтр И бэкстоп на `GetRelationScore` одновременно: фильтр
    /// закрывает голосование, бэкстоп — все прочие входы в модель дипломатии.
    /// Метки в логе разные (`[voter-guard]` и `[diplo-guard]`), чтобы по логу
    /// было видно, какая из защит сработала.
    ///
    /// Kill-switch: имя класса в `SKIP_PATCH_NAMES` (`BannerlordLinkModule.cs`).
    /// </summary>
    [HarmonyPatch(typeof(KingdomDecision), "DetermineSupporters")]
    public static class ValidKingdomSupportersPatch
    {
        // Один и тот же битый клан иначе кричал бы на каждом решении.
        private static readonly HashSet<string> _reported = new HashSet<string>();

        public static void Postfix(ref IEnumerable<Supporter> __result)
        {
            if (__result == null) return;
            var kept = new List<Supporter>();
            var dropped = new List<string>();

            foreach (var supporter in __result)
            {
                var clan = supporter == null ? null : supporter.Clan;
                var leader = clan == null ? null : clan.Leader;
                // Фильтруем ТОЛЬКО то, на чём ваниль падает: лидера нет или он
                // не состоит в этом клане (Supporter.Name → Clan.Leader.Name,
                // GetRelationScore → Leader.Clan). Флаг «уничтожен» сюда НЕ
                // входит: 22.09 под него попал живой клан зрителя
                // (`[BLink] Рой пчёл` — 5 человек, отряд, 24 430 известности,
                // свой лидер), и он молча потерял право голоса в королевстве.
                bool usable = clan != null
                              && leader != null
                              && ReferenceEquals(leader.Clan, clan);
                if (usable) kept.Add(supporter);
                else dropped.Add(Describe(clan));
            }

            if (dropped.Count == 0) return;

            foreach (var name in dropped)
            {
                if (!_reported.Add(name)) continue;
                BannerlordLinkModule.Log(
                    $"[voter-guard] клан '{name}' убран из голосующих: " +
                    "уничтожен либо его лидер не состоит в нём. " +
                    "Ремонт связки — ClanIntegrity.RepairAll на загрузке.");
            }
            __result = kept;
        }

        private static string Describe(Clan clan)
        {
            try
            {
                if (clan == null) return "(null)";
                var name = clan.Name;
                var text = name == null ? null : name.ToString();
                return string.IsNullOrEmpty(text) ? "(без имени)" : text;
            }
            catch (Exception)
            {
                return "(имя недоступно)";
            }
        }
    }
}
