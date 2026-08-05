# Аудит и доработка RimLink — 2026-08-04

## Резюме для независимой проверки

RimLink прошёл статический аудит delivery/ACK, игрового main-thread, жизненного цикла сессии, синхронизации пешек и трупов, HTTP/JSON-контрактов и отказоустойчивости. Найденные проблемы исправлены в рабочем дереве, мод пересобран под .NET Framework 4.8 против установленных RimWorld assemblies и установлен в локальную папку игры.

Текущий проверенный результат:

- `dotnet build RimLink/Source/RimLink.csproj -c Release`: **0 errors, 0 warnings**;
- backend RimWorld ACK/refund regression: **11 PASS, 0 FAIL**;
- `git diff --check -- RimLink`: замечаний нет;
- собранный `RimLink.dll`: **151040 bytes**;
- SHA-256 DLL в репозитории и установленной копии совпадает: `7006E3F223A230C2EBCE13D73EDA71377059969D68D8D82BF53B0D73C69FAAA0`;
- установленная копия: `X:\SteamLibrary\steamapps\common\RimWorld\Mods\RimLink`;
- заявленная совместимость в `About.xml`: RimWorld **1.5 и 1.6**.

Это не заменяет in-game smoke. Реальный игровой движок ещё должен подтвердить применение команд, смену карты/сохранения, смерть/воскрешение и поведение при сетевом разрыве. Этот этап запланирован на следующий стрим.

## Объём изменений

Изменено 11 исходных C#-файлов, добавлены `ViewerIdentity.cs` и скрытый `HediffDef`, пересобран DLL. Суммарный diff существующих текстовых файлов RimLink: около **1051 добавленной и 326 удалённых строк**; новые identity/Def-файлы в эту цифру git diff не включает, поскольку они пока untracked.

Основные затронутые области:

- `Source/Managers/CommandQueue.cs` — main-thread execution, terminal outcome, ACK retry и journal;
- `Source/Managers/PawnManager.cs` — session bootstrap, bulk sync, карты/караваны/трупы и retry состояния;
- `Source/Components/RimLinkGameComponent.cs` — lifecycle, budget и heartbeat;
- `Source/Components/ViewerIdentity.cs` + `Defs/HediffDefs/RimLink_Hediffs.xml` — сохраняемая identity зрителя;
- `Source/API/RimLinkAPI.cs` — строгий HTTP/application-level ACK;
- `Source/Utils/SimpleJson.cs` — строгий ограниченный parser;
- `Source/Actions/*` — rollback и safety caps;
- `Source/RimLinkMod.cs` — безопасные настройки токена, connection test и lifecycle polling.

## Исправленные P1

### P1-1. Потерянный ACK мог повторно применить платный игровой эффект

Раньше защита от повторной доставки жила только в памяти процесса. Если команда успела изменить игру, но ACK потерялся, после рестарта backend мог выдать её снова, а мод — повторно выполнить эффект.

Исправление:

- terminal outcome `{commandId, success, message, ackPending}` записывается **до** отправки ACK;
- журнал хранится в RimWorld config как `RimLink-command-outcomes-v1.txt`;
- при повторной доставке мод не исполняет gameplay второй раз, а повторяет прежний ACK;
- недоставленные ACK восстанавливаются после рестарта;
- применяется retry schedule от немедленной попытки до 240 секунд, всего 10 попыток;
- параллелизм синхронных `WebClient` ACK ограничен четырьмя запросами;
- доставленные outcomes имеют cap 1000, но недоставленные не удаляются ради денежной корректности.

Код: `CommandQueue.cs:17-18, 33-47, 157-268, 270-347, 360-430`.

### P1-2. Все накопленные команды исполнялись за один игровой tick

Без budget всплеск очереди мог заморозить кадр или игру: раньше использовался безлимитный `FlushAll()`.

Исправление:

- очередь имеет hard limit 1000 команд;
- переполнение получает terminal `queue_full` и отрицательный ACK для возврата;
- за tick выполняется не больше пяти команд и не больше примерно 8 мс;
- gameplay остаётся строго на главном потоке;
- сетевой polling только ставит команды в thread-safe очередь.

Код: `CommandQueue.cs:70-138`, `RimLinkGameComponent.cs:30-31, 107-119`.

### P1-3. Гонка `SessionStart → SyncPawnsBulk`

