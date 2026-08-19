# ShedLink — текущее состояние

Обновлено: 2026-08-16

## Источник истины

- Активный checkout: `main`.
- Канонический remote: `afterlait/main`.
- Текущий продуктовый план: `ROADMAP.md`.
- Эксплуатационные процедуры: `RUNBOOK.md`.
- Исторический статус до 2026-08-06:
  `docs/archive/STATUS_THROUGH_2026-08-06.md`.
- Исторический deferred-журнал до 2026-08-06:
  `docs/archive/DEFERRED_THROUGH_2026-08-06.md`.
- Передача работы другой модели (когда у текущей кончаются лимиты):
  `docs/HANDOFF_TO_NEXT_AGENT.md` — состояние по трём трекам, решения владельца,
  которые не пересматриваются, ловушки машины и список непроверенного.

## Подтверждённый фундамент

- Twitch OAuth и реестр каналов;
- channel approval gate;
- runtime Module API и manifests;
- Bannerlord, RimWorld и ShedColony integrations;
- channel-scoped state, heartbeat и action queues;
- atomic/deduplicated денежные пути и refunds для основных проверенных сценариев;
- fresh-install migrations;
- production runbook, monitoring и release artefacts 0.0.2.

## Последнее подтверждённое состояние продукта

- R0 baseline проверен на source commit `03b1fa9` и на production; полный отчёт:
  `docs/R0_GAP_ANALYSIS_2026-08-15.md`.
- Production healthy: публичные страницы отвечают HTTP 200, база проходит
  `quick_check`, незавершённых module actions и отрицательных балансов нет.
- Исправление двух `stream_sessions` live-подтверждено на эфирах 11, 13 и
  14 августа: один Twitch stream ID на непрерывный эфир.
- M109 теперь регистрируется в migration ledger, безопасно ремонтирует уже
  существующую таблицу и покрыта regression; полный backend suite 48/48 green.
  Исправление развёрнуто 2026-08-16 вместе с M110–M112.
- Свежий production backup за 15 августа успешно восстановлен в изолированный
  временный файл и прошёл `quick_check`; живая БД не изменялась.
- Начат R1: создана Installation Manifest v1 schema и проверяемый RimWorld
  manifest, привязанный к release archive по размеру и SHA-256. Artefact
  опубликован как signed immutable HTTPS release.
- Добавлен независимый installation transaction contract: staging verification,
  path boundary, atomic replace, rollback и recovery после жёсткого обрыва
  проходят автоматические conformance-тесты; этот контракт уже перенесён в .NET
  Core и используется Manager.
- M110/M111 создают persistent pairing/session/credential ledger и связывают
  Manager session с одобренным module scope. Browser pairing не передаёт Twitch
  tokens в desktop app; тесты покрывают approve/deny/expire, одноразовый exchange,
  tamper/expiry, restart persistence и refresh replay.
- Pairing HTTP/browser flow, opaque module credentials, refresh rotation и
  logout подключены локально. Module API и RimWorld ingest принимают отзывной
  `slmod_v1` параллельно с legacy auth; полный backend suite 48/48 green.
- Desktop Manager: выбран .NET 8 + WPF, создан UI-independent Core и WPF shell с
  browser pairing/session resume, Windows Credential Manager vault, атомарным
  несекретным state и restart recovery. RimWorld определяется в Steam libraries
  либо проверяется по ручному path. Windows build/self-test зелёные и добавлены
  в CI. Install CTA вызывает recoverable signed-HTTPS operation; production
  Manager API, release delivery и trust gate развёрнуты и проверены.
- Manager получил явный выход с опциональным немедленным отзывом ключа RimLink.
  Смена ключа запрещена при запущенной игре, проверяет новый ключ до активации и
  после сбоя восстанавливает согласованное состояние XML, Credential Manager и
  несекретного state при следующем запуске.
- Диагностический JSON-отчёт показывает версии, health probes, heartbeat и
  последние сообщения только после явного предпросмотра. Автотест подтверждает
  удаление module tokens, authorization, приватного URL и Windows profile path.
  Версия RimWorld читается из `Version.txt`; отчёт отдельно объясняет unmanaged
  installation, а неподдерживаемая версия блокирует install и `Technical Ready`.
- Встроенный release-каталог выбирает самый новый RimLink manifest, совместимый
  с найденной версией RimWorld. Install/repair/config/rotation используют один
  выбранный manifest; отсутствие подходящей версии даёт безопасный отказ.
