# Игра без человека: что держит партию игрока и чем это снимается (1.4.8)

Дата: 13.09.2026. Источник — декомпиляция `D:\shedlink-build\bl-decomp\*.decompiled.cs`
(CampaignSystem, SandBox, SandBox.View, SandBox.GauntletUI, *.ViewModelCollection,
TaleWorlds.Core, TaleWorlds.Library, TaleWorlds.MountAndBlade.GauntletUI).

Карта для следующих кусков автопилота: бои, плен, окна, услуги поселения. Номера
строк — по этим файлам. **Пометка «прочитано» — я открыл код сам; «по разведке» —
пересказ отчёта субагента, перед правкой открыть и сверить.**

## Сделано в коде (коммит `ee058ae`)

| Что | Чем в движке | Статус |
|---|---|---|
| Пребывание в поселении | пункт `town_wait` / `village_wait` → `town_wait_menus` / `village_wait_menus` (PlayerTownVisitCampaignBehavior, CampaignSystem 205847-205957); кнопка = `MenuContext.InvokeConsequence` (GameMenuItemVM.ExecuteAction, CS.VMC 45438) | прочитано; стенд зелёный; **в игре не проверено** |
| Выход из ожидания | пункт `wait_leave` (205911, 205957) | прочитано; в игре не проверено |
| Время в ожидании | `SwitchToMenu` → `StartWait` → `UnstoppableFastForward` (50683, 50756) | прочитано |
| Время на карте | `Stoppable*` не двигает время при `IsMainPartyWaiting` (TickMapTime 9992) | прочитано |
| Пересчёт NPC раз в 6 часов | `PartyHourlyAiTick`, `num = 6` (221132) | прочитано |

## Бой (не сделано)

1. **Разговор в начале встречи.** Полевая встреча открывает меню `encounter_meeting`,
   его init вызывает `PlayerEncounter.DoMeeting()` → разговор на карте, если
   `MeetingDone == false` (185571-185598, по разведке). `GameMenu.PreInit` зовёт
   `CampaignEvents.BeforeGameMenuOpenedEvent` ДО init (HandleStates 154975-154980,
   прочитано) — там можно `PlayerEncounter.SetMeetingDone()`.
   **Опасность:** после `MeetingDone` init сам делает `StartBattle()`, если нет
   `LeaveEncounter`. Для НЕвраждебной партии это нападение на своих — там сначала
   `PlayerEncounter.LeaveEncounter = true`.
2. **Меню `encounter`** (183514-183529, прочитано): `str_order_attack` (отправить
   войска = автобой), `leave` (только если игрок нападающий, 184908), `leave_soldiers_behind`
   → `try_to_get_away` → `try_to_get_away_accept` → `try_to_get_away_debrief` →
   `try_to_get_away_continue` (183539-183546; нужно > 8 бойцов), `surrender`
   (185219). Защищающийся уйти не может никогда (MapEventHelper 3562, по разведке).
3. **Конец автобоя** — `SPScoreboardVM.OnExitBattle` (SandBox.VMC 1556-1596, по
   разведке): `BattleSimulation.Skip()`, когда `IsSimulationFinished` —
   `MapState.EndBattleSimulation()` и `BattleSimulation.OnFinished()` (→
   `ActivateGameMenu("encounter")` → `PlayerEncounter.Update()` крутит итоги).
   `PlayerEncounter.CurrentBattleSimulation` — публичный.
4. **После победы** (DoPlayerVictory … DoEnd, 99176-99505, по разведке):
   * экран пленных/войск `PartyState` → `PartyScreenHelper.CloseScreen(isForced: false)` (= Done);
   * экран трофеев `InventoryState` → `InventoryScreenHelper.CloseScreen(fromCancel: false)`;
   * трофейные корабли `PortState` → `GameStateManager.PopState()`;
   * разговор с пленённым лордом: пункт `talk_lord_defeat_to_lord_capture` (196025);
   * освобождённый из чужого плена лорд: `talk_lord_freed_to_lord_release` (196034) —
     «взять в плен» там БЕЗ условия, для союзника это преступление.
5. **Разговор без кнопок человека** (MissionConversationVM 74933-75035, прочитано):
   есть `CurOptions` → кнопка = `ConversationManager.DoOption(index)`; нет — кнопка
   «дальше» = `ContinueConversation()`. `EndConversation()` не проводит последствия
   выбранной реплики — не использовать.
