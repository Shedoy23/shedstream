using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Library;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Sprint 5.32 BUGFIX — helper для "прописки" wanderer-героев.
    ///
    /// Проблема: TaleWorlds engine считает героев без home settlement / клана /
    /// party "беспризорными" и периодически их утилизирует через
    /// KillCharacterAction.ApplyByRemove с detail=Lost ("пропал без вести").
    ///
    /// Решение: после любого action который делает hero wanderer'ом, ставим
    /// его в подходящий town + ОБЯЗАТЕЛЬНО устанавливаем HomeSettlement
    /// (через reflection — public setter отсутствует). HomeSettlement = key
    /// поле для engine'а: если есть, hero "прописан" и daily ticks его не теряют.
    /// </summary>
    public static class WandererHome
    {
        /// <summary>Place hero в подходящий town + set HomeSettlement.
        /// Возвращает settlement куда placed, или null если не удалось.</summary>
        public static Settlement PlaceInNearestTavern(Hero hero)
        {
            if (hero == null || !hero.IsAlive) return null;
            try
            {
                Settlement target = ResolveTown(hero);
                if (target == null)
                {
                    BannerlordLinkModule.Log(
                        $"[WandererHome] @{hero.Name}: no suitable town found");
                    return null;
                }

                // КЛЮЧЕВОЕ: установить HomeSettlement через reflection.
                // Без него engine считает hero orphan'ом и daily ticks могут
                // его утилизировать (KillCharacterAction.ApplyByRemove Lost).
                try
                {
                    if (hero.HomeSettlement == null)
                    {
                        var homeField = HarmonyLib.AccessTools.Field(
                            typeof(Hero), "_homeSettlement");
                        if (homeField != null)
                        {
                            homeField.SetValue(hero, target);
                        }
                        else
                        {
                            // Fallback name (если TaleWorlds переименует).
                            var homeField2 = HarmonyLib.AccessTools.Field(
                                typeof(Hero), "<HomeSettlement>k__BackingField");
                            homeField2?.SetValue(hero, target);
                        }
                    }
                }
                catch (Exception hex)
                {
                    BannerlordLinkModule.Log(
                        $"[WandererHome] @{hero.Name}: HomeSettlement set warn: {hex.Message}");
                }

                // Move hero в settlement. Engine сам разместит в подходящем
                // location'е (Tavern для Wanderer occupation).
                try
                {
                    EnterSettlementAction.ApplyForCharacterOnly(hero, target);
                }
                catch (Exception eex)
                {
                    BannerlordLinkModule.Log(
                        $"[WandererHome] @{hero.Name}: EnterSettlement warn: {eex.Message}");
                }

                BannerlordLinkModule.Log(
                    $"[WandererHome] @{hero.Name} placed in {target.Name?.ToString() ?? target.StringId} " +
                    $"(home={hero.HomeSettlement?.Name?.ToString() ?? "—"})");
                return target;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[WandererHome] @{hero?.Name}: PlaceInNearestTavern failed: {ex.Message}");
                return null;
            }
        }

        /// <summary>Подходящий town для wanderer'а. Приоритет:
        /// 1. Текущий settlement если town (hero уже где-то).
        /// 2. Town его культуры (battania → battanian town).
        /// 3. Random town вообще.</summary>
        private static Settlement ResolveTown(Hero hero)
        {
            // 1. Уже в town'е? Use current.
            try
            {
                var current = hero.CurrentSettlement;
                if (current != null && current.IsTown) return current;
            }
            catch { }

            var allTowns = Settlement.All?
                .Where(s => s != null && s.IsTown && s.Town != null && !s.IsUnderSiege)
                .ToList();
            if (allTowns == null || allTowns.Count == 0)
            {
                // Last resort — даже под осадой можно. Engine разрулит.
                allTowns = Settlement.All?
                    .Where(s => s != null && s.IsTown)
                    .ToList();
            }
            if (allTowns == null || allTowns.Count == 0) return null;

            // 2. Town hero's culture.
            try
            {
                var culture = hero.Culture;
                if (culture != null)
                {
                    var sameCulture = allTowns
                        .Where(s => s.MapFaction?.Culture == culture)
                        .ToList();
                    if (sameCulture.Count > 0)
                        return sameCulture[new Random().Next(sameCulture.Count)];
                }
            }
            catch { }

            // 3. Random.
            return allTowns[new Random().Next(allTowns.Count)];
        }
    }
}