- Локальный RSA 4096 key generator готов и проверен: не перезаписывает файлы,
  запрещает путь внутри repository и ограничивает private PEM текущим Windows
  user. Production key создан вне repository; external offline backup ещё нужен.
- Независимый release verifier готов: проверяет signed HTTPS manifest, локальные
  или заново скачанные ZIP bytes, size/SHA-256/RSA-PSS, безопасную распаковку и
  обязательные health probes до публикации или встраивания manifest в Manager.
  Полный локальный rehearsal `generate → sign → verify` на RimLink `0.1.1`
  прошёл; все временные ключи и подписанная копия после проверки удалены.
- Production `/releases/` настроен после явного подтверждения: конфиг сохранён в
  backup, `nginx -t` зелёный, reload успешен. HTTPS ZIP отвечает 200 без redirect,
  HTTP 404, listing/POST 403; backend `/health` остался 200.
- Канонический `RimLink-0.1.1.zip` пересобран PowerShell 7 и совпадает с manifest:
  `63673` bytes, SHA-256 `4e9656cb...ed42381`. Упаковщик теперь fail-closed
  отклоняет Windows PowerShell 5, который создаёт другие ZIP bytes.
- Installation transaction перенесён в .NET Core: production manifest parsing,
  artifact size/SHA-256, safe ZIP, reparse guard, atomic swap, rollback и crash
  recovery зелёные. XML writer сохраняет чужие поля и ставит user-only ACL.
- Package install, managed XML и side-effect-free auth-check объединены в одну
  recoverable Core operation для repository и signed HTTPS. Auth failure
  откатывает обе части; verified crash безопасно завершается после restart.
- WPF умеет атомарно удалить RimLink после подтверждения, сохраняя config и
  module credential для восстановления. Interrupted removal откатывается,
  verified crash завершается после restart, повторное удаление идемпотентно.
- Manager различает missing/broken/outdated/healthy RimLink, показывает
  установленную и доступную версии и меняет CTA на install/update/repair/reinstall.
- Authenticated runtime status читает реальный heartbeat без изменения liveness;
  WPF показывает online/offline и возраст последнего сигнала каждые 15 секунд.
  Legacy RimLink heartbeat/offline подключены к общему M109 ledger.
- M112 хранит результат безопасного diagnostic action. RimLink `0.1.1` выполняет
  `diagnostic_ping` без изменения игры и возвращает реальный ACK; только тогда
  WPF показывает итоговый `Technical Ready`.
- HTTPS distribution verifier готов локально: no redirects/downgrade, bounded
  download, SHA-256 и trusted RSA-PSS publisher signature до распаковки.
  Production RSA 4096 key, embedded public key и immutable RimLink `0.1.1` URL
  созданы; downloaded production bytes прошли independent verifier.
- Module credential теперь можно проверить отдельным side-effect-free auth-check:
  он не создаёт ложный heartbeat и не меняет liveness игры.
- Штатный production deploy 2026-08-16 завершён: `/health` и публичные страницы
  отвечают 200, `/v1/module/rimworld/auth-check` отвечает ожидаемым 401 без
  credential вместо прежнего 404, pairing API выполнил тестовую защищённую
  запись. M109–M112 и новые таблицы подтверждены, `quick_check=ok`, отрицательных
  points и незавершённых действий нет. Тестовая pairing-запись удалена. Полный
  evidence: `docs/PRODUCTION_MANAGER_DEPLOY_2026-08-16.md`.
- Реальный Manager-прогон 2026-08-16 дошёл до `Technical Ready`: Twitch channel
  подключён, RimWorld `1.6.4871 rev590` найдена, signed RimLink `0.1.1`
  установлен и настроен, файлы здоровы, heartbeat свежий, production diagnostic
  action получил ACK. Ручной JSON, token или API URL не потребовались.
- По решению владельца production RimWorld разрешает viewer actions без активного
  Twitch-эфира (`RIMWORLD_REQUIRE_STREAM_LIVE=false`). Общий testing bypass
  остаётся выключен, поэтому Bannerlord, дуэли, TTS и остальные stream gates не
  ослаблены. Отдельный regression и внешний API probe пройдены.