6. **Поражение:** `taken_prisoner` / `defeated_and_taken_prisoner`, пункт
   `taken_prisoner_continue` (183455-183458).

## Плен (не сделано; по разведке)

* Во время плена `MobileParty.MainParty.IsActive == false` — **текущий опрос
  выключит автопилот** «партия неактивна». Плен проверять раньше.
* Ждущие меню `prisoner_wait`, `settlement_wait` — время идёт само, пунктов нет.
* Исходы — обычные меню с одним пунктом: `mno_continue` в
  `menu_captivity_end_no_more_enemies`, `…_by_ally_party_saved`, `…_by_party_removed`,
  `…_wilderness_escape`, `menu_escape_captivity_during_battle`,
  `menu_released_after_battle`, `menu_captivity_transfer_to_town`,
  `…_exchanged_with_prisoner`, `menu_captivity_castle_remain`, `…_prison_escape`
  (PlayerCaptivityCampaignBehavior 205517-205655).
* Выкуп: `mno_captivity_end_ransom_accept` (платит золото игрока) /
  `captivity_end_ransom_deny` («ждать лучшего», шанс побега растёт с числом отказов).
  Решение для автопилота — за владельцем денег героя; по умолчанию отказ.

## Окна (не сделано)

* **Решения королевства у правителя висят вечно** (UpdateKingdomDecisions 195453,
  по разведке): авторешение идёт только если игрок не участник или не обязан решать.
  Кнопки «Воздержаться» и «Готово» (CS.VMC 30171-30385, прочитано):
  `new KingdomElection(d)` → `StartElection()` → `DetermineOfficialSupport()` →
  правитель: `OnPlayerAbstainedAsRuler()`, участник: `OnPlayerSupport(null, …)` →
  `ApplySelection()` (решение снимается в `ApplyChosenOutcome`, 91926, прочитано).
  Цена: при воздержании правителя движок может переиграть популярный исход за
  влияние клана игрока (`GetAiChoice` 91999, прочитано) — так делает и кнопка.
* **«Критическое решение королевства»** (обязательные решения: выбор короля после
  отречения, кому достаётся взятое поселение) — окно с одной кнопкой «Изучить» и
  паузой движка каждый тик карты, пока решение не решено (SandBox.View 11621, по разведке).
* **Текущее окно** — `GauntletQueryManager._activeQueryData` (приватное статическое,
  TaleWorlds.MountAndBlade.GauntletUI 3278, прочитано); очередь `_inquiryQueue`.
  Кнопки = `data.AffirmativeAction/NegativeAction` + закрытие; публично —
  `InformationManager.IsAnyInquiryActive()`, `InformationManager.HideInquiry()`.
  Окно с `pauseGameActiveState` останавливает движок целиком (3481-3485).
* Сцены (свадьба, казнь, коронация) — `MBInformationManager.HideSceneNotification()` (по разведке).
* Смерть героя с наследниками — оверлей, не состояние игры:
  `CampaignEvents.OnHeirSelectionRequestedEvent` → `CampaignEventDispatcher.Instance.OnHeirSelectionOver(heir)`.
  Без наследников — конец кампании (по разведке).

## Услуги поселения для партии игрока (не сделано; по разведке)

Движок обслуживает NPC и явно пропускает `MainParty`: еда (PartiesBuyFood 202606),
найм (Recruitment 209279, 209575-209581), продажа пленных (202905) и трофеев (202868).
Без этого партия в городе голодает, не пополняется, а высокая оценка «съездить в
город» не падает — пребывание может стать бесконечным.

* еда: `PartyFoodBuyingModel.FindItemToBuy` + `SellItemsAction.Apply(settlement.Party, MainParty.Party, element, 1)`, порог 30 дней в городе / 12 в деревне;
* найм: как `RecruitmentVM.OnDone` (CS.VMC 51349-51371): `VolunteerTypes[i] = null`, `MemberRoster.AddToCounts`, `OnUnitRecruited`, одна `GiveGoldAction`;
* пленные: `SellPrisonersAction.ApplyForSelectedPrisoners(PartyBase.MainParty, null, MobilePartyHelper.GetPlayerPrisonersPlayerCanSell())` — как пункт `sell_all_prisoners`.
