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
  существующую таблицу и покрыта regression; полный backend suite 45/45 green.
  Исправление ещё не deployed.
- Активная игра определяется по heartbeat мода; действия выключенной integration
  отклоняются безопасно.
- Релиз 0.0.2 зафиксирован тегом `submit/0.0.2`; канонический архив хранится в
  `dist/releases/`.
- Старый stabilization roadmap завершён и перенесён в `docs/archive/`.

## Текущий этап

`R0 — Current HEAD Baseline and Release Gate` из `ROADMAP.md`.

Baseline актуального HEAD завершён. RimWorld — условный кандидат для Manager
vertical slice, но R0 release gate ещё не пройден.

## Следующие действия

1. Выполнить RimWorld live smoke: apply/refuse, lost ACK, restart и reconnect.
2. Провести restore drill свежего production compressed backup в изоляции.
3. После live smoke окончательно утвердить первую Manager integration.
4. Описать Installation Manifest v1 и единый version ledger отдельно от runtime
   manifest.
5. Включить M109 repair в следующий штатный production deploy.

## Правило обновления

Здесь находится только текущее состояние, не дневник. Закрытые подробности
остаются в Git и архивных документах. После каждой значимой сессии обновляются
дата, текущий этап, доказанные факты и следующие действия.