- Production backend поддерживает бесплатные Manager reliability diagnostics:
  безопасный mod refusal и контролируемую потерю ACK с TTL-очисткой. Новый EXE
  показывает отдельную кнопку `Проверить отказы`; автоматические backend и
  Manager tests зелёные. Production live-прогон подтвердил ожидаемый refuse,
  lost-ACK expiry/cleanup и поздний идемпотентный retry без списаний.
- R0 release gate закрыт. Реальные RimWorld-команды применились; backend restart
  и heartbeat reconnect пережиты; отказ и потерянный ACK завершились безопасно.
  После проверки очередь `0`, отрицательных points `0`, `quick_check=ok`.
- Update/Repair rehearsal выполнен на отдельной копии реально установленного
  RimLink: состояния прошли `Healthy → RepairRequired → Healthy →
  UpdateAvailable → Healthy`. Оба восстановления использовали подписанный
  production HTTPS archive; содержимое исходной папки RimLink не изменилось,
  временная копия и transaction artifacts очищены. Evidence:
  `docs/MANAGER_LIFECYCLE_REHEARSAL_2026-08-16.md`.
- Готов передаваемый `ShedLink Manager 0.1.0-alpha.2`: self-contained single-file
  Windows x64 EXE, production manifest, `START-HERE.txt` и `RELEASE.json` без
  debug-файлов и secrets. ZIP распакован и запущен вне repository; SHA-256
  `09238fe1...65a6d18c`. Заменил alpha.1, у которого инструкция отправляла
  тестировщика к файлу вне архива, не давала команды проверки, описывала
  SmartScreen без двух обязательных кликов, а `RELEASE.json` записал commit,
  не содержавший сборки. Упаковщик теперь отказывается работать с грязным
  деревом и проверяет кодировку инструкции. Артефакты alpha.1 удалены, чтобы
  их нельзя было отправить по ошибке. Evidence:
  `docs/MANAGER_ALPHA_0.1.0_ALPHA2_2026-08-16.md`.
- Повторные install и repair доказаны идемпотентными: двойная установка и
  установка поверх повреждённой дают тот же состав файлов, ту же managed
  config и не оставляют служебных копий в папке `Mods`. Тест сначала показан
  красным на намеренно сломанной очистке. Manager Core self-test: 70 проверок,
  код возврата `0`.
- Manager умеет обновлять сам себя тем же проверенным путём, что и моды:
  подписанный манифест по HTTPS, точный размер и SHA-256, подпись издателя до
  распаковки, отказ от подсунутой старой версии, подмена работающего EXE с
  откатом при сбое. Это пока только ядро: кнопки в интерфейсе нет и на сайте
  ничего не опубликовано, поэтому пользователю функция ещё не видна.
- Manager перестал знать, какую игру ищет: поиск в Steam, проверка папки, имя
  процесса и чтение версии берутся из манифеста установки. Доказано тестом на
  игре, которой код не знает. Поведение RimWorld не изменилось. Осталась одна
  заглушка `RimWorldDetectionService` — уйдёт, когда интерфейс начнёт сам
  передавать манифест.
- Вторая интеграция — **Bannerlord** (решение владельца 2026-08-16). Контракт
  настроек расширен под неё: формат `xml`/`json`, конфиг может лежать в папке
  игры, появился источник значения `channel_id`. Файл настроек RimWorld при
  этом не изменился. План и остаток: `docs/MANAGER_MULTI_GAME_PLAN.md`.
- Не сделано и нужно для Bannerlord: манифест самой игры, подписанный и
  опубликованный архив её мода (действие на production), выбор игры в
  интерфейсе и живой прогон до `Technical Ready`.
- Упаковщик архива мода Bannerlord готов (`scripts/pack-bannerlord-release.ps1`):
  кладёт ровно три файла по явному списку, не заглядывая в папку игры, где
  рядом с модом лежит `config.json` с рабочим токеном. Обе защиты — отказ под
  PowerShell 5.1 и отказ при появлении секрета в списке — проверены
  подкладыванием ошибки, архив в обоих случаях не создаётся.
- Блокер публикации снят: PowerShell 7.6.5 установлен 2026-08-16 с разрешения
  владельца. Ставится вариантом из Store, поэтому `pwsh` по имени не находится
  (`WindowsApps` нет в PATH) — зовём полным путём, команда в `RUNBOOK.md`.
  Цепочка выпуска проверена по-настоящему: тем же pwsh пересобран канонический
  `RimLink-0.1.1.zip` и совпал с опубликованным **байт в байт**.
