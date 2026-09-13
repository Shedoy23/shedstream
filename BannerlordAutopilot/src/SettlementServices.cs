using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;
using Helpers;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.CampaignBehaviors;
using TaleWorlds.CampaignSystem.ComponentInterfaces;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Localization;

namespace BannerlordAutopilot
{
    /// <summary>Пределы расходов обслуживания в поселении. Значения и их обоснование —
    /// README, раздел «Обслуживание партии». Меняются здесь, в одном месте.</summary>
    internal static class ServiceLimits
    {
        /// <summary>Сколько денег героя обслуживание не трогает никогда.</summary>
        internal static int MinGoldReserve = 2000;

        /// <summary>Резерв на жалование: столько дней дневного жалования партии
        /// (MobileParty.TotalWage — дневное: движок даёт «недельную премию» как
        /// TotalWage * 7) остаются нетронутыми. Итоговый резерв — большее из двух.</summary>
        internal static int ReserveWageDays = 7;

        /// <summary>Потолок трат на еду за один проход.</summary>
        internal static int MaxFoodSpendPerPass = 5000;

        /// <summary>Потолок трат на найм за один проход.</summary>
        internal static int MaxRecruitSpendPerPass = 5000;

        /// <summary>Потолок числа нанятых за один проход.</summary>
        internal static int MaxRecruitsPerPass = 30;

        /// <summary>Не чаще одного прохода в поселении за столько игровых часов.
        /// Совпадает с периодом пересчёта AI: обслуживание успевает до решения.</summary>
        internal static double PassIntervalHours = 6;

        /// <summary>Запас на расхождение цены. План покупки считается по цене
        /// FindItemToBuy (цена поселения), а списание делает SellItemsAction по ценам
        /// города — для деревни это её торговый город, и цены там другие.</summary>
        internal const float PriceSafety = 1.25f;
    }

