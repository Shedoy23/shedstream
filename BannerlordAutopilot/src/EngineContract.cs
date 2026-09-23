using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using TaleWorlds.CampaignSystem;
using TaleWorlds.CampaignSystem.Actions;
using TaleWorlds.CampaignSystem.ComponentInterfaces;
using TaleWorlds.CampaignSystem.Encounters;
using TaleWorlds.CampaignSystem.Party;
using TaleWorlds.CampaignSystem.Settlements;

namespace BannerlordAutopilot
{
    /// <summary>Проверка структуры движка ПЕРЕД тем, как что-то включать.
    ///
    /// Мод скомпилирован под конкретную сборку 1.4.8. Запустить его могут на
    /// другой версии игры или рядом с модом, который подменил эти типы. Тогда
    /// вместо работы будет ошибка разрешения метода посреди кампании. Поэтому
    /// при старте спрашиваем рантайм: те ли это члены, тех ли типов. Не
    /// сошлось — автопилот не включается, игра работает как обычно.
    ///
    /// ЧЕГО ЭТА ПРОВЕРКА НЕ ДЕЛАЕТ. Она сверяет структуру, а не поведение:
    /// метод с прежней сигнатурой, но другим смыслом, она не заметит.
    ///
    /// 12.09 независимая проверка построила API, где AIBehaviorScores был
    /// строкой, поле Party — целым числом, одного используемого метода не было
    /// вовсе, — и прежний контракт принял его «19 из 19». Он сверял только
    /// наличие имён, пропускал часть реально используемых вызовов и накручивал
    /// счётчик при повторном запуске. Теперь сверяются типы полей, параметры и
    /// возвращаемые значения всех вызовов, которыми пользуется мод.</summary>
    internal static class EngineContract
    {
        internal static bool Ok { get; private set; }
        internal static string Report { get; private set; } = "проверка не выполнялась";

        private static readonly List<string> Problems = new List<string>();
        private static int _checked;

        private const BindingFlags Inst = BindingFlags.Public | BindingFlags.Instance;
        private const BindingFlags Stat = BindingFlags.Public | BindingFlags.Static;

        /// <summary>Окна поверх карты: флаг SandBox.View.Map.MapScreen (11137-11198) и
        /// имя для журнала. Движок сам сверяет эти флаги перед действиями на карте
        /// (SandBox.View 12066, 12558, 17522). Одно место: автопилот читает флаги
        /// отсюда, контракт отсюда же проверяет, что они есть.</summary>
        internal static readonly (string Property, string Name)[] MapWindows =
        {
            ("IsMapIncidentActive", "окно случайного события"),
            ("IsMarriageOfferPopupActive", "предложение брака"),
            ("IsHeirSelectionPopupActive", "выбор наследника"),
            ("IsInArmyManagement", "управление армией"),
            ("IsInRecruitment", "экран найма"),
            ("IsInTownManagement", "управление поселением"),
            ("IsInHideoutTroopManage", "отряд для логова"),
            ("IsInBattleSimulation", "автобой"),
            ("IsInCampaignOptions", "настройки кампании"),
            ("IsEscapeMenuOpened", "меню паузы"),
            ("IsMapCheatsActive", "читы карты"),
            ("IsOverlayContextMenuEnabled", "контекстное меню карты"),
        };

