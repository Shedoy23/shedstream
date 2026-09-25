using System;
using System.Linq;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;

namespace BannerlordLink.Util
{
    /// <summary>
    /// 2026-09-22 — целостность связки «клан ↔ его лидер».
    ///
    /// Два ванильных инварианта, оба проверены крашами одного дня:
    ///
    /// 1. **У неразбойничьего клана `Leader` обязан быть не-null.**
    ///    `ClanVariablesCampaignBehavior.MakeClanFinancialEvaluation` берёт
    ///    `clan.Leader.Gold` в суточном тике для КАЖДОГО такого клана, вне
    ///    зависимости от королевства и от `IsEliminated`. Первая версия этого
    ///    файла зануляла `_leader` — и уронила игру в 14:15 через десять секунд
    ///    после загрузки. Больше не зануляем НИКОГДА.
    /// 2. **Клан с «висящим» лидером (лидер уже не в этом клане) не должен
    ///    состоять в королевстве.** Из королевства ваниль ведёт его на выборы,
    ///    а `DefaultDiplomacyModel.GetRelationScore` разыменовывает
    ///    `Leader.Clan` — это краш в 13:10.
    ///
    /// Отсюда лечение: лидера либо заменяем настоящим членом клана, либо
    /// оставляем как есть, а клан выводим из королевства. Сам висящий указатель
    /// обезврежен двумя защитами: `ValidKingdomSupportersPatch` (не пускает
    /// такой клан в голосующие) и `DiplomacyRelationScorePatch` (бэкстоп).
    ///
    /// Разбор целиком: `docs/BANNERLORD_CRASH_2026-09-22.md`.
    /// </summary>
    internal static class ClanIntegrity
    {
        /// <summary>
        /// Зритель-лидер выходит из своего клана. Возвращает true, если после
        /// этого клан безопасен для ванили: он либо получил настоящего лидера,
        /// либо больше не состоит в королевстве.
        /// </summary>
        internal static bool DetachLeader(Clan clan, Hero hero, string who)
        {
            if (clan == null || hero == null) return false;

            // Если в клане остался живой наследник — ваниль поднимет его, и
            // связка становится честной. При пустом GetHeirApparents() метод
            // молча выходит, поэтому судим по наблюдаемому результату.
            try { ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader(clan); }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[leave_clan] @{who}: ApplyWithoutSelectedNewLeader упал: {ex.Message}");
            }

            if (!ReferenceEquals(clan.Leader, hero))
            {
                BannerlordLinkModule.Log(
                    $"[leave_clan] @{who}: лидерство принял член клана " +
                    $"'{Describe(clan.Leader)}'");
                return true;
            }

            // Наследника нет. Лидера НЕ зануляем (инвариант 1) — вместо этого
            // убираем клан из королевства, чтобы висящая ссылка не доехала до
            // выборов (инвариант 2).
            bool left = DropFromKingdom(clan, who);
            BannerlordLinkModule.Log(
                $"[leave_clan] @{who}: наследника нет, клан '{Describe(clan)}' остаётся " +
                $"с прежней ссылкой на лидера; из королевства {(left ? "выведен" : "ВЫВЕСТИ НЕ УДАЛОСЬ")}");
            return left;
        }

