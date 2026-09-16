using System;
using System.Collections;
using System.Reflection;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.Library;
namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        private PlayerEncounter _lootEncounter;
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
                vm.GetType().GetMethod("ExecuteFilterNone").Invoke(vm, null);
                vm.GetType().GetMethod("ExecuteBuyAllItems").Invoke(vm, null);
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
                roster = MobileParty.MainParty.ItemRoster;
                int actual = 0;
                for (int i = 0; i < roster.Count; i++) actual = checked(actual + roster.GetElementCopyAtIndex(i).Amount);
                if (actual != right) AutopilotLog.Write("ДОБЫЧА: обработчики закрытия изменили инвентарь: до Готово " + right + ", после " + actual + ", разница " + (actual - right));
                AutopilotLog.Write("ДОБЫЧА: получено " + (right - beforeRight) + ", осталось " + left + "; экран закрыт, фактически предметов " + actual);
            }
            catch (Exception ex) { Disable("добыча: обработка остановлена после исключения: " + ex); }
            return true;
        }
    }
}
