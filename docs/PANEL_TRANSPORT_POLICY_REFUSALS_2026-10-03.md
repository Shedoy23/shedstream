# Панель Preact: однозначные policy-отказы транспорта

## Что изменилось

Канонические отказы до выполнения действия больше не превращаются в
«исход неизвестен»: клиент возвращает `success:false` с точным серверным текстом,
и пользователь может сделать новую попытку отдельным нажатием после устранения причины.
`read()` тоже сохраняет проверенный policy-текст. Автоповтора POST нет.

Runtime изменён только в `frontend-next/src/panel/transport.ts` (+24/−1).
Основа: `38beb210f553181915c8ea7fc434a0be1c3a92aa`.
Реализация: `4dbd3843f4b5f68a9c11bbf2ababfb79c450e966`.
Полный проверенный source/test checkpoint: `37824e624347f2c73e6dab0173021d9a08e47e71`.
SHA-256 транспорта: `a09d3bc530a70a9cd1ca23e3f140602bc7cd9bbdc89d329e0acb2f13f2e2a89a`.

Работа выполнена в отдельном worktree со своей копией node_modules без внешнего
symlink. Общая рабочая копия, backend, старый frontend, корневые tests, моды, OBS,
production и remote не менялись. Публикация ждёт отдельного разрешения владельца.

## Причина и строгая граница

Реальный `main.app` через `require_jwt_user` выдаёт ровно эти outer-отказы:

- HTTP 403 + `detail.status=channel_not_registered`
- HTTP 403 + `detail.status=channel_pending_approval`
- HTTP 429 + `detail.status=channel_rate_limited`

Они возникают до чтения тела действия, входа в игровую БД, списания и очереди.
Старый клиент требовал только верхний `success:boolean`, терял текст и ставил
identity-wide unknown-outcome lock, который переживал обновление JWT.
Сам rate-limit счётчик при попытке изменяется; доказательство отсутствия мутации
относится к игровому действию/деньгам/очереди, а не к этому счётчику.

Новый небольшой helper допускает только JSON object с единственным `detail`,
точную status/code пару, положительный safe-integer `channel_id`, его точное
строковое совпадение с авторизацией, захваченной до запроса, и непустой текст.
Пробелы текста сохраняются: trim используется только для проверки пустоты.
Допустимы только ключи текущей канонической формы. Для rate-отказа дополнительно
проверяются непустой строковый tier, положительный safe-integer limit_per_min
и scope `channel`; при чтении допускается также фактический `viewer_poll`.
Названия тарифов, суммы квот и тексты не копируются в allowlist клиента.

Неизвестный code/status, неправильный/неоднозначный канал, пустой/нестроковый текст,
лишние или смешанные поля action/policy, malformed JSON/HTML, abort, потеря ответа,
таймаут и 5xx остаются неизвестным исходом с прежней блокировкой личности.
Любой 5xx и невозможный response status проверяются до обоих форматов ответа;
это консервативное усиление, включая синтетический 500 с `success:false`.
Обычный top-level `success:false` без смешанного `detail` сохраняет текст и
серверные поля, в том числе уже поддерживаемый игровой cooldown.

Authorization, header, сериализованное тело и client_action_id фиксируются для
одной допущенной попытки. Данные вызывающего кода не изменяются. Нормализация не
декодирует JWT, не обходит auth и не разблокирует ранее неизвестную попытку.
Новая ручная попытка после известного отказа получает текущий JWT и новый ID.
Неизвестный исход по-прежнему принадлежит захваченной паре channel/user; чтение
доступно, смена JWT не снимает lock, возврат к прежнему viewer тоже его не снимает.

## Retry-After и cooldown

