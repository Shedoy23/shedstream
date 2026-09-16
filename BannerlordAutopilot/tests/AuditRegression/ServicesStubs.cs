// Заменители движка для обслуживания партии в поселении: еда, найм, пленные.
//
// Каждый повторяет ПРОЧИТАННОЕ тело метода Bannerlord 1.4.8 (строки —
// D:\shedlink-build\bl-decomp\TaleWorlds.CampaignSystem.decompiled.cs, если не
// сказано иначе), включая неудобные места, от которых мод обязан защищаться:
// GiveGoldAction списывает не больше, чем есть; SellItemsAction не проверяет ни
// деньги, ни остаток продавца; SellPrisonersAction без покупателя отпускает героев.
//
// ЧЕГО ЗАМЕНИТЕЛИ НЕ ПОВТОРЯЮТ (требует игры): цены движка меняются с остатком и
// у деревни берутся по её торговому городу — здесь цена постоянная; FindItemToBuy
// в движке выбирает случайно с весом «дешевле — вероятнее» — здесь всегда самый
// дешёвый; события OnUnitRecruited и продажи пленных здесь только записываются,
// навыки и опыт от них не начисляются; расчёт отношений со старостой и модели
// доступа заданы флагами проверки, а не формулами.
using System;
using System.Collections.Generic;
using System.Linq;
using TaleWorlds.CampaignSystem.ComponentInterfaces;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Library;
using TaleWorlds.Localization;

namespace TaleWorlds.Core {
 public class HorseComponent { public bool IsLiveStock { get; set; } public int MeatCount { get; set; } = 1; }
 public class ItemModifier {}
 public class ItemObject {
  public string Name { get; set; }
  public bool IsFood { get; set; }
  public HorseComponent HorseComponent { get; set; }
  public bool HasHorseComponent => HorseComponent != null;               // Core 7037
  public int TestPrice;                                                  // цена единицы у продавца
  public int TestPriceIncreasePerSale;                                   // рост цены после уменьшения рынка
  public override string ToString() => Name;
 }
 public struct EquipmentElement {
  public EquipmentElement(ItemObject item, ItemModifier itemModifier = null) { Item = item; ItemModifier = itemModifier; }
  public ItemObject Item { get; private set; }
  public ItemModifier ItemModifier { get; private set; }
  public bool IsEqualTo(EquipmentElement other) => Item == other.Item && ItemModifier == other.ItemModifier;   // Core 10248
 }
 public struct ItemRosterElement {
  public ItemRosterElement(EquipmentElement equipmentElement, int amount) { EquipmentElement = equipmentElement; _amount = amount; }
  public static ItemRosterElement Invalid => default;
  public EquipmentElement EquipmentElement { get; private set; }
  private int _amount;
  // Core 9507: отрицательное количество — исключение.
  public int Amount { get => _amount; set { if (value < 0) throw new InvalidOperationException("ItemRosterElement::Amount"); _amount = value; } }
 }
}

namespace TaleWorlds.CampaignSystem {
 public interface IFaction { bool IsAtWarWith(IFaction other); }
 public class TestFaction : IFaction {
  public readonly HashSet<IFaction> Enemies = new();
  public bool IsAtWarWith(IFaction other) => other != null && Enemies.Contains(other);
 }
 public class CharacterObject {
  public string Name = "Боец"; public string StringId = "troop";
  public bool IsHero { get; set; }                                         // Core 3195
  public bool IsMounted { get; set; }
  public bool IsRanged { get; set; }
  public int Tier { get; set; } = 1;
  public Hero HeroObject;
  public int TestCost = 30;                                                // PartyWageModel.GetTroopRecruitmentCost
  public int TestRansom = 20;                                              // RansomValueCalculationModel.PrisonerRansomValue
  public override string ToString() => Name;
 }
 public struct ExplainedNumber {
  public ExplainedNumber(float value) { ResultNumber = value; }
  public float ResultNumber { get; }
  public int RoundedResultNumber => (int)Math.Round(ResultNumber);        // 42955
 }
 public class GameModels {
  public MobilePartyAIModel MobilePartyAIModel { get; } = new();
  public PartyFoodBuyingModel PartyFoodBuyingModel { get; } = new();
  public MobilePartyFoodConsumptionModel MobilePartyFoodConsumptionModel { get; } = new();
  public PartyWageModel PartyWageModel { get; } = new();
  public SettlementAccessModel SettlementAccessModel { get; } = new();
  public RansomValueCalculationModel RansomValueCalculationModel { get; } = new();
 }
}