    /// <summary>Обслуживание партии игрока в поселении: продажа обычных пленных,
    /// покупка еды, найм добровольцев.
    ///
    /// ЗАЧЕМ. Движок делает это для NPC и явно пропускает MainParty
    /// (PartiesBuyFoodCampaignBehavior.BuyFoodInternal, RecruitmentCampaignBehavior,
    /// PartiesSellPrisonerCampaignBehavior). Без этого партия под автопилотом голодает,
    /// не пополняется, и оценка «побыть в городе» может не падать никогда (итоговая
    /// независимая проверка 13.09, P1). Исключения движка для MainParty не снимаются:
    /// мод повторяет штатные расчёты и действия сам, ровно для одной партии.
    ///
    /// ЦЕПОЧКИ ДВИЖКА 1.4.8 (строки — TaleWorlds.CampaignSystem.decompiled.cs):
    /// * Пленные — путь игрока «Выкупить пленных» в переулках города
    ///   (SellAllTransferablePrisoners 206378): список
    ///   MobilePartyHelper.GetPlayerPrisonersPlayerCanSell (3255, без закреплённых
    ///   игроком), SellPrisonersAction.ApplyForSelectedPrisoners(MainParty, null, …)
    ///   (228180): обычные снимаются с ростера, выкуп по RansomValueCalculationModel
    ///   платится герою через GiveGoldAction. Героев мод из списка убирает: с
    ///   покупателем null движок их ОТПУСКАЕТ за выкуп (228223) — это решение игрока.
    /// * Еда — путь NPC (TryBuyingFood 202571, BuyFoodInternal 202604): запас в днях
    ///   из PartyFoodBuyingModel, нужное число — штатный CalculateFoodCountToBuy
    ///   (202589, вызывается рефлексией, копии формулы нет), выбор продукта —
    ///   PartyFoodBuyingModel.FindItemToBuy (64183), покупка — SellItemsAction
    ///   (228076). Для игрока — ещё условие пункта «Торговать» (SettlementAccessModel,
    ///   Trade, 206113).
    /// * Найм — путь игрока, экран найма (RecruitmentVM.RefreshScreen 51233,
    ///   RecruitVolunteerVM 52197, OnDone 51349): старосты с CanHaveRecruits,
    ///   доброволец доступен по HeroHelper.HeroCanRecruitFromHero(MainHero, …) — у
    ///   игрока правило «индекс ≤ максимума», у NPC другое (209518), цена —
    ///   PartyWageModel.GetTroopRecruitmentCost(troop, MainHero). Применение как в
    ///   OnDone: слот обнуляется, боец в ростер, OnUnitRecruited, одно списание
    ///   GiveGoldAction на всю сумму. Отличие одно: цена бойца прибавляется к сумме
    ///   сразу, как он попал в ростер, ДО события — подписчик события может упасть,
    ///   и боец не должен остаться бесплатным (проверка 14.09). Условие пункта
    ///   «Нанять» — SettlementAccessModel, RecruitTroops. Вместимость партии экран
    ///   игрока не запрещает, мод — да.
    ///
    /// ЧТО ВАЖНО ПРО ДЕНЬГИ. GiveGoldAction списывает min(золото, сумма) (227100), а
    /// SellItemsAction сначала перекладывает товар и лишь потом платит — при нехватке
    /// денег товар достался бы дешевле. Поэтому деньги проверяются ДО операции, с
    /// резервом и запасом на цену. SellItemsAction не проверяет и остаток у продавца:
    /// сверх остатка покупатель получил бы товар из ничего (ItemRoster.AddToCounts
    /// 95902) — число покупки ограничивается текущим остатком.
    ///
    /// Успехом считается только наблюдаемый результат: изменение ростера и денег.</summary>
    internal sealed class SettlementServices
    {
        // Когда поселение обслуживалось последний раз (час кампании), по StringId
        // поселения. Пределы трат действуют «на проход раз в шесть часов», поэтому
        // отметки пишутся в сейв (SyncData автопилота) и не сбрасываются повторным F11.
        // Раньше они жили только в памяти, а здесь стояло «после загрузки проход
        // безопасен: потребность считается по состоянию». Это верно, пока проход
        // покрывает всю потребность. Упёрся в предел — загрузка через час давала
        // второй такой же проход, и предел умножался на число загрузок (проверка 14.09).
        private readonly Dictionary<string, double> _lastPassHours = new Dictionary<string, double>();

        internal bool IsDue(Settlement settlement)
        {
            return !_lastPassHours.TryGetValue(settlement.StringId, out double last)
                   || CampaignTime.Now.ToHours - last >= ServiceLimits.PassIntervalHours;
        }

        /// <summary>Отметки проходов для сейва: «id=час;id=час». Строка — базовый тип
        /// сохранения: не нужно регистрировать контейнеры, и без мода ключ просто
        /// не прочитается.</summary>
        internal string SavePasses()
        {
            var parts = new List<string>();
            foreach (KeyValuePair<string, double> pass in _lastPassHours)
            {
                parts.Add(pass.Key + "=" + pass.Value.ToString("R", CultureInfo.InvariantCulture));
            }
            return string.Join(";", parts);
        }

        /// <summary>Отметки из сейва. Непонятная запись пропускается: исключение здесь
        /// ушло бы в загрузку кампании — по прочитанным вызовам (Campaign 10581,
        /// CampaignBehaviorManager 169269, CampaignBehaviorDataStore 11385) его никто не
        /// перехватывает. Цена пропуска — один лишний проход в этом поселении.</summary>
        internal void LoadPasses(string saved)
        {
            _lastPassHours.Clear();
            foreach (string part in (saved ?? "").Split(';'))
            {
                int eq = part.LastIndexOf('=');
                if (eq > 0 && double.TryParse(part.Substring(eq + 1), NumberStyles.Float,
                        CultureInfo.InvariantCulture, out double hours))
                {
                    _lastPassHours[part.Substring(0, eq)] = hours;
                }
            }
        }

