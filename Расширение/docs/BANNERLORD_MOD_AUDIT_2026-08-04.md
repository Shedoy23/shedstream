# Аудит BannerlordLink — 2026-08-04

## Независимая перепроверка отчёта — 2026-08-05

Отдельная сессия перепрогнала доказательства этого отчёта и прочитала правки.
**Основное подтвердилось**: Release-пересборка `-t:Rebuild` даёт 0 ошибок и
0 предупреждений; ACK действительно уходит после завершения работы на игровом
потоке (`ActionPoller.ProcessActionAsync` → `MainThreadDispatcher.ExecuteTrackedAsync`),
terminal outcome пишется на диск ДО ACK, у 38 из 41 хендлера с `Enqueue` есть
отчёт об отказе через `ActionFeedback.PostFailed`, компенсация золота и
postcondition в `join_kingdom`/`make_baby` реальные.

**Поправки к тексту выше:**

1. «backend ACK/refund scenario: 29 PASS» — на 05.08 прогон даёт **36 PASS**
   (`tests/test_action_ack_refund_order.py`, код возврата 0). Число в отчёте
   устарело.
2. «`CoreReliabilityHarness`: 131/131 PASS» — прогон честный, но цифра больше
   похожа на объём покрытия, чем есть на деле: **110 из 131** утверждений — это
   один цикл `for i < 110`, заполняющий кэш до предела. Разных проверок ≈ 21,
   сценариев 5. Харнесс компилирует **настоящие** исходники, но только три:
   `MainThreadDispatcher`, `ActionOutcomeStore`, `DurableEventOutbox`.
   `ActionPoller`, хендлеры и `BackendClient` он не покрывает.
3. P2-3 закрыт **ценой механики**: у `SimpleAgentOrigin` метод `SetWounded()`
   пустой (проверено декомпиляцией движка), поэтому призванный зритель, которого
   вырубили в бою, больше не помечается раненым, а `SetKilled()` передаёт убийцу
   как `null`. Подробности и что с этим делать — `DEFERRED.md`, раздел
   «Призванный зритель больше НЕ получает ранение в бою».
4. Комментарий в `DurableEventOutbox` обещает больше, чем есть: дедуп конвертов
   на бэкенде живёт **в памяти процесса** (`_processed_envelopes`, кольцо 5000) и
   теряется при рестарте. Разбор полезной нагрузки показал, что двойных денег
   отсюда не выходит (крустики за мастерские/караваны отвязаны с мая, возврат
   идемпотентен через маркер `REFUNDED:`, свита — установка состояния слота), но
   счётчики «заработано динаров» повторной доставкой можно завысить.
5. Без отчёта об отказе остались 4 хендлера: `SetCombatStance` (путей отказа нет,
   это нормально), `BroadcastMessage`, а также `ActivateHeir` и `ModifyAttribute` —
   у последних двух отказы внутри игрового колбэка молча дают success. В проде
   этими действиями не пользовались ни разу (`module_actions` пуст по обоим),
   поэтому это долг, а не пожар.

Проверено также вне мода: `lint_consistency.py` — код 0 (одно известное
предупреждение про 20 законов), прод отвечает `status=ok`, миграция
`M108.module_action_ack_receipt` применена на боевой базе, совместимость 0.0.1
работает (`GET /api/event/status` → 200 инертный, `POST /api/event/contribute` → 404).

Вывод перепроверки: доказательная база отчёта держится, ин-гейм smoke по-прежнему
обязателен, и к его списку добавляется пункт «вырубить призванного зрителя и
посмотреть, появился ли бейдж “ранен”».

## Статус исправления — 2026-08-04

Все P1 и P2 из этого аудита исправлены в рабочем дереве:

- ACK теперь ждёт завершения callback на игровом потоке; отказ и exception становятся terminal failure, а не ложным success;
- terminal outcome хранится на диске и повторяется при redelivery без второго gameplay-effect;
- refund, workshop/caravan payout и изменение свиты пишутся в durable outbox до сетевой отправки и повторяются с тем же envelope id;
- для charge-first механик добавлены postcondition и точная компенсация Hero.Gold; ошибки после уже подтверждённого gameplay-effect больше не превращают действие в refund;
- unload отменяет ожидающие действия, очищает очередь по generation и дожидается остановки poller;
- combat stance перенесена на game thread;
- summon больше не меняет campaign `MemberRoster` в активном `MapEvent`: hero и свита получают mission-only `SimpleAgentOrigin`;
- добавлен отдельный .NET Framework reliability harness.

P3 также закрыты: outcome store имеет hard cap, Release-сборка проходит без предупреждений.

Проверка после исправлений:

- `CoreReliabilityHarness`: **131/131 PASS**;
- `dotnet build BannerlordLink/src/BannerlordLink.csproj -c Release`: **0 errors, 0 warnings**;
- backend ACK/refund scenario: **29 PASS, 0 FAIL**;
- backend delivery-gap scenario: **9 PASS, 0 FAIL**;
- `git diff --check`: замечаний нет.

