using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Roster;
using TaleWorlds.Core;
namespace BannerlordAutopilot
{
    internal static class TroopUpgrades
    {
        internal static void Run(MobileParty party)
        {
            if (party == null || party != MobileParty.MainParty || Hero.MainHero == null || !Hero.MainHero.IsAlive || Hero.MainHero.IsPrisoner
                || party.MapEvent != null || party.SiegeEvent != null) return;
            var tracker = Campaign.Current.GetCampaignBehavior<IViewDataTracker>();
            if (tracker == null) return;
            var locks = new HashSet<string>(tracker.GetInventoryLocks(), StringComparer.Ordinal);
            object settings = MassUpgradeSettings();
            var roster = party.MemberRoster;
            var snapshot = roster.GetTroopRoster().ToArray();
            foreach (var original in snapshot)
            {
                var source = original.Character;
                if (source == null || source.IsHero || source.UpgradeTargets == null) continue;
                int upgraded = 0;
                for (int n = 0; n < original.Number; n++)
                {
                    int index = roster.FindIndexOfTroop(source);
                    if (index < 0) break;
                    var current = roster.GetElementCopyAtIndex(index);
                    int chosen = -1, best = int.MinValue;
                    EquipmentElement consumed = default;
                    for (int i = 0; i < source.UpgradeTargets.Length; i++)
                    {
                        var target = source.UpgradeTargets[i];
                        if (target == null || target.IsHero || target == source
                            || !Campaign.Current.Models.PartyTroopUpgradeModel.CanPartyUpgradeTroopToTarget(party.Party, source, target)) continue;
                        int xp = source.GetUpgradeXpCost(party.Party, i);
                        int price = source.GetUpgradeGoldCost(party.Party, i);
                        if (xp <= 0 || price < 0 || current.Xp < xp || Hero.MainHero.Gold < price) continue;
                        EquipmentElement horse = RequiredItem(party, target, locks);
                        if (target.UpgradeRequiresItemFromCategory != null && horse.IsEmpty) continue;
                        var future = TroopRoster.CreateDummyTroopRoster();
                        foreach (var entry in roster.GetTroopRoster()) future.Add(entry);
                        int wounded = current.Number == current.WoundedNumber ? 1 : 0;
                        future.AddToCounts(source, -1, false, -wounded);
                        future.AddToCounts(target, 1, false, wounded);
                        float wage = Campaign.Current.Models.PartyWageModel.GetTotalWage(party, future).ResultNumber;
                        if (float.IsNaN(wage) || float.IsInfinity(wage) || wage < 0)
                            throw new InvalidOperationException("улучшение: неизвестно будущее жалование");
                        double reserve = Math.Max(ServiceLimits.MinGoldReserve, Math.Ceiling(wage * ServiceLimits.ReserveWageDays));
                        if (Hero.MainHero.Gold - price < reserve) continue;
                        int priority = Score(target.DefaultFormationClass, settings);
                        if (priority > best) { best = priority; chosen = i; consumed = horse; }
                    }
                    if (chosen < 0) break;
                    var next = source.UpgradeTargets[chosen];
                    int xpCost = source.GetUpgradeXpCost(party.Party, chosen);
                    int goldCost = source.GetUpgradeGoldCost(party.Party, chosen);
                    int goldBefore = Hero.MainHero.Gold, countBefore = roster.TotalManCount, woundedBefore = roster.TotalWounded;
                    int nextIndex = roster.FindIndexOfTroop(next);
                    int nextCount = nextIndex < 0 ? 0 : roster.GetElementCopyAtIndex(nextIndex).Number;
                    int horseCount = consumed.IsEmpty ? 0 : ItemCount(party, consumed);
                    int woundedUpgrade = current.Number == current.WoundedNumber ? 1 : 0;
                    // Native PartyScreenLogic.UpgradeTroop bookkeeping, one troop at a time.
                    roster.SetElementXp(index, current.Xp - xpCost);
                    if (!consumed.IsEmpty) party.ItemRoster.AddToCounts(consumed, -1);
                    roster.AddToCounts(source, -1, false, -woundedUpgrade);
                    roster.AddToCounts(next, 1, false, woundedUpgrade);
                    GiveGoldAction.ApplyBetweenCharacters(Hero.MainHero, null, goldCost, true);
                    int remainingIndex = roster.FindIndexOfTroop(source);
                    int actualNext = roster.FindIndexOfTroop(next);
                    string mismatch = null;
                    if (roster.TotalManCount != countBefore)
                        mismatch = "бойцов было " + countBefore + ", стало " + roster.TotalManCount;
                    else if (roster.TotalWounded != woundedBefore)
                        mismatch = "раненых было " + woundedBefore + ", стало " + roster.TotalWounded;
                    else if (Hero.MainHero.Gold != goldBefore - goldCost)
                        mismatch = "золото было " + goldBefore + ", ждали " + (goldBefore - goldCost) + ", стало " + Hero.MainHero.Gold;
                    else if (actualNext < 0)
                        mismatch = "в отряде не появился «" + next.Name + "»";
                    else if (roster.GetElementCopyAtIndex(actualNext).Number != nextCount + 1)
                        mismatch = "«" + next.Name + "» было " + nextCount + ", ждали " + (nextCount + 1)
                                   + ", стало " + roster.GetElementCopyAtIndex(actualNext).Number;
                    else if (current.Number > 1 && remainingIndex < 0)
                        mismatch = "остаток «" + source.Name + "» пропал, а было " + current.Number;
                    else if (current.Number > 1 && roster.GetElementXp(remainingIndex) != current.Xp - xpCost)
                        mismatch = "опыт остатка был " + current.Xp + ", ждали " + (current.Xp - xpCost)
                                   + ", стал " + roster.GetElementXp(remainingIndex);
                    else if (current.Number > 1 && roster.GetElementCopyAtIndex(remainingIndex).Number != current.Number - 1)
                        mismatch = "остаток «" + source.Name + "» был " + current.Number + ", ждали " + (current.Number - 1)
                                   + ", стал " + roster.GetElementCopyAtIndex(remainingIndex).Number;
                    else if (!consumed.IsEmpty && ItemCount(party, consumed) != horseCount - 1)
                        mismatch = "«" + consumed.Item.Name + "» было " + horseCount + ", ждали " + (horseCount - 1)
                                   + ", стало " + ItemCount(party, consumed);
                    if (mismatch != null)
                    {
                        // Проверка стоит ПОСЛЕ обмена: выключать автопилот поздно — это ничего
                        // не возвращает, зато игра остаётся стоять на открытом экране. 21.09 так
                        // потерян «Замок Флинтолг»: обслуживание упало в 21:18, и до 21:32
                        // никто не играл. Останавливаем только прокачку этого захода и
                        // называем числа, чтобы следующий случай не расследовать заново.
                        AutopilotLog.Write("ПРОКАЧКА ОСТАНОВЛЕНА: «" + source.Name + "» → «" + next.Name
                            + "» не подтверждено: " + mismatch + "; опыт " + xpCost + ", цена " + goldCost
                            + (consumed.IsEmpty ? "" : ", предмет " + consumed.Item.Name)
                            + ". Остальные улучшения в этот заход пропущены.");
                        return;
                    }
                    // Native player event awards leadership XP and notifies campaign subscribers.
                    CampaignEventDispatcher.Instance.OnPlayerUpgradedTroops(source, next, 1);
                    upgraded++;
                    AutopilotLog.Write("ПРОКАЧКА: " + source.Name + " → " + next.Name + "; опыт " + xpCost
                        + ", цена " + goldCost + (consumed.IsEmpty ? "" : ", использован " + consumed.Item.Name));
                }
                if (upgraded > 0) AutopilotLog.Write("ПРОКАЧКА: улучшено бойцов из «" + source.Name + "»: " + upgraded);
            }
        }