Probe реально получил `Retry-After: 60`. Backend вычисляет остаток окна через
`max(1, ceil(reset-now))`; это не всегда 60 и не обещание успешного повтора.
Тело содержит tier/limit_per_min/scope, но не игровой cooldown. В текущем
`main.py` CORS нет `expose_headers` для Retry-After: доступность заголовка браузерному
клиенту cross-origin не доказана. Здесь он не читается и не превращается в
клиентский таймер, cooldown или команду повтора. Серверный текст показан буквально.
Проверки используют и реальный заголовок 60, и явно синтетический 17; ожидание
120 секунд и обновление JWT сами по себе не отправляют новый POST.

## Доказательства

### Red-first

- Commit `46a0a64f6324d6686a257df1b741dd31412faa6f` содержит тесты до реализации:
  на прежнем настоящем transport `22 failed, 73 passed` (95), exit 1
- Typecheck red-first тестов: exit 0
- Финальная расширенная версия тестов против байтов transport точной базы:
  `24 failed, 86 passed` (110), exit 1; после этого возвращены собственные byte-backup
  байты, SHA совпал, `git diff --exit-code` для runtime пуст
- Изменение UI-теста после первого green-кандидата исправило неверное ожидание
  нуля GET: кнопка развития уже имела immediateHero GET. Финальный тест требует
  точные POST+immediateHero, отсутствие success-only tail/balance и второй POST
  только после второго нативного click. Это поведение controller не менялось

### Реальный backend fixture

`generate-policy-responses.py` повторно выполнен в архиве точного base SHA:
exit 0, пять реальных ASGI-ответов. Для каждого: ноль чтений request body,
балансы viewer/hero и число module_actions до/после одинаковы, guard запрещает
вход в get_db. Три policy-отказа плюс существующие expired/missing JWT controls.
Формы/status/body совпадают с исходным независимым исследованием.

Исполнялись неизменные `main.app`, маршруты, middleware, FastAPI HTTPException
handler и JWT verifier. Временная SQLite и синтетический ключ; lifespan не
запускался, socket connect/DNS запрещены. Это in-process ASGI, не живой HTTP proxy,
Twitch или игра. `read()` тесты переигрывают формы реальных POST-ответов;
`viewer_poll` — явно синтетический read-control по действующему
`dependencies.py:_check_request_rate_limit`, а не захваченный GET.

- Fixture: `frontend-next/test/panel-fixtures/policy-responses.json`
- Reproducer: `frontend-next/test/panel-fixtures/generate-policy-responses.py`
- Тест: `frontend-next/test/panel-policy-transport.test.tsx`
- Логи/размеры/мутации: `docs/evidence/panel-policy-2026-10-03/`

### Финальная проверка

- Полный исходный frontend suite с `--maxWorkers=2`: 763 passed + 2 explicit live skips, exit 0
- Первый исходный запуск без ограничения: 735 passed + 2 skipped, exit 1;
  worker `panel-kingdom-safety.test.tsx` завершён SIGKILL, причина сигнала не установлена
- После исправления focused policy+core: 125/125, exit 0; после расширения policy: 110/110, exit 0
- Полный финальный suite: 873 passed + 2 explicit live skips, exit 0 (`final-suite.log`, `verification.json`)
- Финальные typecheck, build, отдельный check-build и измерение: exit 0
- Check-build: шесть входов, парные HTML, Helper первым, CSP, независимые графы,
  readable build, лицензии и исходные Preact sourcesContent в sourcemaps
- Защищённые области и package-lock: diff к базе пуст

### Контролируемые мутации

21 runtime-мутант после commit исходника: 20 опасных изменений дают exit 1,
один ожидаемо избыточный guard даёт exit 0. Восстановление после каждого — из
своей byte-backup копии, затем SHA-256 и пустой diff runtime. Это проверяется скриптом.
Полный green suite запускается после всех восстановлений.

Опасные мутации: снять action/read нормализацию, принять любой 4xx, ослабить
status/code пару, смешать envelopes, принять action-поля внутри detail, убрать
binding/целочисленность/положительность channel_id, coercion auth channel,
blank message, tier/quota/scope, использовать текущую личность вместо snapshot,
принять 5xx либо mixed top-level success.

