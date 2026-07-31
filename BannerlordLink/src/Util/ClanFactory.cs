using System;
using TaleWorlds.CampaignSystem;

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

            BannerlordLinkModule.Log(
                $"[{tag}] клан '{clan.Name}' готов: лидер '{leader.Name}', тир {clan.Tier}, известность {clan.Renown}");
            return true;
        }
    }
}
