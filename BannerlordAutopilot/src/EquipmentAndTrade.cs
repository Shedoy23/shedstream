using System;
using System.Collections.Generic;
using Helpers;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.ComponentInterfaces;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;

namespace BannerlordAutopilot
{
    internal static class EquipmentAndTrade
    {
        // Only the player's battle loadout. Never iterate companion equipment.
        internal static void Equip(MobileParty party)
        {
            Hero hero = Hero.MainHero;
            if (party == null || party != MobileParty.MainParty || hero == null
                || !hero.IsAlive || hero.IsPrisoner || !hero.CanHeroEquipmentBeChanged()) return;
            HashSet<string> locks = InventoryLocks();
            if (locks == null) return;
            Equipment equipment = hero.BattleEquipment;
            for (int i = 0; i <= (int)EquipmentIndex.HorseHarness; i++)
            {
                if (i == (int)EquipmentIndex.ExtraWeaponSlot) continue;
                EquipmentIndex slot = (EquipmentIndex)i;
                EquipmentElement old = equipment[slot];
                if (!old.IsEmpty && Protected(old, locks)) continue;
                EquipmentElement best = old;
                long score = Score(old, slot);
                for (int j = 0; j < party.ItemRoster.Count; j++)
                {
                    ItemRosterElement entry = party.ItemRoster.GetElementCopyAtIndex(j);
                    EquipmentElement candidate = entry.EquipmentElement;
                    if (entry.Amount <= 0 || candidate.IsEmpty || Protected(candidate, locks)
                        || !Fits(candidate, old, slot, equipment)
                        || !CharacterHelper.CanUseItem(hero.CharacterObject, candidate)) continue;
                    long next = Score(candidate, slot);
                    if (next > score) { best = candidate; score = next; }
                }
                if (best.IsEqualTo(old)) continue;
                int beforeNew = Stock(party.ItemRoster, best);
                int beforeOld = old.IsEmpty ? 0 : Stock(party.ItemRoster, old);
                party.ItemRoster.AddToCounts(best, -1);
                equipment[slot] = best;
                if (!old.IsEmpty) party.ItemRoster.AddToCounts(old, 1);
                if (!equipment[slot].IsEqualTo(best) || Stock(party.ItemRoster, best) != beforeNew - 1
                    || (!old.IsEmpty && Stock(party.ItemRoster, old) != beforeOld + 1))
                    throw new InvalidOperationException("экипировка: замена не подтверждена, слот " + slot);
                AutopilotLog.Write("ЭКИПИРОВКА: главный герой, " + slot + ": "
                    + (old.IsEmpty ? "пусто" : old.Item.Name.ToString()) + " → " + best.Item.Name);
            }
        }

        private static bool Fits(EquipmentElement candidate, EquipmentElement old, EquipmentIndex slot, Equipment equipment)
        {
            ItemObject.ItemTypeEnum type = candidate.Item.ItemType;
            switch (slot)
            {
                case EquipmentIndex.Head: return type == ItemObject.ItemTypeEnum.HeadArmor;
                case EquipmentIndex.Body: return type == ItemObject.ItemTypeEnum.BodyArmor;
                case EquipmentIndex.Leg: return type == ItemObject.ItemTypeEnum.LegArmor;
                case EquipmentIndex.Gloves: return type == ItemObject.ItemTypeEnum.HandArmor;
                case EquipmentIndex.Cape: return type == ItemObject.ItemTypeEnum.Cape;
                case EquipmentIndex.Horse:
                    if (type != ItemObject.ItemTypeEnum.Horse || candidate.Item.HorseComponent == null
                        || candidate.Item.HorseComponent.IsLiveStock) return false;
                    EquipmentElement harness = equipment[EquipmentIndex.HorseHarness];
                    return harness.IsEmpty || harness.Item.ArmorComponent?.FamilyType == candidate.Item.HorseComponent.Monster?.FamilyType;
                case EquipmentIndex.HorseHarness:
                    EquipmentElement horse = equipment[EquipmentIndex.Horse];
                    return type == ItemObject.ItemTypeEnum.HorseHarness && !horse.IsEmpty
                        && candidate.Item.ArmorComponent != null && horse.Item.HorseComponent?.Monster != null
                        && candidate.Item.ArmorComponent.FamilyType == horse.Item.HorseComponent.Monster.FamilyType;
                default:
                    // Preserve existing weapon roles and usage (mounted/couched variants included).
                    // Empty weapon slots are deliberately not assigned an arbitrary weapon.
                    return !old.IsEmpty && type == old.Item.ItemType
                        && candidate.Item.PrimaryWeapon?.ItemUsage == old.Item.PrimaryWeapon?.ItemUsage;
            }
        }