namespace TaleWorlds.CampaignSystem.ComponentInterfaces {
 public class MobilePartyAIModel {
  public AiBehavior NextBehavior; public MobileParty NextTarget; public float NextScore;
  public void GetBestInitiativeBehavior(MobileParty party, out AiBehavior behavior, out MobileParty target, out float score, out TaleWorlds.Library.Vec2 averageEnemyVec) { behavior=NextBehavior; target=NextTarget; score=NextScore; averageEnemyVec=default; }
 }
 public class PartyFoodBuyingModel {
  public float MinimumDaysFoodToLastWhileBuyingFoodFromTown => 30f;       // DefaultPartyFoodBuyingModel 64177
  public float MinimumDaysFoodToLastWhileBuyingFoodFromVillage => 12f;    // 64178
  // 64183: еда или скот с остатком > 0; цена < 120 (скот — любая) и не дороже
  // PartyTradeGold; иначе Invalid. Движок выбирает случайно с весом, стенд — самый дешёвый.
  public void FindItemToBuy(MobileParty mobileParty, Settlement settlement, out ItemRosterElement itemRosterElement, out float itemElementsPrice) {
   itemRosterElement = ItemRosterElement.Invalid; itemElementsPrice = 0f; int best = int.MaxValue;
   for (int i = 0; i < settlement.ItemRoster.Count; i++) {
    ItemRosterElement element = settlement.ItemRoster.GetElementCopyAtIndex(i);
    if (element.Amount <= 0) continue;
    ItemObject item = element.EquipmentElement.Item;
    bool livestock = item.HasHorseComponent && item.HorseComponent.IsLiveStock;
    if (!(item.IsFood || livestock)) continue;
    int price = item.TestPrice;
    if (!(price < 120 || livestock) || mobileParty.PartyTradeGold < price) continue;
    if (price < best) { best = price; itemRosterElement = element; itemElementsPrice = price; }
   }
  }
 }
 public class MobilePartyFoodConsumptionModel { public bool DoesPartyConsumeFood(MobileParty mobileParty) => true; }   // 60231: партия игрока ест
 public class PartyWageModel {
  public ExplainedNumber GetTroopRecruitmentCost(CharacterObject troop, Hero buyerHero, bool withoutItemCost = false) => new ExplainedNumber(troop.TestCost);
 }
 public class SettlementAccessModel {
  public enum SettlementAction { RecruitTroops, Craft, JoinTournament, WatchTournament, Trade, WaitInSettlement, ManageTown, WalkAroundTheArena }
  public bool TestTrade = true, TestRecruit = true, TestTavern = true;
  public string TestReason = "закрыто проверкой";
  public bool CanMainHeroDoSettlementAction(Settlement settlement, SettlementAction settlementAction, out bool disableOption, out TextObject disabledText) {
   bool allowed = settlementAction == SettlementAction.Trade ? TestTrade : settlementAction == SettlementAction.RecruitTroops ? TestRecruit : true;
   disableOption = !allowed; disabledText = allowed ? null : new TextObject(TestReason); return allowed;
  }
  public bool CanMainHeroAccessLocation(Settlement settlement, string locationId, out bool disableOption, out TextObject disabledText) {
   bool allowed = locationId != "tavern" || TestTavern;
   disableOption = !allowed; disabledText = allowed ? null : new TextObject(TestReason); return allowed;
  }
 }
 public class RansomValueCalculationModel { public int PrisonerRansomValue(CharacterObject prisoner, Hero sellerHero = null) => prisoner.TestRansom; }
}

