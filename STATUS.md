# ShedLink — текущее состояние

Обновлено: 2026-08-15

## Источник истины

- Активная ветка: `afterlait-main`.
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

- Ветка `afterlait-main` синхронизирована с `afterlait/main` на 2026-08-06.
- Исправлено создание двух `stream_sessions` на один эфир; live-подтверждение
  одной строки на следующем реальном стриме ещё требуется.
- Активная игра определяется по heartbeat мода; действия выключенной integration
  отклоняются безопасно.
- Релиз 0.0.2 зафиксирован тегом `submit/0.0.2`; канонический архив хранится в
  `dist/releases/`.
- Старый stabilization roadmap завершён и перенесён в `docs/archive/`.

## Текущий этап

`R0 — Current HEAD Baseline and Release Gate` из `ROADMAP.md`.

Ближайший результат — достоверный baseline актуального HEAD и выбор первой игры
для Manager vertical slice.

## Следующие действия

1. Сверить открытые P0/P1 из исторических документов с актуальным HEAD.
2. На ближайшем реальном стриме подтвердить одну `stream_sessions` на эфир.
3. Зафиксировать ручную установку и configuration/secrets matrix интеграций.
4. Выбрать первую Manager integration.
5. Описать Installation Manifest v1 отдельно от runtime manifest.

## Правило обновления

Здесь находится только текущее состояние, не дневник. Закрытые подробности
остаются в Git и архивных документах. После каждой значимой сессии обновляются
дата, текущий этап, доказанные факты и следующие действия.
