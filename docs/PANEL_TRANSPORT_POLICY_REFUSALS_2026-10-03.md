# Панель Preact: однозначные policy-отказы транспорта

## Граница работы

Только локальный frontend-кандидат от `38beb210f553181915c8ea7fc434a0be1c3a92aa`.
Работа из отдельного worktree и собственной копии node_modules; общая рабочая копия,
backend, старый frontend, корневые tests, моды, OBS, production и remote не менялись.
Публикация ждёт отдельного разрешения владельца. Браузер, 318 px, телефон,
Hosted Test и игровые эффекты не проверялись.

## Причина

`require_jwt_user` реального `main.app` возвращает HTTP 403 с
`detail.status=channel_not_registered` / `channel_pending_approval` либо HTTP 429
с `detail.status=channel_rate_limited` до чтения тела действия, входа в игровую БД,
списания и очереди. Клиент требовал только верхний `success:boolean`, поэтому эти
отказы теряли серверный текст и ставили постоянный для личности unknown-outcome lock.
Обычные HTTP 200 `success:false` при отсутствии/истечении JWT уже обрабатывались.

## Red-first checkpoint

- Исходная база: полный suite `763 passed, 2 skipped`, exit 0 при `--maxWorkers=2`
- Первоначальный полный запуск без лимита: `735 passed, 2 skipped`, exit 1,
  один worker `panel-kingdom-safety.test.tsx` завершён SIGKILL; причина сигнала не установлена
- Новый regression suite на неизменном transport: `22 failed, 73 passed` (95), exit 1
- Typecheck новых тестов на старом transport: exit 0
- Три канонических отказа, read-текст, ownership, UI, строгая uncertain-граница:
  тест импортирует настоящий committed transport и requestJson, без их мокирования
- Реальный ASGI probe повторён в архиве точной базы: exit 0, 5 реальных ответов,
  0 чтений тела каждого запроса, состояние балансов/героя/очереди до и после совпало

Fixtures: `frontend-next/test/panel-fixtures/policy-responses.json`.
Reproducer: `frontend-next/test/panel-fixtures/generate-policy-responses.py`.
Синтетический JWT, временная SQLite, lifespan не запущен, socket connect/DNS запрещены;
не воспроизводится Twitch/proxy/game окружение. `read()` тесты повторно проигрывают
эти реальные формы POST-ответов; отдельный GET-контракт `viewer_poll` взят из
`dependencies.py:_check_request_rate_limit`, это явно синтетический read-control.

Документация искалась через `scripts/docs-search.py 'unknown outcome'`: найдены
существующие ограничения transport lock в основном результате и отчётах combat/party.
В checkout и исходной общей рабочей копии `.agents/skills` отсутствует.
AGENTS, CLAUDE и LESSONS часть 2 прочитаны. Общие STATUS/DEFERRED/основной результат
не редактируются этим исполнителем по распределению владения.

## Предстоящая проверка

Реализация и окончательные green/mutation/build результаты будут добавлены отдельно.
Никакой фикс на этом red-first checkpoint ещё не заявляется.