        private static int ItemCount(MobileParty party, EquipmentElement item)
        {
            int index = party.ItemRoster.FindIndexOfElement(item);
            return index < 0 ? 0 : party.ItemRoster.GetElementNumber(index);
        }

        private static EquipmentElement RequiredItem(MobileParty party, CharacterObject target, HashSet<string> locks)
        {
            EquipmentElement best = default;
            if (target.UpgradeRequiresItemFromCategory == null) return best;
            foreach (var entry in party.ItemRoster)
            {
                var item = entry.EquipmentElement;
                if (entry.Amount <= 0 || item.IsEmpty || item.IsQuestItem || item.Item.IsFood || item.Item.NotMerchandise
                    || item.Item.ItemCategory != target.UpgradeRequiresItemFromCategory
                    || locks.Contains(item.Item.StringId + (item.ItemModifier?.StringId ?? ""))) continue;
                if (best.IsEmpty || item.ItemValue < best.ItemValue) best = item;
            }
            return best;
        }

        private static object MassUpgradeSettings()
        {
            try
            {
                var type = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType("MassUpgrade.Settings", false)).FirstOrDefault(t => t != null);
                return type?.GetProperty("Instance", BindingFlags.Public | BindingFlags.Static | BindingFlags.FlattenHierarchy)?.GetValue(null);
            }
            catch { return null; } // Optional integration: fallback to the owner's saved priorities below.
        }

        private static int Score(FormationClass formation, object settings)
        {
            try
            {
                object score = settings?.GetType().GetMethod("ScoreOf", new[] { typeof(FormationClass) })?.Invoke(settings, new object[] { formation });
                if (score is int value) return value;
            }
            catch { } // Mass Upgrade is not required to run the autopilot.
            switch (formation)
            {
                case FormationClass.Ranged: return 80;
                case FormationClass.HorseArcher: return 70;
                case FormationClass.HeavyCavalry: return 60;
                case FormationClass.LightCavalry: return 40;
                case FormationClass.Skirmisher: return 30;
                case FormationClass.HeavyInfantry: return 20;
                case FormationClass.Cavalry: return 18;
                case FormationClass.Infantry: return 10;
                default: return 0;
            }
        }
    }
}
