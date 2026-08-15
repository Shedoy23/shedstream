# ShedLink — отложенные решения

Обновлено: 2026-08-15

Этот файл содержит только решения, сознательно отложенные относительно текущего
product roadmap. Полная история до 2026-08-06 находится в
`docs/archive/DEFERRED_THROUGH_2026-08-06.md`.

## До завершения R0–R3

- CK3 integration;
- marketplace/community integrations;
- публичный Integration SDK;
- сложная plugin-система Manager;
- billing и Pro trial;
- viewer monetization;
- масштабный frontend redesign, не подтверждённый activation/retention данными;
- добавление игр ради количества.

## До измеренного infrastructure trigger

- миграция SQLite → PostgreSQL;
- выделенный worker/process;
- object storage/CDN для downloads;
- microservices;
- Kubernetes.

## Требует продуктового решения

- поведение всей integration-вкладки, когда выбранная игра или мод выключены;
- пересчёт исторических streamer/viewer streaks после исправления двойных
  `stream_sessions`;
- окончательный состав Free/Pro после появления retention data;
- выбор CK3 после подключения второй существующей integration к Manager.

## Правило ведения

Новый пункт добавляется только вместе с причиной, условием возврата и ссылкой на
milestone. Выполненный пункт удаляется: история остаётся в Git.
