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
        /// <summary>Фиксированный минимум отключён владельцем: резерв зависит от дней жалования.</summary>
        internal static int MinGoldReserve = 0;

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

        /// <summary>Желаемый состав обычных бойцов. По нему выбирается только между
        /// уже доступными игроку добровольцами; закрытые отношениями слоты не трогаются.</summary>
        internal static float TargetInfantry = 0.10f;
        internal static float TargetArchers = 0.70f;
        internal static float TargetCavalry = 0.10f;
        internal static float TargetHorseArchers = 0.10f;

        /// <summary>Не чаще одного прохода в поселении за столько игровых часов.
        /// Совпадает с периодом пересчёта AI: обслуживание успевает до решения.</summary>
        internal static double PassIntervalHours = 6;

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
    /// резервом по текущей цене перед каждой единицей. SellItemsAction не проверяет и остаток у продавца:
    /// сверх остатка покупатель получил бы товар из ничего (ItemRoster.AddToCounts
    /// 95902) — число покупки ограничивается текущим остатком.
    ///
    /// Успехом считается только наблюдаемый результат: изменение ростера и денег.</summary>
    internal sealed class SettlementServices
    {
        private enum TroopRole { Infantry, Archer, Cavalry, HorseArcher }

        private sealed class RecruitOffer
        {
            internal Hero Notable;
            internal int Index;
            internal CharacterObject Troop;
            internal int Cost;
            internal TroopRole Role;
            internal int Tier;
        }

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

        internal bool WasServicedRecently(Settlement settlement, double hours) =>
            _lastPassHours.TryGetValue(settlement.StringId, out double last)
            && CampaignTime.Now.ToHours - last < hours;

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
            TroopUpgrades.Run(party);
            EquipmentAndTrade.Equip(party);
            EquipmentAndTrade.Sell(party, settlement);
            TroopUpgrades.Run(party);
            int reserve = Reserve(party);
            AutopilotLog.Write("  ОБСЛУЖИВАНИЕ «" + settlement.Name + "» (" + trigger + "): денег "
                               + Hero.MainHero.Gold + ", резерв " + reserve
                               + " (" + ServiceLimits.ReserveWageDays + " дн. жалования по " + party.TotalWage
                               + "; денег хватит на " + (party.TotalWage > 0
                                   ? ((float)Hero.MainHero.Gold / party.TotalWage).ToString("F1", CultureInfo.InvariantCulture) + " дн."
                                   : "содержание без расходов") + ")");
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

            // Покупаем по одной единице, как штатный BuyFoodInternal. После каждой
            // операции рынок меняется и следующая цена пересчитывается. Пакетный
            // план по начальному снимку нарушал лимит при росте цены и мог снова
            // выбирать уже полностью запланированный товар, не закрывая потребность.
            string stop = null;
            int bought = 0;
            int satisfied = 0;
            int spentTotal = 0;
            while (satisfied < need)
            {
                models.PartyFoodBuyingModel.FindItemToBuy(party, settlement, out ItemRosterElement element, out _);
                ItemObject item = element.EquipmentElement.Item;
                if (item == null)
                {
                    stop = "подходящей еды по цене и деньгам больше нет";
                    break;
                }
                int available = Stock(settlement.ItemRoster, element.EquipmentElement);
                if (available <= 0)
                {
                    stop = "выбранного продукта уже нет у продавца";
                    break;
                }
                int price = CurrentBuyPrice(settlement, party, element.EquipmentElement);
                int remainingBudget = Math.Min(budget - spentTotal, Hero.MainHero.Gold - reserve);
                if (price <= 0 || price > remainingBudget)
                {
                    stop = "упёрлись в предел трат (" + budget + ")";
                    break;
                }
                int goldBefore = Hero.MainHero.Gold;
                int haveBefore = Stock(party.ItemRoster, element.EquipmentElement);
                SellItemsAction.Apply(settlement.Party, party.Party, new ItemRosterElement(element.EquipmentElement, 1), 1);
                int got = Stock(party.ItemRoster, element.EquipmentElement) - haveBefore;
                int spent = goldBefore - Hero.MainHero.Gold;
                if (got == 1 && spent > 0 && spent <= remainingBudget)
                {
                    bought++;
                    spentTotal += spent;
                    satisfied += item.HasHorseComponent && item.HorseComponent.IsLiveStock
                        ? Math.Max(1, item.HorseComponent.MeatCount)
                        : 1;
                }
                else
                {
                    AutopilotLog.Write("    еда: покупка 1 × " + item.Name
                                       + " НЕ подтвердилась — получено " + got + ", списано " + spent);
                    break;
                }
            }
            if (satisfied < need && stop == null)
            {
                stop = "у продавца столько нет";
            }
            if (bought > 0)
            {
                AutopilotLog.Write("    еда: КУПЛЕНО " + bought + " ед. товара за " + spentTotal);
            }
            AutopilotLog.Write("    еда: нужно было " + need + ", запас пополнен на " + satisfied
                               + (stop != null ? "; остановка: " + stop : "") + " (" + stockNote + ")");
        }

        private static int Stock(ItemRoster roster, EquipmentElement element)
        {
            int index = roster.FindIndexOfElement(element);
            return index >= 0 ? roster.GetElementNumber(index) : 0;
        }

        /// <summary>Ровно тот Town, цену которого SellItemsAction спросит перед
        /// следующей единицей. Village.GetItemPrice при TradeBound == null возвращает
        /// условную 1, но действие в этом случае использует Bound.Town.</summary>
        private static int CurrentBuyPrice(Settlement settlement, MobileParty party, EquipmentElement element)
        {
            Town town = settlement.Town;
            if (town == null && settlement.IsVillage)
            {
                Settlement priceSettlement = settlement.Village.TradeBound ?? settlement.Village.Bound;
                town = priceSettlement?.Town;
            }
            return town != null ? town.GetItemPrice(element, party, isSelling: false) : -1;
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

        private static int RecruitmentReserve(MobileParty party, TroopRoster roster)
        {
            float wage = Campaign.Current.Models.PartyWageModel.GetTotalWage(party, roster).ResultNumber;
            if (float.IsNaN(wage) || float.IsInfinity(wage) || wage < 0)
                throw new InvalidOperationException("неизвестно жалование после найма");
            return Math.Max(Reserve(party), checked((int)Math.Ceiling(wage * ServiceLimits.ReserveWageDays)));
        }

        internal static bool HasAffordableRecruits(MobileParty party, Settlement settlement)
        {
            if (party == null || settlement == null || (!settlement.IsTown && !settlement.IsVillage)
                || Hero.MainHero == null || party.Party.NumberOfAllMembers >= party.Party.PartySizeLimit)
                return false;
            // Native CanMainHeroRecruitTroops reads Settlement.CurrentSettlement, so it
            // is only safe in Recruit after arrival, not while planning on the map.
            GameModels models = Campaign.Current.Models;
            int budget = Math.Min(ServiceLimits.MaxRecruitSpendPerPass,
                Hero.MainHero.Gold - Reserve(party));
            if (budget <= 0) return false;
            foreach (Hero notable in settlement.Notables)
            {
                if (notable == null || !notable.CanHaveRecruits) continue;
                List<CharacterObject> troops = HeroHelper.GetVolunteerTroopsOfHeroForRecruitment(notable);
                for (int i = 0; i < troops.Count; i++)
                    if (troops[i] != null && HeroHelper.HeroCanRecruitFromHero(Hero.MainHero, notable, i)
                        && models.PartyWageModel.GetTroopRecruitmentCost(troops[i], Hero.MainHero).RoundedResultNumber <= budget)
                        return true;
            }
            return false;
        }

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

            var offers = new List<RecruitOffer>();
            var cart = new List<RecruitOffer>();
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
                    int cost = models.PartyWageModel.GetTroopRecruitmentCost(troop, Hero.MainHero).RoundedResultNumber;
                    if (cost > budget)
                    {
                        tooExpensive++;
                        continue;
                    }
                    offers.Add(new RecruitOffer
                    {
                        Notable = notable, Index = i, Troop = troop, Cost = cost,
                        Role = RoleOf(troop), Tier = troop.Tier
                    });
                }
            }

            int[] simulated = CurrentComposition(party);
            var projectedRoster = TroopRoster.CreateDummyTroopRoster();
            foreach (var troop in party.MemberRoster.GetTroopRoster()) projectedRoster.Add(troop);
            while (offers.Count > 0 && cart.Count < free && cart.Count < ServiceLimits.MaxRecruitsPerPass)
            {
                TroopRole needed = MostNeededRole(simulated);
                RecruitOffer best = null;
                float bestScore = float.NegativeInfinity;
                foreach (RecruitOffer offer in offers)
                {
                    if (total + offer.Cost > budget)
                    {
                        continue;
                    }
                    projectedRoster.AddToCounts(offer.Troop, 1);
                    int projectedReserve;
                    try { projectedReserve = RecruitmentReserve(party, projectedRoster); }
                    finally { projectedRoster.AddToCounts(offer.Troop, -1); }
                    if (Hero.MainHero.Gold - total - offer.Cost < projectedReserve) continue;
                    // Сначала закрываем дефицит рода войск, затем предпочитаем уровень и меньшую цену.
                    float score = (offer.Role == needed ? 100f : 0f)
                                  + offer.Tier * 2f - offer.Cost * 0.02f;
                    if (score > bestScore)
                    {
                        best = offer;
                        bestScore = score;
                    }
                }
                if (best == null)
                {
                    stop = "бюджет найма или запас на " + ServiceLimits.ReserveWageDays + " дней будущего жалования";
                    tooExpensive += offers.FindAll(offer => total + offer.Cost > budget).Count;
                    break;
                }
                cart.Add(best);
                projectedRoster.AddToCounts(best.Troop, 1);
                total += best.Cost;
                simulated[(int)best.Role]++;
                offers.Remove(best);
            }
            if (cart.Count >= free) stop = "партия заполнилась";
            else if (cart.Count >= ServiceLimits.MaxRecruitsPerPass) stop = "предел " + ServiceLimits.MaxRecruitsPerPass + " за проход";

            string summary = "добровольцев " + volunteers + ", не хватает отношений " + noRelation
                             + ", не по деньгам " + tooExpensive + (stop != null ? "; остановка: " + stop : "");
            if (cart.Count == 0)
            {
                AutopilotLog.Write("    найм: никого (" + summary + ")");
                return;
            }
            if (Hero.MainHero.Gold - RecruitmentReserve(party, projectedRoster) < total)
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
                    // Recheck before each change: recruitment callbacks can spend gold.
                    var nextRoster = TroopRoster.CreateDummyTroopRoster();
                    foreach (var troop in party.MemberRoster.GetTroopRoster()) nextRoster.Add(troop);
                    nextRoster.AddToCounts(entry.Troop, 1);
                    if (Hero.MainHero.Gold - charged - entry.Cost < RecruitmentReserve(party, nextRoster))
                    {
                        AutopilotLog.Write("    найм: остановлен — после найма не останется " + ServiceLimits.ReserveWageDays + " дней жалования");
                        break;
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

        private static TroopRole RoleOf(CharacterObject troop)
        {
            if (troop.IsMounted && troop.IsRanged) return TroopRole.HorseArcher;
            if (troop.IsMounted) return TroopRole.Cavalry;
            if (troop.IsRanged) return TroopRole.Archer;
            return TroopRole.Infantry;
        }

        private static int[] CurrentComposition(MobileParty party)
        {
            var counts = new int[4];
            foreach (TroopRosterElement element in party.MemberRoster.GetTroopRoster())
            {
                if (!element.Character.IsHero && element.Number > 0)
                {
                    counts[(int)RoleOf(element.Character)] += element.Number;
                }
            }
            return counts;
        }

        private static TroopRole MostNeededRole(int[] counts)
        {
            float[] targets =
            {
                ServiceLimits.TargetInfantry, ServiceLimits.TargetArchers,
                ServiceLimits.TargetCavalry, ServiceLimits.TargetHorseArchers
            };
            int total = counts[0] + counts[1] + counts[2] + counts[3];
            int best = 0;
            float deficit = float.NegativeInfinity;
            for (int i = 0; i < counts.Length; i++)
            {
                float current = total > 0 ? (float)counts[i] / total : 0f;
                float candidate = targets[i] - current;
                if (candidate > deficit)
                {
                    best = i;
                    deficit = candidate;
                }
            }
            return (TroopRole)best;
        }

        private static string Because(TextObject why)
        {
            string text = why?.ToString();
            return string.IsNullOrEmpty(text) ? "" : ": " + text;
        }
    }
}
