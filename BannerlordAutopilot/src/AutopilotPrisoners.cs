using System;
using System.Collections;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.Core;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        private PlayerEncounter _prisonerEncounter;
        private object _prisonerView;
        private bool _prisonerDoneRequested;

        internal void AuthorizePrisonerScreen()
        {
            if (_mode != Mode.Apply) return;
            _prisonerEncounter = PlayerEncounter.Current;
            _prisonerView = null;
            _prisonerDoneRequested = false;
        }

        private void ResetPrisonerScreen()
        {
            _prisonerEncounter = null;
            _prisonerView = null;
            _prisonerDoneRequested = false;
        }

        private static object ReadScreenMember(object target, string name)
        {
            if (target == null) return null;
            Type type = target.GetType();
            return type.GetProperty(name, BindingFlags.Instance | BindingFlags.Public)?.GetValue(target)
                ?? type.GetField(name, BindingFlags.Instance | BindingFlags.Public)?.GetValue(target);
        }

        private bool PollPrisonerScreen()
        {
            if (_mode != Mode.Apply || _prisonerEncounter == null) return false;
            if (PlayerEncounter.Current != _prisonerEncounter) { ResetPrisonerScreen(); return false; }
            var states = Game.Current?.GameStateManager;
            object state = states?.ActiveState;
            if (state?.GetType().FullName != "TaleWorlds.CampaignSystem.GameState.PartyState"
                || ReadScreenMember(state, "PartyScreenMode")?.ToString() != "Loot") return false;
            if (states.ActiveStateDisabledByUser || InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                object screen = ReadScreenMember(state, "Handler");
                if (screen?.GetType().FullName != "SandBox.GauntletUI.GauntletPartyScreen") return true;
                object vm = screen.GetType().GetField("_dataSource", BindingFlags.NonPublic | BindingFlags.Instance)?.GetValue(screen);
                if (vm == null) return true; // Native OnReady has not built the view yet.
                if (vm.GetType().FullName != "TaleWorlds.CampaignSystem.ViewModelCollection.Party.PartyVM") return true;
                object logic = ReadScreenMember(vm, "PartyScreenLogic");
                if (logic == null || !ReferenceEquals(logic, ReadScreenMember(state, "PartyScreenLogic"))
                    || !ReferenceEquals(ReadScreenMember(logic, "RightOwnerParty"), PartyBase.MainParty)) return false;
                if (ReadScreenMember(vm, "IsAnyPopUpOpen") is true) return true;
                if (_prisonerView != null && !ReferenceEquals(_prisonerView, vm))
                {
                    Disable("пленные: экран сменился во время обработки"); return true;
                }
                _prisonerView = vm;
                if (_prisonerDoneRequested) return true;
                object roster = ReadScreenMember(ReadScreenMember(logic, "CurrentData"), "RightPrisonerRoster");
                int before = Convert.ToInt32(ReadScreenMember(roster, "TotalManCount"));
                int limit = Convert.ToInt32(ReadScreenMember(logic, "RightPartyPrisonersSizeLimit"));
                int free = Math.Max(0, limit - before);
                var prisoners = ReadScreenMember(vm, "OtherPartyPrisoners") as IEnumerable;
                if (prisoners == null) throw new InvalidOperationException("список пленных отсутствует");
                if (free > 0) foreach (object prisoner in prisoners)
                {
                    if (!(ReadScreenMember(prisoner, "IsTroopTransferrable") is true)) continue;
                    object side = ReadScreenMember(prisoner, "Side");
                    if (side?.ToString() != "Left") continue;
                    int count = Math.Min(free, Convert.ToInt32(ReadScreenMember(ReadScreenMember(prisoner, "Troop"), "Number")));
                    if (count <= 0) continue;
                    // The same callback as the transfer arrow, including wounded troops
                    // and engine eligibility checks. One stack per poll, then read again.
                    vm.GetType().GetMethod("OnTransferTroop", BindingFlags.NonPublic | BindingFlags.Instance)
                        .Invoke(vm, new[] { prisoner, (object)(-1), count, side });
                    vm.GetType().GetMethod("ExecuteRemoveZeroCounts").Invoke(vm, null);
                    int after = Convert.ToInt32(ReadScreenMember(roster, "TotalManCount"));
                    if (after != before + count) Disable("пленные: перенос не подтвердился, повторять не буду");
                    else AutopilotLog.Write("ПЛЕННЫЕ: перенесено " + count + ", в окне " + after + "/" + limit);
                    return true;
                }
                if (!(logic.GetType().GetMethod("IsDoneActive").Invoke(logic, null) is true))
                {
                    Disable("пленные: кнопка «Готово» недоступна"); return true;
                }
                _prisonerDoneRequested = true;
                InquiryData ownQuery = null; int queries = 0;
                Action<InquiryData, bool, bool> capture = (data, pause, prioritize) => { ownQuery = data; queries++; };
                // Capture ONLY a query raised synchronously by our own Done click.
                // Never approve an already-open or unrelated dialog.
                InformationManager.OnShowInquiry += capture;
                try { vm.GetType().GetMethod("ExecuteDone").Invoke(vm, null); }
                finally { InformationManager.OnShowInquiry -= capture; }
                if (queries > 0)
                {
                    Action accept = ownQuery?.AffirmativeAction;
                    if (queries != 1 || ownQuery.IsAffirmativeOptionShown != true
                        || accept?.Target != vm || accept.Method.Name != "CloseScreenInternal"
                        || accept.Method.DeclaringType != vm.GetType()
                        || !ReferenceEquals(states.ActiveState, state) || PlayerEncounter.Current != _prisonerEncounter)
                    {
                        Disable("пленные: неизвестное подтверждение после «Готово» — требуется игрок"); return true;
                    }
                    InformationManager.HideInquiry();
                    accept();
                    AutopilotLog.Write("ПЛЕННЫЕ: подтверждено завершение с оставшимися слева пленными/воинами");
                }
                if (!ReferenceEquals(states.ActiveState, state))
                {
                    AutopilotLog.Write("ПЛЕННЫЕ: экран закрыт штатно; фактически в партии " + MobileParty.MainParty.PrisonRoster.TotalManCount);
                    ResetPrisonerScreen();
                }
                else Disable("пленные: после «Готово» экран не закрылся");
            }
            catch (Exception ex)
            {
                Disable("пленные: обработка остановлена после исключения: " + ex);
            }
            return true;
        }
    }
}
