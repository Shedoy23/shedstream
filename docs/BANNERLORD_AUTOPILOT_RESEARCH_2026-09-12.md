# Автопилот партии игрока в Bannerlord 1.4.8 — техническое исследование

Дата: 2026-09-12. Версия игры подтверждена файлом
`bin/Win64_Shipping_Client/Version.xml` → `v1.4.8`, модуль Native →
`<Version value="v1.4.8"/>`. Декомпиляция: `ilspycmd` по
`TaleWorlds.CampaignSystem.dll` и `TaleWorlds.MountAndBlade.dll` из этой
установки. War Sails не установлен.

Каждый вывод помечен:
**[К]** — подтверждено кодом 1.4.8 · **[Р]** — подтверждено только референсом
или другой версией · **[И]** — требует проверки в игре.

---

## 1. Вердикт

**Главный ответ: да, штатный мозг NPC подключается к текущей MainParty, и
барьер ровно один — одно сравнение в одном методе.** Отдельный Director не
нужен, во всяком случае для первого прототипа.

**[К]** Партия игрока получает те же AI-тики, что и партии лордов. Она
классифицируется как **LordParty** (`Campaign.InitializeMainParty` →
`LordPartyComponent.ConvertPartyToLordParty(MainParty, …)`), а значит попадает
в список `MobileParty.AllLordParties`, по которому идёт тикер
`_lordMobilePartyPartialHourlyAiEventTicker`. То есть до места принятия
решений MainParty доходит наравне с NPC.

**[К]** Отсекается она в самом конце, одним условием в
`AiPartyThinkBehavior.PartyHourlyAiTick`:

```csharp
if (mobileParty.Ai.HourCounter % num == 0 && mobileParty != MobileParty.MainParty && (...))
```

Условие из 1.3.15 **сохранилось в 1.4.8** дословно. Всё, что до него —
вычисление периода раздумий, флаги армии, `IsDisabled`/`DoNotMakeNewDecisions`
— для MainParty отрабатывает штатно.

**Что блокирует помимо этого (выявлено на сегодня):**

1. **[К]** Сбор армии упадёт у безкоролевского игрока: в той же ветке стоит
   `((Kingdom)mobileParty.MapFaction).CreateArmy(...)` — прямое приведение
   `MapFaction` к `Kingdom`. Для независимого клана это `InvalidCastException`.
   Смягчающее обстоятельство **[К]**: ветка достижима только когда
   `WillGatherArmy`, а его выставляет `AiMilitaryBehavior` под условием
   `mobileParty.MapFaction is Kingdom` — то есть для независимого игрока
   оценка с `WillGatherArmy` не появится. **[И]** Проверить, что других
   источников `WillGatherArmy` нет.
2. **[К]** `MobilePartyAi.SetInitiative` молча игнорирует партию игрока:
   `if (_mobileParty != MobileParty.MainParty)`. Значит инициатива атаки и
   уклонения у MainParty остаётся дефолтной — поведение в стычках и бегстве
   будет отличаться от NPC.
3. **[К]** `DoNotMakeNewDecisions` и `RethinkAtNextHourlyTick` — сохраняемые
   поля (`SaveableProperty`). Автопилот обязан сбрасывать своё состояние при
   загрузке, иначе оно переживёт сейв.

**Что пока неизвестно (следующий заход):** полный список исключений игрока в
`MobilePartyAi` (19 упоминаний `MainParty`), поведение меню и экранов при
AI-приказах, поведение `TeamAI` у команды игрока в бою.

---

## 1-bis. Главное разделение: ВЫБОР цели и ИСПОЛНЕНИЕ — разные слои

Это ответ на вопрос «почему у ShedLink получалось водить партию игрока, а
автономии не было», и одновременно причина, по которой задача решается малой
кровью.

**[К]** Слоя два, и они живут в разных местах:

