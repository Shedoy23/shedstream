# Вылет при включении автопилота без встречи

Подтверждён дампом `C:/ProgramData/Mount and Blade II Bannerlord/crashes/2026-09-15_18.10.37/dump.dmp`.
Это вылет 15.09.2026 около 23:10 местного времени, Bannerlord 1.4.8.119303.

Поток 0x59e4, объект исключения 000001771fa0bc58: NullReferenceException.
Адрес PlayerEncounter.get_EncounteredBattle в managed stack 0x7ffdb7ff0218
совпадает с ExceptionAddress watchdog. Цепочка:

`OnApplicationTick → Enable(mode=2) → TryEnable → CanHelpDefenders → PlayerEncounter.get_EncounteredBattle`.

Исходный CanHelpDefenders читает EncounteredBattle ДО проверки Current.
При включении на обычной карте Current отсутствует, а getter движка его
разыменовывает. В логе загрузки 23:10:29 также Encounter=False.
Это доказанная причина именно этого дампа; остальные вылеты этим не классифицированы.

Исправление: проверять Current, party и подходящее меню до чтения getter.
Поддержка помощи защитникам и последовательность помощь→атака сохранены.
В исходном codex-public-release уже лежала такая незакоммиченная правка;
она не тронута. Исправление завершено отдельно в codex/autopilot-null-encounter.
Тестовый коммит 36351c2 уже моделирует getter как в игре (throw без Current).

Проверки против настоящего исходника со стабами движка:

- До фикса: exit 1, 19 ok / 66 FAIL с EncounteredBattle requires Current.
- После: exit 0, 153 ok / 0 FAIL, включая включение без встречи и помощь защитникам.
- ContractCheck: exit 0, 262 ожидания совпали с установленными сборками игры.
- BattleMission: exit 0. Release DLL: 0 ошибок, 0 предупреждений.
- Дамп и результаты: `../evidence/crash-20260915-stack.txt`,
  `../evidence/null-encounter-*.log` (локальные выводы).

Установленная до исправления DLL: MD5 9DBEDE52A9BF213A907556D8AC08F64F.
Собранная исправленная DLL: MD5 4F22C7A7C47599A1BEF78B650A637199.
Живой запуск после замены ещё не проверен; требуется загрузить прежний сейв
и включить F11 на карте без встречи, затем проверить помощь защитникам.

Перенос свиты из соседней ветки к этому вылету не относится: его DLL в игру
не устанавливалась. Здесь меняется только отдельный BannerlordAutopilot.dll.