Раньше отдельные фоновые sync пешек могли выполниться до отложенного `session-start`. Затем очистка сессии удаляла уже синхронизированных живых пешек до следующего полного прохода.

Исправление:

- данные игровых объектов собираются на main-thread;
- используется один последовательный pipeline `SessionStart() → SyncPawnsBulk()`;
- операции сериализованы `_networkSyncGate`;
- введён generation/session version: устаревший async callback не применяет snapshot после смены сохранения;
- `_lastSentJson` обновляется только после подтверждённого успешного sync, поэтому сетевой отказ не превращается в ложное «уже отправлено».

Код: `PawnManager.cs:60-197, 287-307`.

### P1-4. Identity пешки зависела от отображаемого имени

Связь со зрителем определялась по `NameTriple("Twitch", username, "RimLink")`. Переименование пешки или некоторые редакторы могли навсегда разорвать связь, после чего синхронизация, покупка или воскрешение искали не того персонажа либо не находили его.

Исправление:

- добавлен скрытый сохраняемый `Hediff_RimLinkViewerIdentity`;
- username сериализуется через `CompExposeData` вместе с пешкой;
- новые пешки получают marker при создании;
- legacy-пешки автоматически мигрируют с прежней схемы имени;
- внутренний marker исключён из пользовательского списка болезней/hediffs, отправляемого backend;
- поиск работает после переименования, перехода в caravan и сохранения/загрузки.

Код: `ViewerIdentity.cs`, `RimLink_Hediffs.xml`, `PawnCommands.cs:54-56`, `PawnDataBuilder.cs:24-29, 334`, `PawnManager.cs:50-57, 98-106`.

## Исправленные P2

### P2-1. Неполная синхронизация мира, смерти и трупов

Раньше bootstrap был завязан преимущественно на текущую карту. Это оставляло разрывы для нескольких карт, караванов, transporters, трупов и пешек без доступного corpse.

Исправление:

- живые viewer pawns сканируются через `AllMapsCaravansAndTravellingTransporters_Alive_FreeColonistsAndPrisoners`;
- трупы сканируются на всех загруженных картах и только для faction игрока;
- corpse имеет отдельный payload `is_alive=false`, `health=0`, `is_corpse=true`;
- уничтоженный/исчезнувший corpse всё равно формирует retryable dead snapshot;
- resurrect умеет использовать cached corpse и повторно регистрирует живую пешку;
- pending death/sync data снимается только после успешной доставки.

Код: `PawnManager.cs:74-169, 204-244, 310-430, 613-685, 1134-1207`.

### P2-2. Lifecycle продолжал polling вне активной игры

Исправление:

- `GameSessionActive` разрешает polling только после готовности мира;
- `FinalizeInit`, `StartedNewGame` и отложенная готовность сведены в идемпотентный `TryInitializeSession`;
- при выходе/смене игры отправляется offline один раз;
- pending main-thread queue очищается, session state и pawn cache инвалидируются;
- мод отписывается от `Application.quitting` и освобождает очередь при `Dispose`.

Код: `RimLinkGameComponent.cs:71-119, 192-225`, `RimLinkMod.cs:20-22, 90-127, 478-493`.

### P2-3. HTTP 200 ошибочно считался успешной операцией

Сам факт получения тела от `POST` раньше означал успех. Backend мог вернуть JSON-отказ, а мод помечал каталог/ACK как доставленный.

Исправление:

- общий `ResponseIsOk` требует `status=ok` либо boolean `success=true`;
- прикладной отказ возвращается вызывающему коду с текстом ошибки;
- `SessionStart`, ACK, pawn/catalog sync теперь возвращают реальный boolean результата;
- добавлен `ReadWriteTimeout=8s` наряду с connect timeout;
- в настройках есть явная проверка URL + module-token;
- module-token отображается как password field и раскрывается только по переключателю.

Код: `RimLinkAPI.cs:35-42, 81-127, 207-307`, `RimLinkMod.cs:160-186, 392-469`.

### P2-4. Перекрывающиеся heartbeat и небезопасный background-доступ

Исправление:

- одновременно допускается только один heartbeat через `Interlocked` guard;
- каталоги строятся на main-thread, фоновой остаётся только HTTP-отправка;
- sync игровых объектов сначала делает immutable snapshot на main-thread;
- polling использует exponential backoff до 60 секунд.

