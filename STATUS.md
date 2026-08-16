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
- Собран передаваемый `ShedLink Manager 0.1.0-alpha.1`: self-contained single-file
  Windows x64 EXE, production manifest, `START-HERE.txt` и `RELEASE.json` без
  debug-файлов и secrets. ZIP распакован и успешно запущен вне repository;
  SHA-256 `ee065338...a8433e`. Evidence:
  `docs/MANAGER_ALPHA_0.1.0_ALPHA1_2026-08-16.md`.
- Активная игра определяется по heartbeat мода; действия выключенной integration
  отклоняются безопасно.
- Релиз 0.0.2 зафиксирован тегом `submit/0.0.2`; канонический архив хранится в
  `dist/releases/`.
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

## Следующие действия

1. Передать alpha-пакет первому внешнему тестировщику и измерить TTTR.
2. Зафиксировать все непонятные шаги и исправить только реальные blockers.
3. При доступной чистой Windows-среде провести matrix и три clean-install.

Offline backup production private key остаётся рекомендуемой операционной
защитой, но переносится до появления подходящего отдельного носителя и не
блокирует alpha-подготовку.

## Правило обновления

Здесь находится только текущее состояние, не дневник. Закрытые подробности
остаются в Git и архивных документах. После каждой значимой сессии обновляются
дата, текущий этап, доказанные факты и следующие действия.
