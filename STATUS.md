# ShedLink — текущее состояние

Обновлено: 2026-08-15

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
  Исправление ещё не deployed.
- Свежий production backup за 15 августа успешно восстановлен в изолированный
  временный файл и прошёл `quick_check`; живая БД не изменялась.
- Начат R1: создана Installation Manifest v1 schema и проверяемый RimWorld
  manifest, привязанный к release archive по размеру и SHA-256. Artefact пока
  локальный и unsigned; внешний distribution ещё не опубликован.
- Добавлен независимый installation transaction contract: staging verification,
  path boundary, atomic replace, rollback и recovery после жёсткого обрыва
  проходят автоматические conformance-тесты; перенос в .NET Core — следующий шаг.
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
  в CI. Install CTA вызывает recoverable signed-HTTPS operation, но текущий
  unsigned manifest и пустой production trust store держат кнопку отключённой;
  production не обновлён.
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
  Offline signer готов и требует внешний RSA 3072+ PEM. Production signing key
  и конечный URL ещё не созданы, CTA остаётся выключен.
- Module credential теперь можно проверить отдельным side-effect-free auth-check:
  он не создаёт ложный heartbeat и не меняет liveness игры.
- Read-only production check 2026-08-16: `/health` отвечает 200 (`db=ok`),
  новый `/v1/module/rimworld/auth-check` ещё не развёрнут и отвечает 404.
  Локальный Manager поэтому не считается production-ready до штатного deploy.
- Активная игра определяется по heartbeat мода; действия выключенной integration
  отклоняются безопасно.
- Релиз 0.0.2 зафиксирован тегом `submit/0.0.2`; канонический архив хранится в
  `dist/releases/`.
- Старый stabilization roadmap завершён и перенесён в `docs/archive/`.

## Текущий этап

`R2 — ShedLink Manager MVP: One Game` из `ROADMAP.md`, при открытом live-gate R0.

Baseline актуального HEAD завершён. RimWorld — условный кандидат для Manager
vertical slice, но R0 release gate ещё не пройден.

## Следующие действия

1. Выполнить RimWorld live smoke: apply/refuse, lost ACK, restart и reconnect.
2. После live smoke окончательно утвердить первую Manager integration.
3. Создать offline production signing key, встроить public key и опубликовать
   RimLink archive по конечному HTTPS URL; после этого уже подключённый WPF CTA
   станет доступен без изменения policy.
4. Проверить `Technical Ready` на реальной RimWorld после signed release/deploy.
5. Включить M109 repair, M110–M112 Manager migrations/API и обновлённые runtime
   manifests в следующий штатный production deploy.

## Правило обновления

Здесь находится только текущее состояние, не дневник. Закрытые подробности
остаются в Git и архивных документах. После каждой значимой сессии обновляются
дата, текущий этап, доказанные факты и следующие действия.