Остаётся обязательный перед выкладкой этап: короткий in-game smoke на реальном движке (apply/refuse, сетевой разрыв, summon в MapEvent, unload во время queued action). Harness проверяет протокол и отказоустойчивость, но не может эмулировать внутренние postcondition TaleWorlds.

## Вывод

Мод собирается и отработал почти шестичасовой стрим без managed-crash, но его ядро пока не гарантирует связь «принято → применено в игре → подтверждено backend’ом». Сейчас ACK часто означает лишь «лямбда положена в main-thread queue». Отсюда три класса редких инцидентов:

1. деньги списаны, а эффекта нет;
2. потерянный ACK превращает реальный отказ в success при retry;
3. одноразовая награда/refund теряется при одном сетевом сбое.

P0 (немедленный краш/эксплойт) в текущем коде не найден. Ниже: 4 P1, 4 P2 и 2 P3.

## P1 — исправить до следующего большого стрима

### P1-1. ACK уходит до реального Apply

`ActionPoller` ждёт `handler.ExecuteAsync`, но почти все gameplay-handler’ы только вызывают `MainThreadDispatcher.Enqueue(...)` и сразу возвращают `(true, null)`. Dispatcher не имеет completion/result; исключение на main thread лишь логируется и поглощается.

Доказательства:

- `Net/ActionPoller.cs:264-307` — ACK формируется из раннего result handler’а;
- `MainThreadDispatcher.cs:35-49` — result нет, exception swallow;
- `Actions/JoinKingdomHandler.cs:46-47` — enqueue + immediate success;
- `Actions/MakeBabyHandler.cs:55-113` — все gameplay-check’и и Apply идут уже после success ACK.

Последствие: любой неучтённый early return/exception даёт «оплачено и ACKed, эффекта нет». `ActionFeedback.PostFailed` — ручной workaround, а не гарантия.

Исправление: добавить `MainThreadDispatcher.InvokeAsync<T>` с `TaskCompletionSource<T>`. Handler должен завершаться только после Apply и возвращать типизированный `ActionResult`. ACK — только после этого result.

### P1-2. Dedupe запоминает action до его исхода

`MarkProcessedOnce(actionId)` вызывается до JSON parse, handler lookup и Apply (`ActionPoller.cs:170-216`). При повторной доставке любой запомненный id безусловно ACK’ается как success (`ActionPoller.cs:175-195`).

Аварийный сценарий:

1. handler вернул failure или упал до эффекта;
2. POST failure-ACK потерялся;
3. backend requeue’ит action;
4. dedupe шлёт success-ACK, поэтому backend больше не вернёт деньги.

Исправление: хранить не `processed bool`, а terminal outcome `{actionId, success, error, effectCommittedAt}`; при retry повторять тот же ACK. Не записывать terminal outcome до завершения main-thread Apply.

### P1-3. Refund и passive-income события не имеют retry/outbox

`PostEventAsync` возвращает `false` при HTTP/JSON failure (`BackendClient.cs:110-160`). `ActionFeedback.PostFailed` игнорирует bool и всё равно логирует `REFUND request` как будто отправка успешна (`ActionFeedback.cs:42-65`). Catch не сработает: HTTP-ошибки внутри `BackendClient` уже превращены в `false/null`.

Для workshop/caravan проблема денежная:

- workshop snapshot сдвигается до успешной доставки (`WorkshopProfitSyncBehavior.cs:86-101`);
- caravan snapshot тоже сдвигается до POST (`CaravanTrackerBehavior.cs:69-81`);
- обе отправки — fire-and-forget `Task.Run`, bool игнорируется (`WorkshopProfitSyncBehavior.cs:114-130`, `CaravanTrackerBehavior.cs:171-183`).

Один сетевой сбой на дневном тике = прибыль больше не будет повторена. Тот же класс ошибки теряет refund.

Исправление: единый durable outbox на диске с постоянным envelope id, exponential retry и удалением только после backend ACK. Snapshot passive income сдвигать после enqueue в outbox, а не после запуска ненадёжного `Task.Run`.

### P1-4. Списание Hero.Gold и gameplay mutation неатомарны

Пример `hero.join_kingdom`: 100 000 gold списываются до `ChangeKingdomAction`; если engine call бросит exception, code лишь логирует и выходит (`JoinKingdomHandler.cs:91-109`). Gold не возвращается, failure на backend не уходит.

Тот же pattern:

- `hero.make_baby`: charge → `MakePregnantAction.Apply` → catch без rollback (`MakeBabyHandler.cs:96-110`);
- `hero.set_gender`: charge перед серией mutation;
- `hero.marry`: charge перед spouse/clan mutation;
- `hero.add_focus` / `hero.add_attribute`: gold списывается до developer mutation.

Исправление: prevalidate всё, что возможно; применять effect; проверять postcondition; списывать gold после успеха. Если engine API требует charge-first — explicit compensation с возвратом точной суммы.

## P2 — важные доработки

### P2-1. Очередь и background tasks переживают unload