        private static long Score(EquipmentElement element, EquipmentIndex slot)
        {
            if (element.IsEmpty) return -1;
            if (slot == EquipmentIndex.HorseHarness) return element.GetModifiedMountBodyArmor();
            if (slot >= EquipmentIndex.Head && slot <= EquipmentIndex.Cape)
                return (long)element.GetModifiedHeadArmor() + element.GetModifiedBodyArmor()
                    + element.GetModifiedArmArmor() + element.GetModifiedLegArmor();
            return element.ItemValue;
        }

        /// <summary>26.09, владелец: «как научить его не быть перегруженным постоянно, он
        /// такой медленный». Еда не продавалась вовсе: после боёв с бандитами её запас
        /// дорос до 460 дней, вес 41–47 тыс. при грузоподъёмности 9 тыс., и разгрузка
        /// ходила по кругу, продавая пару вещей. Держим запас на столько дней, лишнее
        /// продаём (для похода нужно 7 — PreparationNeeded).</summary>
        internal const float FoodKeepDays = 20f;

        internal static int FoodSurplus(MobileParty party)
        {
            float perDay = -party.FoodChange;
            if (float.IsNaN(perDay) || float.IsInfinity(perDay) || perDay <= 0) return 0;
            int keep = (int)Math.Ceiling(perDay * FoodKeepDays);
            return Math.Max(0, party.ItemRoster.TotalFood - keep);
        }

        private static bool SellableFood(EquipmentElement element, HashSet<string> locks) => element.Item.IsFood
            && !element.IsQuestItem && !element.Item.NotMerchandise
            && !locks.Contains(element.Item.StringId + (element.ItemModifier?.StringId ?? ""));

        internal static void Sell(MobileParty party, Settlement settlement)
        {
            if (party == null || party != MobileParty.MainParty || Hero.MainHero == null
                || Hero.MainHero.IsPrisoner || settlement == null || (!settlement.IsTown && !settlement.IsVillage)
                || settlement.MapFaction == null || party.MapFaction == null
                || settlement.MapFaction.IsAtWarWith(party.MapFaction)) return;
            if (!Campaign.Current.Models.SettlementAccessModel.CanMainHeroDoSettlementAction(settlement,
                SettlementAccessModel.SettlementAction.Trade, out bool disabled, out _) || disabled) return;
            HashSet<string> locks = InventoryLocks();
            if (locks == null) return;
            Town town = settlement.IsTown ? settlement.Town
                : (settlement.Village.TradeBound ?? settlement.Village.Bound)?.Town;
            if (town == null) return;
            var stock = new List<ItemRosterElement>();
            for (int i = 0; i < party.ItemRoster.Count; i++) stock.Add(party.ItemRoster.GetElementCopyAtIndex(i));
            int sold = 0; long earned = 0; int unpaid = 0;
            foreach (ItemRosterElement entry in stock)
            {
                EquipmentElement element = entry.EquipmentElement;
                if (element.IsEmpty || Protected(element, locks)) continue;
                for (int i = 0; i < entry.Amount; i++)
                {
                    int before = Stock(party.ItemRoster, element);
                    if (before <= 0) break;
                    // Native sale clamps payment AFTER moving items. Prevent underpayment beforehand.
                    int price = town.GetItemPrice(element, party, true);
                    if (price <= 0 || settlement.SettlementComponent.Gold < price
                        || Hero.MainHero.Gold > int.MaxValue - price) { unpaid += before; break; }
                    int market = Stock(settlement.ItemRoster, element);
                    int gold = Hero.MainHero.Gold;
                    SellItemsAction.Apply(party.Party, settlement.Party, new ItemRosterElement(element, 1), 1);
                    if (Stock(party.ItemRoster, element) != before - 1
                        || Stock(settlement.ItemRoster, element) != market + 1 || Hero.MainHero.Gold != gold + price)
                        throw new InvalidOperationException("продажа: передача/оплата не подтверждена для " + element.Item.Name);
                    sold++; earned += price;
                }
            }
            // Лишняя еда: по одной штуке с самого большого вида — разнообразие еды
            // (бонус к боевому духу) сохраняется, пока лишнее не кончится.
            int surplus = FoodSurplus(party), foodSold = 0;
            while (surplus > 0)
            {
                int pick = -1, most = 0;
                for (int i = 0; i < party.ItemRoster.Count; i++)
                {
                    ItemRosterElement entry = party.ItemRoster.GetElementCopyAtIndex(i);
                    if (entry.Amount > most && !entry.EquipmentElement.IsEmpty && SellableFood(entry.EquipmentElement, locks))
                    { pick = i; most = entry.Amount; }
                }
                if (pick < 0) break;
                EquipmentElement food = party.ItemRoster.GetElementCopyAtIndex(pick).EquipmentElement;
                int price = town.GetItemPrice(food, party, true);
                if (price <= 0 || settlement.SettlementComponent.Gold < price || Hero.MainHero.Gold > int.MaxValue - price)
                { unpaid += surplus; break; }
                int before = Stock(party.ItemRoster, food), market = Stock(settlement.ItemRoster, food), gold = Hero.MainHero.Gold;
                SellItemsAction.Apply(party.Party, settlement.Party, new ItemRosterElement(food, 1), 1);
                if (Stock(party.ItemRoster, food) != before - 1
                    || Stock(settlement.ItemRoster, food) != market + 1 || Hero.MainHero.Gold != gold + price)
                    throw new InvalidOperationException("продажа еды: передача/оплата не подтверждена для " + food.Item.Name);
                surplus--; foodSold++; sold++; earned += price;
            }
            AutopilotLog.Write("ПРОДАЖА: вещей " + sold + " (из них лишней еды " + foodSold + "), получено " + earned
                + " динаров; осталось без полной оплаты " + unpaid + "; еды оставлено на " + FoodKeepDays.ToString("F0")
                + " дней, закреплённые и квестовые сохранены");
        }