        internal void Run(MobileParty party, Settlement settlement, string trigger)
        {
            _lastPassHours[settlement.StringId] = CampaignTime.Now.ToHours;
            int reserve = Reserve(party);
            AutopilotLog.Write("  ОБСЛУЖИВАНИЕ «" + settlement.Name + "» (" + trigger + "): денег "
                               + Hero.MainHero.Gold + ", резерв " + reserve
                               + " (не меньше " + ServiceLimits.MinGoldReserve + " и " + ServiceLimits.ReserveWageDays
                               + " дн. жалования по " + party.TotalWage + ")");
            SellPrisoners(party, settlement);
            BuyFood(party, settlement, reserve);
            Recruit(party, settlement, reserve);
        }

        private static int Reserve(MobileParty party)
        {
            return Math.Max(ServiceLimits.MinGoldReserve, ServiceLimits.ReserveWageDays * Math.Max(0, party.TotalWage));
        }

        // ── Пленные ─────────────────────────────────────────────────────────

        private static void SellPrisoners(MobileParty party, Settlement settlement)
        {
            TroopRoster prison = party.PrisonRoster;
            if (prison.TotalManCount <= 0)
            {
                return;
            }
            if (!settlement.IsTown)
            {
                AutopilotLog.Write("    пленные: не продаём — выкуп у игрока есть только в городе (переулки)");
                return;
            }
            if (!Campaign.Current.Models.SettlementAccessModel.CanMainHeroAccessLocation(
                    settlement, "tavern", out _, out TextObject tavernWhy))
            {
                AutopilotLog.Write("    пленные: переулки закрыты для игрока" + Because(tavernWhy));
                return;
            }

            TroopRoster regulars = TroopRoster.CreateDummyTroopRoster();
            int count = 0;
            int heroes = 0;
            int expected = 0;
            foreach (TroopRosterElement element in MobilePartyHelper.GetPlayerPrisonersPlayerCanSell().GetTroopRoster())
            {
                if (element.Character.IsHero)
                {
                    heroes++;
                    continue;
                }
                if (element.Number <= 0)
                {
                    continue;
                }
                regulars.Add(element);
                count += element.Number;
                expected += Campaign.Current.Models.RansomValueCalculationModel
                    .PrisonerRansomValue(element.Character, Hero.MainHero) * element.Number;
            }
            string heroNote = heroes > 0 ? "; пленных героев не трогаем: " + heroes : "";
            if (count == 0)
            {
                AutopilotLog.Write("    пленные: обычных для продажи нет (закреплённых игроком движок не продаёт)" + heroNote);
                return;
            }
            if (expected <= 0)
            {
                // Штатный пункт скрыт при нулевом выкупе (SellPrisonersCondition 206333).
                AutopilotLog.Write("    пленные: выкуп за " + count + " обычных — 0, пункт у игрока скрыт" + heroNote);
                return;
            }

            int goldBefore = Hero.MainHero.Gold;
            int regularsBefore = prison.TotalRegulars;
            int heroesBefore = prison.TotalHeroes;
            SellPrisonersAction.ApplyForSelectedPrisoners(party.Party, null, regulars);
            int sold = regularsBefore - prison.TotalRegulars;
            int received = Hero.MainHero.Gold - goldBefore;
            if (sold == count && received > 0 && prison.TotalHeroes == heroesBefore)
            {
                AutopilotLog.Write("    пленные: ПРОДАНО " + sold + " обычных, получено " + received
                                   + " (ожидалось " + expected + ")" + heroNote);
            }
            else
            {
                AutopilotLog.Write("    пленные: продажа НЕ подтвердилась — снято " + sold + " из " + count
                                   + ", получено " + received + ", героев было " + heroesBefore
                                   + ", стало " + prison.TotalHeroes);
            }
        }

        // ── Еда ─────────────────────────────────────────────────────────────