namespace TaleWorlds.CampaignSystem.CampaignBehaviors {
 public class PartiesBuyFoodCampaignBehavior {
  // Копия 202589-202602 — только для стенда. Мод формулу не копирует, а вызывает рефлексией.
  private int CalculateFoodCountToBuy(MobileParty mobileParty, float minimumDaysToLast) {
   if (Math.Abs(mobileParty.FoodChange) < 1E-05f) return 0;
   float num = (float)mobileParty.TotalFoodAtInventory / (0f - mobileParty.FoodChange);
   float num2 = minimumDaysToLast - num;
   if (num2 > 0f) return (int)((0f - mobileParty.FoodChange) * num2);
   return 0;
  }
 }
}

namespace TaleWorlds.CampaignSystem.Roster {
 public class ItemRoster : System.Collections.Generic.IReadOnlyList<ItemRosterElement> {
  public ItemRosterElement this[int index] => _data[index];
  public System.Collections.Generic.IEnumerator<ItemRosterElement> GetEnumerator() => _data.GetEnumerator();
  System.Collections.IEnumerator System.Collections.IEnumerable.GetEnumerator() => GetEnumerator();
  private readonly List<ItemRosterElement> _data = new();
  public int Count => _data.Count;
  public int TotalFood => _data.Where(e => e.EquipmentElement.Item != null && e.EquipmentElement.Item.IsFood).Sum(e => e.Amount);
  public ItemRosterElement GetElementCopyAtIndex(int index) => index >= 0 && index < _data.Count ? _data[index] : ItemRosterElement.Invalid;
  public int FindIndexOfElement(EquipmentElement rosterElement) { for (int i = 0; i < _data.Count; i++) if (rosterElement.IsEqualTo(_data[i].EquipmentElement)) return i; return -1; }
  public int GetElementNumber(int index) => index >= 0 && index < _data.Count ? _data[index].Amount : 0;
  // 95902: нет элемента и число < 0 — ничего (assert, −1); иначе прибавить; ≤ 0 — удалить.
  public int AddToCounts(EquipmentElement rosterElement, int number) {
   if (number == 0) return -1;
   int index = FindIndexOfElement(rosterElement);
   if (index < 0) { if (number < 0) return -1; _data.Add(new ItemRosterElement(rosterElement, 0)); index = _data.Count - 1; }
   ItemRosterElement element = _data[index]; element.Amount += number; _data[index] = element;
   if (element.Amount <= 0) { _data.RemoveAt(index); }
   return index;
  }
  public void TestAdd(ItemObject item, int number) => AddToCounts(new EquipmentElement(item), number);
  public int TestCount(ItemObject item) { int i = FindIndexOfElement(new EquipmentElement(item)); return i >= 0 ? _data[i].Amount : 0; }
 }
 public struct TroopRosterElement {
  public CharacterObject Character;
  public int Number { get; set; }
  public int WoundedNumber { get; set; }
  public int Xp { get; set; }
 }
 public class TroopRoster {
  private readonly List<TroopRosterElement> _data = new();
  public static TroopRoster CreateDummyTroopRoster() => new TroopRoster();
  public int Count => _data.Count;
  // 96439-96466: обычные — сумма Number, герой — один на элемент.
  public int TotalRegulars => _data.Where(e => !e.Character.IsHero).Sum(e => e.Number);
  public int TotalHeroes => _data.Count(e => e.Character.IsHero);
  public int TotalManCount => TotalRegulars + TotalHeroes;
  public int TotalWounded => _data.Sum(e => e.WoundedNumber);           // 96343: раненые обычные + герои
  public MBList<TroopRosterElement> GetTroopRoster() { var list = new MBList<TroopRosterElement>(); list.AddRange(_data); return list; }
  public void Add(TroopRosterElement troopRosterElement) => AddToCounts(troopRosterElement.Character, troopRosterElement.Number, false, troopRosterElement.WoundedNumber, troopRosterElement.Xp);   // 96482
  public int AddToCounts(CharacterObject character, int count, bool insertAtFront = false, int woundedCount = 0, int xpChange = 0, bool removeDepleted = true, int index = -1) {
   int i = _data.FindIndex(e => e.Character == character);
   if (i < 0) { if (count <= 0) return -1; _data.Add(new TroopRosterElement { Character = character }); i = _data.Count - 1; }
   TroopRosterElement element = _data[i];
   element.Number += count; element.WoundedNumber = Math.Max(0, element.WoundedNumber + woundedCount); element.Xp += xpChange;
   if (element.Number <= 0 && removeDepleted) { _data.RemoveAt(i); return -1; }
   _data[i] = element; return i;
  }
 }
}