Код: `RimLinkGameComponent.cs:39-68, 151-180`, `RimLinkMod.cs:88-127, 453-469`.

### P2-5. Слишком терпимый JSON parser

Старый parser принимал оборванные объекты, trailing data, неизвестные escapes и произвольные токены. Битый command payload мог частично распарситься и попасть в gameplay.

Исправление:

- payload limit 5 MiB;
- nesting limit 64;
- обязательны корректные `{}`, `[]`, двоеточия и запятые;
- запрещены trailing data и управляющие символы;
- валидируются unicode escapes;
- некорректный payload даёт terminal failure, а не частично выполненную команду.

Код: `SimpleJson.cs:98-280`, `CommandQueue.cs:394-405`.

## Дополнительные safety fixes

- Raid/manhunter points ограничены диапазоном 35–3000, включая top-level и legacy `params.points`.
- При частичном исключении установки xenotype восстанавливаются прежние xenogenes и имя xenotype.
- Ошибка показа игрового notification после успешного создания пешки больше не превращает состоявшийся gameplay effect в failure/refund.
- Пользовательский интерфейс настройки каталога различает успешную доставку и отказ backend.

Код: `EventCommands.cs:113-122, 257-269`, `CommandFactory.cs:208-253`, `PawnCommands.cs:53-88`.

## Проверка backend-контракта

Запущен `python Расширение/backend/tests/test_rimworld_refund.py`:

1. `success=false` возвращает списанную цену и закрывает очередь;
2. повторный fail-ACK не делает второй refund;
3. `success=true` не возвращает валюту и закрывает строку;
4. stale delivered command автоматически возвращает деньги;
5. legacy command без price не падает и не начисляет валюту;
6. внутренняя ошибка обработки ACK отвечает retryable HTTP 503, а не ложным HTTP 200.

Результат: **11 PASS, 0 FAIL**.

Полный пользовательский economic track находится в `scripts/audit-rimworld-track-c.py`: создание пешки, dedup двойного клика, лечение и cooldown, воскрешение, магазин/equip, passions и отказ мода с refund. Скрипт специально запрещает запуск против production и требует локальный backend с тестовой базой.

## Что отчёт не утверждает

- Не утверждается, что все RimWorld engine API прошли реальную игру: автоматический harness не эмулирует Verse/RimWorld simulation.
- Не проверены в живой игре мод-конфликты, несколько карт, caravan transition, corpse destruction, save switch и xenotype rollback.
- Сборка выполнена против установленной локальной версии RimWorld; `About.xml` заявляет 1.5 и 1.6, но отдельная компиляция/игровой smoke на обеих версиях не выполнялись.
- При недоступном диске outcome journal не сможет дать гарантию переживания рестарта; ошибка будет записана в лог.
- Если initial `SessionStart` отклонён, текущая сессия не повторяет полный bootstrap немедленно; обычные sync продолжаются, но очистка старых server rows будет ждать следующей инициализации. Это оставшийся lifecycle edge case для следующей итерации.

## Обязательный smoke на следующем стриме

1. Подключение с валидным и неверным module-token.
2. Платная команда: apply → ACK → один debit.
3. Команда без эффекта: `success=false` → один полный refund.
4. Оборвать сеть после gameplay effect, восстановить и убедиться, что ACK повторён без второго effect.
5. Перезапустить игру с pending ACK и проверить journal recovery.
6. Переименовать viewer pawn, отправить в caravan и вернуть на другую карту.
7. Убить, уничтожить/потерять corpse и воскресить пешку.
8. Сменить save при заполненной очереди и убедиться, что старая команда не применяется в новом мире.
9. Дать burst команд и проверить отсутствие заметного frame hitch.
10. Проверить raid/manhunter safety cap и xenotype failure rollback.

## Команды для перепроверки другим аудитором

```powershell
dotnet build RimLink/Source/RimLink.csproj -c Release
python "Расширение/backend/tests/test_rimworld_refund.py"
git diff --check -- RimLink
Get-FileHash -Algorithm SHA256 RimLink/Assemblies/RimLink.dll
Get-FileHash -Algorithm SHA256 "X:\SteamLibrary\steamapps\common\RimWorld\Mods\RimLink\Assemblies\RimLink.dll"
```

Ожидаемый SHA-256 обеих DLL:

`7006E3F223A230C2EBCE13D73EDA71377059969D68D8D82BF53B0D73C69FAAA0`
