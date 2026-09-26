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
        private bool _swapStopped;

        internal void AuthorizePrisonerScreen()
        {
            if (_mode != Mode.Apply) return;
            _prisonerEncounter = PlayerEncounter.Current;
            _lootEncounter = PlayerEncounter.Current;
            _prisonerView = null;
            _prisonerDoneRequested = false;
            _swapStopped = false;
        }

        private static int TierOf(object troopVm)
        {
            object character = ReadScreenMember(ReadScreenMember(troopVm, "Troop"), "Character");
            return ReadScreenMember(character, "Tier") is int tier ? tier : 0;
        }

        private static bool IsHeroTroop(object troopVm) =>
            ReadScreenMember(ReadScreenMember(ReadScreenMember(troopVm, "Troop"), "Character"), "IsHero") is true;

        private static int NumberOf(object troopVm) => Convert.ToInt32(ReadScreenMember(ReadScreenMember(troopVm, "Troop"), "Number"));

        private static bool Movable(object troopVm, string side) =>
            ReadScreenMember(troopVm, "IsTroopTransferrable") is true && ReadScreenMember(troopVm, "Side")?.ToString() == side
            && !IsHeroTroop(troopVm) && NumberOf(troopVm) > 0;

        private void ResetPrisonerScreen()
        {
            _prisonerEncounter = null;
            _prisonerView = null;
            _prisonerDoneRequested = false;
            _swapStopped = false;
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
                // Loot has two independent left-hand lists: rescued members and prisoners.
                // The native transfer arrow retains wounds and performs eligibility checks.
                object members = ReadScreenMember(ReadScreenMember(logic, "CurrentData"), "RightMemberRoster");
                int membersBefore = Convert.ToInt32(ReadScreenMember(members, "TotalManCount"));
                int memberLimit = Convert.ToInt32(ReadScreenMember(logic, "RightPartyMembersSizeLimit"));
                int memberFree = Math.Max(0, memberLimit - membersBefore);
                var rescued = ReadScreenMember(vm, "OtherPartyTroops") as IEnumerable;
                if (members == null || rescued == null) throw new InvalidOperationException("список освобождённых бойцов отсутствует");
                // 26.09, владелец: «заменять освобождённых из плена войск высокого тира
                // нашими слабыми». Берём сперва самых сильных; отряд полон — отпускаем
                // (влево) самых слабых наших, если слева есть строго сильнее.
                var rescuedByTier = new System.Collections.Generic.List<object>();
                foreach (object t in rescued) rescuedByTier.Add(t);
                rescuedByTier.Sort((a, c) => TierOf(c).CompareTo(TierOf(a)));
                if (memberFree == 0 && !_swapStopped)
                {
                    object best = null, weakest = null;
                    foreach (object t in rescuedByTier) if (Movable(t, "Left")) { best = t; break; }
                    if (best != null && ReadScreenMember(vm, "MainPartyTroops") is IEnumerable ours)
                        foreach (object t in ours)
                            if (Movable(t, "Right") && (weakest == null || TierOf(t) < TierOf(weakest))) weakest = t;
                    if (best != null && weakest != null && TierOf(best) > TierOf(weakest))
                    {
                        int swap = Math.Min(NumberOf(best), NumberOf(weakest));
                        string weakName = ReadScreenMember(ReadScreenMember(ReadScreenMember(weakest, "Troop"), "Character"), "Name")?.ToString();
                        string bestName = ReadScreenMember(ReadScreenMember(ReadScreenMember(best, "Troop"), "Character"), "Name")?.ToString();
                        int tierWeak = TierOf(weakest), tierBest = TierOf(best);
                        vm.GetType().GetMethod("OnTransferTroop", BindingFlags.NonPublic | BindingFlags.Instance)
                            .Invoke(vm, new[] { weakest, (object)(-1), swap, ReadScreenMember(weakest, "Side") });
                        vm.GetType().GetMethod("ExecuteRemoveZeroCounts").Invoke(vm, null);
                        int afterRelease = Convert.ToInt32(ReadScreenMember(members, "TotalManCount"));
                        if (afterRelease != membersBefore - swap)
                        {
                            _swapStopped = true;
                            AutopilotLog.Write("ОБМЕН: отпустить слабых не удалось (было " + membersBefore + ", стало " + afterRelease + ") — обмен на этом экране прекращён");
                        }
                        else AutopilotLog.Write("ОБМЕН: отпущено " + swap + " «" + weakName + "» (тир " + tierWeak
                            + ") ради «" + bestName + "» (тир " + tierBest + ")");
                        return true;
                    }
                }
                if (memberFree > 0) foreach (object troop in rescuedByTier)
                {
                    if (!(ReadScreenMember(troop, "IsTroopTransferrable") is true)) continue;
                    object side = ReadScreenMember(troop, "Side");
                    if (side?.ToString() != "Left") continue;
                    int count = Math.Min(memberFree, Convert.ToInt32(ReadScreenMember(ReadScreenMember(troop, "Troop"), "Number")));
                    if (count <= 0) continue;
                    vm.GetType().GetMethod("OnTransferTroop", BindingFlags.NonPublic | BindingFlags.Instance)
                        .Invoke(vm, new[] { troop, (object)(-1), count, side });
                    vm.GetType().GetMethod("ExecuteRemoveZeroCounts").Invoke(vm, null);
                    int after = Convert.ToInt32(ReadScreenMember(members, "TotalManCount"));
                    if (after != membersBefore + count) Disable("освобождённые бойцы: перенос не подтвердился, повторять не буду");
                    else AutopilotLog.Write("ПОПОЛНЕНИЕ: принято освобождённых бойцов " + count + ", в отряде " + after + "/" + memberLimit);
                    return true;
                }
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