- Архив мода Bannerlord собран: `dist/releases/BannerlordLink-0.1.0.zip`,
  218 775 байт, SHA-256 `2f5e431e…cf43416a`. Внутри ровно три файла —
  `SubModule.xml`, `BannerlordLink.dll`, префаб интерфейса; ни `config.json`,
  ни исходников, ни отладочных символов. Сборка детерминирована: повторная
  упаковка дала ту же сумму. Осталось на владельце: подписать и выложить по
  неизменяемой HTTPS-ссылке (production, приватный ключ), после чего можно
  писать манифест Bannerlord — ему нужны URL, размер и подпись.
- Пакет `0.1.0-alpha.2` собран до этих изменений и контракту настроек не
  противоречит: он несёт свой манифест старого вида и работает. Следующая
  сборка подхватит новый контракт автоматически.
- **Отдавать тестировщику надо `0.1.0-alpha.3`, не `alpha.2`.** `alpha.2`
  собран до починки отказа в правах, то есть в нём строка матрицы
  «недостаточно прав на запись» всё ещё означает закрытие приложения — ровно
  тот сценарий, ради которого тестировщика и зовут. `alpha.3` собран
  2026-08-16 из коммита `d8fb0474614a`, SHA-256 архива
  `788e6f79...ddbb785a`. Проверено: в архиве только EXE, манифест,
  `START-HERE.txt` и `RELEASE.json`; отладочных файлов и секретов нет,
  контрольная сумма в `.sha256` сходится с архивом, записанный коммит
  совпадает с собранным. Манифест внутри — уже нового вида, парный своему EXE.
  Запуск распакованного EXE подтверждён владельцем 2026-08-16. Артефакты
  `alpha.2` удалены в тот же день, чтобы их нельзя было отправить по ошибке —
  как ранее поступили с `alpha.1`; `alpha.3` после удаления сверен по SHA-256 и
  цел. В `dist/releases` остаются четыре папки `ShedLink.Manager-preview-*` от
  16.08 — это черновые сборки дня, не предназначенные для передачи; судьба не
  решена.
- Активная игра определяется по heartbeat мода; действия выключенной integration
  отклоняются безопасно.
- Отказ Windows в правах на запись больше не роняет Manager. Установка,
  удаление и смена ключа перечисляли `IOException`, а отказ в правах приходит
  другим типом и не ловился ни одним обработчиком — то есть строка матрицы R3
  «недостаточно прав на запись» до 16.08 означала закрытие приложения без
  объяснения. Тексты ошибок переехали в Core и покрыты тестом: у каждого класса
  сбоя из матрицы свой текст и названное следующее действие. Оба дефекта
  показаны красными перед починкой.
- После уточнения владельца ожидание первого RimWorld-тестировщика больше не
  блокирует multi-game работу. Чтение версии переведено с первой строки на весь
  файл с группой захвата: Bannerlord `v1.3.15` определяется как совместимость
  `1.3`, XML-декларация `1.0` не принимается за версию игры, RimWorld не
  изменился. Добавлен development-манифест Bannerlord и общий release-каталог,
  который обнаруживает RimWorld и Bannerlord без списка игр в коде. Core
  self-test зелёный. Интерфейс выбора игры и раздельное состояние интеграций
  подключены: дальнейшие поиск, установка и диагностика идут по выбранному
  манифесту, а переключение не перезаписывает папку, версию, credential или
  защищённую сессию другой игры. Последняя RimWorld-заглушка удалена, в коде
  приложения больше нет названий конкретных игр.
- BannerlordLink `0.1.0` подписан и опубликован с подтверждения владельца:
  HTTPS `200` без redirect, `218775` байт, SHA-256 `2f5e431e…cf43416a`,
  повторное скачивание и независимая RSA-проверка зелёные; HTTP `404`,
  listing/POST `403`, backend `/health` `200`. Подписанный манифест встроен в
  multi-game Manager, поэтому безопасная установка Bannerlord из интернета
  локально разблокирована. Evidence:
  `docs/BANNERLORD_MANAGER_RELEASE_2026-08-16.md`.