| Слой | Где | Что делает | Работает ли для MainParty |
|---|---|---|---|
| **Выбор цели** | `AiPartyThinkBehavior.PartyHourlyAiTick` (часовой AI-тик) | собирает оценки от AI-поведений, выбирает лучшую и ставит цель через `SetPartyAiAction` | **нет** — отсекается сравнением с `MobileParty.MainParty` |
| **Исполнение** | `MobilePartyAi.TickInternal` (каждый кадр) | `GetBehaviors(...)` → `SetAiBehavior(...)`: ведёт партию к уже заданной цели, включая переходы вроде «доехал до замка → сажусь в осаду» (`GetBesiegeBehavior`, вызов из `GetBehaviors`) | **да**, если `Ai.IsDisabled == false` |

**[К]** Проверено, что объяснение в нашем `PartyOrderBehavior.cs` (строки
537-552) актуально и для 1.4.8, а не устарело:

* `IsDisabled` действительно выключает весь расчёт поведения:
  `MobilePartyAi.TickInternal` → `if (IsDisabled) { … } else { GetBehaviors(…); SetAiBehavior(…); }`.
  Отсюда и наблюдение «партия доезжала до замка и вставала»: вместе с
  «дрейфом» глушится и переход в осаду.
* `DoNotMakeNewDecisions` читается **ровно в одном месте** — внутри
  `GetBehaviors` (`MobilePartyAi.cs:486`), в ветке инициативы (погнаться за
  соседом / убежать). Долгосрочную цель он не трогает — то есть это мягкий
  тормоз, как и записано в моде.

**Практический вывод для автопилота:** исполнять цели у партии игрока движок
умеет уже сегодня — ShedLink это эксплуатирует три месяца (осады, рейды,
патрули идут штатным движковым исполнением). Не хватает ровно одного:
**кто выберет цель**. Поэтому задача сводится к разблокировке think-слоя, а не
к написанию своего Director.

**[К]** Побочная находка, ещё одно исключение для игрока в исполнении:
`MobilePartyAi.TickInternal:433` — `if (_mobileParty == MobileParty.MainParty &&
DefaultBehavior == AiBehavior.EngageParty && !TargetParty.IsVisible)
MobileParty.MainParty.SetMoveModeHold();`. То есть преследование невидимой
цели у игрока принудительно обрывается. Для автопилота это значит: приказ
«преследовать» будет вести себя не так, как у NPC.

---

## 1-ter. Что уже есть в ShedLink и что из этого переиспользуемо

Разбор нашего кода (`BannerlordLink/src`) — по нему видно, какие грабли уже
пройдены.

**Общая механика, не завязанная на зрителей** (пригодится автопилоту как
опыт, но переносить код не нужно — у автопилота другая задача):

* `PartyOrderBehavior` — sticky-приказ и его переотдача раз в игровой час
  (`REISSUE_THROTTLE_HOURS = 1`), снятие по событиям (`OnMapEventEnded`,
  `OnSettlementOwnerChanged`), `LockPartyAi`/`UnlockPartyAi`;
* синхронизация цели армии: `army.AiBehaviorObject = target` только когда наш
  герой — `army.LeaderParty`, иначе армейская логика каждый час тянет лидера к
  своей цели (наблюдалось расхождение «в панели одна осада, в игре другая»);
* `ArmyHandlers` — тип армии выбирается по активному приказу
  (`Besieger`/`Raider`/`Defender`), иначе `Patrolling` уводил армию с осады;
* немедленная переотдача приказа после `CreateArmy` (`ReissueNow`), потому что
  создание армии перетирает цель партии;
* осадные патчи (`MobilePartySiegePatch`, `SiegeRetreatFix`) — чинят ванильные
  падения и баг капитуляции при отступлении; к автопилоту отношения не имеют,
  но будут в той же игре.

**Специфика зрительской механики — автопилоту НЕ нужна:** обращения к
backend (`PostEventAsync`, статус-события приказа), `username` зрителя и
`HeroIdentityBehavior`, ack-протокол `ActionFeedback.PostApplied/PostFailed`,
бесплатное снабжение осады зерном (`TrySupplySiege`), удержание
`Army.Cohesion = 100` (`TopUpViewerArmyCohesion`), списания крустиков и
влияния, доля с вассалов.