        private static void BuyFood(MobileParty party, Settlement settlement, int reserve)
        {
            GameModels models = Campaign.Current.Models;
            if (!settlement.IsTown && !settlement.IsVillage)
            {
                return; // замки и прочее: у NPC и у игрока там еду не покупают
            }
            if (!models.MobilePartyFoodConsumptionModel.DoesPartyConsumeFood(party))
            {
                return;
            }
            if (!settlement.IsVillage && party.MapFaction != null && party.MapFaction.IsAtWarWith(settlement.MapFaction))
            {
                AutopilotLog.Write("    еда: не покупаем — город враждебен (как у NPC, 202573)");
                return;
            }
            if (!models.SettlementAccessModel.CanMainHeroDoSettlementAction(
                    settlement, SettlementAccessModel.SettlementAction.Trade, out _, out TextObject tradeWhy))
            {
                AutopilotLog.Write("    еда: торговать игроку нельзя" + Because(tradeWhy));
                return;
            }
            if (settlement.ItemRoster.TotalFood <= 0)
            {
                AutopilotLog.Write("    еда: у продавца еды нет");
                return;
            }

            float minDays = settlement.IsVillage
                ? models.PartyFoodBuyingModel.MinimumDaysFoodToLastWhileBuyingFoodFromVillage
                : models.PartyFoodBuyingModel.MinimumDaysFoodToLastWhileBuyingFoodFromTown;
            int need = FoodCountToBuy(party, minDays);
            if (need < 0)
            {
                AutopilotLog.Write("    еда: штатный расчёт запаса недоступен (PartiesBuyFoodCampaignBehavior не найден) — не покупаем");
                return;
            }
            string stockNote = "на складе " + party.TotalFoodAtInventory + ", расход "
                               + (-party.FoodChange).ToString("F1", CultureInfo.InvariantCulture) + " в день, цель "
                               + minDays.ToString("F0", CultureInfo.InvariantCulture) + " дн.";
            if (need == 0)
            {
                AutopilotLog.Write("    еда: хватает (" + stockNote + ")");
                return;
            }
            int budget = Math.Min(ServiceLimits.MaxFoodSpendPerPass, Hero.MainHero.Gold - reserve);
            if (budget <= 0)
            {
                AutopilotLog.Write("    еда: нужно " + need + ", но денег сверх резерва нет (" + stockNote + ")");
                return;
            }

            // План — штатным выбором FindItemToBuy, как цикл BuyFoodInternal: одна
            // единица на шаг, скот считается за MeatCount единиц. Отличие: покупка
            // не по одной штуке, а партиями одного продукта, иначе движок пишет
            // сообщение о трате денег на каждую единицу (OnHeroOrPartyTradedGold).
            // Поэтому шаги плана видят остатки до покупки — каждый продукт
            // ограничен своим остатком.
            var plan = new List<FoodLine>();
            float planned = 0f;
            string stop = null;
            for (int i = 0; i < need; i++)
            {
                models.PartyFoodBuyingModel.FindItemToBuy(party, settlement, out ItemRosterElement element, out float price);
                ItemObject item = element.EquipmentElement.Item;
                if (item == null)
                {
                    stop = "подходящей еды по цене и деньгам больше нет";
                    break;
                }
                if (planned + price * ServiceLimits.PriceSafety > budget)
                {
                    stop = "упёрлись в предел трат (" + budget + ")";
                    break;
                }
                FoodLine line = plan.Find(l => l.Element.IsEqualTo(element.EquipmentElement));
                if (line == null)
                {
                    line = new FoodLine { Element = element.EquipmentElement, Price = price };
                    plan.Add(line);
                }
                if (line.Count < Stock(settlement.ItemRoster, element.EquipmentElement))
                {
                    line.Count++;
                    planned += price * ServiceLimits.PriceSafety;
                }
                if (item.HasHorseComponent && item.HorseComponent.IsLiveStock)
                {
                    i += item.HorseComponent.MeatCount - 1;
                }
            }

            int bought = 0;
            foreach (FoodLine line in plan)
            {
                int count = Math.Min(line.Count, Stock(settlement.ItemRoster, line.Element));
                int affordable = (int)Math.Floor((Hero.MainHero.Gold - reserve) / (line.Price * ServiceLimits.PriceSafety));
                if (affordable < count)
                {
                    stop = "деньги сверх резерва кончились";
                    count = Math.Max(0, affordable);
                }
                if (count <= 0)
                {
                    continue;
                }
                int goldBefore = Hero.MainHero.Gold;
                int haveBefore = Stock(party.ItemRoster, line.Element);
                SellItemsAction.Apply(settlement.Party, party.Party, new ItemRosterElement(line.Element, count), count);
                int got = Stock(party.ItemRoster, line.Element) - haveBefore;
                int spent = goldBefore - Hero.MainHero.Gold;
                if (got == count && spent > 0)
                {
                    bought += got;
                    AutopilotLog.Write("    еда: КУПЛЕНО " + got + " × " + line.Element.Item.Name + " за " + spent);
                }
                else
                {
                    AutopilotLog.Write("    еда: покупка " + count + " × " + line.Element.Item.Name
                                       + " НЕ подтвердилась — получено " + got + ", списано " + spent);
                }
            }
            if (bought < need && stop == null)
            {
                stop = "у продавца столько нет";
            }
            AutopilotLog.Write("    еда: нужно было " + need + ", куплено " + bought
                               + (stop != null ? "; остановка: " + stop : "") + " (" + stockNote + ")");
        }