- Собран первый multi-game пакет Manager `0.1.0-alpha.4` из коммита
  `08827e9e871a`. Внутри подписанные каталоги RimWorld и Bannerlord, новая
  инструкция выбора игры и никаких debug-файлов/секретов. SHA-256 архива
  `9ba1f2ef…2ae1f03`; `.sha256`, записанный commit и обе подписи повторно
  сверены. Отправлять для multi-game проверки нужно `alpha.4`, а не `alpha.3`.
  Evidence: `docs/MANAGER_ALPHA_0.1.0_ALPHA4_2026-08-16.md`.
- Живой Bannerlord install 19.08 нашёл дефект `alpha.4`: Manager пытался
  повторно назначить владельца уже созданному `config.json`, а Windows требует
  для этого административную привилегию на этой Steam library. Без admin
  установка откатывалась. Удалена только лишняя смена владельца; закрытый ACL
  текущего пользователя сохранён. Повторный живой прогон зелёный: BannerlordLink
  `0.1.0` установлен, JSON с URL/channel/token создан автоматически, секрет не
  выводился, transaction-хвостов нет, state записан. Evidence:
  `docs/MANAGER_BANNERLORD_LIVE_INSTALL_2026-08-19.md`.
- Собран исправленный multi-game пакет `0.1.0-alpha.5` из коммита
  `444a7d8e54b7`; SHA-256 `f51580c3…526b14be`. Состав, записанный commit,
  отсутствие секретов/debug-файлов и полный Core self-test повторно сверены.
  Для любых следующих проверок использовать `alpha.5`, не `alpha.4`.
  Evidence: `docs/MANAGER_ALPHA_0.1.0_ALPHA5_2026-08-19.md`.
- Twitch Extension `0.0.2` отправлена в Review 2026-08-16; ждём решение Twitch.
  Релиз зафиксирован тегом `submit/0.0.2`, канонический неизменяемый архив
  хранится в `dist/releases/`, SHA-256 начинается с `E5A2B411`. До вердикта
  frontend Extension, cache-bust и ZIP заморожены. Manager, backend и игровые
  моды продолжаем развивать; backend сохраняет совместимость с публичной
  `0.0.1` и поданной `0.0.2`.
- Старый stabilization roadmap завершён и перенесён в `docs/archive/`.

## Текущий этап

`R2 — ShedLink Manager MVP: One Game` функционально завершён для RimWorld:
production vertical slice, reliability и локальный Update/Repair gate закрыты.
Текущая работа перешла к подготовке handoff-пакета для `R3 — Internal Clean
Install and M1`.

RimWorld утверждён первой Manager integration. Versioned alpha-архив уже собран
и запускается вне repository. Следующий продуктовый результат — первый
независимый clean-install с измерением TTTR и фиксацией непонятных шагов. Clean
Windows matrix остаётся evidence для M1, но не требует покупки оборудования.

Уточнён итоговый контракт Manager: это единая точка входа для нового стримера,
которая сама находит игры, скачивает, проверяет, устанавливает, настраивает и
обновляет все файлы выбранной интеграции. Пользователь не работает с токенами,
JSON/XML, URL или DLL. Текущая RimWorld-only оболочка этому контракту ещё не
соответствует; multi-game каталог и Bannerlord-манифест уже начаты, следующим
результатом должен стать реальный выбор интеграции и раздельное состояние игр.

### Предвыпускная проверка мульти-игрового Manager — 19.08

Артефакты BannerlordLink `0.1.1`, ShedColony `0.1.0` и Manager `alpha.8`
перепроверены независимо от сессии, которая их собирала. Совпали размеры и
SHA-256, подписи верны — в том числе у манифестов, физически лежащих ВНУТРИ
собранного Manager, то есть у тех байтов, которыми будет пользоваться стример.
Public key в приложении побайтово равен релизному. В архивах нет токенов,
`config.json`, PDB, исходников и ключа; код MineColonies внутрь не попал.
SelfTest, Release build, весь backend-набор (51/51) и линтер — ноль.
Целевые URL обоих новых архивов свободны (404), публикация ничего не перезапишет.
Добавлен тест серверного сценария готовности для Bannerlord и ShedColony —
раньше он существовал только для RimWorld. Полное evidence:
`docs/MANAGER_MULTIGAME_PREFLIGHT_2026-08-19.md`.