Честно оставшийся мутант `redundant_channel_type_guard`: удаление только typeof
channel_id не меняет runtime-классификацию, потому что Number.isSafeInteger уже
отклоняет любое нечисло. Это не независимая защита и не «21 убитый мутант»;
явный typeof также нужен для понятного TypeScript narrowing. Мутации прогоняют
runtime-тесты, а typecheck отдельно прогоняется на восстановленном исходнике.

## Размер начального графа панели

Измерено явно для `panel-mobile.html` через `measure-build.mjs`, каждый файл
отдельно `gzip -9 -c`; собственный node_modules и minify:false.

- До фикса: 218 909 raw / 57 729 gzip-9 bytes
- После: 220 598 raw / 58 168 gzip-9 bytes
- Добавка: 1 689 raw / 439 gzip-9 bytes

Граф включает HTML, начальные JS и CSS с полной статической import closure.
Внешний Twitch Helper, API-ответы и source maps в initial traffic не включены.
Полные списки файлов и raw/gzip доступны в baseline-sizes.json/final-sizes.json.

## Воспроизведение

Из корня изолированной рабочей копии:

```sh
npm --prefix frontend-next --cache /tmp/preact-npm-cache test -- test/panel-policy-transport.test.tsx
npm --prefix frontend-next --cache /tmp/preact-npm-cache test -- --maxWorkers=2
npm --prefix frontend-next --cache /tmp/preact-npm-cache run typecheck
npm --prefix frontend-next --cache /tmp/preact-npm-cache run build
node frontend-next/scripts/check-build.mjs
node frontend-next/scripts/measure-build.mjs frontend-next/dist panel-mobile.html
python docs/evidence/panel-policy-2026-10-03/check-parser-mutations.py
```

ASGI отдельно, с backend-deps в изолированном Python environment, из архива
нужного commit (аргумент SOURCE_COMMIT — именно источник этого архива):

```sh
/tmp/preact-backend-venv/bin/python frontend-next/test/panel-fixtures/generate-policy-responses.py "$ISOLATED_ARCHIVE" "$OUTPUT_JSON" "$SOURCE_COMMIT"
```

## Ограничения и передача

Новый helper намеренно узкий: будущая изменённая форма policy-ответа потребует
проверки контракта; без неё action останется неизвестным. Впервые открытая панель
может остановиться ещё на bootstrap при unregistered/pending, поэтому тесты
не утверждают, что все такие кнопки доступны при первом входе. Проверяется ответ
уже допущенного запроса, включая смену approval и действующий action rate limit.

Unknown-outcome lock остаётся только в памяти открытого transport; reload не
доказывает отсутствие прежнего действия. Queue success не доказывает эффект игры.
Браузер, 318 px, телефон, Hosted Test, production и игровые эффекты НЕ проверены.
Никаких backend/mod/prod исправлений, remote writes, merge или deploy нет.

Документация искалась через `scripts/docs-search.py 'unknown outcome'`: найдены
описания lock в основном результате и combat/party отчётах. В checkout и общей
исходной рабочей копии `.agents/skills` отсутствует. AGENTS, CLAUDE и LESSONS часть 2
прочитаны. Общие STATUS/DEFERRED/основной результат не редактируются этим
исполнителем; родитель переносит итог после независимой проверки и cherry-pick.

## Форматирование сохранённых логов после интеграции

При переносе удалены только пустые строки в конце логов. В одном отрицательном
сценарии whitespace-only message показано через `\n`/`\t`, чтобы сам лог не
создавал trailing-whitespace error. Исходные captures доступны в commit
`688336e0b4fec6579043e88ea4f87c401e5405df`; исходные и текущие SHA-256 сохранены в
`verification.json`. Результаты, exit codes, runtime и tests не изменены.