        private sealed class FoodLine
        {
            internal EquipmentElement Element;
            internal float Price;
            internal int Count;
        }

        private static int Stock(ItemRoster roster, EquipmentElement element)
        {
            int index = roster.FindIndexOfElement(element);
            return index >= 0 ? roster.GetElementNumber(index) : 0;
        }

        /// <summary>Штатный расчёт PartiesBuyFoodCampaignBehavior.CalculateFoodCountToBuy
        /// (202589) — приватный, вызывается рефлексией, чтобы не держать копию формулы.
        /// −1 — расчёт недоступен.</summary>
        private static int FoodCountToBuy(MobileParty party, float minimumDaysToLast)
        {
            PartiesBuyFoodCampaignBehavior behavior = Campaign.Current.GetCampaignBehavior<PartiesBuyFoodCampaignBehavior>();
            MethodInfo method = typeof(PartiesBuyFoodCampaignBehavior).GetMethod(
                "CalculateFoodCountToBuy", BindingFlags.Instance | BindingFlags.NonPublic, null,
                new[] { typeof(MobileParty), typeof(float) }, null);
            if (behavior == null || method == null || method.ReturnType != typeof(int))
            {
                return -1;
            }
            return (int)method.Invoke(behavior, new object[] { party, minimumDaysToLast });
        }

        // ── Найм ────────────────────────────────────────────────────────────