        internal static bool Verify()
        {
            Problems.Clear();
            _checked = 0;

            // ── Типы, которые нельзя назвать напрямую, берём из полей и сверяем по имени
            Type vec2 = typeof(AIBehaviorData).GetField("Position", Inst)?.FieldType;
            Need(vec2 != null && vec2.Name == "CampaignVec2", "AIBehaviorData.Position : CampaignVec2");
            Type navigation = typeof(MobileParty.NavigationType);

            // ── Сбор оценок
            MemberOf(typeof(MobileParty), "ThinkParamsCache", Inst, typeof(PartyThinkParams));
            Method(typeof(PartyThinkParams), "Reset", Inst, typeof(void), typeof(MobileParty));
            // Своя проверка типа (коллекцию сверяем на совместимость, а не на
            // точное совпадение), поэтому публичное чтение требуется здесь явно:
            // общая проверка MemberType сюда не доходит (итоговая проверка 13.09).
            PropertyInfo scores = typeof(PartyThinkParams).GetProperty("AIBehaviorScores", Inst);
            Need(scores != null && scores.GetGetMethod() != null
                 && typeof(IEnumerable<(AIBehaviorData, float)>).IsAssignableFrom(scores.PropertyType),
                "PartyThinkParams.AIBehaviorScores : IEnumerable<(AIBehaviorData, float)> (публичное чтение)");
            MemberOf(typeof(CampaignEventDispatcher), "Instance", Stat, typeof(CampaignEventDispatcher));
            Method(typeof(CampaignEventDispatcher), "AiHourlyTick", Inst, typeof(void),
                typeof(MobileParty), typeof(PartyThinkParams));

            // ── Описание решения
            FieldOf(typeof(AIBehaviorData), "AiBehavior", typeof(AiBehavior));
            FieldNamed(typeof(AIBehaviorData), "Party", "IMapPoint");
            FieldOf(typeof(AIBehaviorData), "NavigationType", navigation);
            FieldOf(typeof(AIBehaviorData), "IsFromPort", typeof(bool));
            FieldOf(typeof(AIBehaviorData), "IsTargetingPort", typeof(bool));
            FieldOf(typeof(AIBehaviorData), "WillGatherArmy", typeof(bool));

            // ── Применение решения
            Method(typeof(SetPartyAiAction), "GetActionForVisitingSettlement", Stat, typeof(void),
                typeof(MobileParty), typeof(Settlement), navigation, typeof(bool), typeof(bool));
            Method(typeof(SetPartyAiAction), "GetActionForPatrollingAroundSettlement", Stat, typeof(void),
                typeof(MobileParty), typeof(Settlement), navigation, typeof(bool), typeof(bool));
            if (vec2 != null)
            {
                Method(typeof(SetPartyAiAction), "GetActionForPatrollingAroundPoint", Stat, typeof(void),
                    typeof(MobileParty), vec2, navigation, typeof(bool));
            }
            Method(typeof(SetPartyAiAction), "GetActionForEscortingParty", Stat, typeof(void),
                typeof(MobileParty), typeof(MobileParty), navigation, typeof(bool), typeof(bool));
            Method(typeof(SetPartyAiAction), "GetActionForGoingAroundParty", Stat, typeof(void),
                typeof(MobileParty), typeof(MobileParty), navigation, typeof(bool));
            Method(typeof(SetPartyAiAction), "GetActionForEngagingParty", Stat, typeof(void),
                typeof(MobileParty), typeof(MobileParty), navigation, typeof(bool));

            // ── Состояние партии
            MemberOf(typeof(MobileParty), "MainParty", Stat, typeof(MobileParty));
            MemberOf(typeof(MobileParty), "IsActive", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsMoving", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "CurrentSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "BesiegedSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "TargetSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "TargetParty", Inst, typeof(MobileParty));
            MemberOf(typeof(MobileParty), "LastVisitedSettlement", Inst, typeof(Settlement));
            MemberOf(typeof(MobileParty), "DefaultBehavior", Inst, typeof(AiBehavior));
            MemberOf(typeof(MobileParty), "Ai", Inst, typeof(MobilePartyAi));
            MemberOf(typeof(GameModels), "MobilePartyAIModel", Inst, typeof(MobilePartyAIModel));
            Method(typeof(MobilePartyAIModel), "GetBestInitiativeBehavior", Inst, typeof(void),
                typeof(MobileParty), typeof(AiBehavior).MakeByRefType(), typeof(MobileParty).MakeByRefType(),
                typeof(float).MakeByRefType(), typeof(TaleWorlds.Library.Vec2).MakeByRefType());
            Type mapEvent = MemberType(typeof(MobileParty), "MapEvent", Inst, false, out _);
            Need(mapEvent != null, "MobileParty.MapEvent");
            MemberOf(typeof(PlayerEncounter), "EncounteredBattle", Stat, mapEvent);
            MemberOf(typeof(PlayerEncounter), "EncounteredParty", Stat, typeof(PartyBase));
            Type battleSide = MemberType(mapEvent, "AttackerSide", Inst, false, out _);
            Need(battleSide != null, "MapEvent.AttackerSide");
            MemberOf(mapEvent, "DefenderSide", Inst, battleSide);
            Type leaderParty = MemberType(battleSide, "LeaderParty", Inst, false, out _);
            Need(leaderParty != null, "MapEventSide.LeaderParty");
            MemberNamed(leaderParty, "MapFaction", Inst, "IFaction");
            MemberOf(mapEvent, "MapEventSettlement", Inst, typeof(Settlement));
            MemberOf(mapEvent, "IsNavalMapEvent", Inst, typeof(bool));
            MemberExists(typeof(MobileParty), "SiegeEvent", Inst);
            MemberExists(typeof(MobileParty), "Army", Inst);
            if (vec2 != null)
            {
                MemberOf(typeof(MobileParty), "Position", Inst, vec2, needWrite: true);
            }
            Method(typeof(MobileParty), "SetMoveModeHold", Inst, typeof(void));
            MemberOf(typeof(MobilePartyAi), "IsDisabled", Inst, typeof(bool));
            MemberOf(typeof(MobilePartyAi), "DoNotMakeNewDecisions", Inst, typeof(bool));

            // ── Встреча и выход из поселения (повтор кнопки «Уйти»)
            MemberExists(typeof(PlayerEncounter), "Current", Stat);
            MemberExists(typeof(PlayerEncounter), "Battle", Stat);
            MemberOf(typeof(PlayerEncounter), "EncounterSettlement", Stat, typeof(Settlement));
            MemberOf(typeof(PlayerEncounter), "EncounteredMobileParty", Stat, typeof(MobileParty));
            Method(typeof(PlayerEncounter), "LeaveSettlement", Stat, typeof(void));
            Method(typeof(PlayerEncounter), "Finish", Stat, typeof(void), typeof(bool));
            MemberOf(typeof(Settlement), "IsUnderSiege", Inst, typeof(bool));
            if (vec2 != null)
            {
                MemberOf(typeof(Settlement), "GatePosition", Inst, vec2);
            }

            // ── Ход времени после выхода (Finish ставит паузу) и проверка движка
            //    «партия уже у этого поселения». Типы берём по имени через
            //    рефлексию: сборка проверки не должна зависеть от их наличия.
            MemberNamed(typeof(Campaign), "TimeControlMode", Inst, "CampaignTimeControlMode", needWrite: true);
            Method(typeof(Campaign), "SetTimeSpeed", Inst, typeof(void), typeof(int));
            Type helper = typeof(MobileParty).Assembly.GetType("Helpers.MobilePartyHelper");
            MethodInfo here = helper?.GetMethod("GetCurrentSettlementOfMobilePartyForAICalculation", Stat, null,
                new[] { typeof(MobileParty) }, null);
            Need(here != null && here.ReturnType == typeof(Settlement),
                "MobilePartyHelper.GetCurrentSettlementOfMobilePartyForAICalculation(MobileParty) → Settlement");

            // ── Меню, экран и время. Типы — по имени из сборки движка: в другой
            //    версии игры их может не оказаться, и это должно стать строкой
            //    «не совпало», а не падением проверки.
            Assembly campaignAssembly = typeof(Campaign).Assembly;
            Type menuContext = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.GameState.MenuContext");
            Type gameMenu = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.GameMenus.GameMenu");
            Type gameMenuOption = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.GameMenus.GameMenuOption");
            Type mapState = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.GameState.MapState");
            Type campaignTime = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.CampaignTime");
            Type conversations = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.Conversation.ConversationManager");
            Type gameState = mapState?.BaseType;
            Need(gameState != null && gameState.FullName == "TaleWorlds.Core.GameState", "MapState : TaleWorlds.Core.GameState");
            Type game = TypeNamed(gameState?.Assembly, "TaleWorlds.Core.Game");
            Type gameStates = TypeNamed(gameState?.Assembly, "TaleWorlds.Core.GameStateManager");

            // Пункты меню — тем же путём, что кнопка (GameMenuItemVM.ExecuteAction →
            // MenuContext.InvokeConsequence): «Подождать», «Перестать ждать».
            MemberOf(typeof(Campaign), "CurrentMenuContext", Inst, menuContext);
            MemberOf(menuContext, "GameMenu", Inst, gameMenu);
            Method(menuContext, "InvokeConsequence", Inst, typeof(void), typeof(int));
            MemberOf(gameMenu, "StringId", Inst, typeof(string));
            MemberOf(gameMenu, "MenuOptions", Inst,
                gameMenuOption != null ? typeof(IEnumerable<>).MakeGenericType(gameMenuOption) : null);
            MemberOf(gameMenu, "MenuRepeatObjects", Inst, typeof(List<object>));
            MemberOf(gameMenu, "IsWaitMenu", Inst, typeof(bool));
            MemberOf(gameMenu, "IsWaitActive", Inst, typeof(bool));
            Method(gameMenu, "GetMenuOptionConditionsHold", Inst, typeof(bool), game, menuContext, typeof(int));
            Method(gameMenu, "GetGameMenuOption", Inst, gameMenuOption, typeof(int));
            MemberOf(gameMenuOption, "IdString", Inst, typeof(string));
            MemberOf(gameMenuOption, "IsEnabled", Inst, typeof(bool));
            MemberExists(gameMenuOption, "Tooltip", Inst);
            MemberOf(typeof(PlayerEncounter), "IsPlayerWaiting", Inst, typeof(bool));
            MemberOf(typeof(Settlement), "IsVillage", Inst, typeof(bool));

            // Ход времени без человека и сторож простоя.
            MemberOf(typeof(Campaign), "TimeControlModeLock", Inst, typeof(bool));
            MemberOf(typeof(Campaign), "IsMainPartyWaiting", Inst, typeof(bool));
            MemberOf(campaignTime, "Now", Stat, campaignTime);
            MemberOf(campaignTime, "ToHours", Inst, typeof(double));
            MemberOf(game, "Current", Stat, game);
            MemberOf(game, "GameStateManager", Inst, gameStates);
            MemberOf(gameStates, "ActiveState", Inst, gameState);
            MemberOf(gameStates, "ActiveStateDisabledByUser", Inst, typeof(bool));
            Method(gameStates, "PopState", Inst, typeof(void), typeof(int));
            MemberOf(typeof(Campaign), "ConversationManager", Inst, conversations);
            MemberOf(conversations, "IsConversationInProgress", Inst, typeof(bool));
            MemberOf(conversations, "ConversationParty", Inst, typeof(MobileParty));
            Type conversationOption = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.Conversation.ConversationSentenceOption");
            MemberOf(conversations, "CurOptions", Inst, conversationOption == null ? null : typeof(List<>).MakeGenericType(conversationOption));
            MemberOf(conversationOption, "Id", Inst, typeof(string));
            MemberOf(conversationOption, "IsClickable", Inst, typeof(bool));
            Method(conversations, "DoOption", Inst, typeof(void), typeof(int));
            Method(conversations, "ContinueConversation", Inst, typeof(void));
            Method(conversations, "IsConversationEnded", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsBandit", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsLordParty", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "Speed", Inst, typeof(float));
            Type mission = LoadedType("TaleWorlds.MountAndBlade.Mission", "TaleWorlds.MountAndBlade");
            Type battleEnd = LoadedType("TaleWorlds.MountAndBlade.BattleEndLogic", "TaleWorlds.MountAndBlade");
            Type exitResult = battleEnd?.GetNestedType("ExitResult");
            Need(exitResult != null && exitResult.IsEnum && Enum.IsDefined(exitResult, "True"), "BattleEndLogic.ExitResult.True");
            Method(battleEnd, "TryExit", Inst, exitResult);
            MemberOf(mission, "MissionEnded", Inst, typeof(bool));
            Type missionResult = mission?.GetProperty("MissionResult", Inst)?.PropertyType;
            Need(missionResult != null && missionResult.Name == "MissionResult", "Mission.MissionResult type");
            MemberOf(missionResult, "BattleResolved", Inst, typeof(bool));
            Type agent = LoadedType("TaleWorlds.MountAndBlade.Agent", "TaleWorlds.MountAndBlade");
            Type ridingOrder = LoadedType("TaleWorlds.MountAndBlade.RidingOrder", "TaleWorlds.MountAndBlade");
            Type ridingEnum = ridingOrder?.GetNestedType("RidingOrderEnum");
            Need(ridingEnum != null && ridingEnum.IsEnum && Enum.IsDefined(ridingEnum, "Dismount"),
                "RidingOrder.RidingOrderEnum.Dismount");
            Method(agent, "SetRidingOrder", Inst, typeof(void), ridingEnum);

            // Окна поверх карты (прогон 14.09): экран карты и флаги его окон. SandBox.View
            // мод не подключает, поэтому типы — по имени среди загруженных сборок.
            Type mapHandler = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.GameState.IMapStateHandler");
            MemberOf(mapState, "Handler", Inst, mapHandler);
            Type mapScreen = LoadedType("SandBox.View.Map.MapScreen", "SandBox.View");
            Need(mapScreen != null && mapHandler != null && mapHandler.IsAssignableFrom(mapScreen), "MapScreen : IMapStateHandler");
            foreach ((string property, string _) in MapWindows)
            {
                MemberOf(mapScreen, property, Inst, typeof(bool));
            }
            Type encyclopedia = LoadedType("SandBox.View.Map.MapEncyclopediaView", "SandBox.View");
            MemberOf(mapScreen, "EncyclopediaScreenManager", Inst, encyclopedia);
            MemberOf(encyclopedia, "IsEncyclopediaOpen", Inst, typeof(bool));

            // Обязательные решения королевства: работаем через ту же VM, что
            // экран, чтобы брать её WinPercentage и штатные последствия.
            Type screenManager = LoadedType("TaleWorlds.ScreenSystem.ScreenManager", "TaleWorlds.ScreenSystem");
            Type screenBase = LoadedType("TaleWorlds.ScreenSystem.ScreenBase", "TaleWorlds.ScreenSystem");
            MemberOf(screenManager, "TopScreen", Stat, screenBase);
            Type kingdomScreen = LoadedType("SandBox.GauntletUI.GauntletKingdomScreen", "SandBox.GauntletUI");
            Type kingdomVm = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.KingdomManagementVM",
                "TaleWorlds.CampaignSystem.ViewModelCollection");
            Type decisionsVm = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.KingdomDecisionsVM",
                "TaleWorlds.CampaignSystem.ViewModelCollection");
            Type decisionItem = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.ItemTypes.DecisionItemBaseVM",
                "TaleWorlds.CampaignSystem.ViewModelCollection");
            Type decisionOption = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.KingdomManagement.Decisions.DecisionOptionVM",
                "TaleWorlds.CampaignSystem.ViewModelCollection");
            MemberOf(kingdomScreen, "DataSource", Inst, kingdomVm);
            MemberOf(kingdomVm, "Decision", Inst, decisionsVm);
            MemberOf(decisionsVm, "CurrentDecision", Inst, decisionItem);
            Need(decisionsVm?.GetField("_queryData", BindingFlags.NonPublic | BindingFlags.Instance) != null,
                "KingdomDecisionsVM._queryData");
            Need(decisionsVm?.GetMethod("OnDecisionOver", BindingFlags.NonPublic | BindingFlags.Instance) != null,
                "KingdomDecisionsVM.OnDecisionOver()");
            Need(decisionsVm?.GetMethod("OnSingleDecisionOver", BindingFlags.NonPublic | BindingFlags.Instance) != null,
                "KingdomDecisionsVM.OnSingleDecisionOver()");
            MemberOf(decisionItem, "DecisionOptionsList", Inst,
                decisionItem?.GetProperty("DecisionOptionsList", Inst)?.PropertyType);
            MemberOf(decisionItem, "CanEndDecision", Inst, typeof(bool));
            MemberOf(decisionItem, "IsKingsDecisionOver", Inst, typeof(bool));
            MemberOf(decisionItem, "IsPlayerSupporter", Inst, typeof(bool));
            Method(decisionItem, "ExecuteFinalSelection", Inst, typeof(void));
            Need(decisionItem?.GetMethod("ExecuteDone", BindingFlags.NonPublic | BindingFlags.Instance) != null,
                "DecisionItemBaseVM.ExecuteDone()");
            MemberOf(decisionOption, "CanBeChosen", Inst, typeof(bool));
            MemberOf(decisionOption, "IsOptionForAbstain", Inst, typeof(bool));
            MemberOf(decisionOption, "WinPercentage", Inst, typeof(int));
            MemberOf(decisionOption, "Name", Inst, typeof(string));
            Need(decisionOption?.GetMethod("ExecuteSelection", BindingFlags.NonPublic | BindingFlags.Instance) != null,
                "DecisionOptionVM.ExecuteSelection()");
            Need(decisionOption?.GetMethod("OnSupportStrengthChange", BindingFlags.NonPublic | BindingFlags.Instance) != null,
                "DecisionOptionVM.OnSupportStrengthChange(Int32)");
            Type inquiryData = typeof(TaleWorlds.Library.InquiryData);
            FieldOf(inquiryData, "TitleText", typeof(string));
            FieldOf(inquiryData, "IsAffirmativeOptionShown", typeof(bool));
            FieldOf(inquiryData, "AffirmativeAction", typeof(Action));
            Method(typeof(TaleWorlds.Library.InformationManager), "HideInquiry", Stat, typeof(void));

            // Штатные случайные события: содержимое читается через публичный
            // Incident API, а слой закрывается тем же MapScreen, что и кнопка UI.
            Type incident = TypeNamed(campaignAssembly, "TaleWorlds.CampaignSystem.Incidents.Incident");
            Type textObject = LoadedType("TaleWorlds.Localization.TextObject", "TaleWorlds.Localization");
            // Очередь выпавшего события: по ней автопилот понимает, что выходить
            // из поселения ещё нельзя (Campaign.Tick 10136-10143 проверит условие
            // уже после выхода и упадёт на чужом null). Нужна и запись: предел
            // ожидания снимает очередь сам.
            MemberOf(mapState, "NextIncident", Inst, incident, needWrite: true);
            // Партия в расстройстве после боя стоит по праву: сторож движения
            // обязан отличать её от застрявшей.
            MemberOf(typeof(MobileParty), "IsDisorganized", Inst, typeof(bool));
            MemberOf(incident, "StringId", Inst, typeof(string));
            MemberOf(incident, "Title", Inst, textObject);
            MemberOf(incident, "NumOfOptions", Inst, typeof(int));
            Method(incident, "GetOptionText", Inst, textObject, typeof(int));
            Method(incident, "GetOptionHint", Inst,
                textObject != null ? typeof(List<>).MakeGenericType(textObject) : null, typeof(int));
            Method(incident, "InvokeOption", Inst,
                textObject != null ? typeof(List<>).MakeGenericType(textObject) : null, typeof(int));
            Type mapView = LoadedType("SandBox.View.Map.MapView", "SandBox.View");
            Type incidentView = LoadedType("SandBox.View.Map.MapIncidentView", "SandBox.View");
            FieldOf(incidentView, "Incident", incident);
            MethodInfo getMapView = mapScreen?.GetMethods(Inst)
                .FirstOrDefault(m => m.Name == "GetMapView" && m.IsGenericMethodDefinition && m.GetParameters().Length == 0);
            Need(getMapView != null, "MapScreen.GetMapView<T>()");
            Method(mapScreen, "RemoveMapView", Inst, typeof(void), mapView);
            Type simulationView = LoadedType("SandBox.GauntletUI.Map.GauntletMapBattleSimulationView", "SandBox.GauntletUI");
            Type simulationVm = simulationView?.GetField("_dataSource", BindingFlags.Instance | BindingFlags.NonPublic)?.FieldType;
            Need(simulationVm != null, "simulation view scoreboard");
            foreach (string flag in new[] { "IsOver", "IsSimulation", "ShowScoreboard" })
                MemberOf(simulationVm, flag, Inst, typeof(bool));
            Method(simulationVm, "ExecuteQuitAction", Inst, typeof(void));
            Type battleSimulation = simulationVm?.GetField("_battleSimulation", BindingFlags.Instance | BindingFlags.NonPublic)?.FieldType;
            Need(battleSimulation != null, "scoreboard native battle simulation");
            MemberOf(battleSimulation, "IsSimulationFinished", Inst, typeof(bool));

            VerifySettlementServices(campaignAssembly, gameState?.Assembly, helper);
            VerifyOperations(mapEvent, vec2, menuContext, gameMenu);
            VerifyBanditGathering(mapEvent, battleSide);
            VerifyConquest(campaignAssembly, mapEvent);
            VerifyPrisonerScreen(campaignAssembly);
            VerifyLootScreen(campaignAssembly);

            // ── Прочее
            MemberOf(typeof(Hero), "MainHero", Stat, typeof(Hero));
            MemberOf(typeof(Hero), "IsPrisoner", Inst, typeof(bool));
            MemberOf(typeof(Hero), "IsWounded", Inst, typeof(bool));
            MemberOf(typeof(Campaign), "Current", Stat, typeof(Campaign));

            Ok = Problems.Count == 0;
            Report = Ok
                ? "структура движка совпала со всеми " + _checked + " ожиданиями"
                : "НЕ СОВПАЛО (" + Problems.Count + " из " + _checked + "): " + string.Join("; ", Problems.ToArray());
            return Ok;
        }

        private static void VerifyConquest(Assembly campaign, Type mapEvent)
        {
            var mobile = typeof(MobileParty);
            MemberOf(typeof(Settlement), "All", Stat, typeof(TaleWorlds.Library.MBReadOnlyList<Settlement>));
            MemberOf(typeof(Kingdom), "Fiefs", Inst, typeof(TaleWorlds.Library.MBReadOnlyList<Town>));
            MemberOf(typeof(PlayerEncounter), "PlayerIsDefender", Stat, typeof(bool));
            var navigation = typeof(MobileParty.NavigationType);
            Method(typeof(SetPartyAiAction), "GetActionForBesiegingSettlement", Stat, typeof(void), mobile, typeof(Settlement), navigation, typeof(bool));
            Method(typeof(SetPartyAiAction), "GetActionForRaidingSettlement", Stat, typeof(void), mobile, typeof(Settlement), navigation, typeof(bool), typeof(bool));
            MemberOf(mobile, "Army", Inst, typeof(Army));
            MemberOf(typeof(Army), "LeaderParty", Inst, mobile);
            MemberOf(typeof(Army), "Cohesion", Inst, typeof(float));
            Method(typeof(Army), "BoostCohesionWithInfluence", Inst, typeof(void), typeof(float), typeof(int));
            MemberOf(typeof(Clan), "Influence", Inst, typeof(float));
            Method(typeof(ChangeClanInfluenceAction), "Apply", Stat, typeof(void), typeof(Clan), typeof(float));
            Method(typeof(DisbandArmyAction), "ApplyByUnknownReason", Stat, typeof(void), typeof(Army));
            Type members = typeof(TaleWorlds.Library.MBReadOnlyList<MobileParty>);
            MemberOf(typeof(PartyThinkParams), "PossibleArmyMembersUponArmyCreation", Inst, members);
            Method(typeof(Kingdom), "CreateArmy", Inst, typeof(void), typeof(Hero), typeof(Settlement), typeof(Army.ArmyTypes), members);
            Type model = MemberType(typeof(GameModels), "ArmyManagementCalculationModel", Inst, false, out _);
            Need(model != null, "GameModels.ArmyManagementCalculationModel");
            var text = typeof(TaleWorlds.Localization.TextObject).MakeByRefType();
            Method(model, "CanPlayerCreateArmy", Inst, typeof(bool), text);
            Method(model, "CheckPartyEligibility", Inst, typeof(bool), mobile, text);
            Method(model, "CalculatePartyInfluenceCost", Inst, typeof(int), mobile, mobile);
            Method(model, "GetCohesionBoostInfluenceCost", Inst, typeof(int), typeof(Army), typeof(int));
            Type siege = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Siege.SiegeEvent");
            MemberOf(mobile, "SiegeEvent", Inst, siege);
            MemberOf(siege, "BesiegedSettlement", Inst, typeof(Settlement));
            Type camp = MemberType(siege, "BesiegerCamp", Inst, false, out _);
            Need(camp != null, "SiegeEvent.BesiegerCamp");
            MemberOf(camp, "LeaderParty", Inst, mobile);
            MemberOf(camp, "IsReadyToBesiege", Inst, typeof(bool));
            Type strategy = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Siege.SiegeStrategy");
            Type strategies = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Siege.DefaultSiegeStrategies");
            MemberOf(strategies, "AllAttackerStrategies", Stat, strategy != null ? typeof(IEnumerable<>).MakeGenericType(strategy) : null);
            Type side = siege?.GetMethod("GetSiegeEventSide", Inst)?.ReturnType;
            Method(siege, "GetSiegeEventSide", Inst, side, typeof(TaleWorlds.Core.BattleSideEnum));
            Method(side, "SetSiegeStrategy", Inst, typeof(void), strategy);
            Type siegeModel = MemberType(typeof(GameModels), "SiegeEventModel", Inst, false, out _);
            Need(siegeModel != null, "GameModels.SiegeEventModel");
            Method(siegeModel, "GetSiegeStrategyScore", Inst, typeof(float), siege, typeof(TaleWorlds.Core.BattleSideEnum), strategy);
            foreach (string flag in new[] { "IsRaid", "IsSallyOut", "IsSiegeOutside" }) MemberOf(mapEvent, flag, Inst, typeof(bool));
        }

        private static void VerifyBanditGathering(Type mapEvent, Type side)
        {
            Type battleEnum = MemberType(mapEvent, "PlayerSide", Inst, false, out _);
            MemberOf(mapEvent, "IsFieldBattle", Inst, typeof(bool));
            Type context = MemberType(mapEvent, "SimulationContext", Inst, false, out _);
            Need(context != null && context.IsEnum, "MapEvent.SimulationContext: enum");
            Method(typeof(PartyBase), "GetCustomStrength", Inst, typeof(float), battleEnum, context);
            Method(mapEvent, "CanPartyJoinBattle", Inst, typeof(bool), typeof(PartyBase), battleEnum);
            MemberOf(typeof(PartyBase), "MapEventSide", Inst, side, needWrite: true);
            MemberOf(typeof(PartyBase), "NumberOfHealthyMembers", Inst, typeof(int));
            Type parties = MemberType(side, "Parties", Inst, false, out _);
            Type entry = parties?.IsGenericType == true ? parties.GetGenericArguments()[0] : null;
            Need(entry != null && typeof(System.Collections.IEnumerable).IsAssignableFrom(parties), "MapEventSide.Parties: enumerable");
            MemberOf(entry, "Party", Inst, typeof(PartyBase));
            Type bandits = MemberType(typeof(MobileParty), "AllBanditParties", Stat, false, out _);
            Need(bandits != null && typeof(System.Collections.Generic.IEnumerable<MobileParty>).IsAssignableFrom(bandits), "MobileParty.AllBanditParties: enumerable");
            MemberOf(typeof(MobileParty), "IsEngaging", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsDisbanding", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsTransitionInProgress", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "AttachedTo", Inst, typeof(MobileParty));
            Type attached = MemberType(typeof(MobileParty), "AttachedParties", Inst, false, out _);
            Need(attached != null && typeof(System.Collections.Generic.IEnumerable<MobileParty>).IsAssignableFrom(attached), "MobileParty.AttachedParties: enumerable");
            MemberOf(attached, "Count", Inst, typeof(int));
            Type powerModel = MemberType(typeof(GameModels), "MilitaryPowerModel", Inst, false, out _);
            Need(powerModel != null, "GameModels.MilitaryPowerModel");
            Type position = MemberType(typeof(MobileParty), "Position", Inst, false, out _);
            Method(powerModel, "GetContextForPosition", Inst, context, position);
            Type starter = TypeNamed(typeof(Campaign).Assembly, "TaleWorlds.CampaignSystem.CampaignGameStarter");
            Type sentence = TypeNamed(typeof(Campaign).Assembly, "TaleWorlds.CampaignSystem.Conversation.ConversationSentence");
            Type condition = sentence?.GetNestedType("OnConditionDelegate");
            Type consequence = sentence?.GetNestedType("OnConsequenceDelegate");
            Method(starter, "AddPlayerLine", Inst, sentence, typeof(string), typeof(string), typeof(string), typeof(string),
                condition, consequence, typeof(int), sentence?.GetNestedType("OnClickableConditionDelegate"), sentence?.GetNestedType("OnPersuasionOptionDelegate"));
            Method(condition, "Invoke", Inst, typeof(bool));
            Type sessionEvent = MemberType(typeof(CampaignEvents), "OnSessionLaunchedEvent", Stat, false, out _);
            Method(sessionEvent, "AddNonSerializedListener", Inst, typeof(void), typeof(object),
                starter == null ? null : typeof(Action<>).MakeGenericType(starter));
        }

        private static void VerifyLootScreen(Assembly campaign)
        {
            Type state = TypeNamed(campaign, "TaleWorlds.CampaignSystem.GameState.InventoryState");
            Type logic = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Inventory.InventoryLogic");
            Type screen = LoadedType("SandBox.GauntletUI.GauntletInventoryScreen", "SandBox.GauntletUI");
            Type vm = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.Inventory.SPInventoryVM", "TaleWorlds.CampaignSystem.ViewModelCollection");
            MemberExists(state, "Handler", Inst);
            MemberExists(state, "InventoryMode", Inst);
            MemberOf(state, "InventoryLogic", Inst, logic);
            MemberOf(logic, "IsTrading", Inst, typeof(bool));
            MemberOf(logic, "TotalAmount", Inst, typeof(int));
            Need(screen?.GetField("_dataSource", BindingFlags.Instance | BindingFlags.NonPublic)?.FieldType == vm && vm != null, "GauntletInventoryScreen._dataSource");
            Need(vm?.GetField("_inventoryLogic", BindingFlags.Instance | BindingFlags.NonPublic)?.FieldType == logic && logic != null, "SPInventoryVM._inventoryLogic");
            var side = logic?.GetNestedType("InventorySide");
            var elements = side == null ? null : logic.GetMethod("GetElementsInRoster", new[] { side });
            Need(elements != null && typeof(System.Collections.IEnumerable).IsAssignableFrom(elements.ReturnType), "InventoryLogic.GetElementsInRoster");
            Need(vm?.GetProperty("LeftSearchText")?.GetSetMethod() != null, "SPInventoryVM.LeftSearchText setter");
            Method(vm, "ExecuteFilterNone", Inst, typeof(void));
            Method(vm, "ExecuteBuyAllItems", Inst, typeof(void));
            Method(vm, "ExecuteCompleteTranstactions", Inst, typeof(void));
            Method(vm, "HandleDone", BindingFlags.Instance | BindingFlags.NonPublic, typeof(void));
        }
        private static void VerifyPrisonerScreen(Assembly campaign)
        {
            Type state = TypeNamed(campaign, "TaleWorlds.CampaignSystem.GameState.PartyState");
            Type logic = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Party.PartyScreenLogic");
            Type roster = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Roster.TroopRoster");
            Type screen = LoadedType("SandBox.GauntletUI.GauntletPartyScreen", "SandBox.GauntletUI");
            Type vm = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.Party.PartyVM", "TaleWorlds.CampaignSystem.ViewModelCollection");
            Type troop = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.Party.PartyCharacterVM", "TaleWorlds.CampaignSystem.ViewModelCollection");
            Type side = logic?.GetNestedType("PartyRosterSide");
            Type data = logic == null ? null : MemberType(logic, "CurrentData", Inst, false, out _);
            Need(data != null, "PartyScreenLogic.CurrentData");
            MemberOf(data, "RightPrisonerRoster", Inst, roster);
            MemberOf(data, "RightMemberRoster", Inst, roster);
            MemberOf(logic, "RightPartyMembersSizeLimit", Inst, typeof(int));
            MemberOf(logic, "RightPartyPrisonersSizeLimit", Inst, typeof(int));
            MemberOf(logic, "RightOwnerParty", Inst, typeof(PartyBase));
            Method(logic, "IsDoneActive", Inst, typeof(bool));
            MemberExists(state, "Handler", Inst);
            MemberNamed(state, "PartyScreenMode", Inst, "PartyScreenMode");
            MemberOf(state, "PartyScreenLogic", Inst, logic);
            Need(screen?.GetField("_dataSource", BindingFlags.Instance | BindingFlags.NonPublic)?.FieldType == vm && vm != null,
                "GauntletPartyScreen._dataSource: PartyVM");
            MemberOf(vm, "PartyScreenLogic", Inst, logic);
            MemberOf(vm, "IsAnyPopUpOpen", Inst, typeof(bool));
            var list = vm?.GetProperty("OtherPartyPrisoners", Inst);
            Need(list?.GetGetMethod() != null && typeof(System.Collections.IEnumerable).IsAssignableFrom(list.PropertyType), "PartyVM.OtherPartyPrisoners: enumerable");
            var rescuedList = vm?.GetProperty("OtherPartyTroops", Inst);
            Need(rescuedList?.GetGetMethod() != null && typeof(System.Collections.IEnumerable).IsAssignableFrom(rescuedList.PropertyType), "PartyVM.OtherPartyTroops: enumerable");
            MemberOf(troop, "IsTroopTransferrable", Inst, typeof(bool));
            MemberOf(troop, "Side", Inst, side);
            MemberNamed(troop, "Troop", Inst, "TroopRosterElement");
            Method(vm, "OnTransferTroop", BindingFlags.Instance | BindingFlags.NonPublic, typeof(void), troop, typeof(int), typeof(int), side);
            Method(vm, "ExecuteRemoveZeroCounts", Inst, typeof(void));
            Method(vm, "ExecuteDone", Inst, typeof(void));
            Method(vm, "CloseScreenInternal", BindingFlags.Instance | BindingFlags.NonPublic, typeof(void));
            Need(typeof(TaleWorlds.Library.InformationManager).GetEvent("OnShowInquiry", Stat)?.EventHandlerType
                == typeof(Action<TaleWorlds.Library.InquiryData, bool, bool>), "InformationManager.OnShowInquiry: Action<InquiryData,bool,bool>");
        }

        private static void VerifyOperations(Type mapEvent, Type vector, Type menuContext, Type gameMenu)
        {
            Type hideout = TypeNamed(typeof(Campaign).Assembly, "TaleWorlds.CampaignSystem.Settlements.Hideout");
            Type time = TypeNamed(typeof(Campaign).Assembly, "TaleWorlds.CampaignSystem.CampaignTime");
            MemberOf(hideout, "Settlement", Inst, typeof(Settlement));
            MemberOf(hideout, "IsSpotted", Inst, typeof(bool));
            MemberOf(hideout, "IsInfested", Inst, typeof(bool));
            MemberOf(hideout, "NextPossibleAttackTime", Inst, time);
            var all = hideout?.GetProperty("All", Stat);
            Need(all?.GetGetMethod() != null && typeof(IEnumerable<>).MakeGenericType(hideout).IsAssignableFrom(all.PropertyType), "Hideout.All: enumerable Hideout");
            MemberOf(typeof(Settlement), "Hideout", Inst, hideout);
            MemberOf(typeof(Settlement), "IsHideout", Inst, typeof(bool));
            MemberOf(typeof(Settlement), "IsVisible", Inst, typeof(bool));
            MemberOf(typeof(Settlement), "Position", Inst, vector);
            Method(vector, "DistanceSquared", Inst, typeof(float), vector);
            MemberOf(time, "IsPast", Inst, typeof(bool));
            MemberOf(time, "IsNightTime", Inst, typeof(bool));
            MemberOf(typeof(MobileParty), "IsCurrentlyAtSea", Inst, typeof(bool));
            MemberOf(mapEvent, "IsHideoutBattle", Inst, typeof(bool));
            MemberOf(mapEvent, "IsSiegeAssault", Inst, typeof(bool));
            MemberNamed(mapEvent, "PlayerSide", Inst, "BattleSideEnum");
            Method(typeof(SetPartyAiAction), "GetActionForDefendingSettlement", Stat, typeof(void),
                typeof(MobileParty), typeof(Settlement), typeof(MobileParty.NavigationType), typeof(bool), typeof(bool));
            Method(gameMenu, "StartWait", Inst, typeof(void));
            MemberNamed(menuContext, "Handler", Inst, "IMenuContextHandler");
            Type context = LoadedType("SandBox.View.Menu.MenuViewContext", "SandBox.View");
            Type views = context?.GetProperty("MenuViews", Inst)?.PropertyType;
            Need(views != null && typeof(System.Collections.IEnumerable).IsAssignableFrom(views), "MenuViewContext.MenuViews: enumerable");
            Type view = LoadedType("SandBox.GauntletUI.Menu.GauntletMenuTroopSelectionView", "SandBox.GauntletUI");
            Type vm = LoadedType("TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.TroopSelection.GameMenuTroopSelectionVM", "TaleWorlds.CampaignSystem.ViewModelCollection");
            Need(view?.GetField("_dataSource", BindingFlags.Instance | BindingFlags.NonPublic)?.FieldType == vm && vm != null,
                "GauntletMenuTroopSelectionView._dataSource: GameMenuTroopSelectionVM");
            MemberOf(vm, "IsEnabled", Inst, typeof(bool));
            MemberOf(vm, "IsDoneEnabled", Inst, typeof(bool));
            Method(vm, "ExecuteDone", Inst, typeof(void));
        }

        /// <summary>Обслуживание партии в поселении (SettlementServices): еда, найм,
        /// пленные. Всё по имени — в другой версии игры это строки «не совпало».</summary>
        private static void VerifySettlementServices(Assembly campaign, Assembly core, Type partyHelper)
        {
            Type itemRoster = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Roster.ItemRoster");
            Type troopRoster = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Roster.TroopRoster");
            Type troopElement = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Roster.TroopRosterElement");
            Type character = TypeNamed(campaign, "TaleWorlds.CampaignSystem.CharacterObject");
            Type gameModels = TypeNamed(campaign, "TaleWorlds.CampaignSystem.GameModels");
            Type explained = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ExplainedNumber");
            Type faction = TypeNamed(campaign, "TaleWorlds.CampaignSystem.IFaction");
            Type partyBase = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Party.PartyBase");
            Type foodBuying = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ComponentInterfaces.PartyFoodBuyingModel");
            Type foodConsumption = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ComponentInterfaces.MobilePartyFoodConsumptionModel");
            Type wages = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ComponentInterfaces.PartyWageModel");
            Type access = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ComponentInterfaces.SettlementAccessModel");
            Type ransom = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ComponentInterfaces.RansomValueCalculationModel");
            Type buyFood = TypeNamed(campaign, "TaleWorlds.CampaignSystem.CampaignBehaviors.PartiesBuyFoodCampaignBehavior");
            Type sellItems = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Actions.SellItemsAction");
            Type giveGold = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Actions.GiveGoldAction");
            Type sellPrisoners = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Actions.SellPrisonersAction");
            Type village = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Settlements.Village");
            Type town = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Settlements.Town");
            Type heroHelper = TypeNamed(campaign, "Helpers.HeroHelper");
            Type item = TypeNamed(core, "TaleWorlds.Core.ItemObject");
            Type equipment = TypeNamed(core, "TaleWorlds.Core.EquipmentElement");
            Type itemElement = TypeNamed(core, "TaleWorlds.Core.ItemRosterElement");
            Type horse = TypeNamed(core, "TaleWorlds.Core.HorseComponent");

            Type action = access?.GetNestedType("SettlementAction");
            Need(action != null && action.IsEnum && Enum.GetNames(action).Contains("Trade") && Enum.GetNames(action).Contains("RecruitTroops"),
                "SettlementAccessModel.SettlementAction: Trade, RecruitTroops");
            MethodInfo location = access?.GetMethod("CanMainHeroAccessLocation", Inst);
            Type text = location != null && location.GetParameters().Length == 4 ? location.GetParameters()[3].ParameterType.GetElementType() : null;
            Need(text != null && text.FullName == "TaleWorlds.Localization.TextObject", "тип TaleWorlds.Localization.TextObject");
            Type notables = MemberType(typeof(Settlement), "Notables", Inst, false, out _);
            Need(notables != null && notables.IsGenericType && notables.GetGenericTypeDefinition().Name == "MBReadOnlyList`1"
                 && notables.GetGenericArguments()[0] == typeof(Hero), "Settlement.Notables : MBReadOnlyList<Hero>");
            Type information = TypeNamed(notables?.Assembly, "TaleWorlds.Library.InformationManager");

            // Модели и поведение движка
            MemberOf(typeof(Campaign), "Models", Inst, gameModels);
            Need(typeof(Campaign).GetMethods(Inst).Any(m => m.Name == "GetCampaignBehavior" && m.IsGenericMethodDefinition && m.GetParameters().Length == 0),
                "Campaign.GetCampaignBehavior<T>()");
            MemberOf(gameModels, "PartyFoodBuyingModel", Inst, foodBuying);
            MemberOf(gameModels, "MobilePartyFoodConsumptionModel", Inst, foodConsumption);
            MemberOf(gameModels, "PartyWageModel", Inst, wages);
            MemberOf(gameModels, "SettlementAccessModel", Inst, access);
            MemberOf(gameModels, "RansomValueCalculationModel", Inst, ransom);
            MemberOf(foodBuying, "MinimumDaysFoodToLastWhileBuyingFoodFromTown", Inst, typeof(float));
            MemberOf(foodBuying, "MinimumDaysFoodToLastWhileBuyingFoodFromVillage", Inst, typeof(float));
            Method(foodBuying, "FindItemToBuy", Inst, typeof(void), typeof(MobileParty), typeof(Settlement),
                itemElement?.MakeByRefType(), typeof(float).MakeByRefType());
            Method(foodConsumption, "DoesPartyConsumeFood", Inst, typeof(bool), typeof(MobileParty));
            Method(wages, "GetTroopRecruitmentCost", Inst, explained, character, typeof(Hero), typeof(bool));
            Method(wages, "GetTotalWage", Inst, explained, typeof(MobileParty), troopRoster, typeof(bool));
            MemberOf(explained, "RoundedResultNumber", Inst, typeof(int));
            Method(access, "CanMainHeroDoSettlementAction", Inst, typeof(bool), typeof(Settlement), action,
                typeof(bool).MakeByRefType(), text?.MakeByRefType());
            Method(access, "CanMainHeroAccessLocation", Inst, typeof(bool), typeof(Settlement), typeof(string),
                typeof(bool).MakeByRefType(), text?.MakeByRefType());
            Method(ransom, "PrisonerRansomValue", Inst, typeof(int), character, typeof(Hero));
            Method(buyFood, "CalculateFoodCountToBuy", BindingFlags.Instance | BindingFlags.NonPublic, typeof(int),
                typeof(MobileParty), typeof(float));

            // Действия
            Method(sellItems, "Apply", Stat, typeof(void), partyBase, partyBase, itemElement, typeof(int), typeof(Settlement));
            Method(giveGold, "ApplyBetweenCharacters", Stat, typeof(void), typeof(Hero), typeof(Hero), typeof(int), typeof(bool));
            Method(sellPrisoners, "ApplyForSelectedPrisoners", Stat, typeof(void), partyBase, partyBase, troopRoster);
            Method(partyHelper, "GetPlayerPrisonersPlayerCanSell", Stat, troopRoster);
            Method(heroHelper, "GetVolunteerTroopsOfHeroForRecruitment", Stat,
                character != null ? typeof(List<>).MakeGenericType(character) : null, typeof(Hero));
            Method(heroHelper, "HeroCanRecruitFromHero", Stat, typeof(bool), typeof(Hero), typeof(Hero), typeof(int));
            Method(typeof(CampaignEventDispatcher), "OnUnitRecruited", Inst, typeof(void), character, typeof(int));
            Method(information, "IsAnyInquiryActive", Stat, typeof(bool));

            // Состояние героя, партии и поселения
            MemberOf(typeof(Hero), "Gold", Inst, typeof(int));
            MemberOf(typeof(Hero), "CanHaveRecruits", Inst, typeof(bool));
            MemberOf(typeof(Hero), "VolunteerTypes", Inst, character?.MakeArrayType());
            MemberExists(typeof(Hero), "Name", Inst);
            MemberOf(character, "IsHero", Inst, typeof(bool));
            MemberOf(character, "IsMounted", Inst, typeof(bool));
            MemberOf(character, "IsRanged", Inst, typeof(bool));
            MemberOf(character, "Tier", Inst, typeof(int));
            MemberExists(character, "Name", Inst);
            MemberOf(typeof(MobileParty), "Party", Inst, partyBase);
            MemberOf(typeof(MobileParty), "MemberRoster", Inst, troopRoster);
            MemberOf(typeof(MobileParty), "PrisonRoster", Inst, troopRoster);
            MemberOf(typeof(MobileParty), "ItemRoster", Inst, itemRoster);
            MemberOf(typeof(MobileParty), "MapFaction", Inst, faction);
            MemberOf(typeof(MobileParty), "TotalWage", Inst, typeof(int));
            MemberOf(typeof(MobileParty), "FoodChange", Inst, typeof(float));
            MemberOf(typeof(MobileParty), "TotalFoodAtInventory", Inst, typeof(int));
            MemberOf(partyBase, "PartySizeLimit", Inst, typeof(int));
            MemberOf(partyBase, "NumberOfAllMembers", Inst, typeof(int));
            // Имена сторон чужого боя в журнале ухода (JoinOrLeaveForeignBattle).
            MemberOf(partyBase, "MobileParty", Inst, typeof(MobileParty));
            MemberOf(partyBase, "Settlement", Inst, typeof(Settlement));
            MemberExists(typeof(MobileParty), "Name", Inst);
            MemberExists(typeof(Settlement), "Name", Inst);
            MemberOf(typeof(Settlement), "IsTown", Inst, typeof(bool));
            MemberOf(typeof(Settlement), "IsRaided", Inst, typeof(bool));
            MemberOf(typeof(Settlement), "IsUnderRaid", Inst, typeof(bool));
            MemberOf(typeof(Settlement), "Party", Inst, partyBase);
            MemberOf(typeof(Settlement), "ItemRoster", Inst, itemRoster);
            MemberOf(typeof(Settlement), "MapFaction", Inst, faction);
            MemberOf(typeof(Settlement), "StringId", Inst, typeof(string)); // ключ отметок проходов в сейве
            MemberOf(typeof(Settlement), "Village", Inst, village);
            MemberOf(typeof(Settlement), "Town", Inst, town);
            MemberOf(village, "TradeBound", Inst, typeof(Settlement));
            MemberOf(village, "Bound", Inst, typeof(Settlement));
            Method(town, "GetItemPrice", Inst, typeof(int), equipment, typeof(MobileParty), typeof(bool));
            Method(faction, "IsAtWarWith", Inst, typeof(bool), faction);

            // Ростеры и предметы
            MemberOf(itemRoster, "TotalFood", Inst, typeof(int));
            Method(itemRoster, "FindIndexOfElement", Inst, typeof(int), equipment);
            Method(itemRoster, "GetElementNumber", Inst, typeof(int), typeof(int));
            MemberOf(itemElement, "EquipmentElement", Inst, equipment);
            Need(itemElement != null && equipment != null && itemElement.GetConstructor(new[] { equipment, typeof(int) }) != null,
                "ItemRosterElement(EquipmentElement, int)");
            MemberOf(equipment, "Item", Inst, item);
            // Main-hero equipment and paid inventory sales.
            MemberOf(typeof(MobileParty), "TotalWeightCarried", Inst, typeof(float));
            MemberOf(typeof(MobileParty), "InventoryCapacity", Inst, typeof(int));
            Type upgradeModel = TypeNamed(campaign, "TaleWorlds.CampaignSystem.ComponentInterfaces.PartyTroopUpgradeModel");
            Type category = TypeNamed(core, "TaleWorlds.Core.ItemCategory");
            Type formation = TypeNamed(core, "TaleWorlds.Core.FormationClass");
            MemberOf(gameModels, "PartyTroopUpgradeModel", Inst, upgradeModel);
            Method(upgradeModel, "CanPartyUpgradeTroopToTarget", Inst, typeof(bool), partyBase, character, character);
            MemberOf(character, "UpgradeTargets", Inst, character?.MakeArrayType());
            MemberOf(character, "UpgradeRequiresItemFromCategory", Inst, category);
            MemberOf(character, "DefaultFormationClass", Inst, formation);
            Method(character, "GetUpgradeXpCost", Inst, typeof(int), partyBase, typeof(int));
            Method(character, "GetUpgradeGoldCost", Inst, typeof(int), partyBase, typeof(int));
            MemberOf(item, "ItemCategory", Inst, category);
            Method(troopRoster, "FindIndexOfTroop", Inst, typeof(int), character);
            Method(troopRoster, "GetElementCopyAtIndex", Inst, troopElement, typeof(int));
            Method(troopRoster, "GetElementXp", Inst, typeof(int), typeof(int));
            Method(troopRoster, "SetElementXp", Inst, typeof(void), typeof(int), typeof(int));
            Method(typeof(CampaignEventDispatcher), "OnPlayerUpgradedTroops", Inst, typeof(void), character, character, typeof(int));
            Type equipmentSet = TypeNamed(core, "TaleWorlds.Core.Equipment");
            Type equipmentIndex = TypeNamed(core, "TaleWorlds.Core.EquipmentIndex");
            Type tracker = TypeNamed(campaign, "TaleWorlds.CampaignSystem.IViewDataTracker");
            Type characterHelper = TypeNamed(campaign, "Helpers.CharacterHelper");
            Type basicCharacter = TypeNamed(core, "TaleWorlds.Core.BasicCharacterObject");
            Type modifier = TypeNamed(core, "TaleWorlds.Core.ItemModifier");
            Type armor = TypeNamed(core, "TaleWorlds.Core.ArmorComponent");
            Type monster = TypeNamed(core, "TaleWorlds.Core.Monster");
            Type weapon = TypeNamed(core, "TaleWorlds.Core.WeaponComponentData");
            Type settlementComponent = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Settlements.SettlementComponent");
            MemberOf(typeof(Hero), "BattleEquipment", Inst, equipmentSet);
            Method(typeof(Hero), "CanHeroEquipmentBeChanged", Inst, typeof(bool));
            Method(equipmentSet, "get_Item", Inst, equipment, equipmentIndex);
            Method(equipmentSet, "set_Item", Inst, typeof(void), equipmentIndex, equipment);
            Method(characterHelper, "CanUseItem", Stat, typeof(bool), basicCharacter, equipment);
            Method(tracker, "GetInventoryLocks", Inst, typeof(IEnumerable<string>));
            MemberOf(equipment, "IsEmpty", Inst, typeof(bool));
            MemberOf(equipment, "IsQuestItem", Inst, typeof(bool));
            MemberOf(equipment, "ItemValue", Inst, typeof(int));
            MemberOf(equipment, "ItemModifier", Inst, modifier);
            MemberOf(modifier, "StringId", Inst, typeof(string));
            foreach (string armorMethod in new[] { "GetModifiedHeadArmor", "GetModifiedBodyArmor", "GetModifiedArmArmor", "GetModifiedLegArmor", "GetModifiedMountBodyArmor" })
                Method(equipment, armorMethod, Inst, typeof(int));
            MemberOf(item, "NotMerchandise", Inst, typeof(bool));
            MemberOf(item, "ArmorComponent", Inst, armor);
            MemberOf(item, "PrimaryWeapon", Inst, weapon);
            MemberOf(weapon, "ItemUsage", Inst, typeof(string));
            MemberOf(horse, "Monster", Inst, monster);
            MemberOf(monster, "FamilyType", Inst, typeof(int));
            MemberOf(armor, "FamilyType", Inst, typeof(int));
            MemberOf(typeof(Settlement), "SettlementComponent", Inst, settlementComponent);
            MemberOf(settlementComponent, "Gold", Inst, typeof(int));
            Method(equipment, "IsEqualTo", Inst, typeof(bool), equipment);
            MemberOf(item, "HasHorseComponent", Inst, typeof(bool));
            MemberOf(item, "HorseComponent", Inst, horse);
            MemberExists(item, "Name", Inst);
            MemberOf(horse, "IsLiveStock", Inst, typeof(bool));
            MemberOf(horse, "MeatCount", Inst, typeof(int));
            Method(troopRoster, "CreateDummyTroopRoster", Stat, troopRoster);
            Method(troopRoster, "Add", Inst, typeof(void), troopElement);
            Method(troopRoster, "AddToCounts", Inst, typeof(int), character, typeof(int), typeof(bool), typeof(int),
                typeof(int), typeof(bool), typeof(int));
            MethodInfo list = troopRoster?.GetMethod("GetTroopRoster", Inst, null, Type.EmptyTypes, null);
            Need(list != null && list.ReturnType.IsGenericType && list.ReturnType.GetGenericTypeDefinition().Name == "MBList`1"
                 && list.ReturnType.GetGenericArguments()[0] == troopElement, "TroopRoster.GetTroopRoster() → MBList<TroopRosterElement>");
            MemberOf(troopRoster, "TotalManCount", Inst, typeof(int));
            MemberOf(troopRoster, "TotalWounded", Inst, typeof(int));
            MemberOf(troopRoster, "TotalRegulars", Inst, typeof(int));

            // Недельная сводка прогресса (AutopilotBehavior.WriteWeeklyProgress)
            MemberOf(typeof(Clan), "PlayerClan", Stat, typeof(Clan));
            MemberOf(typeof(Clan), "MapFaction", Inst, faction);
            Type fiefs = MemberType(typeof(Clan), "Fiefs", Inst, false, out _);
            Need(fiefs != null && fiefs.IsGenericType && fiefs.GetGenericTypeDefinition().Name == "MBReadOnlyList`1"
                 && fiefs.GetGenericArguments()[0] == town, "Clan.Fiefs : MBReadOnlyList<Town>");
            Type villages = MemberType(typeof(Clan), "Villages", Inst, false, out _);
            Need(villages != null && villages.IsGenericType && villages.GetGenericTypeDefinition().Name == "MBReadOnlyList`1"
                 && villages.GetGenericArguments()[0] == village, "Clan.Villages : MBReadOnlyList<Village>");
            MemberOf(town, "Settlement", Inst, typeof(Settlement));
            MemberOf(typeof(Settlement), "IsCastle", Inst, typeof(bool));
            Type kingdom = TypeNamed(campaign, "TaleWorlds.CampaignSystem.Kingdom");
            Type factionHelper = TypeNamed(campaign, "Helpers.FactionHelper");
            Method(factionHelper, "GetEnemyKingdoms", Stat,
                kingdom != null ? typeof(IEnumerable<>).MakeGenericType(kingdom) : null, faction);
            MemberExists(kingdom, "Name", Inst);
            MemberOf(troopRoster, "TotalHeroes", Inst, typeof(int));
            MemberOf(troopElement, "Character", Inst, character);
            MemberOf(troopElement, "Number", Inst, typeof(int));
        }

        private static void Need(bool condition, string what)
        {
            _checked++;
            if (!condition)
            {
                Problems.Add(what);
            }
        }

        /// <summary>Тип по полному имени. Нет — несовпадение, и проверки его членов
        /// тоже не пройдут: их null-тип ниже засчитывается как «не совпало».</summary>
        private static Type TypeNamed(Assembly assembly, string fullName)
        {
            Type type = assembly?.GetType(fullName);
            Need(type != null, "тип " + fullName);
            return type;
        }

        /// <summary>Тип из сборки, которую мод не подключает: сначала среди уже
        /// загруженных, затем по имени сборки (в игре её грузит модуль SandBox).</summary>
        private static Type LoadedType(string fullName, string assemblyName)
        {
            Type type = AppDomain.CurrentDomain.GetAssemblies()
                            .Select(a => a.GetType(fullName))
                            .FirstOrDefault(t => t != null)
                        ?? Type.GetType(fullName + ", " + assemblyName);
            Need(type != null, "тип " + fullName);
            return type;
        }

        /// <summary>Метод с точными параметрами и возвращаемым типом.</summary>
        private static void Method(Type type, string name, BindingFlags flags, Type returns, params Type[] args)
        {
            bool typesKnown = type != null && returns != null && Array.TrueForAll(args, a => a != null);
            MethodInfo m = typesKnown ? type.GetMethod(name, flags, null, args, null) : null;
            Need(m != null && m.ReturnType == returns,
                (type?.Name ?? "?") + "." + name + "(" + args.Length + " арг.) → " + (returns?.Name ?? "?"));
        }

        /// <summary>Свойство или поле нужного типа (и с записью, если она нужна).</summary>
        private static void MemberOf(Type type, string name, BindingFlags flags, Type expected, bool needWrite = false)
        {
            bool writable = false;
            Type actual = type == null ? null : MemberType(type, name, flags, needWrite, out writable);
            // CampaignVec2 берётся из поля движка, и при несовпадении его имя —
            // уже чужое; в сообщении нужно ОЖИДАЕМОЕ имя, иначе оно путает.
            string label = expected == null ? "?"
                : expected.Name == "CampaignVec2" || name == "Position" || name == "GatePosition" ? "CampaignVec2"
                : expected.Name;
            Need(actual != null && actual == expected && (!needWrite || writable),
                (type?.Name ?? "?") + "." + name + " : " + label + (needWrite ? " (запись)" : ""));
        }

        private static void MemberNamed(Type type, string name, BindingFlags flags, string typeName, bool needWrite = false)
        {
            bool writable = false;
            Type actual = type == null ? null : MemberType(type, name, flags, needWrite, out writable);
            Need(actual != null && actual.Name == typeName && (!needWrite || writable),
                (type?.Name ?? "?") + "." + name + " : " + typeName + (needWrite ? " (запись)" : ""));
        }

        private static void MemberExists(Type type, string name, BindingFlags flags)
        {
            Need(type != null && MemberType(type, name, flags, false, out _) != null, (type?.Name ?? "?") + "." + name);
        }

        private static void FieldOf(Type type, string name, Type expected)
        {
            Need(type != null && expected != null && type.GetField(name, Inst)?.FieldType == expected,
                (type?.Name ?? "?") + "." + name + " : " + (expected?.Name ?? "?"));
        }

        private static void FieldNamed(Type type, string name, string expectedTypeName)
        {
            Need(type != null && type.GetField(name, Inst)?.FieldType.Name == expectedTypeName,
                (type?.Name ?? "?") + "." + name + " : " + expectedTypeName);
        }

        private static Type MemberType(Type type, string name, BindingFlags flags, bool needWrite, out bool writable)
        {
            PropertyInfo p = type.GetProperty(name, flags);
            if (p != null)
            {
                writable = p.CanWrite && p.GetSetMethod() != null;
                // Мод каждое проверяемое свойство ЧИТАЕТ. Без публичного чтения
                // совпадение типа ничего не значит: вызов упал бы посреди
                // кампании (контрпример проверки 13.09, tests/ContractGetter).
                return p.GetGetMethod() != null ? p.PropertyType : null;
            }
            FieldInfo f = type.GetField(name, flags);
            if (f != null)
            {
                writable = !f.IsInitOnly;
                return f.FieldType;
            }
            writable = false;
            return null;
        }
    }
}
