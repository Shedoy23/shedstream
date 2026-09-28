using System;
using HarmonyLib;
using TaleWorlds.CampaignSystem;

namespace BannerlordLink.Patches
{
    /// <summary>
    /// 2026-07-31 22:24, КРАШ НА ДНЕВНОМ ТИКЕ (дамп разобран dotnet-dump):
    ///
    ///   CraftingCampaignBehavior.CreateTownOrder(Hero, Int32)          ← NRE
    ///     ← CraftingCampaignBehavior.ReplaceCraftingOrder(Town, CraftingOrder)
    ///     ← CraftingCampaignBehavior.DailyTick()
    ///
    /// Это заказы на ковку в городах. Ваниль САМА знает про этот случай и даже
    /// печатает предупреждение — а затем разыменовывает то же поле без проверки:
    ///
    ///     if (orderOwner.CurrentSettlement == null || !orderOwner.CurrentSettlement.IsTown)
    ///         Debug.Print(...);                                        // заметили
    ///     GetTownOrderDifficulty(orderOwner.CurrentSettlement.Town, orderSlot);  // ← упали
    ///
    /// Откуда берётся заказчик (`ReplaceCraftingOrder`):
    ///
    ///     mBList.AddRange(settlement.HeroesWithoutParty);
    ///     foreach (party in settlement.Parties)
    ///         if (party.LeaderHero != null && !party.IsMainParty)
    ///             mBList.Add(party.LeaderHero);
    ///     ...
    ///     CreateTownOrder(mBList.GetRandomElement(), difficultyLevel);
    ///
    /// То есть кандидат — случайный герой из города ИЛИ лидер стоящего там
    /// отряда, и у второго `CurrentSettlement` вполне может быть пустым. Выбор
    /// случайный, поэтому падает «на ровном месте» и не каждый день.
    ///
    /// Наши вью-герои попадают в оба списка: они живут в городах и водят отряды
    /// (`hero.create_party`). Мы не создаём поломку, но мы кратно повышаем шанс
    /// в неё попасть — обычных лордов в городе единицы, а зрителей десятки.
    ///
    /// ЧТО ДЕЛАЕМ. Правило проекта — не глушить, а чинить вход. Чинить тут
    /// нечего: заказчика выбрала ваниль, подменять его — значит переписывать её
    /// логику раздачи заказов. Поэтому prefix ПРОПУСКАЕТ создание заказа для
    /// негодного героя. Цена пропуска — один слот заказов в одном городе
    /// остаётся пустым до следующего дневного тика, когда ваниль выберет
    /// другого. Это незаметно даже игроку, который целенаправленно кузнечит.
    ///
    /// Лог пишем с именем героя — по нему видно, наш это герой или ванильный
    /// лорд. Если окажется, что это всегда наши, значит корень глубже (мы
    /// оставляем героя в списке города, выведя его оттуда), и это надо чинить
    /// у себя, а не здесь.
    /// </summary>
    public static class CraftingOrderPatch
    {
        private static readonly Type _craftingBehaviorType =
            SafeResolveType("TaleWorlds.CampaignSystem.CampaignBehaviors.CraftingCampaignBehavior");

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
        public static class CreateTownOrderGuard
        {
            public static System.Collections.Generic.IEnumerable<System.Reflection.MethodBase>
                TargetMethods()
            {
                if (_craftingBehaviorType == null)
                {
                    BannerlordLinkModule.Log(
                        "[CraftingOrder] CraftingCampaignBehavior type не найден — guard skip " +
                        "(version mismatch?)");
                    yield break;
                }
                var m = AccessTools.Method(_craftingBehaviorType, "CreateTownOrder",
                    new[] { typeof(Hero), typeof(int) });
                if (m == null)
                {
                    BannerlordLinkModule.Log(
                        "[CraftingOrder] CreateTownOrder method не найден — skip");
                    yield break;
                }
                BannerlordLinkModule.Log(
                    "[CraftingOrder] CreateTownOrder guard registered (заказчик вне города → "
                    + "заказ пропускается, дневной тик не падает)");
                yield return m;
            }

            [HarmonyPrefix]
            public static bool Prefix(Hero orderOwner)
            {
                try
                {
                    var settlement = orderOwner?.CurrentSettlement;
                    if (settlement == null || !settlement.IsTown)
                    {
                        string name = "?";
                        try { name = orderOwner?.Name?.ToString() ?? "null"; } catch { }
                        BannerlordLinkModule.Log(
                            $"[CraftingOrder] заказ пропущен: заказчик '{name}' не в городе "
                            + $"(поселение: {settlement?.Name?.ToString() ?? "нет"}) — "
                            + "ваниль здесь падает без проверки");
                        return false;   // skip original — не заходим в баговый путь
                    }
                }
                catch
                {
                    return false;
                }
                return true;            // заказчик годен — обычный путь
            }

            // Подстраховка на случай другого null внутри метода (шаблон ковки,
            // запись города в словаре заказов). Полный стек в лог — чтобы не
            // расследовать вслепую, если сработает.
            [HarmonyFinalizer]
            public static Exception Finalizer(Exception __exception, Hero orderOwner)
            {
                if (__exception == null) return null;
                if (__exception is NullReferenceException)
                {
                    string name = "?";
                    try { name = orderOwner?.Name?.ToString() ?? "null"; } catch { }
                    BannerlordLinkModule.Log(
                        $"[CraftingOrder] SWALLOWED NullReferenceException, заказчик='{name}'; "
                        + $"заказ не создан, дневной тик не падает. Стек: {__exception}");
                    return null;        // swallow → процесс не падает
                }
                return __exception;     // прочее — пусть всплывает для диагностики
            }
        }
    }
}