**Вывод по зависимости:** новый мод не должен зависеть от ShedLink и не
обязан. Единственное, что стоит взять — знание о граблях: не глушить AI, не
ждать, что одна установка цели удержится, и помнить про рассинхрон цели армии.

---

## 2. Таблица доказательств

| Файл (1.4.8) | Класс.Метод | Условие / код | Вывод | Метка |
|---|---|---|---|---|
| Version.xml | — | `v1.4.8` | версия подтверждена | [К] |
| `Campaign.cs:602` | `Campaign.InitializeMainParty` | `LordPartyComponent.ConvertPartyToLordParty(MainParty, Hero.MainHero, Hero.MainHero)` | MainParty — LordParty | [К] |
| `Campaign.cs:1773` | `Campaign.OnLoad` | тот же вызов при пересоздании MainParty | и после загрузки тоже | [К] |
| `CampaignObjectManager.cs:563` | `AddPartyToAppropriateList` | `else if (party.IsLordParty) _lordParties.Add(party)` | попадает в список лордов | [К] |
| `CampaignPeriodicEventManager.cs:279` | `Initialize` | тикер по `MobileParty.AllLordParties` → `TickPartialHourlyAi(x)` | тик доходит до MainParty | [К] |
| `Campaign.cs:982` | `Campaign.Tick` | `_campaignPeriodicEventManager.TickPartialHourlyAi()` | источник тика | [К] |
| `Campaign.cs:1028` | `Campaign.PartiesThink` | `MobileParties[i].Ai.Tick(dt)` | отдельный поток движения AI | [К] |
| `AiPartyThinkBehavior.cs:18` | `RegisterEvents` | `CampaignEvents.TickPartialHourlyAiEvent.AddNonSerializedListener(this, PartyHourlyAiTick)` | точка входа решений | [К] |
| `AiPartyThinkBehavior.cs:49` | `PartyHourlyAiTick` | `if (mobileParty.Ai.IsDisabled \|\| mobileParty.Ai.DoNotMakeNewDecisions) return;` | первый выход | [К] |
| `AiPartyThinkBehavior.cs:65` | `PartyHourlyAiTick` | `&& mobileParty != MobileParty.MainParty &&` | **главный барьер** | [К] |
| `AiPartyThinkBehavior.cs:73` | `PartyHourlyAiTick` | `CampaignEventDispatcher.Instance.AiHourlyTick(mobileParty, thinkParamsCache)` | здесь собираются оценки | [К] |
| `AiPartyThinkBehavior.cs:145+` | `PartyHourlyAiTick` | `SetPartyAiAction.GetActionFor*` | здесь цель превращается в приказ | [К] |
| `AiPartyThinkBehavior.cs:141` | `PartyHourlyAiTick` | `((Kingdom)mobileParty.MapFaction).CreateArmy(...)` | падение у клана без королевства | [К] |
| `AiMilitaryBehavior.cs:522` | сбор оценок | `... && mobileParty.MapFaction is Kingdom && ...` | армию собирает только королевский | [К] |
| `AiMilitaryBehavior.cs:489` | ранний выход | `(mobileParty.MapFaction != Clan.PlayerClan.MapFaction && !mobileParty.MapFaction.IsKingdomFaction)` | фракция игрока проходит явным исключением | [К] |
| `AiVisitSettlementBehavior.cs:140` | ранний выход | `(!mapFaction.IsMinorFaction && !mapFaction.IsKingdomFaction && (LeaderHero == null \|\| !LeaderHero.IsLord))` | нужен лидер-лорд либо королевство/минорка | [К] |
| `MobilePartyAi.cs:1567` | `DisableAi` | `_isDisabled = true; _enableAgainAtHour = CampaignTime.Never;` | полное отключение без срока | [К] |
| `MobilePartyAi.cs:1573` | `EnableAi` | `_isDisabled = false; _enableAgainAtHour = CampaignTime.Now;` | обратная операция | [К] |
| `MobilePartyAi.cs:1607` | `SetDoNotMakeNewDecisions` | присваивание флага | отдельный, более мягкий тормоз | [К] |
| `MobilePartyAi.cs:1596` | `SetInitiative` | `if (_mobileParty != MobileParty.MainParty)` | инициатива игрока не задаётся | [К] |
| `MobilePartyAi.cs:122/125` | свойства | `[SaveableProperty] RethinkAtNextHourlyTick`, `DoNotMakeNewDecisions` | состояние попадает в сейв | [К] |
| `Agent.cs:1199` | `Agent.Controller` (set) | `MBAPI.IMBAgent.SetController(GetPtr(), value)`, при `Player` → `Mission.MainAgent = this` | передача тела AI и возврат | [К] |
| `Agent.cs:1224` | там же | `Formation?.OnAgentControllerChanged`, обход `Mission.MissionBehaviors` | смена контроллера — наблюдаемое событие | [К] |
| `Team.cs:707` | `Team.SetPlayerRole(bool,bool)` | `item.SetControlledByAI(this != Mission.PlayerTeam \|\| !IsPlayerGeneral)` | передача командования формациями AI | [К] |
| `Team.cs:183` | `Team.HasTeamAi` | `TeamAI != null` | нужен TeamAI, иначе тактики не будет | [К] |

