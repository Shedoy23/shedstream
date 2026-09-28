# Независимая проверка меню, 13.09.2026

Проверены claims 1, 8, 10. Репозиторий codex-public-release; код не менялся, игра не запускалась. CodeGraph context вернул database is locked, использованы исходники и локальная декомпиляция DLL 1.4.8. Engine-пути ниже относительно `../autopilot-review/engine-side-effects/`; VM дополнительно декомпилирован в `menu-vm/`.

## P1/P2: успешная остановка ожидания в деревне считается неудачей

Опровергает №8; №10 не покрывает эту ветку.

Цепочка: AutopilotBehavior.cs:520-535 вызывает MenuDriver.TryInvoke(wait_leave), затем требует `Current.IsPlayerWaiting == false`. Реальный village_wait_menus зарегистрирован в PlayerTownVisitCampaignBehavior.cs:165-169. Его stop consequence :207-211 выполняет `EnterSettlementAction.ApplyForParty(MainParty, LastVisitedSettlement)` и `GameMenu.SwitchToMenu("village")`; он НЕ сбрасывает IsPlayerWaiting. EnterSettlementAction.cs:73-91 записывает CurrentSettlement и вызывает события; village init :1104-1116 тоже не сбрасывает флаг. При этом GameMenu.RunMenuOptionConsequence:263-278 уже вызывает EndWait для leave-пункта wait-меню (:292-296 устанавливает IsWaitActive=false и Stop).

Итог: ожидание реально закончено, партия снова внутри деревни, меню village открыто, но оставшийся true в IsPlayerWaiting приводит к Disable на :529 вместо LeaveAndApplyPending. Обычная ситуация: ждать у мирной деревни, получить другое применимое часовое решение. Результат — остановка автоматического сеанса, а не порча сейва. В игре не запускалось; подтверждено цепочкой штатного кода. Стенд Program.cs не содержит модели village waiting: единственная фабрика TownMenu вручную сбрасывает флаг (:77), поэтому этот класс ошибки вообще не исполняет.

## P1/P2: меню можно исполнять под другим экраном

Опровергает сильную трактовку №1 «как кнопка игрока». AutopilotBehavior.PollState/StartWaiting/StopWaitingAndLeave не проверяют активный MapState или ActiveStateDisabledByUser; проверка MapState есть только в KeepTimeRunning:670-677. Campaign.cs:403-418 явно возвращает MenuContext предыдущего MapState, когда активен следующий GameState. MenuContext.InvokeConsequence:154-160 проверяет только совпадение CurrentMenuContext, поэтому такой вызов не отсекается.

Воспроизведение по коду: меню town остается под экраном инвентаря/отряда (с Predecessor=MapState); F11 либо уже включенный Apply; следующий application poll вызывает town_wait под этим экраном. Аналогично pending departure может нажать wait_leave и закончить encounter под экраном. Игрок в этот момент не мог бы нажать скрытую кнопку. Кодовая достижимость подтверждена, конкретный результат закрытия/обновления экранов требует игрового прогона.

## Стенд не повторяет реальные переходы town stop

Опровергает №10 в части достоверности модели, но само по себе не доказывает поломку обычного town выхода.

Program.cs:63-85 TownMenu.wait_leave безусловно возвращает town. Движок PlayerTownVisitCampaignBehavior:123-127 сбрасывает IsPlayerWaiting, затем SwitchToMenuIfThereIsAnInterrupt:1500-1514 запрашивает EncounterGameMenuModel.GetGenericStateMenu; для мирного fortification DefaultEncounterGameMenuModel:295-311 после сброса флага возвращает castle_outside/town_outside, не town. При interrupt возвращается соответствующее меню; fixture его вообще не моделирует. AutopilotBehavior.StopWaitingAndLeave:527 проверяет только IsPlayerWaiting и немедленно вызывает LeaveAndApplyPending:534 — повторной проверки UnsupportedState/идентичности меню после синхронного consequence нет. Возможность появления прерывающего состояния именно между начальной проверкой и consequence требует отдельной демонстрации; не выдавать за доказанный обычный сценарий.

## Что устояло и что не следует объявлять багом

- Синхронность init подтверждается: GameMenu.SwitchToMenu:358-367 -> MenuContext.SwitchToMenu:56-59 -> HandleStates:62-105 -> RunOnInit:89. StartWaiting вправе сразу читать результат обычного town init; заявление «init только следующим кадром» неверно.
- GameMenuItemVM.ExecuteAction действительно только вызывает _menuContext?.InvokeConsequence(Index), строки 376-379 в menu-vm/TaleWorlds.CampaignSystem.ViewModelCollection.GameMenu.GameMenuItemVM.decompiled.cs.
- Формула MenuDriver.cs:65-66 для непервого повторяемого пункта правильна: inverse mapping GameMenuManager.RunConsequenceOfVirtualMenuOption:385-400. Первый повторяемый пункт выбирает первый объект; универсальный выбор другого повторения API MenuDriver не предоставляет, но штатные town_wait/wait_leave не повторяемые.
- Реальный GetMenuOptionConditionsHold не чист: GameMenu:158-171 -> RunWaitMenuCondition:242-255 -> StartWait при неактивном ожидании, который включает UnstoppableFastForward (:285-290). Стенд Stubs.cs:38 только вызывает Condition и этого не моделирует. Для штатного stop следом EndWait выключает ожидание; сам по себе этот побочный эффект не доказан как дефект нормального stop.
- Stubs.cs:48 не моделирует virtual indexing, EndWait, OnGameMenuOptionSelected и проверку актуальности context в реальном InvokeConsequence. Следовательно зеленый стенд не проверяет эти свойства; реальная формула индекса проверена отдельно выше.
- LeavePeacefulSettlement:636-651 считает выход только после CurrentSettlement==null && PlayerEncounter.Current==null. В обычной синхронной цепочке это сильнее проверки одного запроса. Не найден штатный обычный путь, где эти оба условия истинны, но продолжается прежнее ожидание; отдельного ложного счетчика в этой функции не установлено.
