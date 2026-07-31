using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordLink.Util
{
    /// <summary>
    /// Доводка только что созданного клана до состояния, которое движок считает
    /// нормальным.
    ///
    /// ЗАЧЕМ (2026-07-31, после двух крашей игры). Мы создавали кланы через
    /// `Clan.CreateClan` и дальше настраивали их «на глаз», каждый раз по-своему
    /// в трёх местах. Итог — клан БЕЗ ЛИДЕРА уезжал в кампанию, а ванильный
    /// `ClanVariablesCampaignBehavior.MakeClanFinancialEvaluation` первой же
    /// строкой делает `clan.Leader.Gold` **без проверки на null**:
    ///
    ///     if (clan.Leader.Gold > num2)   // ← NRE на безлидерном клане
    ///
    /// То есть любой такой клан гарантированно роняет игру на ближайшем дневном
    /// тике. Подтверждено дампом: NRE ровно в этом методе.
    ///
    /// ЧТО ДЕЛАЕТ САМ ДВИЖОК (декомпиль `Clan.CreateCompanionToLordClan` —
    /// ванильный путь «компаньон уходит основывать свой клан»):
    ///
    ///     clan.Culture = ...; clan.Banner = ...; clan.Kingdom = ...;
    ///     clan.Tier = ClanTierModel.CompanionToLordClanStartingTier;
    ///     clan.SetInitialHomeSettlement(...);
    ///     hero.Clan = clan;
    ///     clan.SetLeader(hero);              ← НЕ ChangeClanLeaderAction
    ///     clan.IsNoble = true;
    ///     CampaignEventDispatcher.Instance.OnClanCreated(clan, isCompanion);
    ///
    /// Здесь собрана та часть, что нужна ВСЕМ нашим кланам: лидер, тир,
    /// «благородность» и оповещение. Культура, знамя и дом остаются за
    /// вызывающим — они у нас разные по смыслу.
    ///
    /// ПОЧЕМУ ОТДЕЛЬНЫЙ ФАЙЛ. Правильный способ ставить лидера был описан в
    /// этом проекте ещё 2026-06-17 — в комментарии метода найма NPC-вассала, с
    /// разбором того же NRE. Его не перенесли в соседний метод, и полтора
    /// месяца спустя он выстрелил ровно там. Пока настройка клана размазана по
    /// местам, это повторится.
    /// </summary>
    public static class ClanFactory
    {

        /// <summary>
        /// Имя вассального клана с приставкой, из которой видно сюзерена.
        ///
        /// 2026-07-31, по просьбе владельца: в списке кланов вассалы ничем не
        /// отличались от прочих, и понять, чей это вассал, было нельзя.
        /// Формат: `[Vassal Седые] Кавиловы`.
        ///
        /// Из имени сюзерена убираем наш служебный префикс `[BLink] `, иначе
        /// получаются вложенные скобки — `[Vassal [BLink] Седые]`.
        /// </summary>
        public static string BuildVassalName(string suzerainClanName, string vassalName)
        {
            string suzerain = (suzerainClanName ?? "").Trim();
            const string blink = "[BLink] ";
            if (suzerain.StartsWith(blink, StringComparison.OrdinalIgnoreCase))
                suzerain = suzerain.Substring(blink.Length).Trim();

            string own = (vassalName ?? "").Trim();
            if (string.IsNullOrEmpty(own)) own = "Vassal Clan";
            if (string.IsNullOrEmpty(suzerain)) return own;

            // Повторный запуск по уже переименованному клану не должен плодить
            // приставку поверх приставки.
            if (own.StartsWith("[Vassal ", StringComparison.OrdinalIgnoreCase)) return own;

            return $"[Vassal {suzerain}] {own}";
        }

        /// <summary>
        /// Назначить лидера и довести клан до рабочего состояния.
        /// false → клан НЕПРИГОДЕН, вызывающий обязан прервать действие и не
        /// оставлять его в кампании (иначе краш на дневном тике).
        /// </summary>
        public static bool FinalizeNewClan(Clan clan, Hero leader, string tag,
                                           bool isCompanion = false)
        {
            if (clan == null || leader == null)
            {
                BannerlordLinkModule.Log($"[{tag}] FinalizeNewClan: clan/leader == null");
                return false;
            }

            leader.Clan = clan;

            // ВАЖНО: именно SetLeader. `ChangeClanLeaderAction` — это СМЕНА
            // существующего лидера, внутри она читает текущего (`clan.Leader`),
            // которого у нового клана нет.
            try
            {
                clan.SetLeader(leader);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[{tag}] SetLeader упал: {ex.Message}");
                return false;
            }

            if (clan.Leader != leader)
            {
                BannerlordLinkModule.Log(
                    $"[{tag}] лидер не установился — клан непригоден, прерываем");
                return false;
            }

            clan.IsNoble = true;

            // Тир НЕ ставим напрямую: у `Clan.Tier` сеттер внутренний — ваниль
            // может, мы нет. Лезть туда рефлексией не стали: тир в движке
            // выводится из известности клана, и вызывающий её начисляет
            // (`AddRenown`). Пробовали присвоить — компилятор отказал
            // (CS0200), и это правильный отказ, а не препятствие.

            // Оповещение: на него подписаны и ваниль, и сторонние моды (у нас
            // стоит Diplomacy). Без него клан существует, но про него никто не
            // знает.
            try
            {
                CampaignEventDispatcher.Instance.OnClanCreated(clan, isCompanion);
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[{tag}] OnClanCreated warn: {ex.Message}");
            }

            // Дом и «центр» фракции. Без них ванильный дневной тик роняет игру
            // — подробности в EnsureHomeAndMid. Клан без центра НЕПРИГОДЕН:
            // лучше отказать в покупке (зритель получит возврат), чем уронить
            // игру на стриме.
            if (!EnsureHomeAndMid(clan, tag))
            {
                BannerlordLinkModule.Log(
                    $"[{tag}] не удалось назначить дом/центр — клан непригоден, прерываем");
                return false;
            }

            BannerlordLinkModule.Log(
                $"[{tag}] клан '{clan.Name}' готов: лидер '{leader.Name}', тир {clan.Tier}, "
                + $"известность {clan.Renown}, дом '{clan.HomeSettlement?.Name?.ToString() ?? "—"}', "
                + $"центр '{clan.FactionMidSettlement?.Name?.ToString() ?? "—"}'");
            return true;
        }

        /// <summary>
        /// Гарантировать клану дом (`HomeSettlement`) и «центр фракции»
        /// (`FactionMidSettlement`). false → центр назначить не удалось.
        ///
        /// ЗАЧЕМ. Выборы за владение читают центр без проверки на null:
        ///
        ///     Settlement factionMidSettlement = faction.FactionMidSettlement;
        ///     ...
        ///     if (faction.FactionMidSettlement.MapFaction != faction)   ← NRE
        ///     (DefaultSettlementValueModel.GeographicalAdvantageForFaction)
        ///
        /// Вызывается это на ДНЕВНОМ ТИКЕ, когда королевство делит феод, то
        /// есть падает у зрителей на глазах. Цена — два краша на стриме 31.07.
        ///
        /// ПОЧЕМУ ОДНОГО `CalculateMidSettlement()` МАЛО (первая версия этой
        /// починки была именно такой и дыру не закрывала). Для клана без
        /// владений движок берёт центр из дома:
        ///
        ///     if (faction.Settlements.Count == 0)
        ///         result = clan.HomeSettlement;      (FactionHelper)
        ///
        /// а дом для клана без владений и без королевства он берёт из
        /// `InitialHomeSettlement`:
        ///
        ///     if (... || clan.MapFaction.Settlements.Count == 0)
        ///         return clan.InitialHomeSettlement; (DefaultSettlementValueModel)
        ///
        /// Мы `SetInitialHomeSettlement` не звали никогда — ваниль в своём
        /// пути (`CreateCompanionToLordClan`) зовёт его явно. Итог: null → null
        /// → null, и расчёт центра честно возвращает null.
        ///
        /// ЭТО ЖЕ ЛЕЧИТ СТАРЫЕ СОХРАНЁНКИ. `Clan.AfterLoad` заканчивается
        /// вызовом `CalculateMidSettlement()`, но он снова даёт null, пока дом
        /// пуст — то есть клан, созданный до этой починки, остаётся миной в
        /// каждой последующей загрузке, а не «чинится сам».
        ///
        /// Цепочка запасных вариантов взята у самой ванили (её миграция на
        /// v1.3.0 в `Clan.AfterLoad`): дом → поселение своей культуры → любое.
        /// </summary>
        public static bool EnsureHomeAndMid(Clan clan, string tag)
        {
            if (clan == null) return false;

            try
            {
                if (clan.HomeSettlement == null)
                {
                    clan.ConsiderAndUpdateHomeSettlement();
                }

                if (clan.HomeSettlement == null)
                {
                    Settlement home = clan.Leader?.BornSettlement;

                    if (home == null)
                        home = Campaign.Current.Settlements
                            .FirstOrDefault(s => s.IsTown && s.Culture == clan.Culture);
                    if (home == null)
                        home = Campaign.Current.Settlements.FirstOrDefault(s => s.IsTown);
                    if (home == null)
                        home = Campaign.Current.Settlements.FirstOrDefault();

                    if (home != null)
                    {
                        // Ставит InitialHomeSettlement и сам пересчитывает дом.
                        clan.SetInitialHomeSettlement(home);
                    }
                }

                clan.CalculateMidSettlement();
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[{tag}] EnsureHomeAndMid упал: {ex.Message}");
                return false;
            }

            return clan.FactionMidSettlement != null;
        }
    }
}
