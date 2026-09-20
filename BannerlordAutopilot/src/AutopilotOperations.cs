using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.GameState;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;
using TaleWorlds.Core;
using TaleWorlds.Library;

namespace BannerlordAutopilot
{
    public partial class AutopilotBehavior
    {
        // Session-owned operation: a menu name alone never authorizes another encounter.
        private Settlement _operationSettlement, _hideoutRoute;
        private PlayerEncounter _simulationEncounter;
        private object _finishedSimulation;

        private bool TrySendTroopsWhenWounded()
        {
            if (_mode != Mode.Apply || Hero.MainHero?.IsWounded != true
                || PlayerEncounter.Current == null || MenuDriver.CurrentMenuId != "encounter"
                || InformationManager.IsAnyInquiryActive() || MenuDriver.CanInvoke("attack", out _)
                || !MenuDriver.CanInvoke("str_order_attack", out _)) return false;
            _simulationEncounter = PlayerEncounter.Current;
            _finishedSimulation = null;
            AuthorizePrisonerScreen();
            if (!MenuDriver.TryInvoke("str_order_attack", out string why))
            {
                _simulationEncounter = null;
                Disable("отправка войск недоступна: " + why);
                return true;
            }
            AutopilotLog.Write("БОЙ: герой ранен; штатное «Послать воинов», ждём завершения авторасчёта");
            return true;
        }