        private static void Recruit(MobileParty party, Settlement settlement, int reserve)
        {
            GameModels models = Campaign.Current.Models;
            if (!settlement.IsTown && !settlement.IsVillage)
            {
                return; // в замке нет старост — пункта найма у игрока нет
            }
            if (!models.SettlementAccessModel.CanMainHeroDoSettlementAction(
                    settlement, SettlementAccessModel.SettlementAction.RecruitTroops, out _, out TextObject recruitWhy))
            {
                AutopilotLog.Write("    найм: нанимать игроку нельзя" + Because(recruitWhy));
                return;
            }
            int free = party.Party.PartySizeLimit - party.Party.NumberOfAllMembers;
            if (free <= 0)
            {
                AutopilotLog.Write("    найм: партия полна (" + party.Party.NumberOfAllMembers + " из " + party.Party.PartySizeLimit + ")");
                return;
            }
            int budget = Math.Min(ServiceLimits.MaxRecruitSpendPerPass, Hero.MainHero.Gold - reserve);
            if (budget <= 0)
            {
                AutopilotLog.Write("    найм: денег сверх резерва нет");
                return;
            }

            var cart = new List<(Hero Notable, int Index, CharacterObject Troop, int Cost)>();
            int total = 0;
            int volunteers = 0;
            int noRelation = 0;
            int tooExpensive = 0;
            string stop = null;
            foreach (Hero notable in settlement.Notables)
            {
                if (!notable.CanHaveRecruits)
                {
                    continue;
                }
                List<CharacterObject> troops = HeroHelper.GetVolunteerTroopsOfHeroForRecruitment(notable);
                for (int i = 0; i < troops.Count && stop == null; i++)
                {
                    CharacterObject troop = troops[i];
                    if (troop == null)
                    {
                        continue;
                    }
                    volunteers++;
                    if (!HeroHelper.HeroCanRecruitFromHero(Hero.MainHero, notable, i))
                    {
                        noRelation++;
                        continue;
                    }
                    if (cart.Count >= free)
                    {
                        stop = "партия заполнилась";
                        break;
                    }
                    if (cart.Count >= ServiceLimits.MaxRecruitsPerPass)
                    {
                        stop = "предел " + ServiceLimits.MaxRecruitsPerPass + " за проход";
                        break;
                    }
                    int cost = models.PartyWageModel.GetTroopRecruitmentCost(troop, Hero.MainHero).RoundedResultNumber;
                    if (total + cost > budget)
                    {
                        tooExpensive++;
                        continue;
                    }
                    cart.Add((notable, i, troop, cost));
                    total += cost;
                }
                if (stop != null)
                {
                    break;
                }
            }

            string summary = "добровольцев " + volunteers + ", не хватает отношений " + noRelation
                             + ", не по деньгам " + tooExpensive + (stop != null ? "; остановка: " + stop : "");
            if (cart.Count == 0)
            {
                AutopilotLog.Write("    найм: никого (" + summary + ")");
                return;
            }
            if (Hero.MainHero.Gold - reserve < total)
            {
                AutopilotLog.Write("    найм: отменён — денег сверх резерва меньше суммы " + total);
                return;
            }

            // Как RecruitmentVM.OnDone: слоты, ростер, событие — затем одно списание.
            // Списание в finally: упади что-то посреди, уже нанятые не останутся бесплатными.
            // Поэтому цена бойца идёт в сумму сразу за ростером, до события: событие
            // зовёт чужих подписчиков, и 14.09 проверка показала, что при их падении
            // боец, уже стоящий в отряде, в сумму не попадал.
            int goldBefore = Hero.MainHero.Gold;
            int membersBefore = party.MemberRoster.TotalManCount;
            int hired = 0;
            int charged = 0;
            try
            {
                foreach (var entry in cart)
                {
                    if (entry.Notable.VolunteerTypes[entry.Index] != entry.Troop)
                    {
                        continue; // слот изменился с момента выбора — второго получения не будет
                    }
                    entry.Notable.VolunteerTypes[entry.Index] = null;
                    party.MemberRoster.AddToCounts(entry.Troop, 1);
                    hired++;
                    charged += entry.Cost;
                    AutopilotLog.Write("    найм: НАНЯТ " + entry.Troop.Name + " у " + entry.Notable.Name + " за " + entry.Cost);
                    CampaignEventDispatcher.Instance.OnUnitRecruited(entry.Troop, 1);
                }
            }
            finally
            {
                if (charged > 0)
                {
                    GiveGoldAction.ApplyBetweenCharacters(Hero.MainHero, null, charged, disableNotification: true);
                }
            }

            int joined = party.MemberRoster.TotalManCount - membersBefore;
            int spent = goldBefore - Hero.MainHero.Gold;
            if (joined == hired && spent == charged)
            {
                AutopilotLog.Write("    найм: итого нанято " + hired + " за " + spent + " (" + summary + ")");
            }
            else
            {
                AutopilotLog.Write("    найм: итог НЕ сходится — в ростере +" + joined + " при " + hired
                                   + " нанятых, списано " + spent + " при сумме " + charged);
            }
        }

        private static string Because(TextObject why)
        {
            string text = why?.ToString();
            return string.IsNullOrEmpty(text) ? "" : ": " + text;
        }
    }
}