namespace TaleWorlds.CampaignSystem.Actions {
 public static class GiveGoldAction {
  // 227096: у дающего героя списывается min(золото, сумма) — в минус не уходит.
  public static void ApplyBetweenCharacters(Hero giverHero, Hero recipientHero, int amount, bool disableNotification = false) {
   if (giverHero != null) { amount = Math.Min(giverHero.Gold, amount); giverHero.Gold -= amount; }
   if (recipientHero != null) recipientHero.Gold += amount;
  }
  public static void ApplyForCharacterToSettlement(Hero giverHero, Settlement settlement, int amount, bool disableNotification = false) {
   if (giverHero != null) { amount = Math.Min(giverHero.Gold, amount); giverHero.Gold -= amount; }
   settlement.TestGold += amount;
  }
 }
 public static class SellItemsAction {
  public static bool TestBroken;                                           // операция молча ничего не сделала
  // 228076: за каждую единицу — цена, продавец −1, покупатель +1; затем оплата всей суммы.
  // Ни денег покупателя, ни остатка продавца действие не проверяет.
  public static void Apply(PartyBase receiverParty, PartyBase payerParty, ItemRosterElement subject, int number, Settlement currentSettlement = null) {
   if (TestBroken) return;
   int total = 0;
   for (int i = 0; i < number; i++) {
   total += subject.EquipmentElement.Item.TestPrice;
   receiverParty.ItemRoster.AddToCounts(subject.EquipmentElement, -1);
   payerParty?.ItemRoster.AddToCounts(subject.EquipmentElement, 1);
   subject.EquipmentElement.Item.TestPrice += subject.EquipmentElement.Item.TestPriceIncreasePerSale;
   }
   GiveGoldAction.ApplyForCharacterToSettlement(payerParty.LeaderHero, receiverParty.Settlement, total);
  }
 }
 public static class SellPrisonersAction {
  public static int TestCalls;
  // 228180, покупатель null: обычные снимаются с ростера; герой отпускается за выкуп
  // (EndCaptivityAction.ApplyByRansom) и уходит из ростера; выкуп за всех — лидеру продавца.
  public static void ApplyForSelectedPrisoners(PartyBase sellerParty, PartyBase buyerParty, TroopRoster prisoners) {
   TestCalls++;
   int num = 0;
   foreach (TroopRosterElement item in prisoners.GetTroopRoster()) {
    CharacterObject character = item.Character;
    if (!character.IsHero) sellerParty.PrisonRoster.AddToCounts(character, -item.Number, false, -item.WoundedNumber);
    else if (buyerParty == null) sellerParty.PrisonRoster.AddToCounts(character, -1);
    num += item.Number * character.TestRansom;
   }
   if (num > 0 && sellerParty.IsMobile) GiveGoldAction.ApplyBetweenCharacters(null, sellerParty.LeaderHero, num);
  }
 }
}