---

## 3. Минимальные необходимые изменения и риски

Все изменения действуют **только при включённом автопилоте** и снимаются при
выключении. Ни подмены `IsMainParty`, ни замены `MobileParty.MainParty`.

| № | Изменение | Зачем | Риск |
|---|---|---|---|
| 1 | Harmony-патч на `AiPartyThinkBehavior.PartyHourlyAiTick`: при активном автопилоте не давать условию `mobileParty != MobileParty.MainParty` отсечь партию игрока | единственный барьер для штатного выбора цели | средний: метод длинный, прочие ветки внутри написаны в расчёте на NPC; transpiler по одному сравнению хрупок к патчам других модов. **[И]** |
| 2 | Гарантировать `Ai.IsDisabled == false` и `DoNotMakeNewDecisions == false` на время автопилота, запомнив прежние значения | иначе выход произойдёт на строке 49 | низкий; значения сохраняемые — восстановить обязательно |
| 3 | Запрос пересмотра цели при включении: `Ai.RethinkAtNextHourlyTick = true` | иначе первое решение придёт в пределах 6 игровых часов | низкий |
| 4 | Страховка от `(Kingdom)MapFaction` при безкоролевском игроке | падение кампании | **[И]** возможно не нужна: `WillGatherArmy` у такого игрока не появляется |
| 5 | В бою: `Mission.PlayerTeam.SetPlayerRole(false, false)` и `Agent.Main.Controller = AgentControllerType.AI`, обратно — при выключении и в конце миссии | герой и его формации воюют сами | **[И]** камера, ввод, поведение при смерти/оглушении не проверены |

**Не делать:** глобальную подмену признака «это партия игрока»; отключение AI
через `DisableAi()` как способ «выключить автопилот» — это не выключение, а
запрет любых решений, и оно сохраняется в сейв.

---

## 4. Состояния игрока: с чего начинать

| Состояние | Что говорит код | Метка |
|---|---|---|
| Вассал королевства | самый безопасный: `MapFaction is Kingdom` выполняется, доступны все ветки, включая сбор армии | [К] |
| Правитель | то же плюс решения уровня королевства — больше побочных эффектов | [К] |
| Наёмник | `IsUnderMercenaryService` явно исключает сбор армии (`AiPartyThinkBehavior:139`), остальное работает | [К] |
| Независимый клан | военные оценки собираются (исключение по `Clan.PlayerClan.MapFaction`), но ветка армии — потенциальное падение | [К] + [И] |
| В чужой армии | решения подменяются приказом лидера армии (`Army.LeaderParty.DefaultBehavior`, `Army.AiBehaviorObject`) — автопилот будет ведомым | [К] |
| Лидер своей армии | период раздумий укорачивается, возможен `DisbandArmyAction.ApplyByUnknownReason` при смене цели | [К] |