**Опубликовано 19.08 по явному подтверждению владельца:** оба архива лежат на
`https://shedoy23.ru/releases/`, скачанные SHA-256 совпали, независимый
верификатор зелёный, HTTP закрыт, листинг и POST 403, `/health` 200. Backend
обновлён отдельно (гейт 107/0, миграции прошли, три модуля обнаружены, чат-бот
переподключился). Фронт расширения не деплоился. И отдельно:
живая проверка Minecraft ПРОЙДЕНА 2026-08-20 на настоящем NeoForge 1.21.1 +
MineColonies (инстанс Lexplosion, 73 мода): ставится только наш JAR, соседние
моды байт-в-байт целы, конфиг создан и в диагностический отчёт токен не утёк,
heartbeat живой и авторизованный, удаление не трогает MineColonies и по «Да»
отзывает ключ. Оговорка в силе: «готовность» для Minecraft — это живой
авторизованный heartbeat, а не исполнение командой мода; опубликованный JAR
`diagnostic_ping` не умеет. Не прогоняли вживую только сценарий «нет
MineColonies» (покрыт тестом). Полное evidence:
`docs/MANAGER_MULTIGAME_PREFLIGHT_2026-08-19.md`.

## Следующие действия

1. Запустить Bannerlord и завершить живой прогон до `Technical Ready`.
2. Передать исправленную multi-game alpha внешнему тестировщику и измерить TTTR.
3. Зафиксировать все непонятные шаги и исправить только реальные blockers.
4. При доступной чистой Windows-среде провести matrix и три clean-install.

Offline backup production private key остаётся рекомендуемой операционной
защитой, но переносится до появления подходящего отдельного носителя и не
блокирует alpha-подготовку.

Отдельное ограничение на время Twitch Review: фронт Extension не ДЕПЛОИТСЯ до
вердикта по `0.0.2`. Это не блокирует текущий план Manager и другие части
продукта. Заморозка сверена командами 16.08: поданный архив совпал по SHA-256,
cache-bust одинаков в обоих шеллах — таблица в
`Расширение/docs/RELEASE_RECORD.md`.

**Уточнение 2026-08-19 (решение владельца «начинай работать всё, что можем»).**
Формулировка «правки фронта не начинаем» заменена на «фронт не деплоится».
Поданный архив неизменяем и пришпилен тегом `submit/0.0.2` — правки в рабочем
дереве его не трогают; на ревью влияет только деплой. С 19.08 фронт в
репозитории ОТЛИЧАЕТСЯ от тега: идёт рефакторинг «ядро + игровые модули»
(`Расширение/docs/FRONTEND_MODULE_ARCH_PLAN.md`, шаги 1–2 из 5 сделаны и
проверены в браузере). Добавлены `frontend/viewer-actions.js` (один платный
путь на все игры) и `frontend/viewer-registry.js` (реестр игр вместо if/else),
оба подключены в обе оболочки. Cache-bust НЕ трогали
намеренно — он бампится только деплоем.
Чтобы «не деплоится» было механизмом, а не обещанием: `scripts/deploy.ps1`
блокирует `-Frontend` флагом `$FrontendReviewOpen` (прежняя защита была
привязана к дате 2026-07-28 и протухла сама ровно к новому ревью). В день
вердикта: снять флаг, сверить фронт с тегом, выпускать батч `0.0.3`.

Шаги Verification 1–8 живьём перед подачей НЕ прогонялись (владелец
подтвердил 16.08). Машинная часть прогона сделана в тот же день, результат — в
`Расширение/docs/CHANGELOG_0.0.2.md`. Шесть шагов из восьми сходятся; два нет:

- **Цена мастерской и каравана на кнопке не та, что списывается.** Показано
  `💎1000 + 💰20 000` и `💎1500 + 💰15 000`, списывается `2500💎` и `4000💎`,
  динары не списываются вовсе. Расхождение с 2026-05-29, когда цены подняли на
  бэкенде. Чинится только фронтом, а фронт заморожен до вердикта Twitch. Это
  же место ломает шаг 4 инструкции ревьюеру.
- **Ревьюер не откроет дашборд из шага 8**: `/streamer/dashboard` требует входа
  как одобренный стример, аккаунта у него нет.

Решение по обоим — за владельцем; варианты и цена каждого разобраны в сессии
16.08. Шаги 1, 2 и горизонтальная прокрутка на мобильном шелле остаются за
живым прогоном.

## Правило обновления

Здесь находится только текущее состояние, не дневник. Закрытые подробности
остаются в Git и архивных документах. После каждой значимой сессии обновляются
дата, текущий этап, доказанные факты и следующие действия.
