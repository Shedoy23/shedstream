using Newtonsoft.Json.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Списание игровых динаров, объявленных бэкендом в поле `hero_gold_cost`.
    ///
    /// ЗАЧЕМ ЭТОТ ФАЙЛ (2026-07-31). Бэкенд для части действий проверяет баланс
    /// героя и кладёт в задание `hero_gold_cost`: смена пола 50 000, брак
    /// 50 000, ребёнок 100 000. Мод это поле НЕ ЧИТАЛ ВООБЩЕ — ни один
    /// обработчик. Действия выполнялись бесплатно: зрителю достаточно было один
    /// раз иметь нужную сумму на счету, дальше механика ничего не стоила.
    ///
    /// Нашёл внешний аудит 31.07 статически; **подтверждено прогоном в игре** в
    /// тот же день: `set_gender` и `make_baby` сработали, золото не изменилось
    /// ни на единицу, а контрольный «ящик» брони в том же прогоне списал ровно
    /// свои 500 000 и записал это в лог.
    ///
    /// ПОЧЕМУ ОБЩИЙ ХЕЛПЕР, А НЕ ТРИ КОПИИ. Ровно в этом проекте один и тот же
    /// фикс уже трижды ложился в один файл из трёх похожих и там оставался
    /// (журнал выплат, «висящий сезон», транзакция вокруг призов). Три копии
    /// списания разъедутся так же. Здесь — одно место.
    /// </summary>
    public static class HeroGoldCharge
    {
        /// <summary>
        /// Списать объявленную цену. Возвращает false, если денег не хватило —
        /// тогда действие выполнять НЕЛЬЗЯ (отказ уже отправлен на бэкенд,
        /// зритель получит возврат крустиков и причину).
        ///
        /// Цена 0 или отсутствует — считаем действие бесплатным и пропускаем:
        /// так ведёт себя большинство действий, и ломать их нельзя.
        /// </summary>
        public static bool TryCharge(Hero hero, JObject data, string actionId, string tag)
        {
            int cost = 0;
            try { cost = (int?)data["hero_gold_cost"] ?? 0; }
            catch { cost = 0; }
            if (cost <= 0) return true;

            if (hero == null)
            {
                ActionFeedback.PostFailed(actionId, "hero_not_found");
                return false;
            }

            // Баланс проверяем ЗДЕСЬ, а не доверяем бэкенду: там он берётся из
            // кэша состояния героя, который отстаёт от игры. Списать больше,
            // чем есть, движок позволит — герой уйдёт в минус.
            if (hero.Gold < cost)
            {
                BannerlordLinkModule.Log(
                    $"[{tag}] @{hero.Name}: недостаточно динаров ({hero.Gold} < {cost}) — отказ");
                ActionFeedback.PostFailed(actionId, "not_enough_gold");
                return false;
            }

            int before = hero.Gold;
            GiveGoldAction.ApplyBetweenCharacters(hero, null, cost, true);
            BannerlordLinkModule.Log(
                $"[{tag}] @{hero.Name}: gold {before} → {hero.Gold} (-{cost})");
            return true;
        }
    }
}
