using System;
using System.Collections;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Library;
namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        private PlayerEncounter _lootEncounter;
        private bool _postBattleRestPending;
        private Settlement _postBattleRestSettlement;
        private double _postBattleRestUntil = -1;
        private const double PostBattleRestHours = 12;

        // Only hold a native wait inside a peaceful town/castle. Travel does not
        // count; leaving interrupts the timer. Session reset gives control back.
        private bool HoldPostBattleRest(MobileParty party, Settlement settlement, bool waiting)
        {
            if (_mode != Mode.Apply || !_postBattleRestPending || settlement == null
                || (!settlement.IsTown && !settlement.IsCastle) || settlement.IsUnderSiege
                || party.CurrentSettlement != settlement || CannotStay(settlement)
                || (party.MapFaction != null && settlement.MapFaction != null
                    && party.MapFaction.IsAtWarWith(settlement.MapFaction))) return false;
            if (!waiting) return true;
            double now = CampaignTime.Now.ToHours;
            if (_postBattleRestSettlement != settlement || _postBattleRestUntil < 0)
            {
                _postBattleRestSettlement = settlement;
                _postBattleRestUntil = now + PostBattleRestHours;
                AutopilotLog.Write("ОТДЫХ: после боя ждём в «" + settlement.Name + "» 12 игровых часов");
                Thoughts.Say("rest", settlement.StringId, settlement.Name);
            }
            if (now >= _postBattleRestUntil)
            {
                _postBattleRestPending = false;
                _postBattleRestSettlement = null;
                _postBattleRestUntil = -1;
                _hoursSinceThink = ThinkPeriodHours;
                AutopilotLog.Write("ОТДЫХ: 12 игровых часов прошли, обычный выбор целей возобновлён");
                return false;
            }
            _hasPendingDecision = false;
            return true;
        }
        private static object LootRoster(object logic, string side)
        {
            var method = logic.GetType().GetMethod("GetElementsInRoster");
            object value = Enum.Parse(method.GetParameters()[0].ParameterType, side);
            return method.Invoke(logic, new[] { value });
        }
        private static int LootCount(object logic, string side)
        {
            int count = 0;
            foreach (object element in (IEnumerable)LootRoster(logic, side))
                count = checked(count + Convert.ToInt32(ReadScreenMember(element, "Amount")));
            return count;
        }
        /// <summary>Порог, с которого добыча интереснее как опыт отряда, чем как
        /// деньги. Решение владельца 22.09: миллион динаров.</summary>
        private const int LootDonationGoldThreshold = 1000000;

        /// <summary>Стоит ли оставить снаряжение движку в опыт отряда.
        ///
        /// Оба числа берём У ИГРЫ, а не считаем сами: `XpGainFromDonations` —
        /// её собственная оценка опыта за НЕдобранное (ноль, если нет перков
        /// `Steward.GivingHands` / `Steward.PaidInPromise`), а
        /// `_donationMaxShareableXp` — сколько отряд вообще способен принять
        /// (сумма недостающего бойцам до апгрейдов). Опыт сверх потолка
        /// сгорает, поэтому при нулевом потолке добычу надо ЗАБРАТЬ и продать.
        /// Разбор механики: docs/BANNERLORD_TROOP_XP_2026-09-22.md.</summary>
        private static bool ShouldDonateLoot(object vm, object logic, out string reason)
        {
            reason = null;
            try
            {
                int gold = Hero.MainHero != null ? Hero.MainHero.Gold : 0;
                if (gold < LootDonationGoldThreshold)
                { reason = "денег " + gold + " < порога " + LootDonationGoldThreshold; return false; }

                object xpValue = ReadScreenMember(logic, "XpGainFromDonations");
                int xp = xpValue == null ? 0 : (int)Convert.ToSingle(xpValue);
                if (xp <= 0)
                { reason = "игра оценивает недобранное в 0 опыта — нет перков интенданта"; return false; }

                var field = vm.GetType().GetField("_donationMaxShareableXp",
                    BindingFlags.NonPublic | BindingFlags.Instance);
                if (field == null)
                { reason = "потолок опыта отряда недоступен"; return false; }
                int room = Convert.ToInt32(field.GetValue(vm));
                if (room <= 0)
                { reason = "отряду некуда расти, опыт сгорит"; return false; }

                reason = "опыта за недобранное " + xp + ", отряд примет " + Math.Min(xp, room);
                return true;
            }
            catch (Exception ex) { reason = "проверка не удалась: " + ex.GetType().Name; return false; }
        }

        private bool PollLootScreen()
        {
            if (_mode != Mode.Apply || _lootEncounter == null) return false;
            if (PlayerEncounter.Current != _lootEncounter) { _lootEncounter = null; return false; }
            var states = Game.Current?.GameStateManager;
            object state = states?.ActiveState;
            if (state?.GetType().FullName != "TaleWorlds.CampaignSystem.GameState.InventoryState"
                || ReadScreenMember(state, "InventoryMode")?.ToString() != "Loot") return false;
            if (states.ActiveStateDisabledByUser || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                object screen = ReadScreenMember(state, "Handler");
                if (screen?.GetType().FullName != "SandBox.GauntletUI.GauntletInventoryScreen") return true;
                object vm = screen.GetType().GetField("_dataSource", BindingFlags.NonPublic | BindingFlags.Instance)?.GetValue(screen);
                if (vm == null) return true;
                if (vm.GetType().FullName != "TaleWorlds.CampaignSystem.ViewModelCollection.Inventory.SPInventoryVM") return true;
                object logic = ReadScreenMember(state, "InventoryLogic");
                if (logic == null || !ReferenceEquals(logic, vm.GetType().GetField("_inventoryLogic", BindingFlags.NonPublic | BindingFlags.Instance)?.GetValue(vm))
                    || !(ReadScreenMember(logic, "IsTrading") is false) || Convert.ToInt32(ReadScreenMember(logic, "TotalAmount")) != 0)
                { Disable("добыча: неподходящий инвентарь"); return true; }
                var roster = MobileParty.MainParty.ItemRoster;
                // Native InitializeRosters uses this exact roster, not a staging copy.
                if (!ReferenceEquals(LootRoster(logic, "PlayerInventory"), roster))
                { Disable("добыча: экран не связан с фактическим инвентарём партии"); return true; }
                // Consume authorization before native callbacks: no repeat after an uncertain effect.
                var encounter = _lootEncounter;
                _lootEncounter = null;
                int beforeLeft = LootCount(logic, "OtherInventory"), beforeRight = LootCount(logic, "PlayerInventory");
                vm.GetType().GetProperty("LeftSearchText").SetValue(vm, string.Empty);
                string donateWhy;
                bool donate = ShouldDonateLoot(vm, logic, out donateWhy);
                if (donate)
                {
                    // Забираем только то, за что опыта не платят: коней и припасы.
                    // Оружие и броня остаются движку — он превратит их в опыт
                    // бойцов (75-300 за предмет по тиру). Фильтр обязателен:
                    // ванильный TransferAll пропускает отфильтрованное.
                    foreach (string filter in new[] { "ExecuteFilterMounts", "ExecuteFilterMisc" })
                    {
                        var apply = vm.GetType().GetMethod(filter);
                        if (apply == null)
                        { Disable("добыча: фильтр " + filter + " недоступен"); return true; }
                        apply.Invoke(vm, null);
                        vm.GetType().GetMethod("ExecuteBuyAllItems").Invoke(vm, null);
                    }
                    vm.GetType().GetMethod("ExecuteFilterNone").Invoke(vm, null);
                    AutopilotLog.Write("ДОБЫЧА: снаряжение оставлено в опыт отряда (" + donateWhy + ")");
                }
                else
                {
                    vm.GetType().GetMethod("ExecuteFilterNone").Invoke(vm, null);
                    vm.GetType().GetMethod("ExecuteBuyAllItems").Invoke(vm, null);
                }
                int left = LootCount(logic, "OtherInventory"), right = LootCount(logic, "PlayerInventory");
                if (left > beforeLeft || right - beforeRight != beforeLeft - left || Convert.ToInt32(ReadScreenMember(logic, "TotalAmount")) != 0)
                { Disable("добыча: перенос не подтвердился, повторять не буду"); return true; }
                if (InformationManager.IsAnyInquiryActive() || !ReferenceEquals(states.ActiveState, state) || PlayerEncounter.Current != encounter)
                { Disable("добыча: состояние изменилось при переносе"); return true; }
                int transferredActual = 0;
                for (int i = 0; i < roster.Count; i++) transferredActual = checked(transferredActual + roster.GetElementCopyAtIndex(i).Amount);
                if (transferredActual != right)
                { Disable("добыча: перенос в инвентарь не подтверждён; ожидалось " + right + ", фактически " + transferredActual); return true; }
                // DoneLogic dispatches inventory events. Their changes are not failed transfers.
                InquiryData ownQuery = null; int queries = 0;
                Action<InquiryData, bool, bool> capture = (data, pause, prioritize) => { ownQuery = data; queries++; };
                InformationManager.OnShowInquiry += capture;
                try { vm.GetType().GetMethod("ExecuteCompleteTranstactions").Invoke(vm, null); }
                finally { InformationManager.OnShowInquiry -= capture; }
                if (queries > 0)
                {
                    Action accept = ownQuery?.AffirmativeAction;
                    if (queries != 1 || ownQuery.IsAffirmativeOptionShown != true || accept?.Target != vm
                        || accept.Method.Name != "HandleDone" || accept.Method.DeclaringType != vm.GetType()
                        || !ReferenceEquals(states.ActiveState, state) || PlayerEncounter.Current != encounter)
                    { Disable("добыча: неизвестное подтверждение — требуется игрок"); return true; }
                    InformationManager.HideInquiry();
                    accept();
                }
                if (ReferenceEquals(states.ActiveState, state) || InformationManager.IsAnyInquiryActive())
                { Disable("добыча: завершение не подтверждено"); return true; }
                _postBattleRestPending = true;
                _postBattleRestSettlement = null;
                _postBattleRestUntil = -1;
                roster = MobileParty.MainParty.ItemRoster;
                int actual = 0;
                for (int i = 0; i < roster.Count; i++) actual = checked(actual + roster.GetElementCopyAtIndex(i).Amount);
                if (actual != right) AutopilotLog.Write("ДОБЫЧА: обработчики закрытия изменили инвентарь: до Готово " + right + ", после " + actual + ", разница " + (actual - right));
                AutopilotLog.Write("ДОБЫЧА: получено " + (right - beforeRight) + ", осталось " + left + "; экран закрыт, фактически предметов " + actual);
                EquipmentAndTrade.Equip(MobileParty.MainParty);
            }
            catch (Exception ex) { Disable("добыча: обработка остановлена после исключения: " + ex); }
            return true;
        }
    }
}