        /// <summary>
        /// Ремонт уже сохранённых кампаний. Возвращает число вылеченных кланов.
        /// </summary>
        internal static int RepairAll()
        {
            int repaired = 0;
            try
            {
                var all = Clan.All;
                if (all == null) return 0;
                foreach (var clan in all.ToList())
                {
                    if (clan == null) continue;
                    if (ReviveIfAlive(clan)) repaired++;
                    var leader = clan.Leader;
                    bool dangling = leader != null && !ReferenceEquals(leader.Clan, clan);
                    bool leaderless = leader == null;

                    if (!dangling && !leaderless) continue;
                    // Вне королевства чинить нечего: на выборы ваниль водит
                    // только членов королевства. Разбойничьи фракции (без
                    // лидера и без королевства) попадают сюда же — и это
                    // ванильная норма, их суточный тик пропускает.
                    // Считать такой клан «вылеченным» = врать в лог на каждой
                    // загрузке.
                    if (clan.Kingdom == null) continue;

                    string name = Describe(clan);

                    // Сначала пробуем вернуть клану настоящего лидера.
                    try { ChangeClanLeaderAction.ApplyWithoutSelectedNewLeader(clan); }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log(
                            $"[clan-repair] '{name}': ApplyWithoutSelectedNewLeader упал: {ex.Message}");
                    }
                    var now = clan.Leader;
                    if (now != null && ReferenceEquals(now.Clan, clan))
                    {
                        repaired++;
                        BannerlordLinkModule.Log(
                            $"[clan-repair] '{name}': лидером стал свой член клана '{Describe(now)}'");
                        continue;
                    }

                    if (DropFromKingdom(clan, name)) repaired++;

                    if (clan.Leader == null)
                    {
                        // Мы такого состояния больше не создаём, но сейв мог
                        // приехать с ним. Починить нечем — предупреждаем громко.
                        BannerlordLinkModule.Log(
                            $"[clan-repair] ВНИМАНИЕ: у клана '{name}' нет лидера и некем заменить. " +
                            "Ваниль упадёт на clan.Leader.Gold в суточном тике.");
                    }
                }
                if (repaired > 0)
                    BannerlordLinkModule.Log($"[clan-repair] вылечено кланов: {repaired}");
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[clan-repair] crashed: {ex.Message}");
            }
            return repaired;
        }

        /// <summary>#61 (24.09): перед роспуском королевства вывести из него все
        /// кланы, кроме правящего. Раньше кланы с флагом «уничтожен» пропускались
        /// и оставались висеть в распущенном королевстве («Рой пчёл»). Живой клан
        /// с застрявшим флагом сначала воскрешаем; если штатный выход упал или не
        /// сработал — выводим присваиванием, как при ремонте.</summary>
        internal static void EvacuateForDissolution(Kingdom kingdom, Clan rulerClan)
        {
            foreach (var member in kingdom.Clans.ToList())
            {
                if (member == null || member == rulerClan) continue;
                ReviveIfAlive(member);
                if (!member.IsEliminated)
                {
                    try { ChangeKingdomAction.ApplyByLeaveKingdom(member, false); }
                    catch (Exception ex)
                    {
                        BannerlordLinkModule.Log($"[clan-repair] '{Describe(member)}': штатный выход при роспуске упал: {ex.Message}");
                    }
                }
                if (member.Kingdom == kingdom) DropFromKingdom(member, Describe(member));
            }
        }

        /// <summary>
        /// <summary>
        /// Снять флаг «уничтожен» с клана, в котором остались живые люди и свой
        /// лидер. Решение владельца 22.09.
        ///
        /// Откуда берётся это состояние: ванильный `DestroyClanAction` помечает
        /// клан и убивает его героев, а наша защита не даёт зрителям умереть —
        /// герои живы, флаг висит. Дальше он всплывает везде: мод перестаёт
        /// отдавать королевство (`HeroStateSync.BuildKingdomInfo`), в клан
        /// нельзя вступить, клан не голосует.
        ///
        /// Ванильного способа снять флаг НЕТ: `IsEliminated` — свойство только
        /// на чтение, а сама ваниль при «уничтожен + лидер жив» в старом сейве
        /// ДОВОДИТ уничтожение (`Clan.cs`, ветка обновления сейва до 1.2.0).
        /// Для нас это означало бы убить зрителей, поэтому пишем поле напрямую.
        /// Условие узкое: в клане есть живой герой И лидер состоит в этом клане
        /// — пустые «призраки» не воскрешаем.
        /// </summary>
        private static bool ReviveIfAlive(Clan clan)
        {
            try
            {
                if (clan == null || !clan.IsEliminated) return false;
                var leader = clan.Leader;
                if (leader == null || !ReferenceEquals(leader.Clan, clan)) return false;
                var heroes = clan.Heroes;
                if (heroes == null) return false;
                int alive = heroes.Count(h => h != null && h.IsAlive);
                if (alive <= 0) return false;

                var field = HarmonyLib.AccessTools.Field(
                    typeof(TaleWorlds.CampaignSystem.Clan), "_isEliminated");
                if (field == null)
                {
                    BannerlordLinkModule.Log(
                        $"[clan-repair] '{Describe(clan)}': поле _isEliminated недоступно");
                    return false;
                }
                field.SetValue(clan, false);
                bool ok = !clan.IsEliminated;      // судим по наблюдаемому
                BannerlordLinkModule.Log(ok
                    ? $"[clan-repair] '{Describe(clan)}': снят флаг «уничтожен» — в клане {alive} живых, лидер '{Describe(leader)}'"
                    : $"[clan-repair] '{Describe(clan)}': снять флаг «уничтожен» НЕ УДАЛОСЬ");
                return ok;
            }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log($"[clan-repair] снятие флага упало: {ex.Message}");
                return false;
            }
        }

        /// Вывести клан из королевства ровно так, как это делает ваниль в
        /// `ChangeKingdomAction` — присваиванием `clan.Kingdom = null`; сеттер
        /// сам чинит списки. Полный `ApplyByLeaveKingdom` тут не годится: его
        /// ветка LeaveKingdom ходит по владениям через `clan.Leader.HomeSettlement`
        /// и падает ровно на тех кланах, которые мы чиним.
        /// Возвращает НАБЛЮДАЕМЫЙ результат, а не факт вызова.
        /// </summary>
        private static bool DropFromKingdom(Clan clan, string who)
        {
            if (clan == null) return false;
            if (clan.Kingdom == null) return true;
            string kingdom = Describe(clan.Kingdom);
            try { clan.Kingdom = null; }
            catch (Exception ex)
            {
                BannerlordLinkModule.Log(
                    $"[clan-repair] '{who}': выход из королевства '{kingdom}' упал: {ex.Message}");
            }
            bool ok = clan.Kingdom == null;
            BannerlordLinkModule.Log(ok
                ? $"[clan-repair] '{who}': клан выведен из королевства '{kingdom}'"
                : $"[clan-repair] '{who}': клан ОСТАЛСЯ в королевстве '{kingdom}' — ваниль поведёт его на выборы");
            return ok;
        }

        private static string Describe(object named)
        {
            try
            {
                if (named == null) return "(null)";
                var clan = named as Clan;
                if (clan != null) return clan.Name == null ? "(без имени)" : clan.Name.ToString();
                var hero = named as Hero;
                if (hero != null) return hero.Name == null ? "(без имени)" : hero.Name.ToString();
                var kingdom = named as Kingdom;
                if (kingdom != null) return kingdom.Name == null ? "(без имени)" : kingdom.Name.ToString();
                return named.ToString();
            }
            catch (Exception) { return "(имя недоступно)"; }
        }
    }
}