**Рекомендация: начинать с вассала королевства без своей армии.** У него
выполняются все предположения кода, не нужен обход приведения к `Kingdom`, и
поведение сравнимо с соседними NPC-лордами — то есть есть с чем сверять.

---

## 5. Что ещё предстоит проверить

Эти пункты задания на сегодня не закрыты и требуют отдельного захода:

* полный разбор 19 мест в `MobilePartyAi`, где выделяется партия игрока;
* таблица «событие → откроется ли меню/экран» (прибытие в поселение, выход,
  встреча, бой, победа, пленные, поражение) — нужен разбор `PlayerEncounter`
  и `EncounterManager`;
* поведение `TeamAI` у команды игрока: создаётся ли компонент и будет ли
  тактика, если генерал — AI;
* референсы (Battle Autopilot, MCC TOR `RemotePartySwitch.HandOffOutgoingPartyToAi`,
  Bannerlord.PartyAI, GABS) — сверка их приёмов с 1.4.8;
* цикл включения/выключения с проверкой необратимых действий (начатая осада,
  вступление в армию, начатый бой).

---

## 5-bis. Цикл включения и выключения

**[К]** Основание: `DisableAi()` ставит `_isDisabled = true` и
`_enableAgainAtHour = CampaignTime.Never`, а `IsDisabled` в
`MobilePartyAi.TickInternal` пропускает весь расчёт поведения. Значит
«выключить автопилот через `DisableAi()`» — не выключение, а заморозка: партия
встанет там, где её застали, сохранив цель. Правильное выключение — вернуть
барьер на место и восстановить флаги.

**Включение** (все шаги обязательны, порядок важен):

1. **Проверка состояния.** Нет активной миссии (`Mission.Current == null`),
   герой не пленён, партия активна, не присоединена к чужой армии
   (`AttachedTo == null`) — для первого прототипа это ограничение, а не
   требование движка. **[И]**
2. **Снимок изменяемого**: `Ai.IsDisabled`, `Ai.DoNotMakeNewDecisions`,
   текущий `DefaultBehavior` и цель. Оба флага сохраняемые — их значение до
   автопилота принадлежит игроку, а не нам.
3. **Допуск к штатному AI**: если `IsDisabled` — `EnableAi()`; если
   `DoNotMakeNewDecisions` — `SetDoNotMakeNewDecisions(false)`.
4. **Запрос пересмотра**: `Ai.RethinkAtNextHourlyTick = true`. Без этого
   период раздумий останется прежним (до 6 игровых часов) — **[К]**
   `DefaultThinkingPeriodInHours = 6` в `AiPartyThinkBehavior`.
5. Поднять собственный флаг автопилота, по которому патч перестаёт отсекать
   MainParty.

**Выключение**:

1. **Снять флаг автопилота первым** — дальше think-слой снова отсекает
   MainParty, и новых целей не появится.
2. **Отменить своё отложенное.** У прототипа отложенных команд быть не должно
   по условию (он не ставит цели сам) — но если появится очередь, её надо
   чистить здесь.
3. **Восстановить снимок** флагов из шага 2 включения.
4. **Решить судьбу текущей цели.** Это отдельное решение, не техническое:
   партия продолжит ехать к последней выбранной AI цели, потому что
   исполнение живёт в `MobilePartyAi.TickInternal` и работает всегда.
   Варианты: оставить (игрок сам перенаправит) либо `SetMoveModeHold()`.
   Для первого прототипа честнее **оставить и написать в лог**, куда именно
   партия шла на момент выключения.