        private bool PollOwnedSimulation()
        {
            if (_mode != Mode.Apply || _simulationEncounter == null
                || PlayerEncounter.Current != _simulationEncounter) return false;
            object screen = (Game.Current?.GameStateManager?.ActiveState as MapState)?.Handler;
            if (!(ReadScreenMember(screen, "IsInBattleSimulation") is true)) return false;
            if (InformationManager.IsAnyInquiryActive() || ReadScreenMember(screen, "IsEscapeMenuOpened") is true) return true;
            try
            {
                Type viewType = null;
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    viewType = assembly.GetType("SandBox.GauntletUI.Map.GauntletMapBattleSimulationView", false);
                    if (viewType != null) break;
                }
                object view = null;
                foreach (var method in screen.GetType().GetMethods())
                    if (viewType != null && method.Name == "GetMapView" && method.IsGenericMethodDefinition && method.GetParameters().Length == 0)
                    { view = method.MakeGenericMethod(viewType).Invoke(screen, null); break; }
                if (view == null) return true;
                object vm = viewType.GetField("_dataSource", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(view);
                if (vm == null || ReferenceEquals(vm, _finishedSimulation)) return true;
                if (!(ReadScreenMember(vm, "IsSimulation") is true) || !(ReadScreenMember(vm, "IsOver") is true)
                    || !(ReadScreenMember(vm, "ShowScoreboard") is true)) return true;
                // IsOver can be published a tick before BattleSimulation finishes. Calling
                // ExecuteQuitAction in that gap opens the native retreat inquiry instead.
                object simulation = vm.GetType().GetField("_battleSimulation", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(vm);
                if (!(ReadScreenMember(simulation, "IsSimulationFinished") is true)) return true;
                _finishedSimulation = vm;
                vm.GetType().GetMethod("ExecuteQuitAction", Type.EmptyTypes).Invoke(vm, null);
                AutopilotLog.Write("БОЙ: авторасчёт завершён; результат подтверждён штатной кнопкой");
            }
            catch (Exception ex) { Disable("завершение авторасчёта: " + ex); }
            return true;
        }
        private bool _hideoutAttackRequested, _awaitingHideoutTroops;
        private bool _hideoutMissionFinished;
        private DateTime _troopsRequestedAt, _nextHideoutDialogAt;
        private readonly Dictionary<string, double> _hideoutRetryAfter = new Dictionary<string, double>();

        private void ResetOperations()
        {
            _simulationEncounter = null; _finishedSimulation = null;
            _offensiveSiege = null;
            _raidSettlement = null;
            _preparingCampaign = false;
            _configuredSiege = null;
            _gatheringArmy = null; _invitedParties.Clear();
            _operationSettlement = _hideoutRoute = null;
            _hideoutAttackRequested = _awaitingHideoutTroops = false;
            _hideoutMissionFinished = false;
            _hideoutRetryAfter.Clear();
            _nextHideoutDialogAt = DateTime.MinValue;
        }

        private static Settlement EncounterPlace(MobileParty party) => party?.CurrentSettlement
            ?? (PlayerEncounter.Current != null ? PlayerEncounter.EncounterSettlement : null);

        private static bool FriendlySiege(Settlement place, MobileParty party) =>
            place != null && place.IsUnderSiege && place.MapFaction != null && party?.MapFaction != null
            && !party.MapFaction.IsAtWarWith(place.MapFaction);

        private static bool CanStartOperation(MobileParty party)
        {
            if (party?.SiegeEvent?.BesiegerCamp.LeaderParty != null && !party.IsCurrentlyAtSea
                && (party.SiegeEvent.BesiegerCamp.LeaderParty == party || party.SiegeEvent.BesiegerCamp.LeaderParty == party.Army?.LeaderParty)) return true;
            if (party == null || party.Army != null || party.IsCurrentlyAtSea || party.Ai == null || party.Ai.IsDisabled) return false;
            var place = EncounterPlace(party);
            string menu = MenuDriver.CurrentMenuId;
            return ((menu == "join_siege_event" || menu == "encounter_interrupted_siege_preparations") && FriendlySiege(place, party))
                || ((menu == "hideout_place" || menu == "hideout_after_wait") && place?.IsHideout == true);
        }

        internal bool IsOwnedOperationBattle(MobileParty party)
        {
            var battle = party?.MapEvent;
            if (_mode != Mode.Apply || _operationSettlement == null || battle == null
                || battle.IsNavalMapEvent || PlayerEncounter.Current == null
                || battle.MapEventSettlement != _operationSettlement) return false;

            // When a relief army attacks the player's besieger camp, Bannerlord
            // publishes the same MapEvent through EncounteredBattle first.  The
            // PlayerEncounter.Battle property can remain null until after the
            // encounter menu's Attack consequence. Requiring Battle here made
            // the autopilot reject its own siege-outside fight, switch itself
            // off, and leave the visible "Attack" button to the player.
            var encounterBattle = PlayerEncounter.EncounteredBattle;
            if (PlayerEncounter.Battle != battle && encounterBattle != battle) return false;
            return (_operationSettlement.IsHideout && _hideoutAttackRequested && battle.IsHideoutBattle)
                || (_operationSettlement == _raidSettlement && battle.IsRaid)
                || (_operationSettlement == _offensiveSiege && (battle.IsSallyOut || battle.IsSiegeOutside))
                || (!_operationSettlement.IsHideout && battle.IsSiegeAssault
                    && (battle.PlayerSide == BattleSideEnum.Defender
                        || (_offensiveSiege == _operationSettlement && battle.PlayerSide == BattleSideEnum.Attacker)));
        }

        internal bool IsOwnedHideoutBattle => _operationSettlement?.IsHideout == true
            && IsOwnedOperationBattle(MobileParty.MainParty);

        internal void OnOperationMissionEnded()
        {
            if (_operationSettlement?.IsHideout == true && _hideoutAttackRequested)
                _hideoutMissionFinished = true; // Native completion, not a claim of victory.
        }

        private bool PollOperations(MobileParty party)
        {
            if (Hero.MainHero == null || Hero.MainHero.IsPrisoner || !ControlsParty(party) || party.IsCurrentlyAtSea) return false;
            if (IsOnFreeMap(party))
            {
                _operationSettlement = null;
                _hideoutAttackRequested = _awaitingHideoutTroops = false;
                _hideoutMissionFinished = false;
                return false;
            }
            var place = EncounterPlace(party);
            if (_operationSettlement == null && CanStartOperation(party)) _operationSettlement = place;
            if (_operationSettlement == null || place != _operationSettlement) return false;
            if (_mode != Mode.Apply) return true;
            if (InformationManager.IsAnyInquiryActive()) return true;
            try
            {
                if (_awaitingHideoutTroops) { ConfirmHideoutTroops(); return true; }
                if (!MapIsActiveScreen()) return true;
                string menu = MenuDriver.CurrentMenuId;
                if (_operationSettlement.IsHideout)
                {
                    if (_hideoutAttackRequested)
                    {
                        if (menu == "hideout_after_defeated_and_saved" || menu == "hideout_after_found_by_sentries")
                            OperationClick("leave");
                        else if (_hideoutMissionFinished && (menu == "hideout_place" || menu == "hideout_after_wait"))
                            OperationClick("leave");
                        else if (Clock() - _troopsRequestedAt > TimeSpan.FromSeconds(30) && party.MapEvent == null)
                            Disable("убежище: атака не открыла миссию; " + MenuDriver.Describe());
                        return true;
                    }
                    if (menu == "hideout_wait") { ResumeOperationWait(); return true; }
                    if (menu != "hideout_place" && menu != "hideout_after_wait") return false;
                    // Full daytime battle; the night option launches a different stealth mission.
                    _hideoutRetryAfter[place.StringId] = CampaignTime.Now.ToHours + 24;
                    if (MenuDriver.TryInvoke("assault", out string why))
                    {
                        _hideoutAttackRequested = _awaitingHideoutTroops = true;
                        _troopsRequestedAt = Clock();
                        AutopilotLog.Write("УБЕЖИЩЕ: штатный штурм «" + place.Name + "», подтверждаем предложенный игрой отряд");
                    }
                    else if (menu == "hideout_place" && CampaignTime.Now.IsNightTime && !Hero.MainHero.IsWounded
                        && place.Hideout?.NextPossibleAttackTime.IsPast == true && MenuDriver.TryInvoke("wait", out _))
                        AutopilotLog.Write("УБЕЖИЩЕ: ждём утра для полноценного штурма");
                    else
                    {
                        AutopilotLog.Write("УБЕЖИЩЕ: штурм недоступен: " + why + "; следующая попытка не раньше суток");
                        // after_wait's leave only returns to hideout_place; next poll leaves that menu too.
                        OperationClick("leave");
                    }
                    return true;
                }
                switch (menu)
                {
                    case "join_siege_event":
                        if (!FriendlySiege(place, party)) return false;
                        OperationClick("join_siege_event_break_in"); break;
                    case "break_in_menu": OperationClick("break_in_menu_accept"); break;
                    case "break_in_debrief_menu": OperationClick("break_in_debrief_continue"); break;
                    case "encounter_interrupted_siege_preparations":
                        if (!FriendlySiege(place, party)) return false;
                        if (MenuDriver.CanInvoke("encounter_interrupted_siege_preparations_join_defend", out _))
                            OperationClick("encounter_interrupted_siege_preparations_join_defend");
                        else if (MenuDriver.CanInvoke("encounter_interrupted_siege_preparations_leave_town", out _))
                        {
                            AutopilotLog.Write("ОСАДА: помощь защитникам скрыта; покидаем «" + place.Name + "» штатной кнопкой");
                            OperationClick("encounter_interrupted_siege_preparations_leave_town");
                        }
                        else Disable("осада: помощь защитникам и выход из поселения недоступны: " + MenuDriver.Describe());
                        break;
                    case "menu_siege_strategies": ResumeOperationWait(); break;
                    case "join_encounter":
                    case "encounter_interrupted":
                        var battle = PlayerEncounter.Current != null ? PlayerEncounter.EncounteredBattle : null;
                        if (battle?.MapEventSettlement != place || battle.IsNavalMapEvent
                            || !FriendlySiege(place, party)) return false;
                        OperationClick(menu + "_help_defenders"); break;
                    case "encounter":
                        if (!IsOwnedOperationBattle(party)) return false;
                        OperationClick("attack"); break;
                    case "siege_attacker_left":
                    case "siege_attacker_defeated": OperationClick(menu + "_leave"); break;
                    default: return false;
                }
                return true;
            }
            catch (Exception ex)
            {
                Disable("осада/убежище: действие остановлено после исключения: " + ex);
                return true;
            }
        }

        private void OperationClick(string option)
        {
            if (option == "attack" && TrySendTroopsWhenWounded()) return;
            if (MenuDriver.TryInvoke(option, out string why)) AutopilotLog.Write("ОПЕРАЦИЯ: " + option);
            else Disable("операция недоступна: " + why);
        }

        private static void ResumeOperationWait()
        {
            var menu = Campaign.Current.CurrentMenuContext?.GameMenu;
            if (menu?.IsWaitMenu != true) return;
            if (!menu.IsWaitActive) menu.StartWait();
            Campaign.Current.TimeControlMode = CampaignTimeControlMode.UnstoppableFastForward;
        }

        private void ConfirmHideoutTroops()
        {
            var states = Game.Current?.GameStateManager;
            if (!(states?.ActiveState is MapState) || states.ActiveStateDisabledByUser) return;
            // Only our own troop picker; every other overlay still blocks the action.
            var window = WindowOverMap();
            if (window != null && window != "отряд для логова") return;
            object handler = Campaign.Current.CurrentMenuContext?.Handler;
            var views = handler?.GetType().GetProperty("MenuViews")?.GetValue(handler) as IEnumerable;
            object source = null;
            if (views != null) foreach (object view in views)
                if (view?.GetType().FullName == "SandBox.GauntletUI.Menu.GauntletMenuTroopSelectionView")
                    source = view.GetType().GetField("_dataSource", BindingFlags.Instance | BindingFlags.NonPublic)?.GetValue(view);
            if (source == null)
            {
                if (Clock() - _troopsRequestedAt > TimeSpan.FromSeconds(15)) Disable("убежище: окно выбора отряда не появилось");
                return;
            }
            Type type = source.GetType();
            if (!(type.GetProperty("IsEnabled")?.GetValue(source) is true)
                || !(type.GetProperty("IsDoneEnabled")?.GetValue(source) is true))
            {
                Disable("убежище: предложенный игрой отряд нельзя подтвердить"); return;
            }
            _awaitingHideoutTroops = false; // Set before native callbacks: never repeat an uncertain effect.
            type.GetMethod("ExecuteDone", Type.EmptyTypes).Invoke(source, null);
            AutopilotLog.Write("УБЕЖИЩЕ: подтверждён штатный отряд; ожидаем миссию");
        }

        private bool PollHideoutConversation()
        {
            var conversation = Campaign.Current?.ConversationManager;
            if (_operationSettlement?.IsHideout != true || !IsOwnedOperationBattle(MobileParty.MainParty)
                || conversation?.IsConversationInProgress != true) return false;
            if (InformationManager.IsAnyInquiryActive() || Clock() < _nextHideoutDialogAt) return true;
            var options = conversation.CurOptions;
            for (int i=0; options != null && i<options.Count; i++)
                if (options[i].Id == "bandit_hideout_start_defender_2" && options[i].IsClickable)
                {
                    _nextHideoutDialogAt = Clock().AddSeconds(2);
                    conversation.DoOption(i);
                    AutopilotLog.Write("УБЕЖИЩЕ: продолжаем бой всем отрядом"); return true;
                }
            if (options == null || options.Count == 0)
            {
                _nextHideoutDialogAt = Clock().AddSeconds(2);
                conversation.ContinueConversation();
            }
            return true;
        }

        private bool CanVisitHideout(Hideout hideout) => hideout != null && hideout.IsSpotted && hideout.IsInfested
            && hideout.Settlement.IsVisible && hideout.NextPossibleAttackTime.IsPast
            && (!_hideoutRetryAfter.TryGetValue(hideout.Settlement.StringId, out double until) || CampaignTime.Now.ToHours >= until);

        private bool TryChooseHideout(MobileParty party)
        {
            if (_mode != Mode.Apply || !IsOnFreeMap(party) || !MapIsActiveScreen()
                || InformationManager.IsAnyInquiryActive() || Hero.MainHero.IsWounded || party.IsCurrentlyAtSea) return false;
            try
            {
                if (_hideoutRoute != null && party.TargetSettlement == _hideoutRoute && CanVisitHideout(_hideoutRoute.Hideout)) return true;
                Settlement nearest = null; float distance = float.MaxValue;
                foreach (var hideout in Hideout.All)
                {
                    if (!CanVisitHideout(hideout)) continue;
                    float next = party.Position.DistanceSquared(hideout.Settlement.Position);
                    if (next < distance) { nearest = hideout.Settlement; distance = next; }
                }
                if (nearest == null) return false;
                _hideoutRoute = nearest;
                SetPartyAiAction.GetActionForVisitingSettlement(party, nearest, MobileParty.NavigationType.Default, false, false);
                AutopilotLog.Write("УБЕЖИЩЕ: своя цель зачистки ближайшего известного лагеря «" + nearest.Name + "» вместо патруля");
                return true;
            }
            catch (Exception ex)
            {
                Disable("убежище: не удалось выдать маршрут: " + ex);
                return true;
            }
        }
    }
}