`MainThreadDispatcher` держит static queue и не имеет `Clear/Cancel`. `OnSubModuleUnloaded` только вызывает `Poller.Stop`, unpatch и `Backend.Dispose` (`BannerlordLinkModule.cs:342-348`). `ActionPoller.Stop` обнуляет task без await (`ActionPoller.cs:58-64`).

При hot reload/save transition уже queued gameplay-lambda может выполниться позже в другом lifecycle. Fire-and-forget event может попытаться работать с уже disposed или заменённым static Backend.

Исправление: session generation id на каждой queued work item, cancellation и drain/cancel при unload; `StopAsync` с await; не обнулять task до реального exit.

### P2-2. Потоконебезопасная запись профиля стойки

`SetCombatStanceHandler` выполняется на poller thread и напрямую вызывает `HeroProfileBehavior.Instance.SetStance` (`SetCombatStanceHandler.cs:27-40`). `HeroProfileBehavior` пи этом хранит профили в обычном `Dictionary` и читает/перебирает его на game thread (`HeroProfileBehavior.cs:35-64, 96-109, 118-132`). Возможны race с save `SyncData` и `OnGameLoadFinished`.

Исправление: stance update тоже через main-thread dispatcher или lock/copy-on-write внутри profile behavior.

### P2-3. MapEvent roster desync не исправлен, а замаскирован

`SummonHeroHandler` меняет `MemberRoster` активной в MapEvent партии (`SummonHeroHandler.cs:181-220`). Комментарии и патчи сами фиксируют, что это протухает indices. `MapEventWoundedPatch` / `MapEventKilledPatch` глотают `IndexOutOfRangeException`, предотвращая crash, но движок пропускает учёт ранения/гибели (`MapEventWoundedPatch.cs:22-31, 56-68`).

В логе стрима 03.08 такой swallow был один. Это не crash, но прямой сигнал, что root cause жив.

Исправление: не трансферить hero/troop roster во время MapEvent; использовать mission-only origin/proxy и отложенную campaign reconciliation после боя. Финалайзер оставить как последнюю защиту.

### P2-4. Нет автотестов самого мода

В `BannerlordLink` нет test/spec project. Backend tests проверяют дебет/refund и API, но не могут доказать, что main-thread gameplay effect состоялся. Поэтому regression в ACK/apply/refund можно найти только стримом.

Минимальный harness должен подменять dispatcher/backend и проверять:

- ACK не уходит до completion;
- exception/refuse даёт failure outcome;
- ACK loss + retry повторяет тот же outcome без второго effect;
- unload отменяет queued work;
- outbox держит envelope до ACK.

## P3 — техдолг

### P3-1. `PROCESSED_IDS_MAX` не является hard cap

При count >= 10 000 удаляются только id старше 3 часов, после чего `TryAdd` всё равно добавляет новый id (`ActionPoller.cs:148-167`). Если 10 000 action пришли за 3 часа, dictionary растёт дальше. На текущей нагрузке это не авария, но коммент `session memory cap` неверен.

### P3-2. Два compiler warning

Rebuild Release: 0 errors, 2 warnings.

- `PowersMissionBehavior.cs:147` — unreachable particle branch, потому что feature flag — compile-time false;
- `ClassLoadout.cs:43` — `UseCamel` нигде не задаётся; camel branch фактически dead.

## Сопоставление с логом 03.08

Фактический лог подтверждает, что hot path в целом стабилен:

- `CRASHED`: 0;
- `MainThreadDispatcher: action crashed`: 0;
- POST ERROR/FAILED: 0;
- `action.failed` при отказе в конце стрима дошёл и был ACKed;
- `MapEventWounded SWALLOWED`: 1;
- GET timeout: 6 во время стрима + 1 позже рядом с unload; poller восстанавливался.

Про «17 ошибок»: это не 17 gameplay incidents. На момент исходного подсчёта туда попали 6 строк GET timeout, 6 дублирующих `poll failed` и 5 успешных строк `Harmony patched ... failed=0`. Реальные инциденты в том окне: 6 таймаутов сети и 1 roster desync, который патч не дал превратить в crash.

## Рекомендуемый порядок работ

1. `InvokeAsync<ActionResult>` и ACK после main-thread completion.
2. Outcome-aware idempotency; не превращать retry в success.
3. Общий durable event outbox для refund, payout и state-changing events.
4. Единый transaction helper для Hero.Gold + postcondition/rollback.
5. Lifecycle cancellation и очистка queue при unload/save switch.
6. Убрать MemberRoster mutation из mid-battle summon.
7. После этого — handler contract tests и короткий in-game smoke matrix.

## Проверки аудита

- Просмотрены core delivery, dispatcher, lifecycle, 42 handler-файла, economy sync, Harmony finalizers и лог 03.08.
- Охват проекта: 107 C#-файлов, 66 зарегистрированных action types, 55 `Task.Run`, 53 call site `PostEventAsync`.
- `dotnet build -c Release -t:Rebuild`: success, 0 errors, 2 warnings.
- Код мода в ходе аудита не изменялся.