**Что уже необратимо на момент выключения** (выключение их не отменяет) — **[К]**:

| Действие | Обратимо выключением? |
|---|---|
| Движение к цели | да — цель просто перестаёт обновляться |
| Присоединение к армии | нет: партия уже в `Army`, выход — отдельное действие |
| Начатая осада (`SiegeEvent`) | нет: событие осады живёт само, снимается `FinalizeSiegeEvent` |
| Начатый `MapEvent` / бой | нет: закончится по своим правилам |
| Роспуск армии, совершённый AI (`DisbandArmyAction.ApplyByUnknownReason`) | нет, уже произошёл |

**После загрузки сохранения автопилот выключен** — требование задания. **[К]**
Обоснование, почему это не формальность: `DoNotMakeNewDecisions` и
`RethinkAtNextHourlyTick` сохраняемые, поэтому при загрузке надо не просто
поднять свой флаг в «выключено», но и убедиться, что чужие флаги не остались
изменёнными нашим прошлым сеансом.

---

## 5-ter. Референсы: что проверено и что нет

| Референс | Статус на 12.09 |
|---|---|
| Battle Autopilot | **не проверен**. Заявленная функция — ровно наша задача 6.1 (AI ведёт тело игрока). Механизм, который мы нашли сами (`Agent.Controller = AgentControllerType.AI`), выглядит тем же, но совместимость с 1.4.8 не подтверждена. [Р] |
| MCC TOR, `RemotePartySwitch.HandOffOutgoingPartyToAi` | **не проверен**: исходников в открытом доступе не нашлось, поиск по имени метода результатов не дал. Важно помнить: там задача ДРУГАЯ — передать AI партию, которая перестала быть главной (смена героя). Нам смена героя не нужна, поэтому большая часть их операций нам не подходит. [Р] |
| [Bannerlord.PartyAI](https://github.com/adwitkow/Bannerlord.PartyAI) | исходники открыты, содержимое не разобрано. Тема — управление решениями партий клана, то есть близко к нашему think-слою. **Разобрать в следующем заходе.** |
| [Party AI Overhaul and Commands Rebuild](https://gitlab.com/octaviusmods/bannerlord-party-ai-overhaul-and-commands) | найден попутно, исходники открыты, не разобран |
| Bannerlord.GABS | **не проверен** |

Ни один из них не является доказательством для 1.4.8: у каждого своя версия
игры и своя задача. Использовать их как подсказку «куда смотреть», а не как
готовое решение.

---

## 6. Спецификация первого эксперимента

**Цель:** доказать, что цель партии игрока выбрал ШТАТНЫЙ цикл решений, а не
мод.

Прототип:
* 1.4.8 без DLC, не зависит от ShedLink;
* тот же `MainHero`, та же `MainParty`, никаких дубликатов;
* включение только вручную, после загрузки сейва — всегда выключен;
* журнал на каждый тик: пришёл ли `PartyHourlyAiTick`, какие
  `AIBehaviorScores` собраны (поведение и число), какая цель выбрана, какой
  `SetPartyAiAction` применён, куда партия фактически поехала;
* рядом — тот же журнал для соседнего NPC-лорда, чтобы видеть расхождение;
* на неподдерживаемом переходе — остановка автопилота с явной причиной в
  логе; никаких автозакрытий окон.

**Критерии успеха:**
1. В журнале есть непустой список оценок для MainParty. **[И]**
2. Выбранная цель появилась из `AIBehaviorScores`, а не задана модом.
3. Партия действительно двинулась к этой цели, и `DefaultBehavior` совпал с
   выбранным.
4. Выключение возвращает ручное управление, и после него в журнале нет ни
   одного приказа от прототипа.
5. Сохранение и загрузка не оставляют `DoNotMakeNewDecisions`/`IsDisabled` в
   изменённом состоянии.

**Чего эксперимент не доказывает:** что бой, меню поселения и плен отработают
корректно. Это отдельные шаги.