        internal static Settlement FindUnloadingTown(MobileParty party, Func<Settlement, bool> eligible)
        {
            // A small margin avoids leaving the next loot screen with no room for one item.
            float weight = party.TotalWeightCarried;
            if (float.IsNaN(weight) || float.IsInfinity(weight) || weight <= 0
                || weight < party.InventoryCapacity * 0.95f) return null;
            HashSet<string> locks = InventoryLocks();
            if (locks == null) return null;
            Settlement nearest = null;
            float distance = float.MaxValue;
            foreach (Settlement town in Settlement.All)
            {
                if (!town.IsTown || town.IsUnderSiege || town.MapFaction == null || party.MapFaction == null
                    || party.MapFaction.IsAtWarWith(town.MapFaction) || !eligible(town)
                    || !Campaign.Current.Models.SettlementAccessModel.CanMainHeroDoSettlementAction(town,
                        SettlementAccessModel.SettlementAction.Trade, out bool disabled, out _) || disabled) continue;
                float next = party.Position.DistanceSquared(town.Position);
                if (next >= distance) continue;
                bool canSell = false;
                bool foodSurplus = FoodSurplus(party) > 0;
                for (int i = 0; i < party.ItemRoster.Count; i++)
                {
                    ItemRosterElement entry = party.ItemRoster.GetElementCopyAtIndex(i);
                    if (entry.Amount <= 0 || entry.EquipmentElement.IsEmpty) continue;
                    if (Protected(entry.EquipmentElement, locks)
                        && !(foodSurplus && SellableFood(entry.EquipmentElement, locks))) continue;
                    int price = town.Town.GetItemPrice(entry.EquipmentElement, party, true);
                    if (price > 0 && price <= town.SettlementComponent.Gold) { canSell = true; break; }
                }
                if (canSell) { nearest = town; distance = next; }
            }
            return nearest;
        }

        private static HashSet<string> InventoryLocks()
        {
            var tracker = Campaign.Current?.GetCampaignBehavior<IViewDataTracker>();
            if (tracker == null)
            {
                AutopilotLog.Write("ИНВЕНТАРЬ: нет данных о закреплённых вещах, подбор/продажа пропущены");
                return null;
            }
            return new HashSet<string>(tracker.GetInventoryLocks(), StringComparer.Ordinal);
        }

        private static bool Protected(EquipmentElement element, HashSet<string> locks) => element.Item.IsFood
            || element.IsQuestItem || element.Item.NotMerchandise
            || locks.Contains(element.Item.StringId + (element.ItemModifier?.StringId ?? ""));

        private static int Stock(ItemRoster roster, EquipmentElement element)
        {
            int index = roster.FindIndexOfElement(element);
            return index < 0 ? 0 : roster.GetElementNumber(index);
        }
    }
}
